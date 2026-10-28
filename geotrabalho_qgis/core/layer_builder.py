# -*- coding: utf-8 -*-
"""
Construtor e Estilizador de Camadas Vetoriais para o GeoTrabalho no QGIS.
Compatível com QGIS 4 (PyQt6 / Qt6) e QGIS 3 (PyQt5 / Qt5).
"""

import colorsys
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsFillSymbol,
    QgsGeometry,
    QgsGraduatedSymbolRenderer,
    QgsProject,
    QgsProperty,
    QgsRendererCategory,
    QgsRendererRange,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

try:
    from qgis.PyQt.QtCore import QMetaType
    HAS_QMETATYPE = True
except ImportError:
    HAS_QMETATYPE = False

from .dardoweb_client import DardoAggregationResult
from .ibge_api import IbgeMalhasClient
from .municipality_mapper import MunicipalityMapper

LOGGER = logging.getLogger("GeoTrabalho")


def create_qgs_field(name: str, field_type: str) -> QgsField:
    if HAS_QMETATYPE and hasattr(QMetaType, "Type"):
        if field_type == "int":
            return QgsField(name, QMetaType.Type.LongLong)
        elif field_type == "float":
            return QgsField(name, QMetaType.Type.Double)
        else:
            return QgsField(name, QMetaType.Type.QString)
    else:
        if field_type == "int":
            return QgsField(name, QVariant.LongLong)
        elif field_type == "float":
            return QgsField(name, QVariant.Double)
        else:
            return QgsField(name, QVariant.String)


# Cores setoriais clássicas para economia e mercado de trabalho
CNAE_COLORS = {
    "AGRO": "#16a34a",         # Verde floresta (Agropecuária)
    "TRANSF": "#1d4ed8",       # Azul royal (Indústria de Transformação)
    "EXTRA": "#0284c7",        # Azul cobalto (Indústrias Extrativas)
    "CONST": "#d97706",        # Amarelo/Âmbar (Construção Civil)
    "COM": "#ea580c",          # Laranja/Coral (Comércio)
    "SERVICO": "#7c3aed",      # Roxo/Púrpura (Serviços gerais)
    "FINANC": "#0d9488",       # Verde-azulado/Teal (Finanças/Seguros)
    "PUB": "#0891b2",          # Ciano/Petróleo (Administração Pública)
    "SAUDE": "#e11d48",        # Rosa/Rubi (Saúde)
    "EDUC": "#4f46e5",         # Índigo (Educação)
    "INFO": "#9333ea",         # Violeta (TI e Comunicação)
}


class GeoTrabalhoLayerBuilder:
    """Constrói camadas espaciais e aplica simbologias temáticas de mercado de trabalho."""

    @staticmethod
    def build_fields(field_specs: List[Tuple[str, str]]) -> QgsFields:
        fields = QgsFields()
        for name, ftype in field_specs:
            fields.append(create_qgs_field(name, ftype))
        return fields

    @classmethod
    def build_layer_from_ibge_api(
        cls,
        result: DardoAggregationResult,
        layer_name: str = "GeoTrabalho_Municipios",
        qualidade: str = "intermediaria",
        keep_unmatched_polygons: bool = True,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> QgsVectorLayer:
        client = IbgeMalhasClient()
        geojson_path = client.fetch_geojson_for_ufs(
            result.detected_ufs,
            qualidade=qualidade,
            progress_callback=progress_callback,
        )

        ibge_layer = QgsVectorLayer(geojson_path, "ibge_malha_temp", "ogr")
        if not ibge_layer.isValid():
            raise RuntimeError(f"Falha ao carregar malha do IBGE: {geojson_path}")

        return cls.build_layer_from_existing_layer(
            result=result,
            source_layer=ibge_layer,
            ibge_field="codarea",
            layer_name=layer_name,
            keep_unmatched_polygons=keep_unmatched_polygons,
        )

    @classmethod
    def build_layer_from_existing_layer(
        cls,
        result: DardoAggregationResult,
        source_layer: QgsVectorLayer,
        ibge_field: str,
        layer_name: str = "GeoTrabalho_Espacializado",
        keep_unmatched_polygons: bool = True,
    ) -> QgsVectorLayer:
        crs_authid = source_layer.crs().authid() or "EPSG:4674"
        mem_layer = QgsVectorLayer(f"MultiPolygon?crs={crs_authid}", layer_name, "memory")
        provider = mem_layer.dataProvider()

        fields = cls.build_fields(result.field_specs)
        provider.addAttributes(fields.toList())
        mem_layer.updateFields()
        out_fields = mem_layer.fields()

        by_ibge7 = {str(r.get("CD_MUN_IBGE", "")).strip(): r for r in result.records}
        by_ibge6 = {str(r.get("CD_MUN_IBGE", "")).strip()[:6]: r for r in result.records if len(str(r.get("CD_MUN_IBGE", ""))) >= 6}
        mapper = MunicipalityMapper.instance()
        out_features: List[QgsFeature] = []

        for src_feat in source_layer.getFeatures():
            raw_code = str(src_feat[ibge_field] or "").strip()
            clean_code = mapper.format_ibge_code(raw_code)
            rec = by_ibge7.get(clean_code)
            if rec is None and len(clean_code) >= 6:
                rec = by_ibge6.get(clean_code[:6])

            if rec is None and not keep_unmatched_polygons:
                continue

            new_feat = QgsFeature(out_fields)
            new_feat.setGeometry(src_feat.geometry())

            if rec is not None:
                attrs = [rec.get(name) for name, _ in result.field_specs]
            else:
                info = mapper.by_ibge.get(clean_code, {})
                nm_official = info.get("nome", "")
                uf_official = info.get("uf", "")
                attrs = []
                for name, ftype in result.field_specs:
                    if name == "CD_MUN_IBGE":
                        attrs.append(clean_code)
                    elif name == "NM_MUN":
                        attrs.append(nm_official)
                    elif name == "SG_UF":
                        attrs.append(uf_official)
                    elif name == "PREDOMINANTE":
                        attrs.append("Sem registros")
                    elif ftype == "float":
                        attrs.append(0.0)
                    elif ftype == "int":
                        attrs.append(0)
                    else:
                        attrs.append("")

            new_feat.setAttributes(attrs)
            out_features.append(new_feat)

        provider.addFeatures(out_features)
        mem_layer.updateExtents()
        return mem_layer

    @staticmethod
    def _resolve_sector_color(sector_name: str, fallback_idx: int) -> str:
        s_upper = sector_name.upper()
        if "MASCULINO" in s_upper or "HOMENS" in s_upper:
            return "#2563eb"  # Azul vibrante para homens
        if "FEMININO" in s_upper or "MULHERES" in s_upper:
            return "#db2777"  # Rosa/magenta vibrante para mulheres
        if any(k in s_upper for k in ("AGRIC", "PECU", "FLOREST", "PESCA")):
            return CNAE_COLORS["AGRO"]
        if "TRANSFORMA" in s_upper:
            return CNAE_COLORS["TRANSF"]
        if "EXTRATIV" in s_upper:
            return CNAE_COLORS["EXTRA"]
        if "CONSTRU" in s_upper:
            return CNAE_COLORS["CONST"]
        if "COM" in s_upper and "REPARA" in s_upper:
            return CNAE_COLORS["COM"]
        if any(k in s_upper for k in ("FINANC", "SEGURO", "IMOBILI")):
            return CNAE_COLORS["FINANC"]
        if any(k in s_upper for k in ("P_BLICA", "PUBLICA", "DEFESA", "SEGURIDADE")):
            return CNAE_COLORS["PUB"]
        if "SA_DE" in s_upper or "SAUDE" in s_upper:
            return CNAE_COLORS["SAUDE"]
        if "EDUCA" in s_upper:
            return CNAE_COLORS["EDUC"]
        if any(k in s_upper for k in ("INFORMA", "COMUNICA", "TECNOLOG")):
            return CNAE_COLORS["INFO"]

        # Distribuição de matizes áureos para outras categorias
        hue = (fallback_idx * 0.618033988749895) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.52, 0.70)
        return QColor(int(r * 255), int(g * 255), int(b * 255)).name()

    @classmethod
    def apply_predominance_symbology(
        cls,
        layer: QgsVectorLayer,
        field_name: str = "PREDOMINANTE",
        result: Optional[DardoAggregationResult] = None,
    ) -> None:
        """
        Aplica mapa categorizado pelo Setor ou Categoria Predominante no município.
        """
        idx = layer.fields().indexFromName(field_name)
        if idx < 0:
            return

        counts: Dict[str, int] = {}
        for feat in layer.getFeatures():
            val = str(feat[idx] or "").strip()
            if val:
                counts[val] = counts.get(val, 0) + 1

        if not counts:
            return

        sorted_items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        categories: List[QgsRendererCategory] = []

        for i, (val, count) in enumerate(sorted_items):
            c_hex = cls._resolve_sector_color(val, i)
            sym = QgsFillSymbol.createSimple({
                "color": c_hex,
                "outline_color": "#333333",
                "outline_width": "0.18",
            })
            lbl = f"{val} ({count} mun.)"
            categories.append(QgsRendererCategory(val, sym, lbl))

        renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    @classmethod
    def apply_graduated_symbology(
        cls,
        layer: QgsVectorLayer,
        target_field: str = "TOTAL_GERAL",
        color_scheme: str = "blue",
    ) -> None:
        """
        Aplica mapa coroplético em 5 faixas sobre Total de Vínculos/Empresas ou Salário.
        """
        idx = layer.fields().indexFromName(target_field)
        if idx < 0:
            return

        vals = []
        for feat in layer.getFeatures():
            v = feat[idx]
            if v is not None:
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    pass

        if not vals:
            return

        vals.sort()
        min_v, max_v = vals[0], vals[-1]
        if max_v <= min_v:
            max_v = min_v + 1.0

        num_classes = 5
        breaks = [min_v]
        for c_idx in range(1, num_classes):
            q_pos = int(round((c_idx / num_classes) * (len(vals) - 1)))
            b_val = vals[q_pos]
            if b_val <= breaks[-1]:
                b_val = breaks[-1] + (max_v - min_v) / num_classes
            breaks.append(min(max_v, b_val))
        breaks.append(max_v)

        # Paletas graduadas: Azul, Verde ou Laranja/Âmbar
        if color_scheme == "green":
            hex_steps = ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"]
        elif color_scheme == "teal":
            hex_steps = ["#e0f2f1", "#80cbc4", "#26a69a", "#00897b", "#004d40"]
        elif color_scheme == "amber":
            hex_steps = ["#fffbeb", "#fde68a", "#f59e0b", "#d97706", "#92400e"]
        else:
            hex_steps = ["#eff6ff", "#bfdbfe", "#60a5fa", "#2563eb", "#1e3a8a"]

        ranges: List[QgsRendererRange] = []
        for i in range(num_classes):
            low, high = breaks[i], breaks[i + 1]
            sym = QgsFillSymbol.createSimple({
                "color": hex_steps[i],
                "outline_color": "#444444",
                "outline_width": "0.18",
            })
            lbl = f"{int(round(low)):,} a {int(round(high)):,}".replace(",", ".")
            ranges.append(QgsRendererRange(low, high, sym, lbl))

        renderer = QgsGraduatedSymbolRenderer(target_field, ranges)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    @classmethod
    def apply_activity_filter_symbology(
        cls,
        layer: QgsVectorLayer,
        target_field: str = "VINC_FILTR",
        filter_label: str = "Atividade Específica",
    ) -> None:
        """
        Aplica mapa coroplético graduado com paleta contextualizada para a atividade filtrada.
        """
        s_upper = filter_label.upper()
        if any(k in s_upper for k in ("PECU", "AGRO", "RURAL", "BOVIN", "AGRIC")):
            scheme = "green"
        elif any(k in s_upper for k in ("LATIC", "LEITE", "ALIM", "IND")):
            scheme = "teal"
        else:
            scheme = "amber"

        cls.apply_graduated_symbology(layer, target_field=target_field, color_scheme=scheme)

    @classmethod
    def apply_divergent_caged_symbology(
        cls,
        layer: QgsVectorLayer,
        target_field: str = "TOTAL_GERAL",
    ) -> None:
        """
        Aplica simbologia bipolar para Saldo do CAGED (Vermelho < 0 < Azul/Verde).
        """
        idx = layer.fields().indexFromName(target_field)
        if idx < 0:
            return

        steps = [
            (-9999999.0, -100.0, "#b91c1c", "Perda Severa (< -100 vagas)"),
            (-100.0, -1.0, "#f87171", "Perda Moderada (-100 a -1 vagas)"),
            (-1.0, 1.0, "#f3f4f6", "Estável / Neutro (0 vagas)"),
            (1.0, 100.0, "#60a5fa", "Criação Moderada (1 a 100 vagas)"),
            (100.0, 9999999.0, "#1d4ed8", "Alta Criação (> 100 vagas)"),
        ]
        ranges: List[QgsRendererRange] = []
        for low, high, c_hex, lbl in steps:
            sym = QgsFillSymbol.createSimple({
                "color": c_hex,
                "outline_color": "#444444",
                "outline_width": "0.18",
            })
            ranges.append(QgsRendererRange(low, high, sym, lbl))

        renderer = QgsGraduatedSymbolRenderer(target_field, ranges)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
