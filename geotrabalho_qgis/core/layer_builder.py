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
    QgsCentroidFillSymbolLayer,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsFillSymbol,
    QgsGeometry,
    QgsGraduatedSymbolRenderer,
    QgsMarkerSymbol,
    QgsProject,
    QgsProperty,
    QgsRendererCategory,
    QgsRendererRange,
    QgsSimpleFillSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
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
        qualidade: str = "auto",
        keep_unmatched_polygons: bool = True,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        geojson_path: Optional[str] = None,
        filtro_meso: Optional[str] = None,
    ) -> QgsVectorLayer:
        """
        Monta a camada a partir da malha do IBGE. Se `geojson_path` já tiver sido obtido
        (ex.: baixado em segundo plano), nenhum acesso à rede é feito aqui.
        """
        if not geojson_path:
            client = IbgeMalhasClient()
            geojson_path = client.fetch_geojson_for_ufs(
                result.detected_ufs,
                qualidade=qualidade,
                progress_callback=progress_callback,
            )

        ibge_layer = QgsVectorLayer(geojson_path, "ibge_malha_temp", "ogr")
        if not ibge_layer.isValid():
            # Arquivo de cache corrompido (download interrompido): remove para forçar novo download
            try:
                os.remove(geojson_path)
            except OSError as exc:
                LOGGER.debug("Nao foi possivel remover arquivo corrompido %s: %s", geojson_path, exc)
            raise RuntimeError(
                "Falha ao carregar a malha do IBGE (arquivo de cache inválido foi removido). "
                "Execute novamente para baixar a malha."
            )

        return cls.build_layer_from_existing_layer(
            result=result,
            source_layer=ibge_layer,
            ibge_field="codarea",
            layer_name=layer_name,
            keep_unmatched_polygons=keep_unmatched_polygons,
            filtro_meso=filtro_meso,
        )

    @classmethod
    def build_layer_from_existing_layer(
        cls,
        result: DardoAggregationResult,
        source_layer: QgsVectorLayer,
        ibge_field: str,
        layer_name: str = "GeoTrabalho_Espacializado",
        keep_unmatched_polygons: bool = True,
        filtro_meso: Optional[str] = None,
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

            # Filtro opcional por Mesorregião
            if filtro_meso and filtro_meso.strip():
                reg_check = mapper.get_regional_info(clean_code)
                if (reg_check.get("meso") or "").strip().lower() != filtro_meso.strip().lower():
                    continue

            rec = by_ibge7.get(clean_code)
            if rec is None and len(clean_code) >= 6:
                rec = by_ibge6.get(clean_code[:6])

            if rec is None and not keep_unmatched_polygons:
                continue

            new_feat = QgsFeature(out_fields)
            new_feat.setGeometry(src_feat.geometry())

            if rec is not None:
                attrs = [
                    rec.get(name, 0.0 if ftype == "float" else (0 if ftype == "int" else ""))
                    for name, ftype in result.field_specs
                ]
            else:
                info = mapper.by_ibge.get(clean_code, {})
                nm_official = info.get("nome", "")
                uf_official = info.get("uf", "")
                reg_info = mapper.get_regional_info(clean_code)
                macro_official = mapper.get_macrorregiao_for_uf(uf_official)
                attrs = []
                for name, ftype in result.field_specs:
                    if name == "CD_MUN_IBGE":
                        attrs.append(clean_code)
                    elif name == "NM_MUN":
                        attrs.append(nm_official)
                    elif name == "SG_UF":
                        attrs.append(uf_official)
                    elif name == "MACRORREGIAO":
                        attrs.append(macro_official)
                    elif name == "MESORREGIAO":
                        attrs.append(reg_info.get("meso", "Outras"))
                    elif name == "MICRORREGIAO":
                        attrs.append(reg_info.get("micro", "Outras"))
                    elif name == "PREDOMINANTE":
                        attrs.append("Sem registros")
                    elif name == "ESPECIALIZ":
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
                    continue

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
    def apply_ql_symbology(
        cls,
        layer: QgsVectorLayer,
        ql_field: str = "QL",
    ) -> bool:
        """
        Aplica rampa temática divergente padronizada para Quociente Locacional (QL):
        - QL = 0: Cinza claro neutro (Sem registros)
        - 0.00 a 0.75: Sub-representado (Amarelo palha / âmbar claro #fed7aa)
        - 0.75 a 1.25: Equilíbrio com a Média (Azul celeste suave / neutro #bae6fd)
        - 1.25 a 2.00: Especializado / Pólo Local (Azul real vibrante #2563eb)
        - QL >= 2.00: Super Pólo / Cluster Expressivo (Azul marinho profundo #082f49)
        """
        idx = layer.fields().indexFromName(ql_field)
        if idx < 0:
            return False

        classes = [
            (0.000, 0.001, "#f3f4f6", "Sem Registros (QL = 0)"),
            (0.001, 0.750, "#fed7aa", "Sub-representado (QL < 0,75)"),
            (0.750, 1.250, "#bae6fd", "Equilíbrio Regional (0,75 a 1,25)"),
            (1.250, 2.000, "#2563eb", "Especializado / Pólo (1,25 a 2,00)"),
            (2.000, 999999.0, "#082f49", "Super Pólo / Cluster (QL >= 2,00)"),
        ]

        ranges: List[QgsRendererRange] = []
        for low, high, color_hex, label in classes:
            sym = QgsFillSymbol.createSimple({
                "color": color_hex,
                "outline_color": "#ffffff" if color_hex in ("#2563eb", "#082f49") else "#64748b",
                "outline_width": "0.22",
            })
            ranges.append(QgsRendererRange(low, high, sym, label))

        renderer = QgsGraduatedSymbolRenderer(ql_field, ranges)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
        return True




    @classmethod
    def build_centroid_point_layer(
        cls,
        poly_layer: QgsVectorLayer,
        target_field: str,
        layer_name: str = "GeoTrabalho_Circulos",
    ) -> QgsVectorLayer:
        """
        Gera uma camada de pontos (Point) com exatamente 1 centroide por município que possua valor > 0.
        Para feições multipart (municípios com ilhas/enclaves, ex: Florianópolis), seleciona
        obrigatoriamente o sub-polígono de maior área superficial antes de extrair o pointOnSurface.
        Isso elimina duplicação de centroides em ilhas e garante posicionamento representativo.
        """
        crs_authid = poly_layer.crs().authid() or "EPSG:4674"
        pt_layer = QgsVectorLayer(f"Point?crs={crs_authid}", layer_name, "memory")
        pr = pt_layer.dataProvider()
        pr.addAttributes(poly_layer.fields().toList())
        pt_layer.updateFields()

        idx = poly_layer.fields().indexFromName(target_field)
        new_features: List[QgsFeature] = []

        for feat in poly_layer.getFeatures():
            # Filtra apenas municípios com valores positivos
            if idx >= 0:
                val = feat[idx]
                if val is None:
                    continue
                try:
                    fval = float(val)
                    if fval <= 0:
                        continue
                except (ValueError, TypeError):
                    continue

            geom = feat.geometry()
            if not geom or geom.isEmpty():
                continue

            if geom.isMultipart():
                parts = geom.asGeometryCollection()
                if parts:
                    main_part = max(parts, key=lambda p: p.area())
                    pt_geom = main_part.pointOnSurface()
                else:
                    pt_geom = geom.pointOnSurface()
            else:
                pt_geom = geom.pointOnSurface()

            pt_feat = QgsFeature(pt_layer.fields())
            pt_feat.setGeometry(pt_geom)
            pt_feat.setAttributes(feat.attributes())
            new_features.append(pt_feat)

        pr.addFeatures(new_features)
        pt_layer.updateExtents()
        return pt_layer

    @classmethod
    def apply_base_polygon_symbology(cls, poly_layer: QgsVectorLayer) -> None:
        """
        Aplica estilo de mapa base neutro e elegante nos polígonos dos municípios.
        Permite que a camada de círculos proporcionais sobreposta seja visualizada
        com máxima clareza cartográfica, sem poluição visual.
        """
        poly_sym = QgsFillSymbol()
        bg = QgsSimpleFillSymbolLayer()
        bg.setFillColor(QColor("#f8fafc"))    # Slate 50 ultra suave
        bg.setStrokeColor(QColor("#cbd5e1"))  # Slate 300 sutil
        bg.setStrokeWidth(0.18)
        poly_sym.changeSymbolLayer(0, bg)

        poly_layer.setRenderer(QgsSingleSymbolRenderer(poly_sym))
        poly_layer.triggerRepaint()

    @classmethod
    def apply_proportional_circles_symbology(
        cls,
        pt_layer: QgsVectorLayer,
        target_field: str = "TOTAL_GERAL",
        color_scheme: str = "ruby",
        num_classes: int = 5,
    ) -> None:
        """
        Aplica a técnica cartográfica de Círculos Proporcionais / Símbolos Pontuais Graduados.
        Esta função atua em uma camada de pontos (Point), onde cada ponto representa um município.

        Garantias cartográficas:
        1. Ordenação Decrescente (OrderBy target_field DESC): os círculos maiores são desenhados
           primeiro no fundo, e os círculos menores são desenhados por cima, evitando que cidades
           grandes engulam cidades vizinhas menores.
        2. Borda branca e semitransparência (alpha 160-235): permite ler perfeitamente as sobreposições.
        3. Nunca é cortado ou mordido por polígonos vizinhos, pois os pontos ficam em camada sobreposta.
        """
        idx = pt_layer.fields().indexFromName(target_field)
        if idx < 0:
            return

        pos_vals: List[float] = []
        for feat in pt_layer.getFeatures():
            v = feat[idx]
            if v is not None:
                try:
                    fv = float(v)
                    if fv > 0:
                        pos_vals.append(fv)
                except (ValueError, TypeError):
                    continue

        if not pos_vals:
            return

        pos_vals.sort()

        if color_scheme == "blue":
            # Azul Petróleo / Cobalto
            rgba_steps = [
                "37,99,235,160",
                "29,78,216,180",
                "30,64,175,200",
                "30,58,138,220",
                "15,23,42,235",
            ]
        elif color_scheme == "green":
            # Verde Floresta / Esmeralda
            rgba_steps = [
                "22,163,74,160",
                "21,128,61,180",
                "22,101,52,200",
                "20,83,45,220",
                "6,78,59,235",
            ]
        elif color_scheme == "amber":
            # Âmbar / Laranja
            rgba_steps = [
                "245,158,11,165",
                "217,119,6,185",
                "180,83,9,205",
                "146,64,14,225",
                "120,53,15,240",
            ]
        else:
            # Carmesim / Rubi clássico (Padrão para cartografia de trabalho e indústria)
            rgba_steps = [
                "239,68,68,160",   # Vermelho suave
                "220,38,38,180",   # Vermelho
                "185,28,28,200",   # Carmesim
                "153,27,27,220",   # Vinho
                "127,29,29,235",   # Vinho profundo
            ]

        # Diâmetros progressivos dos círculos em milímetros (3.5mm a 21.0mm)
        size_steps = [3.5, 6.5, 10.5, 15.0, 21.0]

        min_pos = pos_vals[0]
        max_pos = pos_vals[-1]
        k = min(num_classes, len(pos_vals))

        breaks = [min_pos]
        for c_idx in range(1, k):
            q_pos = int(round((c_idx / k) * (len(pos_vals) - 1)))
            b_val = pos_vals[q_pos]
            if b_val <= breaks[-1]:
                b_val = breaks[-1] + (max_pos - min_pos) / k
            breaks.append(min(max_pos, b_val))
        breaks.append(max_pos)

        is_integer_range = all(v.is_integer() for v in breaks)
        ranges: List[QgsRendererRange] = []

        for i in range(k):
            low = breaks[i]
            high = breaks[i + 1]
            sz = size_steps[min(i, len(size_steps) - 1)]
            rgba = rgba_steps[min(i, len(rgba_steps) - 1)]

            sym = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": rgba,
                "outline_color": "#ffffff",
                "outline_width": "0.35",
                "size": str(sz),
            })

            if is_integer_range:
                lbl = f"{int(round(low)):,} a {int(round(high)):,}".replace(",", ".")
            else:
                lbl = f"{low:,.1f} a {high:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
            ranges.append(QgsRendererRange(low, high, sym, lbl))

        renderer = QgsGraduatedSymbolRenderer(target_field, ranges)
        # Ordenação decrescente: desenha os maiores círculos primeiro (fundo) e os menores por cima
        renderer.setOrderBy(QgsFeatureRequest.OrderBy([
            QgsFeatureRequest.OrderByClause(target_field, ascending=False)
        ]))
        renderer.setOrderByEnabled(True)

        pt_layer.setRenderer(renderer)
        pt_layer.triggerRepaint()







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










