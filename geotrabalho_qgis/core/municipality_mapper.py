# -*- coding: utf-8 -*-
"""
Tradutor oficial de códigos municipais (UF, Nome do Município ou Código de 6 dígitos)
para o geocódigo oficial do IBGE de 7 dígitos.
"""

import json
import logging
import os
import unicodedata
from typing import Dict, Optional, Tuple

LOGGER = logging.getLogger("GeoTrabalho")


def normalize_text(text: str) -> str:
    """Remove acentos, converte para maiúsculas e padroniza espaços."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    return " ".join(ascii_str.upper().strip().split())


class MunicipalityMapper:
    """Mapeador em memória para todos os 5.571 municípios brasileiros."""

    _instance = None

    def __init__(self, json_path: Optional[str] = None):
        if json_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            json_path = os.path.join(base_dir, "data", "tse_ibge_municipios.json")

        self.by_tse: Dict[str, Dict[str, str]] = {}
        self.by_uf_name: Dict[str, Dict[str, str]] = {}
        self.by_ibge: Dict[str, Dict[str, str]] = {}
        self.by_ibge6: Dict[str, Dict[str, str]] = {}
        self._load(json_path)

    @classmethod
    def instance(cls) -> "MunicipalityMapper":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self, json_path: str) -> None:
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"Tabela de municípios não encontrada em: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.by_tse = data.get("by_tse", {})
        self.by_uf_name = data.get("by_uf_name", {})

        for tse_code, info in self.by_tse.items():
            ibge_code = info.get("ibge", "")
            if ibge_code:
                entry = {
                    "tse": tse_code,
                    "ibge": ibge_code,
                    "uf": info.get("uf", ""),
                    "nome": info.get("nome", ""),
                }
                self.by_ibge[ibge_code] = entry
                if len(ibge_code) >= 6:
                    self.by_ibge6[ibge_code[:6]] = entry

    @staticmethod
    def format_ibge_code(raw_code) -> str:
        """Padroniza código IBGE para 7 dígitos."""
        if raw_code is None:
            return ""
        s = str(raw_code).strip().strip('"').strip("'")
        if not s:
            return ""
        if s.endswith(".0"):
            s = s[:-2]
        if s.isdigit():
            return s.zfill(7)
        return s

    def resolve(
        self,
        cd_ibge_or_6=None,
        sg_uf: Optional[str] = None,
        nm_municipio: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """
        Retorna a tupla (cd_ibge_7, sg_uf, nm_municipio_oficial).
        """
        raw_code = str(cd_ibge_or_6 or "").strip()
        if raw_code.isdigit():
            if len(raw_code) == 7 and raw_code in self.by_ibge:
                info = self.by_ibge[raw_code]
                return info["ibge"], info["uf"], info["nome"]
            if len(raw_code) == 6 and raw_code in self.by_ibge6:
                info = self.by_ibge6[raw_code]
                return info["ibge"], info["uf"], info["nome"]

        uf_clean = str(sg_uf or "").strip().upper()
        nm_clean = str(nm_municipio or "").strip()

        # Trata formato misto do DardoWeb: "SC-FLORIANOPOLIS" ou "420540 - Florianópolis"
        if "-" in nm_clean and not uf_clean:
            parts = nm_clean.split("-", 1)
            p0 = parts[0].strip()
            if len(p0) == 2 and p0.isalpha():
                uf_clean = p0.upper()
                nm_clean = parts[1].strip()
            elif p0.isdigit() and len(p0) in (6, 7):
                return self.resolve(p0)

        if uf_clean and nm_clean:
            norm_nm = normalize_text(nm_clean)
            key = f"{uf_clean}:{norm_nm}"
            if key in self.by_uf_name:
                info = self.by_uf_name[key]
                return info["ibge"], info["uf"], info["nome"]

            # Variações flexíveis de pontuação (hífen, apóstrofo, etc.)
            for sep in ("-", "'", ".", "/"):
                if sep in norm_nm:
                    alt_nm = normalize_text(norm_nm.replace(sep, " "))
                    alt_key = f"{uf_clean}:{alt_nm}"
                    if alt_key in self.by_uf_name:
                        info = self.by_uf_name[alt_key]
                        return info["ibge"], info["uf"], info["nome"]

                    alt_nm2 = normalize_text(norm_nm.replace(sep, ""))
                    alt_key2 = f"{uf_clean}:{alt_nm2}"
                    if alt_key2 in self.by_uf_name:
                        info = self.by_uf_name[alt_key2]
                        return info["ibge"], info["uf"], info["nome"]

        if uf_clean == "DF":
            return "5300108", "DF", "Brasília"

        return "", uf_clean, nm_clean
