# -*- coding: utf-8 -*-
"""
Cliente otimizado para a API de Malhas v3 do IBGE (servicodados.ibge.gov.br/api/v3/malhas).
Inclui:
  - Cache permanente em disco (~/.geotrabalho/cache_malhas) para evitar downloads repetidos.
  - Compressão GZIP obrigatória (reduz a malha nacional de ~35 MB para ~830 KB).
  - Seleção automática de qualidade ("minima" para Brasil inteiro, "intermediaria" por UF).
  - Escrita direta em disco (zero-copy) sem re-serializar JSON gigante em memória.
  - Fallback automático por Grandes Regiões do IBGE (1 a 5) caso o endpoint nacional oscile.
"""

import gzip
import http.client
import json
import logging
import os
import tempfile
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import urlparse

LOGGER = logging.getLogger("GeoTrabalho")

VALID_BRAZIL_UFS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

IBGE_MACRO_REGIONS = [
    ("1", "Norte"),
    ("2", "Nordeste"),
    ("3", "Sudeste"),
    ("4", "Sul"),
    ("5", "Centro-Oeste"),
]

ALLOWED_IBGE_HOST = "servicodados.ibge.gov.br"


def get_persistent_cache_dir() -> str:
    """Retorna diretório permanente de cache de malhas no perfil do usuário."""
    candidates = [
        os.path.join(os.path.expanduser("~"), ".geotrabalho", "cache_malhas"),
        os.path.join(tempfile.gettempdir(), "geotrabalho_ibge_cache"),
    ]
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue
    return tempfile.gettempdir()


def _atomic_write_bytes(path: str, data: bytes) -> None:
    """Grava em arquivo temporário e renomeia, para nunca deixar um cache pela metade."""
    tmp_path = f"{path}.part"
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, path)


def _atomic_write_json(path: str, obj: Dict) -> None:
    _atomic_write_bytes(path, json.dumps(obj, ensure_ascii=False).encode("utf-8"))


class IbgeMalhasClient:
    """Cliente com cache permanente e compressão gzip para download de malhas municipais da API v3 do IBGE."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or get_persistent_cache_dir()
        os.makedirs(self.cache_dir, exist_ok=True)

    @staticmethod
    def _fetch_bytes_https(url: str, timeout: int = 180) -> Optional[bytes]:
        """Faz download direto via HTTPS com suporte explícito a GZIP e timeout estendido."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != ALLOWED_IBGE_HOST:
            raise ValueError(f"Host ou protocolo não permitido para API do IBGE: {url}")

        path_query = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        conn = http.client.HTTPSConnection(ALLOWED_IBGE_HOST, timeout=timeout)
        try:
            conn.request(
                "GET",
                path_query,
                headers={
                    "User-Agent": "QGIS-GeoTrabalho-Plugin/1.1",
                    "Accept": "application/vnd.geo+json, application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "close",
                },
            )
            resp = conn.getresponse()
            if resp.status != 200:
                LOGGER.warning("API IBGE retornou HTTP %s para %s", resp.status, url)
                return None
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw
        except Exception as exc:
            LOGGER.warning("Falha em _fetch_bytes_https (%s): %s", url, exc)
            return None
        finally:
            conn.close()

    @staticmethod
    def _fetch_bytes_qgis(url: str) -> Optional[bytes]:
        """Fallback via QgsBlockingNetworkRequest (útil quando o usuário usa proxy configurado no QGIS)."""
        try:
            from qgis.core import QgsBlockingNetworkRequest
            from qgis.PyQt.QtCore import QUrl
            from qgis.PyQt.QtNetwork import QNetworkRequest

            qreq = QNetworkRequest(QUrl(url))
            qreq.setRawHeader(b"User-Agent", b"QGIS-GeoTrabalho-Plugin/1.1")
            qreq.setRawHeader(b"Accept", b"application/vnd.geo+json, application/json")
            qreq.setRawHeader(b"Accept-Encoding", b"gzip, deflate")
            blocker = QgsBlockingNetworkRequest()
            err = blocker.get(qreq)
            if err == QgsBlockingNetworkRequest.ErrorCode.NoError:
                raw = bytes(blocker.reply().content())
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return raw
        except (ImportError, AttributeError, RuntimeError, OSError):
            return None
        return None

    @classmethod
    def _fetch_raw_geojson_bytes(cls, url: str, timeout: int = 180) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != ALLOWED_IBGE_HOST:
            raise ValueError(f"Host ou protocolo não permitido para API do IBGE: {url}")

        raw = cls._fetch_bytes_https(url, timeout=timeout)
        if not raw:
            raw = cls._fetch_bytes_qgis(url)
        if not raw:
            raise RuntimeError(f"Não foi possível baixar a malha da API do IBGE ({url}). Verifique sua conexão.")
        return raw

    @classmethod
    def _fetch_json(cls, url: str, timeout: int = 180) -> Dict:
        raw = cls._fetch_raw_geojson_bytes(url, timeout=timeout)
        return json.loads(raw.decode("utf-8"))

    def _fetch_br_by_regions(
        self,
        qual_clean: str,
        cache_file: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """
        Baixa a malha nacional dividida pelas 5 Grandes Regiões do IBGE (Norte, Nordeste,
        Sudeste, Sul e Centro-Oeste) e unifica em um único FeatureCollection com os 5.570 municípios.
        Evita o endpoint nacional /paises/BR, que costuma dar 'The read operation timed out' no servidor do IBGE.
        """
        all_features: List[Dict] = []
        for idx, (reg_code, reg_name) in enumerate(IBGE_MACRO_REGIONS, start=1):
            if progress_callback:
                progress_callback(
                    82 + int((idx - 1) * 2.4),
                    f"Baixando malha municipal: Região {reg_name} ({idx}/5) na API do IBGE...",
                )
            reg_url = (
                f"https://servicodados.ibge.gov.br/api/v3/malhas/regioes/{reg_code}"
                f"?formato=application/vnd.geo+json&qualidade={qual_clean}&intrarregiao=municipio"
            )
            data = self._fetch_json(reg_url, timeout=60)
            feats = data.get("features", [])
            all_features.extend(feats)
            LOGGER.info("Região %s (%s) carregada com %d municípios.", reg_name, reg_code, len(feats))

        if not all_features:
            raise RuntimeError("Nenhum município foi retornado pela API do IBGE ao consultar as regiões.")

        combined_geojson = {
            "type": "FeatureCollection",
            "features": all_features,
        }
        _atomic_write_json(cache_file, combined_geojson)
        if progress_callback:
            progress_callback(94, f"Malha nacional consolidada ({len(all_features)} municípios) com sucesso.")
        return cache_file

    def fetch_uf_geojson(
        self,
        uf: str,
        qualidade: str = "auto",
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        uf_clean = uf.strip().upper()
        is_br = uf_clean == "BR" or uf_clean not in VALID_BRAZIL_UFS
        if is_br:
            uf_clean = "BR"

        qual_clean = (qualidade or "auto").strip().lower()
        if qual_clean == "auto" or qual_clean not in ("minima", "intermediaria", "maxima"):
            # Para o Brasil inteiro (5.570 municípios), 'minima' tem ~830 KB gzipped (< 1s de download)
            qual_clean = "minima" if is_br else "intermediaria"

        cache_file = os.path.join(self.cache_dir, f"malha_mun_{uf_clean}_{qual_clean}.geojson")
        if os.path.exists(cache_file) and os.path.getsize(cache_file) > 1000:
            if progress_callback:
                progress_callback(92, f"Carregando malha municipal ({uf_clean}) do cache local...")
            return cache_file

        if is_br:
            # Baixa direto pelas 5 Grandes Regiões para evitar 'The read operation timed out' no IBGE
            return self._fetch_br_by_regions(qual_clean, cache_file, progress_callback=progress_callback)

        url = (
            f"https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf_clean}"
            f"?formato=application/vnd.geo+json&qualidade={qual_clean}&intrarregiao=municipio"
        )
        raw_bytes = self._fetch_raw_geojson_bytes(url, timeout=120)
        if b"FeatureCollection" in raw_bytes[:512]:
            _atomic_write_bytes(cache_file, raw_bytes)
            return cache_file

        geojson_data = json.loads(raw_bytes.decode("utf-8"))
        _atomic_write_json(cache_file, geojson_data)
        return cache_file

    def fetch_geojson_for_ufs(
        self,
        ufs: Iterable[str],
        qualidade: str = "auto",
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        valid_ufs = sorted({u.strip().upper() for u in ufs if u and u.strip().upper() in VALID_BRAZIL_UFS})
        if not valid_ufs or len(valid_ufs) > 6:
            if progress_callback:
                progress_callback(86, "Obtendo malha municipal nacional (BR) otimizada...")
            return self.fetch_uf_geojson("BR", qualidade=qualidade, progress_callback=progress_callback)

        if len(valid_ufs) == 1:
            uf = valid_ufs[0]
            if progress_callback:
                progress_callback(86, f"Obtendo malha municipal de {uf} na API do IBGE...")
            return self.fetch_uf_geojson(uf, qualidade=qualidade, progress_callback=progress_callback)

        eff_qual = "intermediaria" if qualidade in (None, "", "auto") else qualidade
        combined_key = "_".join(valid_ufs)
        combined_path = os.path.join(self.cache_dir, f"malha_mun_{combined_key}_{eff_qual}.geojson")
        if os.path.exists(combined_path) and os.path.getsize(combined_path) > 1000:
            if progress_callback:
                progress_callback(92, f"Carregando malha combinada ({combined_key}) do cache local...")
            return combined_path

        all_features: List[Dict] = []
        for idx, uf in enumerate(valid_ufs):
            if progress_callback:
                progress_callback(
                    85 + int((idx / len(valid_ufs)) * 9),
                    f"Baixando malha municipal de {uf} na API do IBGE...",
                )
            uf_path = self.fetch_uf_geojson(uf, eff_qual)
            with open(uf_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                all_features.extend(data.get("features", []))

        combined_geojson = {
            "type": "FeatureCollection",
            "features": all_features,
        }
        _atomic_write_json(combined_path, combined_geojson)
        return combined_path
