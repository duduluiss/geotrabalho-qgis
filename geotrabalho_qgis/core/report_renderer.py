# -*- coding: utf-8 -*-
"""
Renderizador de Tabelas Acadêmicas e Gráficos de Alta Resolução (300 DPI)
para o plugin GeoTrabalho (RAIS/CAGED DardoWeb).
Suporta geração granular (um único gráfico ou tabela específica) ou combinada,
exportando PNG de alta resolução, CSV (UTF-8 com BOM) e HTML opcional.
"""

from __future__ import annotations

import base64
import csv
import os
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .analytics_engine import AnalyticsReportBundle, StyledTableSpec, fmt_float_br, fmt_int_br


THEME_COLORS = {
    "wine": "#7a1c1c",
    "green": "#14532d",
    "navy": "#0f2c59",
}

SERIES_PALETTE = [
    "#0f2c59",
    "#990000",
    "#1b7837",
    "#d95f02",
    "#5b21b6",
    "#0e7490",
    "#b45309",
    "#475569",
]


def fmt_currency_or_metric(val: float, unit: str = "INT") -> str:
    """Formata valores numéricos conforme a unidade ('INT', 'PCT', 'BRL', 'SM', 'DEC')."""
    if unit == "BRL":
        return f"R$ {fmt_float_br(val, 2)}"
    if unit == "SM":
        return f"{fmt_float_br(val, 2)} SM"
    if unit == "PCT":
        return f"{fmt_float_br(val, 1)}%"
    if unit == "DEC":
        return fmt_float_br(val, 1)
    return fmt_int_br(val)


def render_styled_table_png(table_spec: StyledTableSpec, out_path: str, dpi: int = 240) -> str:
    """
    Renderiza uma `StyledTableSpec` como imagem PNG de alta resolução:
    - Faixa superior institucional (vinho/verde/azul-marinho) com o título;
    - Cabeçalho escuro (#2b3a4a) com texto branco em negrito;
    - Linhas zebradas (#ffffff / #f3f5f8);
    - Colunas de Variação % coloridas em verde (#15803d) para '+' e vermelho (#b91c1c) para '-';
    - Linhas de Subtotal e Total destacadas no rodapé (#dce3ec) em negrito;
    - Nota de rodapé em itálico.
    """
    n_rows = max(1, len(table_spec.rows))
    n_cols = max(1, len(table_spec.headers))

    fig_w = max(8.8, min(14.5, 2.6 + n_cols * 1.45))
    fig_h = max(3.2, 1.55 + (n_rows + 1) * 0.42)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.axis("off")
    fig.patch.set_facecolor("#ffffff")

    primary_hex = THEME_COLORS.get(table_spec.theme, "#0f2c59")

    col_widths = []
    for c_idx, h in enumerate(table_spec.headers):
        h_low = h.lower()
        if c_idx == 0 and ("classif" in h_low or h_low == "#"):
            col_widths.append(0.09)
        elif any(
            k in h_low
            for k in (
                "município",
                "mesorregião",
                "região",
                "microrregião",
                "indicador",
                "categoria",
                "faixa",
                "escolaridade",
                "nacionalidade",
                "natureza",
                "ocupação",
                "grupo",
                "porte",
                "vínculo",
                "sexo",
            )
        ):
            col_widths.append(0.32)
        else:
            col_widths.append(0.16)

    tot_w = sum(col_widths)
    col_widths = [w / tot_w * 0.96 for w in col_widths]

    fig.text(
        0.5,
        0.93,
        table_spec.title,
        ha="center",
        va="center",
        fontsize=10.2,
        fontweight="bold",
        color="#ffffff",
        bbox=dict(boxstyle="round,pad=0.45", facecolor=primary_hex, edgecolor="none"),
    )

    tbl = ax.table(
        cellText=table_spec.rows,
        colLabels=table_spec.headers,
        colWidths=col_widths,
        loc="center",
        cellLoc="center",
        bbox=[0.02, 0.10, 0.96, 0.76],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.0)

    footer_set = set(table_spec.footer_row_indices)
    var_col_set = set(table_spec.var_col_indices)

    for (r_idx, c_idx), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        cell.set_linewidth(0.6)

        if r_idx == 0:
            cell.set_facecolor("#2b3a4a")
            cell.get_text().set_color("#ffffff")
            cell.get_text().set_weight("bold")
            cell.get_text().set_fontsize(9.2)
        else:
            data_row_idx = r_idx - 1
            is_footer = data_row_idx in footer_set
            txt_val = table_spec.rows[data_row_idx][c_idx] if c_idx < len(table_spec.rows[data_row_idx]) else ""

            if is_footer:
                cell.set_facecolor("#dce3ec")
                cell.get_text().set_weight("bold")
                cell.get_text().set_color("#111827")
            else:
                cell.set_facecolor("#ffffff" if data_row_idx % 2 == 0 else "#f3f5f8")
                cell.get_text().set_color("#1f2937")
                if c_idx == 2 and "classif" in table_spec.headers[0].lower() and len(table_spec.headers) >= 4:
                    cell.get_text().set_weight("bold")

            if (c_idx == 1 and "classif" in table_spec.headers[0].lower()) or (
                c_idx == 0 and "classif" not in table_spec.headers[0].lower()
            ):
                cell.get_text().set_ha("left")
                cell.PAD = 0.04

            if c_idx in var_col_set:
                cell.get_text().set_weight("bold")
                if txt_val.startswith("+") or txt_val == "Novo":
                    cell.get_text().set_color("#15803d")
                elif txt_val.startswith("-"):
                    cell.get_text().set_color("#b91c1c")

    if table_spec.footnote:
        fig.text(
            0.03,
            0.03,
            table_spec.footnote,
            ha="left",
            va="center",
            fontsize=8.0,
            style="italic",
            color="#4b5563",
        )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="#ffffff")
    plt.close(fig)
    return out_path


def render_slide7_combined_meso_chart(
    payload_part: Dict[str, Any],
    payload_porte: Dict[str, Any],
    out_path: str,
    dpi: int = 240,
) -> str:
    """
    Renderiza o painel duplo regional:
    - Esquerda: Participação Relativa por Região IBGE (%) (% Vínculos vs % Estabelecimentos)
    - Direita: Porte Médio por Região IBGE (Vínculos / Estab.) + linha tracejada da Média Estadual
    """
    labels = payload_part.get("labels", [])
    pct_vinc = payload_part.get("pct_vinc", [])
    pct_estab = payload_part.get("pct_estab", [])
    porte_vals = payload_porte.get("porte_vals", [])
    state_avg = float(payload_porte.get("state_avg") or 0.0)
    uf = payload_part.get("uf", "UF")

    short_labels = [lbl.replace(" ", "\n", 1) if len(lbl) > 12 else lbl for lbl in labels]
    x = np.arange(len(labels))
    width = 0.36

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.0), dpi=dpi)
    fig.patch.set_facecolor("#ffffff")

    rects1 = ax1.bar(x - width / 2, pct_vinc, width, label=f"% dos Vínculos ({uf})", color="#990000")
    rects2 = ax1.bar(x + width / 2, pct_estab, width, label=f"% dos Estabelecimentos ({uf})", color="#1b7837")
    ax1.set_title(payload_part.get("title", "Participação Relativa (%)"), fontsize=10.8, fontweight="bold", pad=12)
    ax1.set_ylabel(f"Participação no Total de {uf} (%)", fontsize=9.2)
    ax1.set_xticks(x)
    rot = 20 if len(labels) > 6 else 0
    ha_lbl = "right" if rot else "center"
    ax1.set_xticklabels(short_labels, rotation=rot, ha=ha_lbl, fontsize=8.3, fontweight="bold")
    max_y1 = max(max(pct_vinc, default=10.0), max(pct_estab, default=10.0))
    ax1.set_ylim(0, max_y1 * 1.20)
    ax1.grid(axis="y", linestyle=":", alpha=0.5)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(fontsize=8.3, loc="upper right")

    for r in rects1:
        h = r.get_height()
        ax1.annotate(
            f"{fmt_float_br(h, 1)}%",
            xy=(r.get_x() + r.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.8,
            fontweight="bold",
            color="#990000",
        )
    for r in rects2:
        h = r.get_height()
        ax1.annotate(
            f"{fmt_float_br(h, 1)}%",
            xy=(r.get_x() + r.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.8,
            fontweight="bold",
            color="#1b7837",
        )

    rects_p = ax2.bar(x, porte_vals, width=0.52, color="#1f4e78")
    if state_avg > 0:
        ax2.axhline(
            state_avg,
            color="#d95f02",
            linestyle="--",
            linewidth=1.5,
            label=f"Média {uf} ({fmt_float_br(state_avg, 1)} vínc./estab.)",
        )
        ax2.legend(fontsize=8.3, loc="upper right")

    ax2.set_title(payload_porte.get("title", "Porte Médio (Vínculos / Estab.)"), fontsize=10.8, fontweight="bold", pad=12)
    ax2.set_ylabel("Média de Vínculos / Estabelecimento", fontsize=9.2)
    ax2.set_xticks(x)
    ax2.set_xticklabels(short_labels, rotation=rot, ha=ha_lbl, fontsize=8.3, fontweight="bold")
    max_y2 = max(max(porte_vals, default=10.0), state_avg)
    ax2.set_ylim(0, max_y2 * 1.20)
    ax2.grid(axis="y", linestyle=":", alpha=0.5)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    for r in rects_p:
        h = r.get_height()
        ax2.annotate(
            fmt_float_br(h, 1),
            xy=(r.get_x() + r.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8.2,
            fontweight="bold",
            color="#1f4e78",
        )

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="#ffffff")
    plt.close(fig)
    return out_path


def render_single_chart_payload(payload: Dict[str, Any], out_path: str, dpi: int = 240) -> str:
    """Renderiza qualquer payload de gráfico individual em PNG de alta resolução."""
    ctype = payload.get("type", "")
    title = payload.get("title", "Gráfico")
    subtitle = payload.get("subtitle", "")
    footnote = payload.get("footnote", "")

    # Ajusta altura dinamicamente para gráficos de barras horizontais com muitas linhas
    n_items = len(payload.get("items", payload.get("categories", payload.get("labels", []))))
    n_years_rank = len(payload.get("years", []))
    fig_h = 5.2
    if ctype == "ranking_horizontal_bars" and n_years_rank >= 2 and payload.get("rank_style") != "lines":
        fig_h = max(6.4, min(11.0, 2.0 + n_items * (0.48 + 0.07 * min(n_years_rank, 6))))
    elif ctype in ("diverging_bars", "ranking_horizontal_bars") or (
        ctype == "multi_year_category_bars" and n_items > 6 and len(payload.get("years", [])) <= 3
    ):
        fig_h = max(4.8, min(9.5, 1.8 + n_items * 0.42))

    fig, ax = plt.subplots(figsize=(9.8 if n_years_rank >= 2 else 9.4, fig_h), dpi=dpi)
    fig.patch.set_facecolor("#ffffff")

    if ctype == "meso_grouped_bars":
        labels = payload.get("labels", [])
        short_labels = [lbl.replace(" ", "\n", 1) if len(lbl) > 13 else lbl for lbl in labels]
        pct_vinc = payload.get("pct_vinc", [])
        pct_estab = payload.get("pct_estab", [])
        lbl_a = payload.get("label_a") or f"% dos Vínculos ({payload.get('uf', 'UF')})"
        lbl_b = payload.get("label_b") or f"% dos Estabelecimentos ({payload.get('uf', 'UF')})"
        x = np.arange(len(labels))
        w = 0.36
        r1 = ax.bar(x - w / 2, pct_vinc, w, label=lbl_a, color="#990000")
        r2 = ax.bar(x + w / 2, pct_estab, w, label=lbl_b, color="#1b7837")
        ax.set_xticks(x)
        rot = 22 if len(labels) > 5 else 0
        ax.set_xticklabels(short_labels, rotation=rot, ha="right" if rot else "center", fontsize=8.3, fontweight="bold")
        ax.set_ylabel("Participação (%)", fontsize=9.5)
        ax.set_ylim(0, max(max(pct_vinc, default=10), max(pct_estab, default=10)) * 1.22)
        ax.legend(fontsize=8.5)
        for r in r1:
            h = r.get_height()
            ax.annotate(f"{fmt_float_br(h, 1)}%", (r.get_x() + r.get_width() / 2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.8, fontweight="bold", color="#990000")
        for r in r2:
            h = r.get_height()
            ax.annotate(f"{fmt_float_br(h, 1)}%", (r.get_x() + r.get_width() / 2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.8, fontweight="bold", color="#1b7837")

    elif ctype == "meso_porte_bars":
        labels = payload.get("labels", [])
        short_labels = [lbl.replace(" ", "\n", 1) if len(lbl) > 13 else lbl for lbl in labels]
        porte_vals = payload.get("porte_vals", [])
        state_avg = float(payload.get("state_avg") or 0.0)
        uf = payload.get("uf", "UF")
        x = np.arange(len(labels))
        rp = ax.bar(x, porte_vals, width=0.52, color="#1f4e78")
        if state_avg > 0:
            ax.axhline(state_avg, color="#d95f02", linestyle="--", linewidth=1.5, label=f"Média {uf} ({fmt_float_br(state_avg, 1)} vínc./estab.)")
            ax.legend(fontsize=8.5)
        ax.set_xticks(x)
        rot = 22 if len(labels) > 5 else 0
        ax.set_xticklabels(short_labels, rotation=rot, ha="right" if rot else "center", fontsize=8.5, fontweight="bold")
        ax.set_ylabel("Média de Vínculos / Estabelecimento", fontsize=9.5)
        ax.set_ylim(0, max(max(porte_vals, default=10), state_avg) * 1.22)
        for r in rp:
            h = r.get_height()
            ax.annotate(fmt_float_br(h, 1), (r.get_x() + r.get_width() / 2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8.3, fontweight="bold", color="#1f4e78")

    elif ctype == "dual_axis_evolution":
        years = payload.get("years", [])
        vinc_vals = payload.get("vinc_vals", [])
        estab_vals = payload.get("estab_vals", [])
        x = np.arange(len(years))
        bars = ax.bar(x, vinc_vals, width=0.42 if len(years) > 1 else 0.30, color="#7a1c1c", alpha=0.88, label="Vínculos Trabalhistas")
        ax.set_xticks(x)
        ax.set_xticklabels(years, fontsize=9.5, fontweight="bold")
        ax.set_ylabel("Total de Vínculos Trabalhistas", color="#7a1c1c", fontsize=9.5, fontweight="bold")
        ax.set_ylim(0, max(vinc_vals, default=100) * 1.24)
        for b in bars:
            h = b.get_height()
            ax.annotate(fmt_int_br(h), (b.get_x() + b.get_width() / 2, h), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.5, fontweight="bold", color="#7a1c1c")

        ax_r = ax.twinx()
        ax_r.plot(x, estab_vals, color="#14532d", marker="o", linewidth=2.5, markersize=7, label="Nº de Estabelecimentos")
        ax_r.set_ylabel("Nº de Estabelecimentos (Plantas)", color="#14532d", fontsize=9.5, fontweight="bold")
        ax_r.set_ylim(0, max(estab_vals, default=10) * 1.38)
        ax_r.spines["top"].set_visible(False)
        for xi, ev in zip(x, estab_vals):
            ax_r.annotate(f"{fmt_int_br(ev)} plantas", (xi, ev), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8.0, fontweight="bold", color="#14532d")

    elif ctype == "temporal_series_bars":
        years = payload.get("years", [])
        vals = [float(v) for v in payload.get("values", [])]
        step_pcts = payload.get("step_pcts") or payload.get("step_vars", [])
        bar_color = payload.get("color", "#7a1c1c")
        unit = payload.get("unit", "INT")
        ylabel = payload.get("ylabel", "Vínculos Trabalhistas")

        x = np.arange(len(years))
        w = 0.44 if len(years) > 1 else 0.30
        bars = ax.bar(x, vals, width=w, color=bar_color, alpha=0.88, label=ylabel)
        if len(years) >= 2:
            ax.plot(x, vals, color="#0f2c59", marker="o", linewidth=2.2, markersize=6.5, zorder=4)
        ax.set_xticks(x)
        ax.set_xticklabels(years, fontsize=9.8, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=9.5, fontweight="bold")
        ax.set_ylim(0, max(vals, default=10.0) * 1.26)
        for i, (b, v) in enumerate(zip(bars, vals)):
            lbl = fmt_currency_or_metric(v, unit)
            if i < len(step_pcts) and step_pcts[i]:
                lbl += f"\n({step_pcts[i]})"
            ax.annotate(
                lbl,
                (b.get_x() + b.get_width() / 2, v),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
                color=bar_color,
            )

    elif ctype == "ranking_horizontal_bars":
        raw_items = payload.get("items", [])
        years = payload.get("years", [])
        bar_color = payload.get("color", "#7a1c1c")
        unit = payload.get("unit", "INT")
        xlabel = payload.get("xlabel", "Quantidade")
        rank_style = payload.get("rank_style", "bars")

        if len(years) >= 2 and rank_style == "lines":
            x = np.arange(len(years))
            max_v = 10.0
            for idx_it, it in enumerate(raw_items[:10]):
                y_series = [float(it.get("by_year", {}).get(yr, 0.0)) for yr in years]
                max_v = max(max_v, max(y_series, default=0.0))
                col_line = SERIES_PALETTE[idx_it % len(SERIES_PALETTE)]
                var_s = it.get("var_str", "")
                lbl_leg = f"{it['name']} ({var_s})" if var_s else it["name"]
                ax.plot(x, y_series, marker="o", linewidth=2.2, markersize=5.5, label=lbl_leg, color=col_line)
                if y_series:
                    ax.annotate(
                        fmt_currency_or_metric(y_series[-1], unit),
                        (x[-1], y_series[-1]),
                        xytext=(5, 0),
                        textcoords="offset points",
                        va="center",
                        fontsize=7.8,
                        fontweight="bold",
                        color=col_line,
                    )
            ax.set_xticks(x)
            ax.set_xticklabels(years, fontsize=9.5, fontweight="bold")
            ax.set_ylabel(xlabel, fontsize=9.5)
            ax.set_xlim(-0.2, len(years) - 1 + 0.55)
            ax.set_ylim(0, max_v * 1.18)
            ax.legend(fontsize=8.0, loc="upper left", ncol=2 if len(raw_items) > 6 else 1)
        elif len(years) >= 2:
            # Barras horizontais agrupadas exibindo TODOS os anos selecionados para cada município
            items = list(reversed(raw_items))
            names = [it["name"] for it in items]
            y_pos = np.arange(len(names))
            n_y = len(years)
            group_h = 0.78
            bar_h = group_h / n_y

            # Paleta progressiva terminando na cor principal do indicador para o ano mais recente
            multi_colors = ["#94a3b8", "#3b82f6", "#d97706", "#0e7490", "#6d28d9", bar_color]
            if n_y <= len(multi_colors):
                yr_colors = multi_colors[len(multi_colors) - n_y - 1 : len(multi_colors) - 1] + [bar_color]
            else:
                yr_colors = [SERIES_PALETTE[i % len(SERIES_PALETTE)] for i in range(n_y - 1)] + [bar_color]

            max_v = 10.0
            for idx_y, yr in enumerate(years):
                vals_yr = [float(it.get("by_year", {}).get(yr, 0.0)) for it in items]
                max_v = max(max_v, max(vals_yr, default=0.0))
                # No eixo Y invertido (1º no topo), colocamos o 1º ano acima e o último ano abaixo dentro do grupo
                offset = ((n_y - 1) / 2.0 - idx_y) * bar_h
                c_yr = yr_colors[idx_y]
                rects = ax.barh(y_pos + offset, vals_yr, height=bar_h * 0.92, color=c_yr, label=f"Ano {yr}", alpha=0.94)
                for r, v, it in zip(rects, vals_yr, items):
                    if v <= 0:
                        continue
                    txt = f" {fmt_currency_or_metric(v, unit)}"
                    if idx_y == n_y - 1 and it.get("annot"):
                        txt += f" ({it['annot']})"
                    fsz = 7.4 if n_y >= 4 else 8.0
                    ax.annotate(
                        txt,
                        (v, r.get_y() + r.get_height() / 2),
                        va="center",
                        ha="left",
                        fontsize=fsz,
                        fontweight="bold" if idx_y == n_y - 1 else "normal",
                        color=c_yr if idx_y == n_y - 1 else "#334155",
                    )

            ax.set_yticks(y_pos)
            ax.set_yticklabels(names, fontsize=8.6, fontweight="bold")
            ax.set_xlabel(xlabel, fontsize=9.5)
            ax.set_xlim(0, max_v * 1.38)
            ax.grid(axis="x", linestyle=":", alpha=0.5)
            ax.grid(axis="y", visible=False)
            ax.legend(fontsize=8.4, loc="lower right", frameon=True)
        else:
            items = list(reversed(raw_items))
            names = [it["name"] for it in items]
            vals = [float(it["value"]) for it in items]
            annots = [it.get("annot", "") for it in items]

            y_pos = np.arange(len(names))
            bars = ax.barh(y_pos, vals, color=bar_color, height=0.62, alpha=0.92)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(names, fontsize=8.6, fontweight="bold")
            ax.set_xlabel(xlabel, fontsize=9.5)
            max_v = max(vals, default=10.0)
            ax.set_xlim(0, max_v * 1.32)
            ax.grid(axis="x", linestyle=":", alpha=0.5)
            ax.grid(axis="y", visible=False)
            for b, v, extra in zip(bars, vals, annots):
                txt = f" {fmt_currency_or_metric(v, unit)}"
                if extra:
                    txt += f" ({extra})"
                ax.annotate(txt, (v, b.get_y() + b.get_height() / 2), va="center", ha="left", fontsize=8.2, fontweight="bold", color=bar_color)

    elif ctype == "diverging_bars":
        items = list(reversed(payload.get("items", [])))
        names = [it["name"] for it in items]
        diffs = [float(it["diff"]) for it in items]
        pcts = [it["pct_str"] for it in items]
        y_pos = np.arange(len(names))
        colors = ["#15803d" if d >= 0 else "#b91c1c" for d in diffs]
        bars = ax.barh(y_pos, diffs, color=colors, height=0.62)
        ax.axvline(0, color="#374151", linewidth=1.0)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontsize=8.5, fontweight="bold")
        ax.set_xlabel("Saldo Líquido de Vínculos no Período", fontsize=9.5)
        span = max(abs(min(diffs, default=0)), abs(max(diffs, default=10)))
        ax.set_xlim(min(0, min(diffs, default=0)) - span * 0.32, max(0, max(diffs, default=0)) + span * 0.32)
        ax.grid(axis="x", linestyle=":", alpha=0.5)
        ax.grid(axis="y", visible=False)
        for b, d, pstr in zip(bars, diffs, pcts):
            sign = "+" if d > 0 else ""
            lbl = f" {sign}{fmt_int_br(d)} ({pstr}) "
            ha = "left" if d >= 0 else "right"
            ax.annotate(lbl, (d, b.get_y() + b.get_height() / 2), va="center", ha=ha, fontsize=8.0, fontweight="bold", color="#15803d" if d >= 0 else "#b91c1c")

    elif ctype == "scatter_scale":
        pts = payload.get("points", [])
        state_avg = float(payload.get("state_avg") or 0.0)
        regions = sorted({p["region"] for p in pts})
        palette = ["#990000", "#1f4e78", "#1b7837", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02"]
        reg_color = {r: palette[i % len(palette)] for i, r in enumerate(regions)}
        for r in regions[:10]:
            sub = [p for p in pts if p["region"] == r]
            ax.scatter(
                [p["estab"] for p in sub],
                [p["vinc"] for p in sub],
                label=r,
                color=reg_color[r],
                s=55,
                alpha=0.82,
                edgecolors="#ffffff",
            )
        max_e = max((p["estab"] for p in pts), default=10.0)
        if state_avg > 0:
            x_line = np.linspace(0, max_e * 1.05, 50)
            ax.plot(x_line, x_line * state_avg, linestyle="--", color="#4b5563", linewidth=1.2, label=f"Porte Médio ({fmt_float_br(state_avg, 1)})")
        top_labeled = sorted(pts, key=lambda p: (p["vinc"], p["estab"]), reverse=True)[:8]
        for p in top_labeled:
            ax.annotate(p["name"], (p["estab"], p["vinc"]), xytext=(4, 4), textcoords="offset points", fontsize=7.8, fontweight="bold")
        ax.set_xlabel("Nº de Estabelecimentos (Plantas)", fontsize=9.5)
        ax.set_ylabel("Nº de Vínculos Trabalhistas", fontsize=9.5)
        ax.legend(fontsize=7.8, loc="best")

    elif ctype == "stacked_concentration":
        years = payload.get("years", [])
        cr4 = np.array(payload.get("cr4", []), dtype=float)
        cr5_10 = np.array(payload.get("cr5_10", []), dtype=float)
        rest = np.array(payload.get("rest", []), dtype=float)
        x = np.arange(len(years))
        w = 0.45 if len(years) > 1 else 0.30
        ax.bar(x, cr4, w, label="Top 4 Municípios (CR4)", color="#7a1c1c")
        ax.bar(x, cr5_10, w, bottom=cr4, label="5º ao 10º Município", color="#d95f02")
        ax.bar(x, rest, w, bottom=cr4 + cr5_10, label="Demais Municípios", color="#cbd5e1")
        ax.set_xticks(x)
        ax.set_xticklabels(years, fontsize=9.5, fontweight="bold")
        ax.set_ylabel("Participação no Emprego Total (%)", fontsize=9.5)
        ax.set_ylim(0, 108)
        ax.legend(fontsize=8.5, loc="upper right")
        for i in range(len(years)):
            if cr4[i] > 6:
                ax.text(i, cr4[i] / 2, f"{fmt_float_br(cr4[i], 1)}%", ha="center", va="center", color="#ffffff", fontweight="bold", fontsize=8.5)
            if cr5_10[i] > 6:
                ax.text(i, cr4[i] + cr5_10[i] / 2, f"{fmt_float_br(cr5_10[i], 1)}%", ha="center", va="center", color="#ffffff", fontweight="bold", fontsize=8.5)
            if rest[i] > 8:
                ax.text(i, cr4[i] + cr5_10[i] + rest[i] / 2, f"{fmt_float_br(rest[i], 1)}%", ha="center", va="center", color="#1e293b", fontweight="bold", fontsize=8.2)

    elif ctype == "donut_chart":
        cats = payload.get("categories", [])
        vals = [float(v) for v in payload.get("values", [])]
        tot = sum(vals)
        is_gender = len(cats) == 2 and any("masc" in c.lower() for c in cats)
        if is_gender:
            colors = ["#1f4e78" if "masc" in c.lower() else "#9d174d" for c in cats]
        else:
            colors = [SERIES_PALETTE[i % len(SERIES_PALETTE)] for i in range(len(cats))]

        wedges, _ = ax.pie(
            vals,
            labels=None,
            colors=colors,
            startangle=90,
            wedgeprops=dict(width=0.44, edgecolor="#ffffff", linewidth=2),
        )
        ax.text(
            0,
            0,
            f"Total\n{fmt_int_br(tot)}",
            ha="center",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#0f2c59",
        )
        legend_labels = [
            f"{c}: {fmt_int_br(v)} ({fmt_float_br((v / tot * 100.0) if tot > 0 else 0.0, 1)}%)"
            for c, v in zip(cats, vals)
        ]
        ax.legend(wedges, legend_labels, loc="center left", bbox_to_anchor=(0.95, 0.5), fontsize=8.8, frameon=True)
        ax.axis("equal")

    elif ctype == "multi_year_category_bars":
        cats = payload.get("categories", [])
        years = payload.get("years", [])
        series = payload.get("series", {})
        unit = payload.get("unit", "INT")  # "INT", "PCT", "BRL", "SM"
        ylabel = payload.get("ylabel", "Vínculos Trabalhistas")

        if len(years) > 6:
            # Muitos anos selecionados -> gráfico de linhas por categoria para leitura limpa
            x = np.arange(len(years))
            for idx_c, cat in enumerate(cats[:8]):
                y_vals = [float(series.get(y, [0.0] * len(cats))[idx_c]) for y in years]
                color = SERIES_PALETTE[idx_c % len(SERIES_PALETTE)]
                ax.plot(x, y_vals, marker="o", linewidth=2.2, markersize=5.5, label=cat[:30], color=color)
            ax.set_xticks(x)
            ax.set_xticklabels(years, rotation=25 if len(years) > 8 else 0, fontsize=8.8, fontweight="bold")
            ax.set_ylabel(ylabel, fontsize=9.5)
            ax.legend(fontsize=8.2, loc="best")
        elif len(years) == 1:
            y0 = years[0]
            vals = [float(v) for v in series.get(y0, [])]
            tot_raw = float(payload.get("raw_total_last") or sum(vals))
            is_gender = len(cats) == 2 and any("masc" in c.lower() for c in cats)
            if is_gender:
                bar_colors = ["#1f4e78" if "masc" in c.lower() else "#9d174d" for c in cats]
            else:
                bar_colors = [payload.get("color", "#0f2c59")] * len(cats)

            if len(cats) > 6:
                # Barras horizontais quando há muitas categorias (ex: Escolaridade, Nacionalidade, CBO)
                cats_rev = list(reversed(cats))
                vals_rev = list(reversed(vals))
                cols_rev = list(reversed(bar_colors))
                raw_vals = list(reversed(payload.get("raw_values_last", vals)))
                y_pos = np.arange(len(cats_rev))
                bars = ax.barh(y_pos, vals_rev, color=cols_rev, height=0.62)
                ax.set_yticks(y_pos)
                ax.set_yticklabels([c[:36] for c in cats_rev], fontsize=8.5, fontweight="bold")
                ax.set_xlabel(ylabel, fontsize=9.5)
                ax.set_xlim(0, max(vals_rev, default=10.0) * 1.28)
                ax.grid(axis="x", linestyle=":", alpha=0.5)
                ax.grid(axis="y", visible=False)
                for b, v, rv in zip(bars, vals_rev, raw_vals):
                    if unit == "INT" and tot_raw > 0:
                        pct = rv / tot_raw * 100.0
                        lbl = f" {fmt_int_br(v)} ({fmt_float_br(pct, 1)}%)"
                    else:
                        lbl = f" {fmt_currency_or_metric(v, unit)}"
                    ax.annotate(lbl, (v, b.get_y() + b.get_height() / 2), va="center", ha="left", fontsize=8.1, fontweight="bold", color="#1e293b")
            else:
                x = np.arange(len(cats))
                w = 0.45 if len(cats) <= 3 else 0.55
                bars = ax.bar(x, vals, width=w, color=bar_colors)
                short_cats = [c[:24] + ("…" if len(c) > 24 else "") for c in cats]
                rot = 18 if len(cats) >= 5 else 0
                ax.set_xticks(x)
                ax.set_xticklabels(short_cats, rotation=rot, ha="right" if rot else "center", fontsize=8.8, fontweight="bold")
                ax.set_ylabel(ylabel, fontsize=9.5)
                ax.set_ylim(0, max(vals, default=10.0) * 1.22)
                raw_vals = payload.get("raw_values_last", vals)
                for b, v, rv, col_c in zip(bars, vals, raw_vals, bar_colors):
                    if unit == "INT" and tot_raw > 0:
                        pct = rv / tot_raw * 100.0
                        lbl = f"{fmt_int_br(v)}\n({fmt_float_br(pct, 1)}%)"
                    else:
                        lbl = fmt_currency_or_metric(v, unit)
                    ax.annotate(lbl, (b.get_x() + b.get_width() / 2, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.3, fontweight="bold", color=col_c)
        else:
            # De 2 a 6 anos selecionados -> barras agrupadas com todas as séries selecionadas
            n_y = len(years)
            x = np.arange(len(cats))
            total_group_w = 0.78
            w = total_group_w / n_y
            max_val = 1.0
            for idx_y, yr in enumerate(years):
                y_vals = [float(v) for v in series.get(yr, [0.0] * len(cats))]
                max_val = max(max_val, max(y_vals, default=0.0))
                offset = (idx_y - (n_y - 1) / 2.0) * w
                col_yr = SERIES_PALETTE[idx_y % len(SERIES_PALETTE)]
                rects = ax.bar(x + offset, y_vals, width=w * 0.94, label=f"Ano {yr}", color=col_yr)
                if len(cats) <= 5 and n_y <= 4:
                    for r in rects:
                        h = r.get_height()
                        if h > 0:
                            ax.annotate(
                                fmt_currency_or_metric(h, unit),
                                (r.get_x() + r.get_width() / 2, h),
                                xytext=(0, 3),
                                textcoords="offset points",
                                ha="center",
                                fontsize=7.5,
                                fontweight="bold",
                                color=col_yr,
                            )
            short_cats = [c[:24] + ("…" if len(c) > 24 else "") for c in cats]
            rot = 20 if len(cats) >= 4 else 0
            ax.set_xticks(x)
            ax.set_xticklabels(short_cats, rotation=rot, ha="right" if rot else "center", fontsize=8.5, fontweight="bold")
            ax.set_ylabel(ylabel, fontsize=9.5)
            ax.set_ylim(0, max_val * 1.24)
            ax.legend(fontsize=8.4, loc="best")

    elif ctype == "gender_pay_gap_bars":
        labels = payload.get("labels", [])
        short_labels = [lbl.replace(" ", "\n", 1) if len(lbl) > 13 else lbl for lbl in labels]
        masc_vals = payload.get("masc_vals", [])
        fem_vals = payload.get("fem_vals", [])
        unit = payload.get("unit", "BRL")
        ylabel = payload.get("ylabel", "Remuneração Média")
        x = np.arange(len(labels))
        w = 0.36
        r1 = ax.bar(x - w / 2, masc_vals, w, label="Homens", color="#1f4e78")
        r2 = ax.bar(x + w / 2, fem_vals, w, label="Mulheres", color="#9d174d")
        ax.set_xticks(x)
        rot = 20 if len(labels) > 5 else 0
        ax.set_xticklabels(short_labels, rotation=rot, ha="right" if rot else "center", fontsize=8.5, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=9.5)
        ax.set_ylim(0, max(max(masc_vals, default=2), max(fem_vals, default=2)) * 1.24)
        ax.legend(fontsize=8.5)
        for r in r1:
            h = r.get_height()
            ax.annotate(fmt_currency_or_metric(h, unit), (r.get_x() + r.get_width() / 2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.8, fontweight="bold", color="#1f4e78")
        for r in r2:
            h = r.get_height()
            ax.annotate(fmt_currency_or_metric(h, unit), (r.get_x() + r.get_width() / 2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.8, fontweight="bold", color="#9d174d")

    ax.set_title(f"{title}\n{subtitle}" if subtitle else title, fontsize=10.4, fontweight="bold", pad=10)
    if ctype != "donut_chart":
        if ctype not in ("diverging_bars", "ranking_horizontal_bars"):
            ax.grid(axis="y", linestyle=":", alpha=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    if footnote:
        fig.text(0.02, 0.01, footnote, ha="left", va="bottom", fontsize=7.8, style="italic", color="#4b5563")

    fig.tight_layout(rect=[0, 0.03 if footnote else 0, 1, 1])
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="#ffffff")
    plt.close(fig)
    return out_path


def export_full_report_bundle(
    bundle: AnalyticsReportBundle,
    output_dir: str,
    include_tables: bool = True,
    include_charts: bool = True,
    include_html: bool = False,
) -> Dict[str, Any]:
    """
    Exporta na pasta `output_dir` estritamente os itens solicitados pelo usuário:
    - Tabelas em `.PNG` e `.CSV` (se `include_tables=True`);
    - Gráficos em `.PNG` (se `include_charts=True`);
    - Relatório `.HTML` opcional (se `include_html=True`).
    """
    os.makedirs(output_dir, exist_ok=True)
    table_pngs: List[Tuple[str, str]] = []
    csv_files: List[str] = []
    chart_pngs: List[Tuple[str, str]] = []

    if include_tables:
        for tspec in bundle.tables:
            png_path = os.path.join(output_dir, f"{tspec.table_id}.png")
            render_styled_table_png(tspec, png_path)
            table_pngs.append((tspec.subtitle or tspec.title, png_path))

            csv_path = os.path.join(output_dir, f"{tspec.table_id}.csv")
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as cf:
                writer = csv.writer(cf, delimiter=";")
                writer.writerow([tspec.title])
                writer.writerow(tspec.headers)
                for row in tspec.rows:
                    writer.writerow(row)
                if tspec.footnote:
                    writer.writerow([tspec.footnote])
            csv_files.append(csv_path)

    if include_charts:
        part_payload = next((p for p in bundle.chart_payloads if p.get("chart_id", "").endswith("meso_participacao_painel")), None)
        porte_payload = next((p for p in bundle.chart_payloads if p.get("chart_id", "").endswith("meso_porte_painel")), None)
        if part_payload and porte_payload and part_payload.get("labels"):
            slide7_name = part_payload.get("combined_filename", f"painel_regional_{bundle.uf}_{bundle.years_asc[-1]}.png")
            slide7_path = os.path.join(output_dir, slide7_name)
            render_slide7_combined_meso_chart(part_payload, porte_payload, slide7_path)
            chart_pngs.append(("Painel Regional: Participação (%) e Porte Médio", slide7_path))
        else:
            for cpayload in bundle.chart_payloads:
                cpath = os.path.join(output_dir, f"{cpayload['chart_id']}.png")
                render_single_chart_payload(cpayload, cpath)
                chart_pngs.append((cpayload.get("title", cpayload["chart_id"]), cpath))

    html_path: Optional[str] = None
    html_str = ""
    if include_html:
        y_tag = bundle.years_asc[0] if len(bundle.years_asc) == 1 else f"{bundle.years_asc[0]}_{bundle.years_asc[-1]}"
        html_path = os.path.join(output_dir, f"Relatorio_GeoTrabalho_{bundle.uf}_{y_tag}.html")
        html_str = build_html_report(bundle, table_pngs, chart_pngs)
        with open(html_path, "w", encoding="utf-8") as hf:
            hf.write(html_str)

    return {
        "output_dir": output_dir,
        "table_pngs": table_pngs,
        "chart_pngs": chart_pngs,
        "csv_files": csv_files,
        "html_path": html_path,
        "html_content": html_str,
    }


def _img_to_base64_uri(img_path: str) -> str:
    if not os.path.exists(img_path):
        return ""
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_html_report(
    bundle: AnalyticsReportBundle,
    table_pngs: List[Tuple[str, str]],
    chart_pngs: List[Tuple[str, str]],
) -> str:
    """Gera documento HTML limpo com KPIs (se presentes), tabelas copiáveis e gráficos gerados."""
    kpi_cards_html = ""
    if bundle.kpis:
        cards = ""
        for k in bundle.kpis:
            cards += f"""
            <div style="flex:1; min-width:190px; background:#ffffff; border-top:5px solid {k['color']}; border-radius:6px; padding:12px 14px; box-shadow:0 1px 4px rgba(0,0,0,0.1);">
                <div style="font-size:20px; font-weight:bold; color:{k['color']};">{k['value']}</div>
                <div style="font-size:12px; font-weight:bold; color:#111827; margin-top:4px;">{k['title']}</div>
                <div style="font-size:11px; color:#4b5563; margin-top:4px;">{k['sub']}</div>
            </div>
            """
        kpi_cards_html = f"<div style='display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px;'>{cards}</div>"

    tables_html = ""
    if table_pngs or bundle.tables:
        for tspec in bundle.tables:
            primary_hex = THEME_COLORS.get(tspec.theme, "#0f2c59")
            ths = "".join(
                f"<th style='background:#2b3a4a; color:#ffffff; padding:7px 10px; font-size:12px; border:1px solid #cbd5e1;'>{h}</th>"
                for h in tspec.headers
            )
            trs = ""
            footer_set = set(tspec.footer_row_indices)
            var_set = set(tspec.var_col_indices)
            for r_idx, row in enumerate(tspec.rows):
                bg = "#dce3ec" if r_idx in footer_set else ("#ffffff" if r_idx % 2 == 0 else "#f8fafc")
                fw = "bold" if r_idx in footer_set else "normal"
                tds = ""
                for c_idx, val in enumerate(row):
                    color = "#111827"
                    cell_fw = fw
                    if c_idx in var_set:
                        cell_fw = "bold"
                        if val.startswith("+") or val == "Novo":
                            color = "#15803d"
                        elif val.startswith("-"):
                            color = "#b91c1c"
                    align = "left" if c_idx in (0, 1) and not val.endswith("º") and val != "—" else "center"
                    tds += f"<td style='background:{bg}; color:{color}; font-weight:{cell_fw}; text-align:{align}; padding:6px 10px; font-size:12px; border:1px solid #e2e8f0;'>{val}</td>"
                trs += f"<tr>{tds}</tr>"

            fn_html = f"<div style='font-size:11px; color:#4b5563; font-style:italic; margin-top:5px;'>{tspec.footnote}</div>" if tspec.footnote else ""
            tables_html += f"""
            <div style="margin-bottom:24px; background:#ffffff; padding:14px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.08);">
                <div style="background:{primary_hex}; color:#ffffff; font-weight:bold; font-size:13px; padding:8px 12px; border-radius:4px; text-align:center;">
                    {tspec.title}
                </div>
                <table style="width:100%; border-collapse:collapse; margin-top:6px;">
                    <thead><tr>{ths}</tr></thead>
                    <tbody>{trs}</tbody>
                </table>
                {fn_html}
            </div>
            """

    charts_html = ""
    for ctitle, cpath in chart_pngs:
        uri = _img_to_base64_uri(cpath)
        if uri:
            charts_html += f"""
            <div style="margin-bottom:24px; background:#ffffff; padding:14px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.08); text-align:center;">
                <div style="font-weight:bold; font-size:13px; color:#0f2c59; margin-bottom:8px;">{ctitle}</div>
                <img src="{uri}" style="max-width:100%; height:auto; border:1px solid #e5e7eb; border-radius:4px;" />
            </div>
            """

    period_lbl = bundle.years_asc[0] if len(bundle.years_asc) == 1 else f"{bundle.years_asc[0]}–{bundle.years_asc[-1]}"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<title>Relatório GeoTrabalho — {bundle.uf_name} ({bundle.sector_label})</title>
</head>
<body style="font-family:Segoe UI, Arial, sans-serif; background:#f1f5f9; color:#1f2937; margin:0; padding:18px;">
    <div style="background:#0f2c59; color:#ffffff; padding:16px 20px; border-radius:8px; margin-bottom:18px;">
        <h2 style="margin:0; font-size:18px;">RELATÓRIO GEOTRABALHO — {bundle.uf_name.upper()} ({period_lbl})</h2>
        <div style="font-size:13px; color:#dbeafe; margin-top:4px;">
            Recorte Setorial: <b>{bundle.sector_label}</b> | Fonte: MTE — DardoWeb (RAIS/CAGED)
        </div>
    </div>
    {kpi_cards_html}
    {tables_html}
    {charts_html}
</body>
</html>
"""
