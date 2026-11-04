# -*- coding: utf-8 -*-
"""
Motor de Análise Multitemporal e Relatórios Específicos da RAIS/CAGED (DardoWeb/MTE).
Suporta execução granular (gerando apenas o gráfico ou tabela solicitada pelo usuário)
para todas as 27 UFs e os 5.571 municípios brasileiros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .dardoweb_client import DardoAggregationResult, DardoWebClient, UF_CODE_MAP, UF_SIGLA_TO_CODE
from .municipality_mapper import MunicipalityMapper


def fmt_int_br(val: float | int) -> str:
    """Formata inteiro no padrão brasileiro: 89.459."""
    v = int(round(float(val or 0)))
    return f"{v:,}".replace(",", ".")


def fmt_float_br(val: float, decimals: int = 1) -> str:
    """Formata decimal no padrão brasileiro: 128,9."""
    s = f"{float(val or 0.0):,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def calc_var_pct(v_old: float, v_new: float) -> Optional[float]:
    """Calcula a variação percentual entre v_old e v_new."""
    if v_old is None or abs(v_old) < 1e-9:
        if v_new and abs(v_new) > 1e-9:
            return None
        return 0.0
    return ((float(v_new) - float(v_old)) / float(v_old)) * 100.0


def fmt_var_pct_br(v_old: float, v_new: float) -> str:
    """Formata variação percentual com sinal (+82,4% ou -16,5%)."""
    pct = calc_var_pct(v_old, v_new)
    if pct is None:
        return "Novo"
    sign = "+" if pct > 0 else ""
    return f"{sign}{fmt_float_br(pct, 1)}%"


def prettify_category_label(raw: str) -> str:
    """Padroniza rótulos em CAIXA ALTA vindos do DardoWeb (ex: CBO) sem alterar siglas curtas."""
    s = (raw or "").strip()
    if len(s) > 14 and s.isupper():
        words = s.capitalize().split()
        lower_words = {"de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "para", "por", "a", "o"}
        out = [words[0]]
        for w in words[1:]:
            lw = w.lower()
            out.append(lw if lw in lower_words else w.capitalize())
        return " ".join(out)
    return s


@dataclass
class StyledTableSpec:
    """Especificação estruturada de uma tabela analítica para exportação PNG, CSV e HTML."""
    table_id: str
    title: str
    subtitle: str
    headers: List[str]
    rows: List[List[str]]
    footer_row_indices: List[int] = field(default_factory=list)
    var_col_indices: List[int] = field(default_factory=list)
    theme: str = "navy"
    footnote: str = ""
    highlights: List[str] = field(default_factory=list)


@dataclass
class AnalyticsReportBundle:
    """Pacote de saída contendo apenas as tabelas e/ou gráficos solicitados."""
    uf: str
    uf_name: str
    sector_label: str
    years_asc: List[str]
    years_desc: List[str]
    region_type_label: str
    kpis: List[Dict[str, str]] = field(default_factory=list)
    tables: List[StyledTableSpec] = field(default_factory=list)
    chart_payloads: List[Dict[str, Any]] = field(default_factory=list)
    municipal_multiyear_records: List[Dict[str, Any]] = field(default_factory=list)


class GeoTrabalhoAnalyticsEngine:
    """Motor de extração e cálculo estatístico-espacial sobre o DardoWeb/MTE."""

    def __init__(self, client: Optional[DardoWebClient] = None) -> None:
        self.client = client or DardoWebClient()
        self.mapper = MunicipalityMapper.instance()

    def _extract_mun_value(self, rec: Dict[str, Any], has_filter: bool) -> float:
        if has_filter and "VINC_FILTR" in rec:
            return float(rec.get("VINC_FILTR") or 0.0)
        return float(rec.get("TOTAL_GERAL") or 0.0)

    def _get_region_name(self, cd_ibge: str, region_mode: str = "meso") -> str:
        info = self.mapper.get_regional_info(cd_ibge)
        if region_mode == "interm":
            return info.get("interm") or info.get("meso") or "Outras"
        if region_mode == "micro":
            return info.get("micro") or info.get("meso") or "Outras"
        return info.get("meso") or "Outras"

    def _extract_category_totals(self, res: DardoAggregationResult) -> Dict[str, float]:
        """Extrai o total de cada coluna/categoria (usando summary_totals oficial ou soma municipal)."""
        cat_sums: Dict[str, float] = {}
        for col_f, orig_h in res.col_label_map.items():
            if orig_h.lower().startswith("{ñ") or orig_h.lower() in ("total", "total geral"):
                continue
            pretty_h = prettify_category_label(orig_h)
            if orig_h in res.summary_totals:
                val = float(res.summary_totals[orig_h] or 0.0)
            else:
                val = sum(float(r.get(col_f) or 0.0) for r in res.records)
            cat_sums[pretty_h] = cat_sums.get(pretty_h, 0.0) + val
        return cat_sums

    @staticmethod
    def _group_schooling_5_tiers(cat_map: Dict[str, float]) -> Dict[str, float]:
        """Agrupa os 11 níveis de escolaridade da RAIS em 5 faixas sintéticas clássicas."""
        tiers = {
            "Até Fundamental Incompleto": 0.0,
            "Fundamental Completo": 0.0,
            "Médio Incompleto": 0.0,
            "Médio Completo": 0.0,
            "Superior (Incompleto ou Completo)": 0.0,
        }
        for k, val in cat_map.items():
            kl = k.lower()
            if any(t in kl for t in ("analfabeto", "5º", "6º", "9º", "quarta", "oitava", "incompleto")) and "médio" not in kl and "sup" not in kl:
                tiers["Até Fundamental Incompleto"] += val
            elif "fundamental completo" in kl or "oitava completa" in kl:
                tiers["Fundamental Completo"] += val
            elif "médio incompleto" in kl or "2º grau incompleto" in kl:
                tiers["Médio Incompleto"] += val
            elif "médio completo" in kl or "2º grau completo" in kl:
                tiers["Médio Completo"] += val
            else:
                tiers["Superior (Incompleto ou Completo)"] += val
        return tiers

    def run_specific_report(
        self,
        report_key: str,
        uf: str,
        years: List[str],
        filtro_nivel: Optional[str] = None,
        filtro_codigo: Optional[str] = None,
        filtro_texto: Optional[str] = None,
        top_n: int = 10,
        region_mode: str = "meso",
        chart_style: str = "bars_abs",
        rank_chart_style: str = "bars",
        wage_unit: str = "BRL",
        rem_scope: str = "serie_uf",
        regional_subview: str = "painel_duplo",
        base_cubo_override: str = "rais_vinculos",
        only_foreigners: bool = True,
        max_categories: int = 12,
        prog_cb: Optional[Callable[[int, str], None]] = None,
    ) -> AnalyticsReportBundle:
        """
        Executa estritamente a consulta necessária para o item `report_key` escolhido pelo usuário,
        evitando consultas ou gráficos desnecessários.
        """
        clean_years = sorted({str(y).strip() for y in years if str(y).strip().isdigit()}, key=lambda x: int(x))
        if not clean_years:
            clean_years = ["2025"]
        years_asc = list(clean_years)
        years_desc = list(reversed(clean_years))
        y_first = years_asc[0]
        y_last = years_asc[-1]
        y_tag = y_last if len(years_asc) == 1 else f"{y_first}_{y_last}"

        uf_clean = (uf or "SC").strip().upper()
        if uf_clean in ("BR", "TODAS", "TODOS"):
            uf_name = "Brasil"
        else:
            uf_num = UF_SIGLA_TO_CODE.get(uf_clean, "")
            uf_name = UF_CODE_MAP.get(uf_num, uf_clean)

        _, _, resolved_label = self.client.resolve_cnae_filter(filtro_nivel, filtro_codigo, filtro_texto)
        sector_label = resolved_label or filtro_texto or "Toda a Economia"
        eff_nivel = filtro_nivel if filtro_nivel and filtro_nivel != "none" else None

        region_type_label = {
            "meso": "Mesorregião (IBGE)",
            "interm": "Região Geográfica Intermediária (IBGE)",
            "micro": "Microrregião (IBGE)",
        }.get(region_mode, "Mesorregião (IBGE)")

        bundle = AnalyticsReportBundle(
            uf=uf_clean,
            uf_name=uf_name,
            sector_label=sector_label,
            years_asc=years_asc,
            years_desc=years_desc,
            region_type_label=region_type_label,
        )

        var_col_label = f"Var. {y_first[-2:]}–{y_last[-2:]}"

        # ------------------------------------------------------------------
        # Auxiliar: consulta municipal multi-anos para um cubo específico
        # ------------------------------------------------------------------
        def fetch_municipal_series(cubo: str, target_years: List[str], label_step: str) -> Tuple[Dict[str, Dict[str, float]], Dict[str, str], Dict[str, str]]:
            by_year: Dict[str, Dict[str, float]] = {y: {} for y in target_years}
            m_names: Dict[str, str] = {}
            m_ufs: Dict[str, str] = {}
            for idx, y in enumerate(target_years, start=1):
                if prog_cb:
                    prog_cb(
                        int(10 + (idx / max(1, len(target_years))) * 75),
                        f"Consultando {label_step} ({uf_clean}) — Ano {y}...",
                    )
                res = self.client.query_dardo(
                    base_cubo=cubo,
                    ano=y,
                    uf=uf_clean,
                    coluna_cruzamento="---------Não---------",
                    indicador="->Frequência",
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                )
                has_f = bool(res.filter_applied)
                for rec in res.records:
                    cd = rec["CD_MUN_IBGE"]
                    m_names[cd] = rec["NM_MUN"]
                    m_ufs[cd] = rec.get("SG_UF", uf_clean)
                    by_year[y][cd] = self._extract_mun_value(rec, has_f)
            return by_year, m_names, m_ufs

        # ==================================================================
        # SUB-ABA 1: DINÂMICA ESPACIAL E REGIONAL
        # ==================================================================
        if report_key in ("esp_evolucao_vinculos", "esp_evolucao_estabelecimentos"):
            is_vinc = report_key == "esp_evolucao_vinculos"
            cubo = "rais_vinculos" if is_vinc else "rais_estabelecimentos"
            metric_lbl = "Vínculos Trabalhistas" if is_vinc else "Estabelecimentos (Plantas)"
            theme = "wine" if is_vinc else "green"
            chart_color = "#7a1c1c" if is_vinc else "#14532d"
            slug = f"evolucao_{'vinculos' if is_vinc else 'estabelecimentos'}_{uf_clean}_{y_tag}"

            data_by_y, _, _ = fetch_municipal_series(cubo, years_asc, f"RAIS {metric_lbl}")
            tot_uf = {y: sum(data_by_y[y].values()) for y in years_asc}
            vals_series = [tot_uf[y] for y in years_asc]

            has_multi = len(years_asc) >= 2
            step_vars: List[str] = [""]
            rows_evo: List[List[str]] = []
            for idx_y, y in enumerate(years_asc):
                v_cur = tot_uf[y]
                if idx_y == 0:
                    step_s = "—"
                    acum_s = "Base (100%)"
                else:
                    v_prev = tot_uf[years_asc[idx_y - 1]]
                    step_s = fmt_var_pct_br(v_prev, v_cur)
                    acum_s = fmt_var_pct_br(tot_uf[y_first], v_cur)
                    step_vars.append(step_s)
                if has_multi:
                    rows_evo.append([y, fmt_int_br(v_cur), step_s, acum_s])
                else:
                    rows_evo.append([y, fmt_int_br(v_cur)])

            headers_evo = (
                ["Ano", f"Total de {metric_lbl}", "Var. no Período Anterior", f"Var. Acumulada ({y_first}–Ano)"]
                if has_multi
                else ["Ano", f"Total de {metric_lbl}"]
            )
            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_{slug}",
                    title=f"Evolução de {metric_lbl} — {uf_name} ({', '.join(years_asc)})",
                    subtitle=f"Série Histórica de {metric_lbl} ({', '.join(years_asc)})",
                    headers=headers_evo,
                    rows=rows_evo,
                    var_col_indices=[2, 3] if has_multi else [],
                    theme=theme,
                    footnote=f"Fonte: MTE — DardoWeb (RAIS {metric_lbl}, {sector_label}).",
                )
            )

            total_var_txt = f" | Variação {y_first}–{y_last}: {fmt_var_pct_br(tot_uf[y_first], tot_uf[y_last])}" if has_multi else ""
            bundle.chart_payloads.append({
                "chart_id": f"grafico_{slug}",
                "title": f"Evolução de {metric_lbl} ({', '.join(years_asc)}) — {uf_name}",
                "subtitle": f"Recorte: {sector_label}{total_var_txt}",
                "type": "temporal_series_bars",
                "years": years_asc,
                "values": vals_series,
                "step_vars": step_vars,
                "color": chart_color,
                "unit": "INT",
                "ylabel": f"Total de {metric_lbl}",
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {', '.join(years_asc)}). Taxas percentuais indicam a variação entre os anos selecionados.",
            })
            return bundle

        elif report_key in ("esp_ranking_vinculos", "esp_ranking_estabelecimentos"):
            is_vinc = report_key == "esp_ranking_vinculos"
            cubo = "rais_vinculos" if is_vinc else "rais_estabelecimentos"
            metric_lbl = "Vínculos Trabalhistas" if is_vinc else "Estabelecimentos"
            theme = "wine" if is_vinc else "green"
            chart_color = "#7a1c1c" if is_vinc else "#14532d"
            slug = f"{'vinculos' if is_vinc else 'estabelecimentos'}_{uf_clean}_{y_tag}"

            data_by_y, m_names, m_ufs = fetch_municipal_series(cubo, years_asc, f"RAIS {metric_lbl}")
            all_cds = sorted(m_names.keys())
            tot_uf = {y: sum(data_by_y[y].values()) for y in years_asc}

            top_cds = sorted(
                all_cds,
                key=lambda c: (data_by_y[y_last].get(c, 0.0), data_by_y[y_first].get(c, 0.0)),
                reverse=True,
            )[:top_n]

            has_multi = len(years_asc) >= 2
            headers = ["Classif.*", "Município"] + years_desc + ([var_col_label] if has_multi else [f"% em {y_last}"])
            rows: List[List[str]] = []
            sub_y = {y: 0.0 for y in years_desc}
            chart_items: List[Dict[str, Any]] = []

            for r_idx, cd in enumerate(top_cds, start=1):
                nm = m_names.get(cd, cd)
                if uf_clean == "BR":
                    nm = f"{nm} ({m_ufs.get(cd, '')})"
                vals_desc = [fmt_int_br(data_by_y[y].get(cd, 0.0)) for y in years_desc]
                for y in years_desc:
                    sub_y[y] += data_by_y[y].get(cd, 0.0)
                v_last = data_by_y[y_last].get(cd, 0.0)
                v_first = data_by_y[y_first].get(cd, 0.0)
                share_last = (v_last / tot_uf[y_last] * 100.0) if tot_uf[y_last] > 0 else 0.0

                if has_multi:
                    var_s = fmt_var_pct_br(v_first, v_last)
                    rows.append([f"{r_idx}º", nm] + vals_desc + [var_s])
                    annot = f"{fmt_float_br(share_last, 1)}% | {var_s}"
                else:
                    var_s = ""
                    pct_s = f"{fmt_float_br(share_last, 1)}%"
                    rows.append([f"{r_idx}º", nm] + vals_desc + [pct_s])
                    annot = pct_s

                chart_items.append({
                    "name": f"{r_idx}º {nm}",
                    "value": v_last,
                    "annot": annot,
                    "var_str": var_s,
                    "by_year": {y: data_by_y[y].get(cd, 0.0) for y in years_asc},
                })

            pct_sub_last = (sub_y[y_last] / tot_uf[y_last] * 100.0) if tot_uf[y_last] > 0 else 0.0
            if has_multi:
                rows.append(
                    ["—", f"Subtotal (Top {len(top_cds)} — {fmt_float_br(pct_sub_last, 1)}%)"]
                    + [fmt_int_br(sub_y[y]) for y in years_desc]
                    + [fmt_var_pct_br(sub_y[y_first], sub_y[y_last])]
                )
                rows.append(
                    ["—", f"Total {uf_name} (100%)"]
                    + [fmt_int_br(tot_uf[y]) for y in years_desc]
                    + [fmt_var_pct_br(tot_uf[y_first], tot_uf[y_last])]
                )
            else:
                rows.append(
                    ["—", f"Subtotal (Top {len(top_cds)})", fmt_int_br(sub_y[y_last]), f"{fmt_float_br(pct_sub_last, 1)}%"]
                )
                rows.append(
                    ["—", f"Total {uf_name}", fmt_int_br(tot_uf[y_last]), "100,0%"]
                )

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_ranking_{slug}",
                    title=f"{uf_name}: Top {len(top_cds)} Municípios em {metric_lbl} — {sector_label} ({', '.join(years_desc)})",
                    subtitle=f"Ranking Top {len(top_cds)} Municípios em {metric_lbl}",
                    headers=headers,
                    rows=rows,
                    footer_row_indices=[len(rows) - 2, len(rows) - 1],
                    var_col_indices=[len(headers) - 1] if has_multi else [],
                    theme=theme,
                    footnote=f"*Ordenado pelo ano {y_last}. Fonte: MTE — DardoWeb (RAIS {metric_lbl}, {sector_label}).",
                )
            )
            years_title_str = ", ".join(years_asc) if has_multi else y_last
            bundle.chart_payloads.append({
                "chart_id": f"grafico_ranking_{slug}",
                "title": f"Top {len(top_cds)} Municípios em {metric_lbl} ({years_title_str}) — {uf_name}",
                "subtitle": f"Recorte: {sector_label}",
                "type": "ranking_horizontal_bars",
                "years": years_asc,
                "rank_style": rank_chart_style,
                "items": chart_items,
                "color": chart_color,
                "unit": "INT",
                "xlabel": f"Quantidade de {metric_lbl} ({years_title_str})" if has_multi else f"Quantidade de {metric_lbl} em {y_last}",
                "footnote": (
                    f"Fonte: MTE — DardoWeb (RAIS {years_title_str}). Ordenado por {y_last}; variação calculada entre {y_first} e {y_last}."
                    if has_multi
                    else f"Fonte: MTE — DardoWeb (RAIS {y_last}). Participação calculada sobre o total de {uf_name}."
                ),
            })
            return bundle

        elif report_key == "esp_quadro_global":
            vinc_by_y, _, _ = fetch_municipal_series("rais_vinculos", years_asc, "RAIS Vínculos")
            estab_by_y, _, _ = fetch_municipal_series("rais_estabelecimentos", years_asc, "RAIS Estabelecimentos")
            tot_v = {y: sum(vinc_by_y[y].values()) for y in years_asc}
            tot_e = {y: sum(estab_by_y[y].values()) for y in years_asc}
            porte = {y: (tot_v[y] / tot_e[y]) if tot_e[y] > 0 else 0.0 for y in years_asc}

            has_multi = len(years_asc) >= 2
            headers = [f"Indicador ({uf_name})"] + years_asc + ([var_col_label] if has_multi else [])
            r_v = ["Vínculos Trabalhistas"] + [fmt_int_br(tot_v[y]) for y in years_asc]
            r_e = ["Nº de Estabelecimentos (Plantas)"] + [fmt_int_br(tot_e[y]) for y in years_asc]
            r_p = ["Porte Médio (Vínculos / Estab.)"] + [fmt_float_br(porte[y], 1) for y in years_asc]
            if has_multi:
                r_v.append(fmt_var_pct_br(tot_v[y_first], tot_v[y_last]))
                r_e.append(fmt_var_pct_br(tot_e[y_first], tot_e[y_last]))
                r_p.append(fmt_var_pct_br(porte[y_first], porte[y_last]))

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_evolucao_global_{uf_clean}_{y_tag}",
                    title=f"Quadro Global de Vínculos, Estabelecimentos e Porte Médio — {uf_name}",
                    subtitle=f"Quadro de Evolução Global ({', '.join(years_asc)})",
                    headers=headers,
                    rows=[r_v, r_e, r_p],
                    var_col_indices=[len(headers) - 1] if has_multi else [],
                    theme="navy",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS Vínculos e Estabelecimentos, {sector_label}).",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_evolucao_global_{uf_clean}_{y_tag}",
                "title": f"Vínculos Trabalhistas e Nº de Estabelecimentos — {uf_name}",
                "subtitle": f"{sector_label} | Porte Médio em {y_last}: {fmt_float_br(porte[y_last], 1)} vínc./estab.",
                "type": "dual_axis_evolution",
                "years": years_asc,
                "vinc_vals": [tot_v[y] for y in years_asc],
                "estab_vals": [tot_e[y] for y in years_asc],
                "porte_vals": [porte[y] for y in years_asc],
                "footnote": f"Fonte: MTE — DardoWeb ({sector_label}).",
            })
            return bundle

        elif report_key == "esp_sintese_regional":
            # Consulta apenas o ano mais recente selecionado (y_last) para retrato regional de escala e participação
            vinc_by_y, m_names, _ = fetch_municipal_series("rais_vinculos", [y_last], "RAIS Vínculos")
            estab_by_y, m_names_e, _ = fetch_municipal_series("rais_estabelecimentos", [y_last], "RAIS Estabelecimentos")
            all_cds = sorted(set(m_names.keys()) | set(m_names_e.keys()))

            tot_v = sum(vinc_by_y[y_last].values())
            tot_e = sum(estab_by_y[y_last].values())
            porte_uf = (tot_v / tot_e) if tot_e > 0 else 0.0

            reg_v: Dict[str, float] = {}
            reg_e: Dict[str, float] = {}
            for cd in all_cds:
                rn = self._get_region_name(cd, region_mode)
                reg_v[rn] = reg_v.get(rn, 0.0) + vinc_by_y[y_last].get(cd, 0.0)
                reg_e[rn] = reg_e.get(rn, 0.0) + estab_by_y[y_last].get(cd, 0.0)

            sorted_regs = sorted(reg_v.keys(), key=lambda r: (reg_v.get(r, 0.0), reg_e.get(r, 0.0)), reverse=True)
            rows = []
            c_labels, c_pv, c_pe, c_pm = [], [], [], []
            for rn in sorted_regs:
                vv = reg_v.get(rn, 0.0)
                ee = reg_e.get(rn, 0.0)
                if vv <= 0 and ee <= 0:
                    continue
                pv = (vv / tot_v * 100.0) if tot_v > 0 else 0.0
                pe = (ee / tot_e * 100.0) if tot_e > 0 else 0.0
                pm = (vv / ee) if ee > 0 else 0.0
                rows.append([
                    rn,
                    fmt_int_br(vv),
                    f"{fmt_float_br(pv, 1)}%",
                    fmt_int_br(ee),
                    f"{fmt_float_br(pe, 1)}%",
                    f"{fmt_float_br(pm, 1)} vínc./planta",
                ])
                c_labels.append(rn)
                c_pv.append(pv)
                c_pe.append(pe)
                c_pm.append(pm)

            rows.append([
                f"Total / Média {uf_name}",
                fmt_int_br(tot_v),
                "100,0%",
                fmt_int_br(tot_e),
                "100,0%",
                f"{fmt_float_br(porte_uf, 1)} vínc./planta",
            ])

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_regioes_{region_mode}_{uf_clean}_{y_last}",
                    title=f"Distribuição Regional por {region_type_label} em {y_last} — {uf_name}",
                    subtitle=f"Síntese por {region_type_label} ({y_last})",
                    headers=[region_type_label, f"Vínculos ({y_last})", "% Vínc.", f"Estab. ({y_last})", "% Estab.", "Porte Médio"],
                    rows=rows,
                    footer_row_indices=[len(rows) - 1],
                    theme="navy",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS {y_last}, {sector_label}) integrado à malha regional do IBGE.",
                )
            )

            p_part = {
                "chart_id": f"grafico_regioes_participacao_{uf_clean}_{y_last}",
                "title": f"Participação por {region_type_label} em {y_last} (%)",
                "subtitle": f"{uf_name} — {sector_label}",
                "type": "meso_grouped_bars",
                "labels": c_labels[:12],
                "pct_vinc": c_pv[:12],
                "pct_estab": c_pe[:12],
                "uf": uf_clean,
                "year": y_last,
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {y_last}) e IBGE.",
            }
            p_porte = {
                "chart_id": f"grafico_regioes_porte_{uf_clean}_{y_last}",
                "title": f"Porte Médio por {region_type_label} em {y_last} (Vínc./Estab.)",
                "subtitle": f"{uf_name} — {sector_label}",
                "type": "meso_porte_bars",
                "labels": c_labels[:12],
                "porte_vals": c_pm[:12],
                "state_avg": porte_uf,
                "uf": uf_clean,
                "year": y_last,
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {y_last}) e IBGE.",
            }

            if regional_subview == "apenas_participacao":
                bundle.chart_payloads.append(p_part)
            elif regional_subview == "apenas_porte":
                bundle.chart_payloads.append(p_porte)
            else:
                p_part["chart_id"] = f"{uf_clean}_{y_last}_meso_participacao_painel"
                p_part["combined_filename"] = f"painel_regional_{region_mode}_{uf_clean}_{y_last}.png"
                p_porte["chart_id"] = f"{uf_clean}_{y_last}_meso_porte_painel"
                bundle.chart_payloads.extend([p_part, p_porte])
            return bundle

        elif report_key == "esp_evolucao_regional":
            vinc_by_y, m_names, _ = fetch_municipal_series("rais_vinculos", years_asc, "RAIS Vínculos")
            reg_series: Dict[str, Dict[str, float]] = {}
            for cd in m_names:
                rn = self._get_region_name(cd, region_mode)
                if rn not in reg_series:
                    reg_series[rn] = {y: 0.0 for y in years_asc}
                for y in years_asc:
                    reg_series[rn][y] += vinc_by_y[y].get(cd, 0.0)

            tot_y = {y: sum(vinc_by_y[y].values()) for y in years_asc}
            sorted_regs = sorted(reg_series.keys(), key=lambda r: reg_series[r].get(y_last, 0.0), reverse=True)
            active_regs = [r for r in sorted_regs if any(reg_series[r][y] > 0 for y in years_asc)][:12]

            has_multi = len(years_asc) >= 2
            headers = [region_type_label] + years_asc + ([var_col_label, f"% em {y_last}"] if has_multi else [f"% em {y_last}"])
            rows = []
            for rn in active_regs:
                vals = [fmt_int_br(reg_series[rn][y]) for y in years_asc]
                sh = (reg_series[rn][y_last] / tot_y[y_last] * 100.0) if tot_y[y_last] > 0 else 0.0
                if has_multi:
                    rows.append([rn] + vals + [fmt_var_pct_br(reg_series[rn][y_first], reg_series[rn][y_last]), f"{fmt_float_br(sh, 1)}%"])
                else:
                    rows.append([rn] + vals + [f"{fmt_float_br(sh, 1)}%"])

            tot_row = [f"Total {uf_name}"] + [fmt_int_br(tot_y[y]) for y in years_asc]
            if has_multi:
                tot_row.extend([fmt_var_pct_br(tot_y[y_first], tot_y[y_last]), "100,0%"])
            else:
                tot_row.append("100,0%")
            rows.append(tot_row)

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_evolucao_regional_{region_mode}_{uf_clean}_{y_tag}",
                    title=f"Evolução de Vínculos por {region_type_label} — {uf_name}",
                    subtitle=f"Evolução Regional ({', '.join(years_asc)})",
                    headers=headers,
                    rows=rows,
                    footer_row_indices=[len(rows) - 1],
                    var_col_indices=[len(headers) - 2] if has_multi else [],
                    theme="navy",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS Vínculos, {sector_label}) e IBGE.",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_evolucao_regional_{region_mode}_{uf_clean}_{y_tag}",
                "title": f"Vínculos Trabalhistas por {region_type_label} — {uf_name}",
                "subtitle": f"{sector_label} ({', '.join(years_asc)})",
                "type": "multi_year_category_bars",
                "categories": active_regs,
                "years": years_asc,
                "series": {y: [reg_series[r][y] for r in active_regs] for y in years_asc},
                "raw_values_last": [reg_series[r][y_last] for r in active_regs],
                "raw_total_last": tot_y[y_last],
                "unit": "INT",
                "ylabel": "Vínculos Trabalhistas",
                "footnote": f"Fonte: MTE — DardoWeb e IBGE.",
            })
            return bundle

        elif report_key == "esp_saldo_variacao_municipal":
            if len(years_asc) < 2:
                raise ValueError("Selecione pelo menos 2 anos na grade de anos para calcular o saldo e a variação entre períodos.")
            vinc_by_y, m_names, m_ufs = fetch_municipal_series("rais_vinculos", [y_first, y_last], "RAIS Vínculos")
            deltas = []
            for cd, nm in m_names.items():
                v0 = vinc_by_y[y_first].get(cd, 0.0)
                v1 = vinc_by_y[y_last].get(cd, 0.0)
                if v0 == 0 and v1 == 0:
                    continue
                lbl = f"{nm} ({m_ufs.get(cd, '')})" if uf_clean == "BR" else nm
                deltas.append((cd, lbl, v1 - v0, v0, v1))

            deltas_sorted = sorted(deltas, key=lambda x: x[2], reverse=True)
            half_n = max(4, top_n // 2)
            top_gains = [d for d in deltas_sorted if d[2] > 0][:half_n]
            top_losses = sorted([d for d in deltas_sorted if d[2] < 0], key=lambda x: x[2])[:half_n]
            combined = top_gains + list(reversed(top_losses))

            rows = [
                [
                    nm,
                    fmt_int_br(v0),
                    fmt_int_br(v1),
                    f"{'+' if diff > 0 else ''}{fmt_int_br(diff)}",
                    fmt_var_pct_br(v0, v1),
                ]
                for _, nm, diff, v0, v1 in combined
            ]
            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_saldo_municipal_{uf_clean}_{y_first}_{y_last}",
                    title=f"Maiores Expansões e Retrações Municipais de Vínculos ({y_first}–{y_last}) — {uf_name}",
                    subtitle=f"Saldo e Variação Municipal ({y_first}–{y_last})",
                    headers=["Município", y_first, y_last, f"Saldo ({y_first}–{y_last})", var_col_label],
                    rows=rows,
                    var_col_indices=[3, 4],
                    theme="wine",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS Vínculos, {sector_label}).",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_saldo_municipal_{uf_clean}_{y_first}_{y_last}",
                "title": f"Saldo Líquido e Variação % de Vínculos por Município ({y_first}–{y_last})",
                "subtitle": f"{uf_name} — {sector_label}",
                "type": "diverging_bars",
                "items": [{"name": nm, "diff": diff, "pct_str": fmt_var_pct_br(v0, v1)} for _, nm, diff, v0, v1 in combined],
                "footnote": f"Fonte: MTE — DardoWeb (RAIS Vínculos, {y_first} e {y_last}).",
            })
            return bundle

        elif report_key == "esp_dispersao_escala":
            vinc_by_y, m_names, _ = fetch_municipal_series("rais_vinculos", [y_last], "RAIS Vínculos")
            estab_by_y, m_names_e, _ = fetch_municipal_series("rais_estabelecimentos", [y_last], "RAIS Estabelecimentos")
            all_cds = sorted(set(m_names.keys()) | set(m_names_e.keys()))
            tot_v = sum(vinc_by_y[y_last].values())
            tot_e = sum(estab_by_y[y_last].values())
            porte_uf = (tot_v / tot_e) if tot_e > 0 else 0.0

            pts = []
            for cd in all_cds:
                vv = vinc_by_y[y_last].get(cd, 0.0)
                ee = estab_by_y[y_last].get(cd, 0.0)
                if vv > 0 or ee > 0:
                    nm = m_names.get(cd) or m_names_e.get(cd, cd)
                    rn = self._get_region_name(cd, region_mode)
                    pts.append({"name": nm, "estab": ee, "vinc": vv, "porte": (vv / ee) if ee > 0 else 0.0, "region": rn})

            top_porte = sorted([p for p in pts if p["estab"] >= 1], key=lambda x: (x["porte"], x["vinc"]), reverse=True)[:top_n]
            rows = [
                [f"{i}º", p["name"], p["region"], fmt_int_br(p["vinc"]), fmt_int_br(p["estab"]), f"{fmt_float_br(p['porte'], 1)} vínc./planta"]
                for i, p in enumerate(top_porte, start=1)
            ]
            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_escala_tecnica_{uf_clean}_{y_last}",
                    title=f"Municípios com Maior Escala Técnica (Vínculos por Planta) em {y_last} — {uf_name}",
                    subtitle=f"Escala Técnica Municipal ({y_last})",
                    headers=["Classif.", "Município", region_type_label, f"Vínculos ({y_last})", f"Plantas ({y_last})", "Porte Médio"],
                    rows=rows,
                    theme="navy",
                    footnote=f"Média {uf_name}: {fmt_float_br(porte_uf, 1)} vínc./planta. Fonte: MTE — DardoWeb ({y_last}, {sector_label}).",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_dispersao_escala_{uf_clean}_{y_last}",
                "title": f"Escala Técnica Municipal em {y_last}: Nº de Plantas × Vínculos",
                "subtitle": f"{uf_name} — {sector_label} (Linha tracejada = Média {uf_clean}: {fmt_float_br(porte_uf, 1)} vínc./planta)",
                "type": "scatter_scale",
                "points": pts,
                "state_avg": porte_uf,
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {y_last}) e IBGE.",
            })
            return bundle

        elif report_key == "esp_concentracao_cr":
            vinc_by_y, _, _ = fetch_municipal_series("rais_vinculos", years_asc, "RAIS Vínculos")
            cr4_l, cr5_10_l, rest_l, rows = [], [], [], []
            for y in years_asc:
                vals = sorted(vinc_by_y[y].values(), reverse=True)
                tot = sum(vals)
                c4 = (sum(vals[:4]) / tot * 100.0) if tot > 0 else 0.0
                c5_10 = (sum(vals[4:10]) / tot * 100.0) if tot > 0 else 0.0
                c10 = c4 + c5_10
                rest = max(0.0, 100.0 - c10)
                cr4_l.append(c4)
                cr5_10_l.append(c5_10)
                rest_l.append(rest)
                rows.append([
                    y,
                    fmt_int_br(tot),
                    f"{fmt_float_br(c4, 1)}%",
                    f"{fmt_float_br(c5_10, 1)}%",
                    f"{fmt_float_br(c10, 1)}%",
                    f"{fmt_float_br(rest, 1)}%",
                ])

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_concentracao_espacial_{uf_clean}_{y_tag}",
                    title=f"Razão de Concentração Espacial do Emprego (CR4 e CR10) — {uf_name}",
                    subtitle=f"Concentração Espacial CR4 e CR10 ({', '.join(years_asc)})",
                    headers=["Ano", "Total de Vínculos", "Top 4 (CR4)", "5º ao 10º Mun.", "Top 10 (CR10)", "Demais Municípios"],
                    rows=rows,
                    theme="wine",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS Vínculos, {sector_label}).",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_concentracao_espacial_{uf_clean}_{y_tag}",
                "title": f"Concentração Espacial do Emprego em {uf_name} ({', '.join(years_asc)})",
                "subtitle": f"Participação dos 4 maiores (CR4), 5º ao 10º e demais municípios ({sector_label})",
                "type": "stacked_concentration",
                "years": years_asc,
                "cr4": cr4_l,
                "cr5_10": cr5_10_l,
                "rest": rest_l,
                "footnote": f"Fonte: MTE — DardoWeb (RAIS Vínculos).",
            })
            return bundle

        # ==================================================================
        # SUB-ABA 2 E SUB-ABA 4: DIMENSÕES CATEGÓRICAS (PERFIL E ESTRUTURA)
        # ==================================================================
        categorical_specs: Dict[str, Tuple[str, str, str, bool]] = {
            # report_key: (dardo_col, human_title, slug_prefix, sort_by_value)
            "perf_sexo": ("Sexo Trabalhador", "Divisão por Sexo do Trabalhador", "sexo_trabalhador", False),
            "perf_escolaridade": ("Escolaridade após 2005", "Escolaridade Detalhada dos Trabalhadores", "escolaridade_detalhada", False),
            "perf_escolaridade_agrupada": ("Escolaridade após 2005", "Escolaridade por Grandes Níveis", "escolaridade_agrupada", False),
            "perf_faixa_etaria": ("Faixa Etária", "Estrutura Etária dos Trabalhadores", "faixa_etaria", False),
            "perf_nacionalidade": ("Nacionalidade", "Trabalhadores por Nacionalidade", "nacionalidade", True),
            "perf_tipo_vinculo": ("Tipo Vínculo", "Trabalhadores por Tipo de Vínculo", "tipo_vinculo", True),
            "rem_faixas_salariais": ("Faixa Remun Média (SM)", "Trabalhadores por Faixa Salarial (SM)", "faixas_salariais", False),
            "est_porte_evolucao": ("Tamanho Estabelecimento", "Vínculos por Porte do Estabelecimento", "porte_evolucao", False),
            "est_tempo_emprego": ("Faixa Tempo Emprego", "Trabalhadores por Tempo de Permanência no Emprego", "tempo_emprego", False),
            "est_natureza_juridica": ("Natureza Jurídica", "Distribuição por Natureza Jurídica", "natureza_juridica", True),
            "est_ocupacoes_cbo": ("CBO 2002 Gr Grupo", "Grandes Grupos Ocupacionais (CBO 2002)", "ocupacoes_cbo", True),
            "est_jornada_horas": ("Faixa Hora Contrat", "Trabalhadores por Faixa de Horas Contratadas", "jornada_horas", False),
            "est_simples_nacional": ("Ind Simples", "Adesão ao Simples Nacional (Sim vs. Não)", "simples_nacional", False),
        }

        if report_key in categorical_specs:
            dardo_col, human_title, slug_prefix, sort_desc = categorical_specs[report_key]
            cubo_use = base_cubo_override if report_key in ("est_natureza_juridica", "est_simples_nacional") else "rais_vinculos"
            unit_lbl = "Estabelecimentos" if cubo_use == "rais_estabelecimentos" else "Vínculos Trabalhistas"

            totals_by_year: Dict[str, Dict[str, float]] = {}
            ordered_keys: List[str] = []

            for idx, y in enumerate(years_asc, start=1):
                if prog_cb:
                    prog_cb(
                        int(12 + (idx / max(1, len(years_asc))) * 75),
                        f"Consultando {human_title} ({uf_clean}) — Ano {y}...",
                    )
                res_c = self.client.query_dardo(
                    base_cubo=cubo_use,
                    ano=y,
                    uf=uf_clean,
                    coluna_cruzamento=dardo_col,
                    indicador="->Frequência",
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                )
                raw_map = self._extract_category_totals(res_c)
                if report_key == "perf_escolaridade_agrupada":
                    raw_map = self._group_schooling_5_tiers(raw_map)
                totals_by_year[y] = raw_map
                for k in raw_map:
                    if k not in ordered_keys:
                        ordered_keys.append(k)

            if report_key == "perf_nacionalidade" and only_foreigners:
                ordered_keys = [
                    k for k in ordered_keys
                    if not any(b in k.lower() for b in ("brasileir", "total", "{ñ"))
                ]
                human_title = "Trabalhadores Estrangeiros / Imigrantes por Nacionalidade"

            active_cats = [
                k for k in ordered_keys
                if any(totals_by_year[y].get(k, 0.0) > 0 for y in years_asc)
            ]
            if sort_desc:
                active_cats.sort(key=lambda k: totals_by_year[y_last].get(k, 0.0), reverse=True)
            active_cats = active_cats[:max_categories]

            if not active_cats:
                raise ValueError("Nenhum registro encontrado para os filtros e anos selecionados.")

            has_multi = len(years_asc) >= 2
            tot_per_y = {y: sum(totals_by_year[y].get(c, 0.0) for c in active_cats) for y in years_asc}

            t_headers = ["Categoria"] + years_asc + ([var_col_label, f"% em {y_last}"] if has_multi else [f"% em {y_last}"])
            t_rows = []
            for c in active_cats:
                vals_str = [fmt_int_br(totals_by_year[y].get(c, 0.0)) for y in years_asc]
                v_last = totals_by_year[y_last].get(c, 0.0)
                v_first = totals_by_year[y_first].get(c, 0.0)
                sh_last = (v_last / tot_per_y[y_last] * 100.0) if tot_per_y[y_last] > 0 else 0.0
                if has_multi:
                    t_rows.append([c] + vals_str + [fmt_var_pct_br(v_first, v_last), f"{fmt_float_br(sh_last, 1)}%"])
                else:
                    t_rows.append([c] + vals_str + [f"{fmt_float_br(sh_last, 1)}%"])

            tot_row = ["Total"] + [fmt_int_br(tot_per_y[y]) for y in years_asc]
            if has_multi:
                tot_row.extend([fmt_var_pct_br(tot_per_y[y_first], tot_per_y[y_last]), "100,0%"])
            else:
                tot_row.append("100,0%")
            t_rows.append(tot_row)

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_{slug_prefix}_{uf_clean}_{y_tag}",
                    title=f"{human_title} — {uf_name} ({', '.join(years_asc)})",
                    subtitle=f"{human_title} ({', '.join(years_asc)})",
                    headers=t_headers,
                    rows=t_rows,
                    footer_row_indices=[len(t_rows) - 1],
                    var_col_indices=[len(t_headers) - 2] if has_multi else [],
                    theme="navy",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS {unit_lbl}, {sector_label}).",
                )
            )

            if chart_style == "donut":
                bundle.chart_payloads.append({
                    "chart_id": f"grafico_{slug_prefix}_proporcao_{uf_clean}_{y_last}",
                    "title": f"{human_title} em {y_last} — {uf_name}",
                    "subtitle": f"Recorte: {sector_label}",
                    "type": "donut_chart",
                    "categories": active_cats,
                    "values": [totals_by_year[y_last].get(c, 0.0) for c in active_cats],
                    "footnote": f"Fonte: MTE — DardoWeb (RAIS {y_last}).",
                })
            elif chart_style == "bars_pct":
                pct_series = {
                    y: [
                        (totals_by_year[y].get(c, 0.0) / tot_per_y[y] * 100.0) if tot_per_y[y] > 0 else 0.0
                        for c in active_cats
                    ]
                    for y in years_asc
                }
                bundle.chart_payloads.append({
                    "chart_id": f"grafico_{slug_prefix}_pct_{uf_clean}_{y_tag}",
                    "title": f"{human_title} (%) — {uf_name}",
                    "subtitle": f"{sector_label} ({', '.join(years_asc)})",
                    "type": "multi_year_category_bars",
                    "categories": active_cats,
                    "years": years_asc,
                    "series": pct_series,
                    "unit": "PCT",
                    "ylabel": f"Participação no Total de {unit_lbl} (%)",
                    "footnote": f"Fonte: MTE — DardoWeb ({sector_label}).",
                })
            else:
                abs_series = {
                    y: [totals_by_year[y].get(c, 0.0) for c in active_cats]
                    for y in years_asc
                }
                bundle.chart_payloads.append({
                    "chart_id": f"grafico_{slug_prefix}_{uf_clean}_{y_tag}",
                    "title": f"{human_title} — {uf_name}",
                    "subtitle": f"{sector_label} ({', '.join(years_asc)})",
                    "type": "multi_year_category_bars",
                    "categories": active_cats,
                    "years": years_asc,
                    "series": abs_series,
                    "raw_values_last": abs_series[y_last],
                    "raw_total_last": tot_per_y[y_last],
                    "unit": "INT",
                    "ylabel": unit_lbl,
                    "footnote": f"Fonte: MTE — DardoWeb ({sector_label}).",
                })
            return bundle

        # ==================================================================
        # SUB-ABA 4 (ITEM COMPARATIVO ESPECIAL): PORTE VÍNCULOS VS. PLANTAS
        # ==================================================================
        if report_key == "est_porte_comparativo":
            if prog_cb:
                prog_cb(25, f"Consultando Vínculos por Tamanho do Estabelecimento ({y_last})...")
            res_pv = self.client.query_dardo(
                base_cubo="rais_vinculos",
                ano=y_last,
                uf=uf_clean,
                coluna_cruzamento="Tamanho Estabelecimento",
                indicador="->Frequência",
                filtro_atividade=filtro_texto,
                filtro_cnae_nivel=eff_nivel,
                filtro_cnae_codigo=filtro_codigo,
            )
            if prog_cb:
                prog_cb(65, f"Consultando Plantas por Tamanho do Estabelecimento ({y_last})...")
            res_pe = self.client.query_dardo(
                base_cubo="rais_estabelecimentos",
                ano=y_last,
                uf=uf_clean,
                coluna_cruzamento="Tamanho Estabelecimento",
                indicador="->Frequência",
                filtro_atividade=filtro_texto,
                filtro_cnae_nivel=eff_nivel,
                filtro_cnae_codigo=filtro_codigo,
            )
            pv_map = self._extract_category_totals(res_pv)
            pe_map = self._extract_category_totals(res_pe)
            cats = list(pv_map.keys())
            for k in pe_map:
                if k not in cats:
                    cats.append(k)
            active = [c for c in cats if pv_map.get(c, 0.0) > 0 or pe_map.get(c, 0.0) > 0]
            tot_v = sum(pv_map.get(c, 0.0) for c in active)
            tot_e = sum(pe_map.get(c, 0.0) for c in active)

            rows, pct_v, pct_e = [], [], []
            for c in active:
                vv = pv_map.get(c, 0.0)
                ee = pe_map.get(c, 0.0)
                sv = (vv / tot_v * 100.0) if tot_v > 0 else 0.0
                se = (ee / tot_e * 100.0) if tot_e > 0 else 0.0
                pct_v.append(sv)
                pct_e.append(se)
                rows.append([c, fmt_int_br(vv), f"{fmt_float_br(sv, 1)}%", fmt_int_br(ee), f"{fmt_float_br(se, 1)}%"])
            rows.append(["Total", fmt_int_br(tot_v), "100,0%", fmt_int_br(tot_e), "100,0%"])

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_porte_estabelecimentos_{uf_clean}_{y_last}",
                    title=f"Concentração por Porte do Estabelecimento em {y_last} — {uf_name}",
                    subtitle=f"Porte dos Estabelecimentos: Vínculos vs. Plantas ({y_last})",
                    headers=["Faixa de Tamanho da Planta", f"Vínculos ({y_last})", "% Vínculos", f"Plantas ({y_last})", "% Plantas"],
                    rows=rows,
                    footer_row_indices=[len(rows) - 1],
                    theme="green",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS Vínculos e Estabelecimentos {y_last}, {sector_label}).",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_porte_estabelecimentos_{uf_clean}_{y_last}",
                "title": f"Distribuição por Faixa de Tamanho da Planta em {y_last} (% Vínculos vs. % Plantas)",
                "subtitle": f"{uf_name} — {sector_label}",
                "type": "meso_grouped_bars",
                "labels": active,
                "pct_vinc": pct_v,
                "pct_estab": pct_e,
                "uf": uf_clean,
                "year": y_last,
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {y_last}).",
            })
            return bundle

        # ==================================================================
        # SUB-ABA 3: REMUNERAÇÃO E RENDA
        # ==================================================================
        indic_sal = "Vl Remun Média Nom" if wage_unit == "BRL" else "Vl Remun Média (SM)"
        unit_code = "BRL" if wage_unit == "BRL" else "SM"
        unit_desc = "Reais (R$)" if wage_unit == "BRL" else "Salários Mínimos (SM)"

        def fmt_w(val: float) -> str:
            return f"R$ {fmt_float_br(val, 2)}" if unit_code == "BRL" else f"{fmt_float_br(val, 2)} SM"

        if report_key == "rem_evolucao_geral":
            sal_by_y: Dict[str, float] = {}
            for idx, y in enumerate(years_asc, start=1):
                if prog_cb:
                    prog_cb(int(15 + (idx / max(1, len(years_asc))) * 70), f"Consultando Remuneração Média ({unit_desc}) — Ano {y}...")
                res_s = self.client.query_dardo(
                    base_cubo="rais_vinculos",
                    ano=y,
                    uf=uf_clean,
                    coluna_cruzamento="---------Não---------",
                    indicador=indic_sal,
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                    operacao="Média",
                )
                avg_v = float(res_s.summary_totals.get("__TOTAL_GERAL__") or 0.0)
                if avg_v <= 0 and res_s.records:
                    pos = [float(r.get("TOTAL_GERAL") or 0.0) for r in res_s.records if float(r.get("TOTAL_GERAL") or 0.0) > 0]
                    avg_v = (sum(pos) / len(pos)) if pos else 0.0
                sal_by_y[y] = avg_v

            has_multi = len(years_asc) >= 2
            headers = [f"Indicador ({uf_name})"] + years_asc + ([var_col_label] if has_multi else [])
            row_vals = [f"Remuneração Média ({unit_desc})"] + [fmt_w(sal_by_y[y]) for y in years_asc]
            if has_multi:
                row_vals.append(fmt_var_pct_br(sal_by_y[y_first], sal_by_y[y_last]))

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_remuneracao_media_{unit_code.lower()}_{uf_clean}_{y_tag}",
                    title=f"Remuneração Média em {unit_desc} — {uf_name} ({', '.join(years_asc)})",
                    subtitle=f"Remuneração Média Geral ({', '.join(years_asc)})",
                    headers=headers,
                    rows=[row_vals],
                    var_col_indices=[len(headers) - 1] if has_multi else [],
                    theme="navy",
                    footnote=f"Nota: Valores nominais correntes de cada ano (RAIS). Fonte: MTE — DardoWeb ({sector_label})." if unit_code == "BRL" else f"Fonte: MTE — DardoWeb (RAIS Vínculos, {sector_label}).",
                )
            )
            step_vars_sal: List[str] = [""]
            for idx_y in range(1, len(years_asc)):
                step_vars_sal.append(fmt_var_pct_br(sal_by_y[years_asc[idx_y - 1]], sal_by_y[years_asc[idx_y]]))

            total_var_sal = f" | Variação {y_first}–{y_last}: {fmt_var_pct_br(sal_by_y[y_first], sal_by_y[y_last])}" if has_multi else ""
            bundle.chart_payloads.append({
                "chart_id": f"grafico_remuneracao_media_{unit_code.lower()}_{uf_clean}_{y_tag}",
                "title": f"Remuneração Média dos Trabalhadores ({unit_desc}) — {uf_name}",
                "subtitle": f"Recorte: {sector_label}{total_var_sal}",
                "type": "temporal_series_bars",
                "years": years_asc,
                "values": [sal_by_y[y] for y in years_asc],
                "step_vars": step_vars_sal,
                "color": "#0f2c59",
                "unit": unit_code,
                "ylabel": f"Remuneração Média ({unit_desc})",
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {', '.join(years_asc)}). Taxas percentuais indicam a variação entre os anos selecionados.",
            })
            return bundle

        elif report_key == "rem_diferencial_sexo":
            if rem_scope == "regiao_ibge":
                # Diferencial salarial Homens vs. Mulheres por Região do IBGE ponderado pelo nº de vínculos no ano mais recente
                if prog_cb:
                    prog_cb(25, f"Consultando Remuneração por Sexo e Município ({y_last})...")
                res_sal = self.client.query_dardo(
                    base_cubo="rais_vinculos",
                    ano=y_last,
                    uf=uf_clean,
                    coluna_cruzamento="Sexo Trabalhador",
                    indicador=indic_sal,
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                    operacao="Média",
                )
                if prog_cb:
                    prog_cb(65, f"Consultando Vínculos por Sexo para ponderação regional ({y_last})...")
                res_cnt = self.client.query_dardo(
                    base_cubo="rais_vinculos",
                    ano=y_last,
                    uf=uf_clean,
                    coluna_cruzamento="Sexo Trabalhador",
                    indicador="->Frequência",
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                )
                col_s_m = next((cf for cf, oh in res_sal.col_label_map.items() if "masc" in oh.lower()), None)
                col_s_f = next((cf for cf, oh in res_sal.col_label_map.items() if "fem" in oh.lower()), None)
                col_c_m = next((cf for cf, oh in res_cnt.col_label_map.items() if "masc" in oh.lower()), None)
                col_c_f = next((cf for cf, oh in res_cnt.col_label_map.items() if "fem" in oh.lower()), None)

                cnt_by_mun = {r["CD_MUN_IBGE"]: r for r in res_cnt.records}
                reg_acc: Dict[str, List[float]] = {}  # [sum_sal_m*n_m, n_m, sum_sal_f*n_f, n_f, sum_sal_t*n_t, n_t]
                for r in res_sal.records:
                    cd = r["CD_MUN_IBGE"]
                    rc = cnt_by_mun.get(cd, {})
                    nm_cnt = float(rc.get(col_c_m) or 0.0) if col_c_m else 0.0
                    nf_cnt = float(rc.get(col_c_f) or 0.0) if col_c_f else 0.0
                    nt_cnt = nm_cnt + nf_cnt
                    if nt_cnt <= 0:
                        continue
                    sm_val = float(r.get(col_s_m) or 0.0) if col_s_m else 0.0
                    sf_val = float(r.get(col_s_f) or 0.0) if col_s_f else 0.0
                    st_val = float(r.get("TOTAL_GERAL") or 0.0)
                    rn = self._get_region_name(cd, region_mode)
                    acc = reg_acc.setdefault(rn, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                    acc[0] += sm_val * nm_cnt
                    acc[1] += nm_cnt
                    acc[2] += sf_val * nf_cnt
                    acc[3] += nf_cnt
                    acc[4] += st_val * nt_cnt
                    acc[5] += nt_cnt

                rows, lbls, m_list, f_list = [], [], [], []
                for rn, acc in sorted(reg_acc.items(), key=lambda kv: (kv[1][4] / kv[1][5]) if kv[1][5] > 0 else 0.0, reverse=True):
                    am = (acc[0] / acc[1]) if acc[1] > 0 else 0.0
                    af = (acc[2] / acc[3]) if acc[3] > 0 else 0.0
                    at = (acc[4] / acc[5]) if acc[5] > 0 else 0.0
                    gap = ((af - am) / am * 100.0) if am > 0 and af > 0 else 0.0
                    rows.append([rn, fmt_w(at), fmt_w(am), fmt_w(af), f"{'+' if gap > 0 else ''}{fmt_float_br(gap, 1)}%"])
                    lbls.append(rn)
                    m_list.append(am)
                    f_list.append(af)

                bundle.tables.append(
                    StyledTableSpec(
                        table_id=f"tabela_remuneracao_sexo_{region_mode}_{uf_clean}_{y_last}",
                        title=f"Remuneração Média por Sexo e {region_type_label} em {y_last} — {uf_name}",
                        subtitle=f"Diferencial Salarial por Sexo e {region_type_label} ({y_last})",
                        headers=[region_type_label, f"Média Geral ({y_last})", "Homens", "Mulheres", "Dif. Mulheres/Homens"],
                        rows=rows,
                        var_col_indices=[4],
                        theme="wine",
                        footnote=f"Médias regionais ponderadas pelo número de vínculos ativos. Fonte: MTE — DardoWeb ({y_last}, {sector_label}).",
                    )
                )
                bundle.chart_payloads.append({
                    "chart_id": f"grafico_remuneracao_sexo_{region_mode}_{uf_clean}_{y_last}",
                    "title": f"Remuneração Média por Sexo ({unit_desc}) — {y_last}",
                    "subtitle": f"Homens vs. Mulheres por {region_type_label} ({uf_name} — {sector_label})",
                    "type": "gender_pay_gap_bars",
                    "labels": lbls[:12],
                    "masc_vals": m_list[:12],
                    "fem_vals": f_list[:12],
                    "unit": unit_code,
                    "ylabel": f"Remuneração Média ({unit_desc})",
                    "footnote": f"Fonte: MTE — DardoWeb (RAIS {y_last}) e IBGE.",
                })
                return bundle
            else:
                # Série por Ano na UF/Brasil usando a linha oficial de Total do DardoWeb
                rows, m_list, f_list = [], [], []
                for idx, y in enumerate(years_asc, start=1):
                    if prog_cb:
                        prog_cb(int(15 + (idx / max(1, len(years_asc))) * 75), f"Consultando Remuneração por Sexo ({uf_clean}) — Ano {y}...")
                    res_s = self.client.query_dardo(
                        base_cubo="rais_vinculos",
                        ano=y,
                        uf=uf_clean,
                        coluna_cruzamento="Sexo Trabalhador",
                        indicador=indic_sal,
                        filtro_atividade=filtro_texto,
                        filtro_cnae_nivel=eff_nivel,
                        filtro_cnae_codigo=filtro_codigo,
                        operacao="Média",
                    )
                    h_masc = next((oh for oh in res_s.summary_totals if "masc" in oh.lower()), "Masculino")
                    h_fem = next((oh for oh in res_s.summary_totals if "fem" in oh.lower()), "Feminino")
                    vm = float(res_s.summary_totals.get(h_masc) or 0.0)
                    vf = float(res_s.summary_totals.get(h_fem) or 0.0)
                    vt = float(res_s.summary_totals.get("__TOTAL_GERAL__") or 0.0)
                    gap = ((vf - vm) / vm * 100.0) if vm > 0 and vf > 0 else 0.0
                    rows.append([y, fmt_w(vt), fmt_w(vm), fmt_w(vf), f"{'+' if gap > 0 else ''}{fmt_float_br(gap, 1)}%"])
                    m_list.append(vm)
                    f_list.append(vf)

                bundle.tables.append(
                    StyledTableSpec(
                        table_id=f"tabela_remuneracao_sexo_{unit_code.lower()}_{uf_clean}_{y_tag}",
                        title=f"Remuneração Média por Sexo ({unit_desc}) — {uf_name} ({', '.join(years_asc)})",
                        subtitle=f"Diferencial Salarial Homens vs. Mulheres ({', '.join(years_asc)})",
                        headers=["Ano", "Média Geral", "Homens", "Mulheres", "Dif. Mulheres/Homens"],
                        rows=rows,
                        var_col_indices=[4],
                        theme="wine",
                        footnote=f"Fonte: MTE — DardoWeb (RAIS Vínculos, {sector_label}).",
                    )
                )
                bundle.chart_payloads.append({
                    "chart_id": f"grafico_remuneracao_sexo_{unit_code.lower()}_{uf_clean}_{y_tag}",
                    "title": f"Remuneração Média: Homens vs. Mulheres ({unit_desc}) — {uf_name}",
                    "subtitle": f"Recorte: {sector_label}",
                    "type": "gender_pay_gap_bars",
                    "labels": years_asc,
                    "masc_vals": m_list,
                    "fem_vals": f_list,
                    "unit": unit_code,
                    "ylabel": f"Remuneração Média ({unit_desc})",
                    "footnote": f"Fonte: MTE — DardoWeb (RAIS Vínculos).",
                })
                return bundle

        elif report_key == "rem_por_escolaridade":
            sal_esc_by_y: Dict[str, Dict[str, float]] = {y: {} for y in years_asc}
            tot_sal_by_y: Dict[str, float] = {y: 0.0 for y in years_asc}
            cats_order: List[str] = []
            for idx_y, y in enumerate(years_asc, start=1):
                if prog_cb:
                    prog_cb(int(20 + (idx_y / max(1, len(years_asc))) * 65), f"Consultando Remuneração Média por Escolaridade ({y})...")
                res_se = self.client.query_dardo(
                    base_cubo="rais_vinculos",
                    ano=y,
                    uf=uf_clean,
                    coluna_cruzamento="Escolaridade após 2005",
                    indicador=indic_sal,
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                    operacao="Média",
                )
                for _, orig_h in res_se.col_label_map.items():
                    if orig_h.lower().startswith("{ñ") or orig_h.lower() in ("total", "total geral"):
                        continue
                    v = float(res_se.summary_totals.get(orig_h) or 0.0)
                    if v > 0:
                        sal_esc_by_y[y][orig_h] = v
                        if orig_h not in cats_order:
                            cats_order.append(orig_h)
                tot_sal_by_y[y] = float(res_se.summary_totals.get("__TOTAL_GERAL__") or 0.0)

            has_multi = len(years_asc) >= 2
            rows = []
            for cat in cats_order:
                row_c = [cat] + [fmt_w(sal_esc_by_y[y].get(cat, 0.0)) for y in years_asc]
                if has_multi:
                    row_c.append(fmt_var_pct_br(sal_esc_by_y[y_first].get(cat, 0.0), sal_esc_by_y[y_last].get(cat, 0.0)))
                rows.append(row_c)

            has_footer = any(v > 0 for v in tot_sal_by_y.values())
            if has_footer:
                row_f = [f"Média Geral ({uf_name})"] + [fmt_w(tot_sal_by_y[y]) for y in years_asc]
                if has_multi:
                    row_f.append(fmt_var_pct_br(tot_sal_by_y[y_first], tot_sal_by_y[y_last]))
                rows.append(row_f)

            years_lbl = ", ".join(years_asc)
            headers_esc = ["Grau de Instrução / Escolaridade"] + years_asc + ([var_col_label] if has_multi else [])
            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_remuneracao_escolaridade_{unit_code.lower()}_{uf_clean}_{y_tag}",
                    title=f"Remuneração Média por Escolaridade ({unit_desc}) — {uf_name} ({years_lbl})",
                    subtitle=f"Remuneração Média por Escolaridade ({years_lbl})",
                    headers=headers_esc,
                    rows=rows,
                    footer_row_indices=[len(rows) - 1] if has_footer else [],
                    var_col_indices=[len(headers_esc) - 1] if has_multi else [],
                    theme="navy",
                    footnote=f"Fonte: MTE — DardoWeb (RAIS {years_lbl}, {sector_label}).",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_remuneracao_escolaridade_{unit_code.lower()}_{uf_clean}_{y_tag}",
                "title": f"Remuneração Média por Escolaridade ({unit_desc}) — {uf_name} ({years_lbl})",
                "subtitle": f"Recorte: {sector_label}",
                "type": "multi_year_category_bars",
                "categories": cats_order,
                "years": years_asc,
                "series": {y: [sal_esc_by_y[y].get(c, 0.0) for c in cats_order] for y in years_asc},
                "unit": unit_code,
                "ylabel": f"Remuneração Média ({unit_desc})",
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {years_lbl}).",
            })
            return bundle

        elif report_key == "rem_ranking_municipal":
            sal_mun_by_y: Dict[str, Dict[str, float]] = {y: {} for y in years_asc}
            vinc_mun_by_y: Dict[str, Dict[str, float]] = {y: {} for y in years_asc}
            mun_names: Dict[str, str] = {}

            for idx_y, y in enumerate(years_asc, start=1):
                if prog_cb:
                    prog_cb(int(15 + (idx_y / max(1, len(years_asc))) * 70), f"Consultando Remuneração e Vínculos por Município ({y})...")
                res_sm = self.client.query_dardo(
                    base_cubo="rais_vinculos",
                    ano=y,
                    uf=uf_clean,
                    coluna_cruzamento="---------Não---------",
                    indicador=indic_sal,
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                    operacao="Média",
                )
                res_vm = self.client.query_dardo(
                    base_cubo="rais_vinculos",
                    ano=y,
                    uf=uf_clean,
                    coluna_cruzamento="---------Não---------",
                    indicador="->Frequência",
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=eff_nivel,
                    filtro_cnae_codigo=filtro_codigo,
                )
                for r in res_vm.records:
                    cd = r["CD_MUN_IBGE"]
                    vinc_mun_by_y[y][cd] = float(r.get("TOTAL_GERAL") or 0.0)
                for r in res_sm.records:
                    cd = r["CD_MUN_IBGE"]
                    sal_mun_by_y[y][cd] = float(r.get("TOTAL_GERAL") or 0.0)
                    mun_names[cd] = f"{r['NM_MUN']} ({r.get('SG_UF', '')})" if uf_clean == "BR" else r["NM_MUN"]

            candidates_cd = [
                cd for cd in mun_names
                if sal_mun_by_y[y_last].get(cd, 0.0) > 0 and vinc_mun_by_y[y_last].get(cd, 0.0) >= 5
            ]
            if not candidates_cd:
                candidates_cd = [
                    cd for cd in mun_names
                    if sal_mun_by_y[y_last].get(cd, 0.0) > 0 and vinc_mun_by_y[y_last].get(cd, 0.0) > 0
                ]

            top_sal_cds = sorted(
                candidates_cd,
                key=lambda cd: (sal_mun_by_y[y_last].get(cd, 0.0), sal_mun_by_y[y_first].get(cd, 0.0)),
                reverse=True,
            )[:top_n]

            has_multi = len(years_asc) >= 2
            years_lbl = ", ".join(years_asc)
            if has_multi:
                headers_rm = ["Classif.*", "Município"] + [f"Remun. {y}" for y in years_desc] + [var_col_label, f"Vínculos ({y_last})"]
            else:
                headers_rm = ["Classif.*", "Município", f"Remuneração Média ({y_last})", f"Vínculos ({y_last})"]

            rows = []
            chart_items_sal = []
            for i, cd in enumerate(top_sal_cds, start=1):
                nm = mun_names[cd]
                sal_last = sal_mun_by_y[y_last].get(cd, 0.0)
                sal_first = sal_mun_by_y[y_first].get(cd, 0.0)
                vc_last = vinc_mun_by_y[y_last].get(cd, 0.0)
                if has_multi:
                    var_s = fmt_var_pct_br(sal_first, sal_last)
                    rows.append([f"{i}º", nm] + [fmt_w(sal_mun_by_y[y].get(cd, 0.0)) for y in years_desc] + [var_s, fmt_int_br(vc_last)])
                else:
                    var_s = ""
                    rows.append([f"{i}º", nm, fmt_w(sal_last), fmt_int_br(vc_last)])
                chart_items_sal.append({
                    "name": f"{i}º {nm}",
                    "value": sal_last,
                    "annot": f"{fmt_int_br(vc_last)} vínc.",
                    "var_str": var_s,
                    "by_year": {y: sal_mun_by_y[y].get(cd, 0.0) for y in years_asc},
                })

            bundle.tables.append(
                StyledTableSpec(
                    table_id=f"tabela_ranking_remuneracao_{unit_code.lower()}_{uf_clean}_{y_tag}",
                    title=f"Top {len(top_sal_cds)} Municípios por Remuneração Média ({years_lbl}) — {uf_name}",
                    subtitle=f"Ranking Municipal de Remuneração Média ({years_lbl})",
                    headers=headers_rm,
                    rows=rows,
                    var_col_indices=[len(headers_rm) - 2] if has_multi else [],
                    theme="navy",
                    footnote=f"*Ordenado por {y_last} (mín. 5 vínculos ativos). Fonte: MTE — DardoWeb (RAIS {years_lbl}, {sector_label}).",
                )
            )
            bundle.chart_payloads.append({
                "chart_id": f"grafico_ranking_remuneracao_{unit_code.lower()}_{uf_clean}_{y_tag}",
                "title": f"Top {len(top_sal_cds)} Municípios por Remuneração Média ({unit_desc}) ({years_lbl}) — {uf_name}",
                "subtitle": f"Recorte: {sector_label}",
                "type": "ranking_horizontal_bars",
                "years": years_asc,
                "rank_style": rank_chart_style,
                "items": chart_items_sal,
                "color": "#0f2c59",
                "unit": unit_code,
                "xlabel": f"Remuneração Média ({unit_desc})",
                "footnote": f"Fonte: MTE — DardoWeb (RAIS {years_lbl}).",
            })
            return bundle

        raise ValueError(f"Tipo de relatório não reconhecido: {report_key}")
