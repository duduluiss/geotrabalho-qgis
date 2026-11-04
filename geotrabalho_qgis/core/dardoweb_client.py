# -*- coding: utf-8 -*-
"""
Cliente e Parser Universal para o DardoWeb (BGCAGED / BGRAIS).
Suporta:
  1. Conexão Online Automática com bi.trabalho.gov.br (login público ou credencial própria).
  2. Execução de consultas dinâmicas (RAIS Vínculos, RAIS Estabelecimentos e CAGED).
  3. Suporte a anos correntes (2025, 2024, 2023, 2022) e séries históricas (até 2002 via cubos dedicados).
  4. Filtragem específica de atividades econômicas por CNAE (ex: Pecuária, Laticínios, Calçados, Abate de Carnes).
  5. Suporte a todos os indicadores contínuos (Frequência, Remuneração Média em SM e R$, Massa Salarial, Tempo de Emprego, Idade, Horas) e operações (Soma / Média).
  6. Importação e limpeza de arquivos locais exportados (.html, .htm).
  7. Extração automática de código IBGE de 7 dígitos e identificação de setor predominante / filtros temáticos.
"""

from __future__ import annotations

import gzip
import http.client
import http.cookies
import json
import logging
import os
import re
import secrets
import ssl
import unicodedata
import urllib.parse
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .municipality_mapper import MunicipalityMapper

LOGGER = logging.getLogger("GeoTrabalho")

HOST = "bi.trabalho.gov.br"
ENC = "iso-8859-1"

# Mapeamento oficial das UFs para o DardoWeb
UF_CODE_MAP = {
    "11": "Rondônia", "12": "Acre", "13": "Amazonas", "14": "Roraima", "15": "Pará",
    "16": "Amapá", "17": "Tocantins", "21": "Maranhão", "22": "Piauí", "23": "Ceará",
    "24": "Rio Grande do Norte", "25": "Paraíba", "26": "Pernambuco", "27": "Alagoas",
    "28": "Sergipe", "29": "Bahia", "31": "Minas Gerais", "32": "Espírito Santo",
    "33": "Rio de Janeiro", "35": "São Paulo", "41": "Paraná", "42": "Santa Catarina",
    "43": "Rio Grande do Sul", "50": "Mato Grosso do Sul", "51": "Mato Grosso",
    "52": "Goiás", "53": "Distrito Federal"
}

UF_SIGLA_TO_CODE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15",
    "AP": "16", "TO": "17", "MA": "21", "PI": "22", "CE": "23",
    "RN": "24", "PB": "25", "PE": "26", "AL": "27", "SE": "28",
    "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35",
    "PR": "41", "SC": "42", "RS": "43", "MS": "50", "MT": "51",
    "GO": "52", "DF": "53"
}


def normalize_text(text: str) -> str:
    """Remove acentuação e converte para minúsculas para busca e comparação flexível."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def parse_brazilian_number(val_str: str) -> float:
    """Converte números formatados no padrão brasileiro (1.234,56 ou 1.234) para float."""
    if not val_str:
        return 0.0
    s = val_str.strip().strip('"').strip("'")
    if s in ("-", "--", "", "...", "{ñ class}"):
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def make_clean_field_name(text: str, max_len: int = 24) -> str:
    """Gera nome ASCII seguro para colunas do Shapefile / GeoPackage."""
    nfkd = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    if not nfkd:
        nfkd = "COL"
    return nfkd[:max_len].strip("_")


_CNAE_CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cnae_catalog.json")


def get_cube_config(base_cubo: str, ano: str) -> Dict[str, str]:
    """
    Roteia a consulta para o cubo e endpoint correto do DardoWeb de acordo com o ano.
    - RAIS Vínculos e Estabelecimentos >= 2022: caged_rais_vinculo_id (Ano corrente a 2022)
    - RAIS Vínculos e Estabelecimentos < 2022: caged_rais_vinculo_id_2021 (2021 a 2002)
    - CAGED: caged_estatistico_id
    """
    ano_int = 2025
    try:
        ano_int = int(str(ano).strip())
    except ValueError:
        pass

    if base_cubo == "rais_vinculos":
        if ano_int >= 2022:
            return {
                "title": f"RAIS Vínculos {ano}",
                "base_path": "/bgcaged/caged_rais_vinculo_id/",
                "tab_file": "caged_rais_vinculo_basico_tab.php",
                "par_file": "caged_rais_vinculo_basico_tab.par",
            }
        else:
            return {
                "title": f"RAIS Vínculos {ano}",
                "base_path": "/bgcaged/caged_rais_vinculo_id_2021/",
                "tab_file": "caged_rais_vinculo_basico_2021_tab.php",
                "par_file": "caged_rais_vinculo_basico_2021_tab.par",
            }
    elif base_cubo == "rais_estabelecimentos":
        if ano_int >= 2022:
            return {
                "title": f"RAIS Estabelecimentos {ano}",
                "base_path": "/bgcaged/caged_rais_estabelecimento_id/",
                "tab_file": "caged_rais_estabelecimento_basico_tab.php",
                "par_file": "caged_rais_estabelecimento_basico_tab.par",
            }
        else:
            return {
                "title": f"RAIS Estabelecimentos {ano}",
                "base_path": "/bgcaged/caged_rais_estabelecimento_id_2021/",
                "tab_file": "caged_rais_estabelecimento_basico_2021_tab.php",
                "par_file": "caged_rais_estabelecimento_basico_2021_tab.par",
            }
    elif base_cubo == "caged":
        return {
            "title": f"CAGED {ano}",
            "base_path": "/bgcaged/caged_estatistico_id/",
            "tab_file": "caged_estatistico_basico_tabela.php",
            "par_file": "caged_estatistico_basico_tabela.par",
        }

    return {
        "title": "RAIS Vínculos",
        "base_path": "/bgcaged/caged_rais_vinculo_id/",
        "tab_file": "caged_rais_vinculo_basico_tab.php",
        "par_file": "caged_rais_vinculo_basico_tab.par",
    }


@dataclass
class DardoAggregationResult:
    """Resultado processado da consulta ou arquivo do DardoWeb."""
    base_name: str
    field_specs: List[Tuple[str, str]]  # [(nome_coluna, tipo: 'str' | 'int' | 'float')]
    records: List[Dict[str, Any]]
    column_headers: List[str]
    detected_ufs: Set[str] = field(default_factory=set)
    unmatched_rows: int = 0
    total_records: int = 0
    filter_applied: str = ""
    matched_columns: List[str] = field(default_factory=list)
    col_label_map: Dict[str, str] = field(default_factory=dict)  # field_name -> original_header
    summary_totals: Dict[str, float] = field(default_factory=dict)  # original_header -> table_footer_total


class DardoWebClient:
    """Cliente para automação de login, consultas e parsing do DardoWeb."""

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        self.username = username or "basico"
        self.password = password or os.environ.get("DARDOWEB_PASSWORD", "12345678")
        self.cookies: Dict[str, str] = {}
        self.mapper = MunicipalityMapper.instance()

        # Configura contexto SSL TLS 1.2 com cifras do DardoWeb
        self.ctx = ssl.create_default_context()
        self.ctx.set_ciphers("DEFAULT:AES256-GCM-SHA384:AES128-GCM-SHA256:@SECLEVEL=1")

    def _http_request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
        referer: Optional[str] = None,
        timeout: int = 180,
    ) -> Tuple[int, Optional[str], bytes]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GeoTrabalho-QGIS/1.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if referer:
            headers["Referer"] = referer

        data_bytes = None
        if body is not None:
            data_bytes = urllib.parse.urlencode(body, encoding=ENC).encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        last_exc: Optional[Exception] = None
        for attempt in range(2):
            conn = http.client.HTTPSConnection(HOST, timeout=timeout, context=self.ctx)
            try:
                conn.request(method, path, body=data_bytes, headers=headers)
                resp = conn.getresponse()
                for k, v in resp.getheaders():
                    if k.lower() == "set-cookie":
                        ck = http.cookies.SimpleCookie()
                        ck.load(v.split(";")[0])
                        for m in ck.values():
                            self.cookies[m.key] = m.value
                raw = resp.read()
                content_enc = (resp.getheader("Content-Encoding") or "").lower()
                if raw[:2] == b"\x1f\x8b" or "gzip" in content_enc:
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                elif "deflate" in content_enc:
                    try:
                        raw = zlib.decompress(raw)
                    except Exception:
                        pass
                loc = resp.getheader("Location")
                return resp.status, loc, raw
            except TimeoutError:
                # Timeout: o servidor já demorou o limite inteiro; repetir só dobraria a espera.
                raise
            except (OSError, http.client.HTTPException) as exc:
                last_exc = exc
                if attempt == 0:
                    LOGGER.warning("Tentativa 1 falhou em %s %s (%s). Retentando...", method, path, exc)
                    continue
                raise
            finally:
                conn.close()
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Falha de comunicação com {HOST}{path}")

    def login(self) -> bool:
        """Autentica na plataforma bi.trabalho.gov.br e armazena os cookies de sessão."""
        st, loc, raw = self._http_request(
            "POST",
            "/bgcaged/login.php",
            {"login": self.username, "senha": self.password},
        )
        if st in (200, 302) and "PHPSESSID" in self.cookies:
            return True
        return False

    _catalog_cache: Optional[Dict[str, Any]] = None

    @classmethod
    def load_cnae_catalog(cls) -> Dict[str, Any]:
        """Carrega o catálogo completo da CNAE com códigos, nomes e rótulos."""
        if cls._catalog_cache is None:
            if os.path.exists(_CNAE_CATALOG_PATH):
                try:
                    with open(_CNAE_CATALOG_PATH, "r", encoding="utf-8") as f:
                        cls._catalog_cache = json.load(f)
                except Exception:
                    cls._catalog_cache = {"secoes": [], "divisoes": [], "grupos": [], "classes": []}
            else:
                cls._catalog_cache = {"secoes": [], "divisoes": [], "grupos": [], "classes": []}
        return cls._catalog_cache

    def resolve_cnae_filter(
        self,
        filtro_nivel: Optional[str] = None,
        filtro_codigo: Optional[str] = None,
        filtro_texto: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Resolve a dimensão CNAE ('CNAE 2.0 Grupo'), código ('015') e descrição ('01.5 - Pecuária')
        a partir do nível/código ou busca textual. Retorna (var_name, code, label).
        """
        cat = self.load_cnae_catalog()
        level_map = {
            "secoes": "CNAE 2.0 Seção",
            "divisoes": "CNAE 2.0 Div",
            "grupos": "CNAE 2.0 Grupo",
            "classes": "CNAE 2.0 Classe",
        }
        if filtro_nivel in level_map and filtro_codigo and str(filtro_codigo).strip():
            code_str = str(filtro_codigo).strip()
            var_name = level_map[filtro_nivel]
            lbl = filtro_texto or code_str
            for it in cat.get(filtro_nivel, []):
                if it.get("code", "").lower() == code_str.lower():
                    lbl = it.get("label", lbl)
                    break
            return var_name, code_str, lbl

        if filtro_texto and filtro_texto.strip():
            raw_norm = normalize_text(filtro_texto.strip())
            if raw_norm not in ("todas", "toda a economia", "todas as 21 secoes", "todos", "none", ""):
                for lvl in ("classes", "grupos", "divisoes", "secoes"):
                    for it in cat.get(lvl, []):
                        c_code = it.get("code", "").lower()
                        c_name_norm = normalize_text(it.get("name", ""))
                        c_label_norm = normalize_text(it.get("label", ""))
                        if raw_norm == c_code or raw_norm == c_name_norm or raw_norm == c_label_norm:
                            return level_map[lvl], it.get("code", ""), it.get("label", "")
                for lvl in ("grupos", "classes", "divisoes", "secoes"):
                    for it in cat.get(lvl, []):
                        c_code = it.get("code", "").lower()
                        c_name_norm = normalize_text(it.get("name", ""))
                        c_label_norm = normalize_text(it.get("label", ""))
                        if raw_norm in c_name_norm or raw_norm in c_label_norm:
                            return level_map[lvl], it.get("code", ""), it.get("label", "")

        return None, None, None

    def query_dardo(
        self,
        base_cubo: str = "rais_vinculos",
        ano: str = "2025",
        uf: str = "SC",
        coluna_cruzamento: str = "CNAE 2.0 Seção",
        indicador: str = "->Frequência",
        filtro_atividade: Optional[str] = None,
        filtro_cnae_nivel: Optional[str] = None,
        filtro_cnae_codigo: Optional[str] = None,
        operacao: Optional[str] = None,
        prog_cb: Optional[Callable[[int, str], None]] = None,
    ) -> DardoAggregationResult:
        """
        Executa consulta ao DardoWeb gerando o cubo por Município cruzado com a dimensão informada,
        com suporte a roteamento de anos (2025 até séries históricas), filtro específico de CNAE
        e indicadores contínuos (Frequência, Remuneração em SM/R$, Tempo de Emprego, Idade, Horas).
        """
        if prog_cb:
            prog_cb(10, "Conectando ao sistema DardoWeb (bi.trabalho.gov.br)...")

        if not self.cookies and not self.login():
            raise RuntimeError("Falha ao autenticar no DardoWeb com o usuário informado.")

        cfg = get_cube_config(base_cubo, ano)
        base_path = cfg["base_path"]

        ano_int = 2025
        try:
            ano_int = int(str(ano).strip())
        except ValueError:
            pass

        col_efetiva = coluna_cruzamento if coluna_cruzamento else "---------Não---------"
        is_cnae_col = any(c in col_efetiva for c in ("CNAE 2.0", "CNAE 95"))

        cnae_var, cnae_code, cnae_label = self.resolve_cnae_filter(
            filtro_cnae_nivel, filtro_cnae_codigo, filtro_atividade
        )

        if is_cnae_col and cnae_var:
            if col_efetiva in ("CNAE 2.0 Seção", "CNAE 95 Seção", "---------Não---------", ""):
                col_efetiva = cnae_var
                if prog_cb:
                    prog_cb(15, f"Filtro ativo '{cnae_label}': comutando para {col_efetiva} para detalhamento...")

        if ano_int <= 2005:
            if "CNAE 2.0" in col_efetiva:
                col_antiga = col_efetiva
                col_efetiva = col_efetiva.replace("CNAE 2.0", "CNAE 95")
                if "Subclasse" in col_efetiva:
                    col_efetiva = "CNAE 95 Classe"
                if prog_cb:
                    prog_cb(18, f"Ano {ano} <= 2005: comutando '{col_antiga}' para '{col_efetiva}'...")
            elif "Escolaridade" in col_efetiva and "2005" in col_efetiva:
                col_efetiva = "Grau Instrução 2005-1985"
            if cnae_var and "CNAE 2.0" in cnae_var:
                cnae_var = cnae_var.replace("CNAE 2.0", "CNAE 95")
        else:
            if "CNAE 95" in col_efetiva:
                col_efetiva = col_efetiva.replace("CNAE 95", "CNAE 2.0")
            elif "Grau Instrução 2005-1985" in col_efetiva:
                col_efetiva = "Escolaridade após 2005"

        self._http_request("GET", base_path + cfg["tab_file"])

        eff_indic = indicador if indicador else "->Frequência"
        if operacao:
            eff_ce1 = operacao
        elif eff_indic in (
            "Vl Remun Média (SM)",
            "Vl Remun Média Nom",
            "Vl Remun Dezembro (SM)",
            "Vl Remun Dezembro Nom",
            "Tempo Emprego",
            "Idade",
            "Qtd Hora Contr",
        ):
            eff_ce1 = "Média"
        else:
            eff_ce1 = "Soma"

        if prog_cb:
            msg_filtro = f" [Filtro CNAE: {cnae_label}]" if (cnae_var and cnae_code and not is_cnae_col) else ""
            prog_cb(30, f"Enviando consulta: Municípios ({uf}) x {col_efetiva} ({ano}){msg_filtro}...")

        nt = str(secrets.randbelow(99999999) + 1)
        form_params: List[Tuple[str, str]] = [
            ("NT", nt),
            ("EA", f"https://{HOST}{base_path}"),
            ("EC", "0;7C725A;BAB19E;D9D6CA;F0EEDB"),
            ("AQ", cfg["par_file"]),
            ("AC", "0"),
            ("XC", "1"),
            ("IN", "0"),
            ("UM", "1"),
            ("UU", "0"),
            ("US", self.username),
            ("DF", f"https://{HOST}{base_path}{cfg['tab_file']}"),
            ("ND", ""),
            ("CJ", "Base de Gestão do MTE::CAGED"),
            ("LI", "Município"),
            ("CO", col_efetiva),
            ("UB", "---------Não---------"),
            ("QU", "---------Não---------"),
            ("SL", "---------Não---------"),
            ("CN", eff_indic),
            ("CE1", eff_ce1),
            ("OL", "SemOrdem"),
            ("OC", "SemOrdem"),
            ("OQ", "SemOrdem"),
            ("TT", ""),
            ("IU", ""),
            ("PL", ""),
        ]

        if base_cubo in ("rais_vinculos", "rais_estabelecimentos"):
            form_params.extend([
                ("YZAno", "0"),
                ("YCAno", f'"{ano}":NOME;{ano}'),
            ])
            if base_cubo == "rais_vinculos":
                form_params.extend([
                    ("YZVínculo Ativo 31/12", "0"),
                    ("YCVínculo Ativo 31/12", '"1":NOME;Sim'),
                ])
        elif base_cubo == "caged":
            form_params.extend([
                ("YZAno Declarado", "0"),
                ("YCAno Declarado", f'"{ano}":NOME;{ano}'),
            ])

        uf_clean = uf.strip().upper() if uf else ""
        is_national = not uf_clean or uf_clean in ("TODAS", "BR", "TODOS", "ALL")

        # Se for Brasil inteiro com cruzamento pesado sem filtro específico (ex: 673 Classes ou 285 Grupos x 5570 municípios),
        # divide automaticamente pelas 5 Grandes Regiões para evitar Gateway Timeout no servidor CGI do MTE.
        heavy_unfiltered_cross = (
            is_national
            and not cnae_code
            and "CNAE" in col_efetiva
            and any(tag in col_efetiva for tag in ("Grupo", "Classe", "Subclasse"))
        )
        if heavy_unfiltered_cross:
            return self._query_national_by_batches(
                base_cubo=base_cubo,
                ano=ano,
                coluna_cruzamento=coluna_cruzamento,
                indicador=indicador,
                filtro_atividade=filtro_atividade,
                filtro_cnae_nivel=filtro_cnae_nivel,
                filtro_cnae_codigo=filtro_cnae_codigo,
                operacao=operacao,
                prog_cb=prog_cb,
            )

        if not is_national:
            uf_parts = [u.strip() for u in uf_clean.split(",") if u.strip()]
            uf_entries: List[Tuple[str, str]] = []
            for u_sig in uf_parts:
                uf_num = UF_SIGLA_TO_CODE.get(u_sig, "")
                uf_nome = UF_CODE_MAP.get(uf_num, u_sig)
                if uf_num:
                    uf_entries.append(("YCUF", f'"{uf_num}":NOME;{uf_num} - {uf_nome}'))
            if uf_entries:
                form_params.append(("YZUF", "0"))
                form_params.extend(uf_entries)

        if cnae_var and cnae_code:
            form_params.extend([
                (f"YZ{cnae_var}", "0"),
                (f"YC{cnae_var}", f'"{cnae_code}":NOME;{cnae_code}'),
            ])
            if prog_cb:
                prog_cb(40, f"Aplicando filtro setorial no DardoWeb: {cnae_var} = {cnae_label or cnae_code}...")

        req_timeout = 180

        try:
            st, loc, raw_resp = self._http_request(
                "POST",
                "/scripts10/dardoweb.cgi",
                form_params,
                referer=f"https://{HOST}{base_path}{cfg['tab_file']}",
                timeout=req_timeout,
            )

            resp_text = raw_resp.decode(ENC, errors="replace")
            m_table = re.search(r'name=tabela SRC="?([^"\s>]+)', resp_text, re.I)
            if not m_table:
                if "Nenhum dado selecionado" in resp_text:
                    raise ValueError(f"Nenhum dado encontrado para o ano {ano} e filtros informados.")
                raise RuntimeError(f"O DardoWeb não gerou a tabela de resultados: {resp_text[:300]}")

            table_path = m_table.group(1).split(HOST, 1)[-1]

            if prog_cb:
                prog_cb(60, "Baixando e processando tabela de resultados do DardoWeb...")

            st_tbl, _, raw_tbl = self._http_request("GET", table_path, timeout=req_timeout)
            table_html = raw_tbl.decode(ENC, errors="replace")
        except (TimeoutError, OSError, RuntimeError) as exc:
            if is_national:
                LOGGER.warning("Consulta nacional única falhou/expirou (%s). Acionando consulta fatiada por Regiões...", exc)
                return self._query_national_by_batches(
                    base_cubo=base_cubo,
                    ano=ano,
                    coluna_cruzamento=coluna_cruzamento,
                    indicador=indicador,
                    filtro_atividade=filtro_atividade,
                    filtro_cnae_nivel=filtro_cnae_nivel,
                    filtro_cnae_codigo=filtro_cnae_codigo,
                    operacao=operacao,
                    prog_cb=prog_cb,
                )
            raise

        title_full = cfg["title"] if eff_indic == "->Frequência" else f"{cfg['title']} ({eff_indic})"
        applied_server_cnae = bool(cnae_var and cnae_code and not is_cnae_col)
        return self.parse_dardo_html(
            table_html,
            base_name=title_full,
            filtro_atividade=cnae_label or filtro_atividade,
            server_filtered=applied_server_cnae,
        )

    def _query_national_by_batches(
        self,
        base_cubo: str,
        ano: str,
        coluna_cruzamento: str,
        indicador: str,
        filtro_atividade: Optional[str],
        filtro_cnae_nivel: Optional[str],
        filtro_cnae_codigo: Optional[str],
        operacao: Optional[str],
        prog_cb: Optional[Callable[[int, str], None]] = None,
    ) -> DardoAggregationResult:
        """
        Divide uma consulta pesada do Brasil inteiro pelas 5 Grandes Regiões (Norte, Nordeste,
        Sudeste, Sul e Centro-Oeste) e unifica todos os municípios em um único resultado.
        """
        regional_batches = [
            ("Norte", "RO,AC,AM,RR,PA,AP,TO"),
            ("Nordeste", "MA,PI,CE,RN,PB,PE,AL,SE,BA"),
            ("Sudeste", "MG,ES,RJ,SP"),
            ("Sul", "PR,SC,RS"),
            ("Centro-Oeste", "MS,MT,GO,DF"),
        ]
        merged: Optional[DardoAggregationResult] = None
        seen_ibge: Set[str] = set()

        for idx, (reg_name, uf_csv) in enumerate(regional_batches, start=1):
            if prog_cb:
                prog_cb(
                    15 + int((idx - 1) / len(regional_batches) * 60),
                    f"Consultando DardoWeb por Região ({idx}/5: {reg_name}) para evitar timeout...",
                )
            part = self.query_dardo(
                base_cubo=base_cubo,
                ano=ano,
                uf=uf_csv,
                coluna_cruzamento=coluna_cruzamento,
                indicador=indicador,
                filtro_atividade=filtro_atividade,
                filtro_cnae_nivel=filtro_cnae_nivel,
                filtro_cnae_codigo=filtro_cnae_codigo,
                operacao=operacao,
                prog_cb=None,
            )
            if merged is None:
                merged = DardoAggregationResult(
                    base_name=part.base_name,
                    field_specs=list(part.field_specs),
                    records=[],
                    column_headers=list(part.column_headers),
                    detected_ufs=set(part.detected_ufs),
                    unmatched_rows=part.unmatched_rows,
                    total_records=0,
                    filter_applied=part.filter_applied,
                    matched_columns=list(part.matched_columns),
                    col_label_map=dict(part.col_label_map),
                    summary_totals=dict(part.summary_totals),
                )
            else:
                merged.detected_ufs.update(part.detected_ufs)
                merged.unmatched_rows += part.unmatched_rows
                existing_fields = {f_name for f_name, _ in merged.field_specs}
                for f_name, f_type in part.field_specs:
                    if f_name not in existing_fields:
                        merged.field_specs.append((f_name, f_type))
                        existing_fields.add(f_name)
                for h_col in part.column_headers:
                    if h_col not in merged.column_headers:
                        merged.column_headers.append(h_col)
                merged.col_label_map.update(part.col_label_map)
                for k, v in part.summary_totals.items():
                    merged.summary_totals[k] = merged.summary_totals.get(k, 0.0) + v

            for rec in part.records:
                cd = str(rec.get("CD_MUN_IBGE", ""))
                if cd and cd not in seen_ibge:
                    seen_ibge.add(cd)
                    merged.records.append(rec)

        if merged is None:
            raise RuntimeError("Não foi possível obter os dados nacionais do DardoWeb.")
        merged.total_records = len(merged.records)
        return merged

    def parse_dardo_html(
        self,
        html_content: str,
        base_name: str = "DardoWeb",
        filtro_atividade: Optional[str] = None,
        server_filtered: bool = False,
    ) -> DardoAggregationResult:
        """
        Interpreta o código HTML gerado pelo DardoWeb e extrai colunas, municípios e métricas.
        Suporta filtragem específica por palavras-chave CNAE e captura a linha de Total Geral.
        """
        raw_headers: List[str] = []
        for m in re.finditer(r'<TH\b[^>]*\bid=["\']?zw\d+["\']?[^>]*>([\s\S]*?)</TH>', html_content, re.I):
            raw_h = m.group(1)
            if "<br>" in raw_h.lower():
                raw_h = raw_h.split("<br>", 1)[1]
            clean_h = re.sub(r'<[^>]+>', '', raw_h).strip().replace('&nbsp;', ' ')
            if clean_h:
                raw_headers.append(clean_h)

        if not raw_headers:
            raw_headers = ["Total"]

        filter_terms: List[str] = []
        filter_codes: List[str] = []
        if filtro_atividade and filtro_atividade.strip():
            raw_parts = [t.strip() for t in filtro_atividade.split(",") if t.strip()]
            for part in raw_parts:
                norm_full = normalize_text(part)
                filter_terms.append(norm_full)
                m_code = re.match(r"^([A-Za-z0-9\.\-]+)\s*[\-\:]\s*(.*)$", part)
                if m_code:
                    clean_code = re.sub(r"[^A-Za-z0-9]", "", m_code.group(1)).lower()
                    clean_desc = normalize_text(m_code.group(2))
                    if clean_code:
                        filter_codes.append(clean_code)
                    if clean_desc:
                        filter_terms.append(clean_desc)

        matched_col_indices: List[Tuple[int, str]] = []
        if (filter_terms or filter_codes) and not server_filtered:
            for idx, h in enumerate(raw_headers):
                if h.lower() in ("total", "total geral"):
                    continue
                h_norm = normalize_text(h)
                h_digits = "".join(re.findall(r"\d+", h))
                matched = False
                for term in filter_terms:
                    if term and (term in h_norm or h_norm in term):
                        matched = True
                        break
                if not matched and filter_codes:
                    for c in filter_codes:
                        if c and (c in h_norm or (h_digits and c == h_digits)):
                            matched = True
                            break
                if matched:
                    matched_col_indices.append((idx, h))

        has_active_filter = len(matched_col_indices) > 0
        server_side_filtered = bool(server_filtered or (filtro_atividade and filtro_atividade.strip() and not has_active_filter))
        matched_names = [h for _, h in matched_col_indices] if has_active_filter else ([filtro_atividade] if server_side_filtered else [])

        cols_to_keep: List[Tuple[int, str]] = []
        if has_active_filter:
            cols_to_keep = matched_col_indices
        else:
            for idx, h in enumerate(raw_headers):
                if h.lower() not in ("total", "total geral"):
                    cols_to_keep.append((idx, h))

        used_fields: Set[str] = {
            "CD_MUN_IBGE", "SG_UF", "NM_MUN", "TOTAL_GERAL", "PREDOMINANTE", "PERC_PREDOMINANTE",
            "VINC_FILTR", "PCT_FILTR",
        }
        col_field_map: List[Tuple[int, str, str]] = []
        col_label_map: Dict[str, str] = {}

        is_float_metric = any(
            k in base_name for k in ("Nom", "SM", "Remun", "Salário", "Tempo", "Idade", "Hora", "Média")
        )

        for orig_idx, h in cols_to_keep:
            slug = make_clean_field_name(h, max_len=18)
            candidate = f"C_{slug}"
            c_idx = 2
            while candidate in used_fields:
                candidate = f"C_{slug}_{c_idx}"
                c_idx += 1
            used_fields.add(candidate)
            col_field_map.append((orig_idx, h, candidate))
            col_label_map[candidate] = h

        row_regex = re.compile(r'<TR[^>]*onClick="tc\(this\)"[^>]*>([\s\S]*?)(?=<TR|\Z)', re.I)
        matches = row_regex.findall(html_content)

        records: List[Dict[str, Any]] = []
        detected_ufs: Set[str] = set()
        unmatched = 0
        summary_totals: Dict[str, float] = {}

        for row_html in matches:
            th_match = re.search(r'<TH[^>]*>([\s\S]*?)</TH>', row_html, re.I)
            if not th_match:
                continue

            raw_mun_name = re.sub(r'<[^>]+>', '', th_match.group(1)).strip().replace('&nbsp;', ' ')
            td_values = re.findall(r'<TD[^>]*class=["\']col\d+["\'][^>]*>([\s\S]*?)</TD>', row_html, re.I)
            clean_tds = [re.sub(r'<[^>]+>', '', td).strip() for td in td_values]

            if not raw_mun_name or raw_mun_name.lower().startswith("total"):
                if clean_tds and raw_mun_name.lower().startswith("total"):
                    for idx_h, h_name in enumerate(raw_headers):
                        if idx_h < len(clean_tds):
                            summary_totals[h_name] = parse_brazilian_number(clean_tds[idx_h])
                    summary_totals["__TOTAL_GERAL__"] = parse_brazilian_number(clean_tds[-1])
                continue

            if raw_mun_name.lower().startswith("{ñ"):
                continue

            cd_ibge, uf_res, nm_res = self.mapper.resolve(None, None, raw_mun_name)
            if not cd_ibge:
                unmatched += 1
                continue

            if uf_res:
                detected_ufs.add(uf_res)

            row_dict: Dict[str, Any] = {
                "CD_MUN_IBGE": cd_ibge,
                "SG_UF": uf_res,
                "NM_MUN": nm_res,
            }

            max_val = -1.0
            predominant_col = ""
            total_row = 0.0
            filtered_sum = 0.0

            for orig_idx, orig_header, col_field in col_field_map:
                if orig_idx < len(clean_tds):
                    num_val = parse_brazilian_number(clean_tds[orig_idx])
                else:
                    num_val = 0.0

                row_dict[col_field] = round(num_val, 2) if is_float_metric else int(round(num_val))
                if num_val > max_val and num_val > 0:
                    max_val = num_val
                    predominant_col = orig_header

            if has_active_filter:
                for orig_idx, _ in matched_col_indices:
                    if orig_idx < len(clean_tds):
                        filtered_sum += parse_brazilian_number(clean_tds[orig_idx])

            if clean_tds:
                total_from_table = parse_brazilian_number(clean_tds[-1])
                final_total = total_from_table if total_from_table > 0 else total_row
            else:
                final_total = total_row

            row_dict["TOTAL_GERAL"] = round(final_total, 2) if is_float_metric else int(round(final_total))
            row_dict["PREDOMINANTE"] = predominant_col if predominant_col else "Sem atividade"
            row_dict["PERC_PREDOMINANTE"] = round((max_val / final_total) * 100.0, 2) if final_total > 0 else 0.0

            if has_active_filter:
                pct_filt = round((filtered_sum / final_total) * 100.0, 2) if final_total > 0 else 0.0
                row_dict["VINC_FILTR"] = round(filtered_sum, 2) if is_float_metric else int(round(filtered_sum))
                row_dict["PCT_FILTR"] = pct_filt
            elif server_side_filtered:
                row_dict["VINC_FILTR"] = row_dict["TOTAL_GERAL"]
                row_dict["PCT_FILTR"] = 100.0

            records.append(row_dict)

        val_type = "float" if is_float_metric else "int"
        field_specs: List[Tuple[str, str]] = [
            ("CD_MUN_IBGE", "str"),
            ("SG_UF", "str"),
            ("NM_MUN", "str"),
            ("TOTAL_GERAL", val_type),
        ]

        if has_active_filter or server_side_filtered:
            field_specs.extend([
                ("VINC_FILTR", val_type),
                ("PCT_FILTR", "float"),
            ])

        field_specs.extend([
            ("PREDOMINANTE", "str"),
            ("PERC_PREDOMINANTE", "float"),
        ])

        for _, _, col_field in col_field_map:
            field_specs.append((col_field, val_type))

        return DardoAggregationResult(
            base_name=base_name,
            field_specs=field_specs,
            records=records,
            column_headers=[h for _, h, _ in col_field_map],
            detected_ufs=detected_ufs,
            unmatched_rows=unmatched,
            total_records=len(records),
            filter_applied=filtro_atividade.strip() if filtro_atividade else "",
            matched_columns=matched_names,
            col_label_map=col_label_map,
            summary_totals=summary_totals,
        )

    def parse_local_file(self, file_path: str, filtro_atividade: Optional[str] = None) -> DardoAggregationResult:
        """
        Lê arquivo salvo localmente do DardoWeb (.html, .htm).
        Suporta tanto tabelas diretas quanto páginas completas do navegador salvas com <frameset>.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

        content = ""
        for enc in ("utf-8", "utf-8-sig", "iso-8859-1", "windows-1252"):
            try:
                with open(file_path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        base_name = os.path.splitext(os.path.basename(file_path))[0]

        if "<frame" in content.lower():
            m_frame = re.search(r'<frame[^>]*\bname=["\']?tabela["\']?[^>]*\bsrc=["\']([^"\'>]+)["\']', content, re.I)
            if not m_frame:
                m_frame = re.search(r'<frame[^>]*\bsrc=["\']([^"\'>]*t\.html?)[^"\']*["\']', content, re.I)
            if m_frame:
                rel_src = m_frame.group(1).replace("/", os.sep)
                frame_path = os.path.normpath(os.path.join(os.path.dirname(file_path), rel_src))
                if os.path.exists(frame_path):
                    for enc in ("utf-8", "utf-8-sig", "iso-8859-1", "windows-1252"):
                        try:
                            with open(frame_path, "r", encoding=enc) as f_frame:
                                content = f_frame.read()
                            break
                        except UnicodeDecodeError:
                            continue

        if "<table" in content.lower():
            return self.parse_dardo_html(content, base_name=base_name, filtro_atividade=filtro_atividade)
        else:
            raise NotImplementedError("Para arquivos tabulares separados (.csv/.txt), salve em HTML pelo DardoWeb.")
