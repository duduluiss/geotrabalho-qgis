# -*- coding: utf-8 -*-
"""
Interface gráfica do plugin GeoTrabalho - Espacializador e Gerador de Relatórios RAIS/CAGED (DardoWeb).
Autor: Luís Eduardo Araújo de Souza
Compatível com QGIS 4 (PyQt6 / Qt6) e QGIS 3 (PyQt5 / Qt5).
"""

from __future__ import annotations

import json
import logging
import os
import traceback
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.analytics_engine import GeoTrabalhoAnalyticsEngine
from ..core.background_job import BackgroundJob
from ..core.dardoweb_client import DardoWebClient
from ..core.ibge_api import IbgeMalhasClient
from ..core.layer_builder import GeoTrabalhoLayerBuilder
from ..core.report_renderer import export_full_report_bundle

LOGGER = logging.getLogger("GeoTrabalho")

BRAZIL_UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

AVAILABLE_YEARS = [str(y) for y in range(2002, 2026)]

# Catálogo estruturado de relatórios específicos por sub-aba temática
# Cada item: (report_key, titulo_lista, flags_opcoes)
REPORT_CATEGORIES: List[Tuple[str, List[Tuple[str, str, Dict[str, Any]]]]] = [
    (
        "Dinâmica Espacial e Regional",
        [
            (
                "esp_evolucao_vinculos",
                "Evolução Total de Vínculos Trabalhistas (Série Histórica)",
                {"default_out": "chart"},
            ),
            (
                "esp_evolucao_estabelecimentos",
                "Evolução Total de Estabelecimentos (Série Histórica)",
                {"default_out": "chart"},
            ),
            (
                "esp_ranking_vinculos",
                "Ranking Municipal de Vínculos Trabalhistas",
                {"has_topn": True, "has_rank_style": True, "default_out": "table"},
            ),
            (
                "esp_ranking_estabelecimentos",
                "Ranking Municipal de Estabelecimentos (Plantas)",
                {"has_topn": True, "has_rank_style": True, "default_out": "table"},
            ),
            (
                "esp_quadro_global",
                "Quadro Global: Vínculos, Plantas e Porte Médio",
                {"default_out": "both"},
            ),
            (
                "esp_sintese_regional",
                "Síntese por Região do IBGE (% e Porte Médio)",
                {"has_region": True, "has_reg_subview": True, "default_out": "both"},
            ),
            (
                "esp_evolucao_regional",
                "Evolução de Vínculos por Região do IBGE",
                {"has_region": True, "default_out": "both"},
            ),
            (
                "esp_saldo_variacao_municipal",
                "Saldo e Variação % Municipal (Ganhos e Perdas)",
                {"has_topn": True, "needs_2_years": True, "default_out": "chart"},
            ),
            (
                "esp_dispersao_escala",
                "Escala Técnica Municipal (Plantas x Vínculos)",
                {"has_region": True, "has_topn": True, "default_out": "chart"},
            ),
            (
                "esp_concentracao_cr",
                "Concentração Espacial (CR4, Top 10 e Demais)",
                {"default_out": "chart"},
            ),
        ],
    ),
    (
        "Perfil do Trabalhador",
        [
            (
                "perf_sexo",
                "Sexo do Trabalhador (Homens e Mulheres)",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "perf_escolaridade_agrupada",
                "Escolaridade por Grandes Níveis (5 Faixas)",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "perf_escolaridade",
                "Escolaridade Detalhada (11 Níveis RAIS)",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "perf_faixa_etaria",
                "Faixa Etária dos Trabalhadores",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "perf_nacionalidade",
                "Nacionalidade / Trabalhadores Imigrantes",
                {"has_chart_style": True, "has_foreign_toggle": True, "default_out": "chart"},
            ),
            (
                "perf_tipo_vinculo",
                "Tipo de Vínculo (CLT, Determinado, Aprendiz, etc.)",
                {"has_chart_style": True, "default_out": "chart"},
            ),
        ],
    ),
    (
        "Remuneração e Renda",
        [
            (
                "rem_diferencial_sexo",
                "Diferencial Salarial por Sexo (Homens vs. Mulheres)",
                {"has_wage_unit": True, "has_rem_scope": True, "default_out": "chart"},
            ),
            (
                "rem_evolucao_geral",
                "Evolução da Remuneração Média Geral",
                {"has_wage_unit": True, "default_out": "chart"},
            ),
            (
                "rem_faixas_salariais",
                "Distribuição por Faixa Salarial (em SM)",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "rem_por_escolaridade",
                "Remuneração Média por Escolaridade",
                {"has_wage_unit": True, "default_out": "chart"},
            ),
            (
                "rem_ranking_municipal",
                "Ranking Municipal de Maior Remuneração Média",
                {"has_wage_unit": True, "has_topn": True, "has_rank_style": True, "default_out": "table"},
            ),
        ],
    ),
    (
        "Estrutura e Ocupações",
        [
            (
                "est_porte_comparativo",
                "Porte da Planta (% Vínculos vs. % Estabelecimentos)",
                {"default_out": "chart"},
            ),
            (
                "est_porte_evolucao",
                "Evolução de Vínculos por Porte do Estabelecimento",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "est_tempo_emprego",
                "Tempo de Permanência no Emprego / Rotatividade",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "est_natureza_juridica",
                "Natureza Jurídica (Ltda, S/A, Cooperativa, Pública)",
                {"has_chart_style": True, "has_cubo_choice": True, "default_out": "chart"},
            ),
            (
                "est_ocupacoes_cbo",
                "Grandes Grupos Ocupacionais (CBO 2002)",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "est_jornada_horas",
                "Jornada Contratada (Faixa de Horas Semanais)",
                {"has_chart_style": True, "default_out": "chart"},
            ),
            (
                "est_simples_nacional",
                "Adesão ao Simples Nacional (Sim vs. Não)",
                {"has_chart_style": True, "has_cubo_choice": True, "default_out": "chart"},
            ),
        ],
    ),
]


def _sp_max_fixed() -> Tuple[Any, Any]:
    if hasattr(QSizePolicy, "Policy"):
        return QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
    return QSizePolicy.Maximum, QSizePolicy.Fixed


def make_compact_button(text: str, primary: bool = False) -> QPushButton:
    """Cria botão compacto que não se estende horizontalmente pela tela."""
    btn = QPushButton(text)
    h_pol, v_pol = _sp_max_fixed()
    btn.setSizePolicy(h_pol, v_pol)
    if primary:
        btn.setMinimumHeight(30)
        btn.setStyleSheet(
            "QPushButton { background-color: #0f2c59; color: #ffffff; font-weight: bold; "
            "padding: 5px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1e3a8a; }"
            "QPushButton:disabled { background-color: #94a3b8; }"
        )
    else:
        btn.setMinimumHeight(26)
        btn.setStyleSheet("padding: 3px 10px;")
    return btn


def load_cnae_catalog() -> Dict[str, List[Dict[str, str]]]:
    """Carrega o catálogo completo da CNAE (Seções, Divisões, Grupos e Classes com códigos)."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    json_path = os.path.join(data_dir, "cnae_catalog.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            LOGGER.warning("Falha ao carregar cnae_catalog.json: %s", exc)
    return {"secoes": [], "divisoes": [], "grupos": [], "classes": []}


class GeoTrabalhoDialog(QDialog):
    """Diálogo principal para espacialização e geração granular de relatórios e gráficos RAIS/CAGED."""

    def __init__(self, iface, parent: Optional[QWidget] = None):
        super().__init__(parent or (iface.mainWindow() if iface else None))
        self.iface = iface
        self.client = DardoWebClient()
        self.analytics_engine = GeoTrabalhoAnalyticsEngine(self.client)
        self._layer_map: Dict[str, QgsVectorLayer] = {}
        self._cnae_catalog = load_cnae_catalog()
        self._last_report_export: Optional[Dict[str, Any]] = None
        self._preview_items: List[Tuple[str, str]] = []
        self._year_checkboxes: Dict[str, QCheckBox] = {}
        self._subtab_lists: List[QListWidget] = []
        self._report_meta_by_key: Dict[str, Dict[str, Any]] = {}
        self._active_job: Optional[BackgroundJob] = None
        self._close_after_job = False

        self.setWindowTitle("GeoTrabalho - Espacializador e Relatórios RAIS/CAGED (DardoWeb / MTE)")
        self._setup_ui()
        self._populate_project_layers()
        self._on_filtro_nivel_changed()
        self._on_rep_filtro_nivel_changed()
        self._update_contextual_options()
        self._adjust_to_screen()

    def _adjust_to_screen(self) -> None:
        self.setMinimumSize(640, 580)
        target_w, target_h = 720, 710
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_w = min(740, max(640, int(avail.width() * 0.50)))
            target_h = min(760, max(600, int(avail.height() * 0.84)))
        self.resize(target_w, target_h)

    @staticmethod
    def _prevent_horizontal_stretch(cmb: QComboBox, min_chars: int = 16, popup_min_w: int = 380) -> None:
        """Impede que itens longos (como descrições CNAE) forcem a janela a ficar larga horizontalmente."""
        pol = (
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            if hasattr(QComboBox, "SizeAdjustPolicy")
            else QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        cmb.setSizeAdjustPolicy(pol)
        cmb.setMinimumContentsLength(min_chars)
        if cmb.view() is not None:
            cmb.view().setMinimumWidth(popup_min_w)

    def _setup_searchable_combo(self, cmb: QComboBox) -> None:
        cmb.setEditable(True)
        if hasattr(QComboBox, "InsertPolicy"):
            cmb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        else:
            cmb.setInsertPolicy(QComboBox.NoInsert)
        self._prevent_horizontal_stretch(cmb, min_chars=18, popup_min_w=460)
        comp = cmb.completer()
        if comp is not None:
            flag = Qt.MatchFlag.MatchContains if hasattr(Qt, "MatchFlag") else Qt.MatchContains
            comp.setFilterMode(flag)

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_main_tab_changed)
        root_layout.addWidget(self.tabs, stretch=1)

        # =============================================================
        # ABA 1: Configuração e Espacialização
        # =============================================================
        scroll_t1 = QScrollArea()
        scroll_t1.setWidgetResizable(True)
        scroll_t1.setFrameShape(QFrame.Shape.NoFrame if hasattr(QFrame, "Shape") else QFrame.NoFrame)

        main_page = QWidget()
        page_layout = QVBoxLayout(main_page)
        page_layout.setContentsMargins(4, 4, 4, 4)
        page_layout.setSpacing(8)

        grp_source = QGroupBox("1. Origem dos Dados (DardoWeb / MTE)")
        vbox_source = QVBoxLayout(grp_source)
        vbox_source.setContentsMargins(8, 8, 8, 8)
        vbox_source.setSpacing(6)

        row_src_mode = QHBoxLayout()
        row_src_mode.addWidget(QLabel("Modo:"))
        self.cmb_source_mode = QComboBox()
        self.cmb_source_mode.addItem("Consulta Online Direta ao DardoWeb (Automática)", "online")
        self.cmb_source_mode.addItem("Importar Arquivo Local Exportado (.html, .htm)", "local")
        self.cmb_source_mode.currentIndexChanged.connect(self._on_source_mode_changed)
        row_src_mode.addWidget(self.cmb_source_mode, stretch=1)
        vbox_source.addLayout(row_src_mode)

        self.wid_online = QWidget()
        grid_online = QGridLayout(self.wid_online)
        grid_online.setContentsMargins(0, 2, 0, 0)
        grid_online.setHorizontalSpacing(8)
        grid_online.setVerticalSpacing(6)

        grid_online.addWidget(QLabel("Base / Módulo:"), 0, 0)
        self.cmb_cubo = QComboBox()
        self.cmb_cubo.addItem("RAIS Vínculos (Estoque de trabalhadores)", "rais_vinculos")
        self.cmb_cubo.addItem("RAIS Estabelecimentos (Empresas / Plantas)", "rais_estabelecimentos")
        self.cmb_cubo.addItem("CAGED (Admissões e Desligamentos)", "caged")
        self.cmb_cubo.currentIndexChanged.connect(self._on_cubo_changed)
        grid_online.addWidget(self.cmb_cubo, 0, 1, 1, 3)

        grid_online.addWidget(QLabel("Ano:"), 1, 0)
        self.cmb_ano = QComboBox()
        for y in range(2025, 2001, -1):
            self.cmb_ano.addItem(str(y), str(y))
        self.cmb_ano.setCurrentText("2025")
        self.cmb_ano.currentIndexChanged.connect(self._on_ano_changed)
        grid_online.addWidget(self.cmb_ano, 1, 1)

        grid_online.addWidget(QLabel("UF:"), 1, 2)
        self.cmb_uf = QComboBox()
        self.cmb_uf.addItem("TODAS (Brasil)", "BR")
        for u in sorted(BRAZIL_UFS):
            self.cmb_uf.addItem(u, u)
        self.cmb_uf.setCurrentText("SC")
        grid_online.addWidget(self.cmb_uf, 1, 3)

        self.lbl_ano_info = QLabel("")
        self.lbl_ano_info.setWordWrap(True)
        self.lbl_ano_info.setStyleSheet("color: #b45309; font-size: 11px; font-weight: bold; padding: 2px;")
        self.lbl_ano_info.setVisible(False)
        grid_online.addWidget(self.lbl_ano_info, 2, 0, 1, 4)

        grid_online.addWidget(QLabel("Cruzamento:"), 3, 0)
        self.cmb_coluna = QComboBox()
        self.cmb_coluna.addItem("CNAE 2.0 Seção (21 Grandes Setores)", ("CNAE 2.0 Seção", "secoes"))
        self.cmb_coluna.addItem("CNAE 2.0 Divisão (87 Ramos)", ("CNAE 2.0 Div", "divisoes"))
        self.cmb_coluna.addItem("CNAE 2.0 Grupo (285 Grupos)", ("CNAE 2.0 Grupo", "grupos"))
        self.cmb_coluna.addItem("CNAE 2.0 Classe (673 Classes)", ("CNAE 2.0 Classe", "classes"))
        self.cmb_coluna.addItem("Sexo do Trabalhador (Homens vs. Mulheres)", ("Sexo Trabalhador", "sexo"))
        self.cmb_coluna.addItem("Tamanho do Estabelecimento (Porte)", ("Tamanho Estabelecimento", "porte"))
        self.cmb_coluna.addItem("Faixa Etária", ("Faixa Etária", "faixa_etaria"))
        self.cmb_coluna.addItem("Escolaridade após 2005", ("Escolaridade após 2005", "escolaridade"))
        self.cmb_coluna.addItem("Nacionalidade (Imigração)", ("Nacionalidade", "nacionalidade"))
        self.cmb_coluna.addItem("Faixa de Remuneração Média (SM)", ("Faixa Remun Média (SM)", "faixa_remun"))
        self.cmb_coluna.addItem("Faixa de Tempo de Emprego", ("Faixa Tempo Emprego", "faixa_tempo"))
        self.cmb_coluna.addItem("Natureza Jurídica", ("Natureza Jurídica", "nat_jur"))
        self.cmb_coluna.addItem("CBO 2002 Grande Grupo Ocupacional", ("CBO 2002 Gr Grupo", "cbo_gr"))
        self.cmb_coluna.addItem("Apenas Total por Município (Sem cruzamento)", ("---------Não---------", "none"))
        self.cmb_coluna.currentIndexChanged.connect(self._on_coluna_changed)
        grid_online.addWidget(self.cmb_coluna, 3, 1, 1, 3)

        grid_online.addWidget(QLabel("Indicador:"), 4, 0)
        self.cmb_indicador = QComboBox()
        self.cmb_indicador.addItem("Quantidade (Vínculos ou Empresas)", ("->Frequência", "Soma"))
        self.cmb_indicador.addItem("Remuneração Média em Reais (R$)", ("Vl Remun Média Nom", "Média"))
        self.cmb_indicador.addItem("Remuneração Média em Salários Mínimos (SM)", ("Vl Remun Média (SM)", "Média"))
        self.cmb_indicador.addItem("Massa Salarial Total em Reais (Soma R$)", ("Vl Remun Média Nom", "Soma"))
        self.cmb_indicador.addItem("Tempo Médio de Emprego (Meses)", ("Tempo Emprego", "Média"))
        self.cmb_indicador.addItem("Idade Média dos Trabalhadores (Anos)", ("Idade", "Média"))
        grid_online.addWidget(self.cmb_indicador, 4, 1, 1, 3)

        grid_online.addWidget(QLabel("Filtro CNAE:"), 5, 0)
        self.cmb_filtro_nivel = QComboBox()
        self.cmb_filtro_nivel.addItem("[Toda a Economia (Sem filtro)]", "none")
        self.cmb_filtro_nivel.addItem("Seção CNAE (21 Grandes Setores)", "secoes")
        self.cmb_filtro_nivel.addItem("Divisão CNAE (87 Ramos)", "divisoes")
        self.cmb_filtro_nivel.addItem("Grupo CNAE (285 Grupos)", "grupos")
        self.cmb_filtro_nivel.addItem("Classe CNAE (673 Classes)", "classes")
        self.cmb_filtro_nivel.currentIndexChanged.connect(self._on_filtro_nivel_changed)
        grid_online.addWidget(self.cmb_filtro_nivel, 5, 1, 1, 3)

        grid_online.addWidget(QLabel("Atividade:"), 6, 0)
        self.cmb_atividade = QComboBox()
        self._setup_searchable_combo(self.cmb_atividade)
        grid_online.addWidget(self.cmb_atividade, 6, 1, 1, 3)
        grid_online.setColumnStretch(1, 1)
        grid_online.setColumnStretch(3, 1)

        vbox_source.addWidget(self.wid_online)

        self.wid_local = QWidget()
        vbox_local = QVBoxLayout(self.wid_local)
        vbox_local.setContentsMargins(0, 0, 0, 0)
        vbox_local.setSpacing(6)

        row_local_file = QHBoxLayout()
        row_local_file.addWidget(QLabel("Arquivo Local:"))
        self.txt_local_file = QLineEdit()
        self.txt_local_file.setPlaceholderText("Selecione o arquivo .html salvo pelo DardoWeb...")
        self.btn_browse = make_compact_button("Procurar...")
        self.btn_browse.clicked.connect(self._on_browse_file)
        row_local_file.addWidget(self.txt_local_file, stretch=1)
        row_local_file.addWidget(self.btn_browse)
        vbox_local.addLayout(row_local_file)

        row_local_filter = QHBoxLayout()
        row_local_filter.addWidget(QLabel("Atividade / Filtro:"))
        self.cmb_local_atividade = QComboBox()
        self._setup_searchable_combo(self.cmb_local_atividade)
        row_local_filter.addWidget(self.cmb_local_atividade, stretch=1)
        vbox_local.addLayout(row_local_filter)

        self.wid_local.setVisible(False)
        vbox_source.addWidget(self.wid_local)
        page_layout.addWidget(grp_source)

        grp_spatial = QGroupBox("2. Modo de Espacialização e Camada")
        vbox_spatial = QVBoxLayout(grp_spatial)
        vbox_spatial.setContentsMargins(8, 8, 8, 8)
        vbox_spatial.setSpacing(6)

        row_sp_mode = QHBoxLayout()
        row_sp_mode.addWidget(QLabel("Geometria:"))
        self.cmb_spatial_mode = QComboBox()
        self.cmb_spatial_mode.addItem("Baixar malha municipal da API do IBGE (7 dígitos)", "ibge_api")
        self.cmb_spatial_mode.addItem("Unir (Join 1:1) com camada municipal já aberta no QGIS", "existing_layer")
        self.cmb_spatial_mode.currentIndexChanged.connect(self._on_spatial_mode_changed)
        row_sp_mode.addWidget(self.cmb_spatial_mode, stretch=1)
        vbox_spatial.addLayout(row_sp_mode)

        self.wid_existing = QWidget()
        grid_ex = QGridLayout(self.wid_existing)
        grid_ex.setContentsMargins(0, 0, 0, 0)
        grid_ex.addWidget(QLabel("Camada QGIS:"), 0, 0)
        self.cmb_existing_layer = QComboBox()
        self.cmb_existing_layer.currentIndexChanged.connect(self._on_existing_layer_changed)
        grid_ex.addWidget(self.cmb_existing_layer, 0, 1)
        grid_ex.addWidget(QLabel("Campo IBGE:"), 1, 0)
        self.cmb_ibge_field = QComboBox()
        grid_ex.addWidget(self.cmb_ibge_field, 1, 1)
        grid_ex.setColumnStretch(1, 1)
        self.wid_existing.setVisible(False)
        vbox_spatial.addWidget(self.wid_existing)

        row_symb = QHBoxLayout()
        row_symb.addWidget(QLabel("Simbologia:"))
        self.cmb_symbology = QComboBox()
        self.cmb_symbology.addItem("Automática (Atividade Filtrada ou Predominância)", "auto")
        self.cmb_symbology.addItem("Círculos Proporcionais no Centroide (Vermelho Carmesim)", "proportional_circles")
        self.cmb_symbology.addItem("Círculos Proporcionais no Centroide (Azul Petróleo)", "proportional_circles_blue")
        self.cmb_symbology.addItem("Círculos Proporcionais no Centroide (Verde Floresta)", "proportional_circles_green")
        self.cmb_symbology.addItem("Círculos Proporcionais no Centroide (Âmbar / Laranja)", "proportional_circles_amber")
        self.cmb_symbology.addItem("Graduado Coroplético em Tons Verdes", "graduated_green")
        self.cmb_symbology.addItem("Graduado Coroplético em Tons Azuis", "graduated_blue")
        self.cmb_symbology.addItem("Predominância Setorial / Categoria", "predominance")
        self.cmb_symbology.addItem("Saldo Divergente CAGED (Vermelho < 0 < Azul)", "caged_divergent")
        self.cmb_symbology.addItem("Sem Simbologia Automática", "none")
        row_symb.addWidget(self.cmb_symbology, stretch=1)
        vbox_spatial.addLayout(row_symb)

        page_layout.addWidget(grp_spatial)
        page_layout.addStretch(1)

        scroll_t1.setWidget(main_page)
        self.tabs.addTab(scroll_t1, "1. Configuração e Espacialização")

        # =============================================================
        # ABA 2: Relatórios, Tabelas e Gráficos
        # =============================================================
        self._build_reports_tab()

        # =============================================================
        # ABA 3: Log de Execução
        # =============================================================
        log_page = QWidget()
        vbox_log = QVBoxLayout(log_page)
        vbox_log.setContentsMargins(6, 6, 6, 6)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        vbox_log.addWidget(self.txt_log)
        self.tabs.addTab(log_page, "3. Log de Execução")

        # Rodapé compacto
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(150)
        footer.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Pronto.")
        footer.addWidget(self.lbl_status, stretch=1)

        self.btn_run = make_compact_button("Consultar e Gerar Camada", primary=True)
        self.btn_run.clicked.connect(self._on_run_clicked)
        footer.addWidget(self.btn_run)

        self.btn_cancel_job = make_compact_button("Cancelar")
        self.btn_cancel_job.setToolTip("Interrompe a consulta em andamento após a resposta atual do servidor")
        self.btn_cancel_job.clicked.connect(self._on_cancel_job_clicked)
        self.btn_cancel_job.setVisible(False)
        footer.addWidget(self.btn_cancel_job)

        btn_close = make_compact_button("Fechar")
        btn_close.clicked.connect(self.reject)
        footer.addWidget(btn_close)

        root_layout.addLayout(footer)

    def _build_reports_tab(self) -> None:
        """Constrói a Aba 2 com layout compacto, seleção clicável de anos e sub-abas temáticas."""
        rep_scroll = QScrollArea()
        rep_scroll.setWidgetResizable(True)
        rep_scroll.setFrameShape(QFrame.Shape.NoFrame if hasattr(QFrame, "Shape") else QFrame.NoFrame)

        rep_page = QWidget()
        rep_layout = QVBoxLayout(rep_page)
        rep_layout.setContentsMargins(4, 4, 4, 4)
        rep_layout.setSpacing(6)

        # -------------------------------------------------------------
        # 1. Recorte Territorial e Setor CNAE (compacto em 2 linhas)
        # -------------------------------------------------------------
        grp_scope = QGroupBox("1. Recorte Territorial e Setor CNAE")
        grid_scope = QGridLayout(grp_scope)
        grid_scope.setContentsMargins(8, 6, 8, 6)
        grid_scope.setHorizontalSpacing(8)
        grid_scope.setVerticalSpacing(5)

        grid_scope.addWidget(QLabel("UF:"), 0, 0)
        self.cmb_rep_uf = QComboBox()
        self.cmb_rep_uf.addItem("TODAS (Brasil)", "BR")
        for u in sorted(BRAZIL_UFS):
            self.cmb_rep_uf.addItem(u, u)
        self.cmb_rep_uf.setCurrentText("SC")
        grid_scope.addWidget(self.cmb_rep_uf, 0, 1)

        grid_scope.addWidget(QLabel("Filtro CNAE:"), 0, 2)
        self.cmb_rep_filtro_nivel = QComboBox()
        self.cmb_rep_filtro_nivel.addItem("[Toda a Economia (Sem filtro)]", "none")
        self.cmb_rep_filtro_nivel.addItem("Seção CNAE (21 Grandes Setores)", "secoes")
        self.cmb_rep_filtro_nivel.addItem("Divisão CNAE (87 Ramos)", "divisoes")
        self.cmb_rep_filtro_nivel.addItem("Grupo CNAE (285 Grupos)", "grupos")
        self.cmb_rep_filtro_nivel.addItem("Classe CNAE (673 Classes)", "classes")
        self.cmb_rep_filtro_nivel.setCurrentIndex(0)
        self.cmb_rep_filtro_nivel.currentIndexChanged.connect(self._on_rep_filtro_nivel_changed)
        self._prevent_horizontal_stretch(self.cmb_rep_filtro_nivel, min_chars=16, popup_min_w=300)
        grid_scope.addWidget(self.cmb_rep_filtro_nivel, 0, 3)

        btn_sync = make_compact_button("Copiar da Aba 1")
        btn_sync.setToolTip("Importa a UF e o filtro setorial CNAE configurados na Aba 1")
        btn_sync.clicked.connect(self._sync_from_tab1)
        grid_scope.addWidget(btn_sync, 0, 4)

        grid_scope.addWidget(QLabel("Atividade:"), 1, 0)
        self.cmb_rep_atividade = QComboBox()
        self._setup_searchable_combo(self.cmb_rep_atividade)
        grid_scope.addWidget(self.cmb_rep_atividade, 1, 1, 1, 4)
        grid_scope.setColumnStretch(3, 1)

        rep_layout.addWidget(grp_scope)

        # -------------------------------------------------------------
        # 2. Grade clicável de Anos (3 linhas x 8 colunas: 2002 a 2025)
        # -------------------------------------------------------------
        grp_years = QGroupBox("2. Seleção de Anos")
        vbox_years = QVBoxLayout(grp_years)
        vbox_years.setContentsMargins(8, 5, 8, 5)
        vbox_years.setSpacing(4)

        grid_y = QGridLayout()
        grid_y.setContentsMargins(0, 0, 0, 0)
        grid_y.setHorizontalSpacing(8)
        grid_y.setVerticalSpacing(2)

        for idx, yr in enumerate(AVAILABLE_YEARS):
            chk = QCheckBox(yr)
            chk.setChecked(yr == "2025")
            chk.toggled.connect(self._on_year_selection_changed)
            self._year_checkboxes[yr] = chk
            grid_y.addWidget(chk, idx // 8, idx % 8)
        vbox_years.addLayout(grid_y)

        row_y_btns = QHBoxLayout()
        row_y_btns.setSpacing(6)
        self.lbl_years_summary = QLabel("1 ano marcado: 2025")
        self.lbl_years_summary.setStyleSheet("color: #334155; font-size: 11px;")
        row_y_btns.addWidget(self.lbl_years_summary, stretch=1)

        btn_y_clear = make_compact_button("Limpar")
        btn_y_clear.clicked.connect(lambda: self._set_checked_years([]))
        btn_y_latest = make_compact_button("Apenas 2025")
        btn_y_latest.clicked.connect(lambda: self._set_checked_years(["2025"]))
        row_y_btns.addWidget(btn_y_clear)
        row_y_btns.addWidget(btn_y_latest)
        vbox_years.addLayout(row_y_btns)

        rep_layout.addWidget(grp_years)

        # -------------------------------------------------------------
        # Bloco Central: Sub-Abas Específicas + Opções Contextuais
        # -------------------------------------------------------------
        grp_specific = QGroupBox("3. Escolha da Categoria e do Relatório / Gráfico Específico")
        vbox_spec = QVBoxLayout(grp_specific)
        vbox_spec.setContentsMargins(8, 6, 8, 6)
        vbox_spec.setSpacing(6)

        self.subtabs_reports = QTabWidget()

        sel_mode = (
            QAbstractItemView.SelectionMode.SingleSelection
            if hasattr(QAbstractItemView, "SelectionMode")
            else QAbstractItemView.SingleSelection
        )

        for cat_title, items in REPORT_CATEGORIES:
            tab_w = QWidget()
            tab_l = QVBoxLayout(tab_w)
            tab_l.setContentsMargins(4, 4, 4, 4)
            lst = QListWidget()
            lst.setSelectionMode(sel_mode)
            lst.setMinimumHeight(112)
            lst.setMaximumHeight(138)
            for r_key, r_label, r_meta in items:
                self._report_meta_by_key[r_key] = r_meta
                lw_item = QListWidgetItem(r_label)
                lw_item.setData(Qt.ItemDataRole.UserRole if hasattr(Qt, "ItemDataRole") else Qt.UserRole, r_key)
                lst.addItem(lw_item)
            lst.setCurrentRow(0)
            self._subtab_lists.append(lst)
            tab_l.addWidget(lst)
            self.subtabs_reports.addTab(tab_w, cat_title)

        vbox_spec.addWidget(self.subtabs_reports)

        # Linha compacta de Opções Contextuais (só mostra o que se aplica ao item selecionado)
        self.wid_ctx_opts = QWidget()
        grid_opts = QGridLayout(self.wid_ctx_opts)
        grid_opts.setContentsMargins(2, 0, 2, 0)
        grid_opts.setHorizontalSpacing(8)
        grid_opts.setVerticalSpacing(4)

        self.lbl_opt_out = QLabel("Formato de Saída:")
        self.cmb_opt_out = QComboBox()
        self.cmb_opt_out.addItem("Apenas Gráfico (PNG)", "chart")
        self.cmb_opt_out.addItem("Apenas Tabela (PNG + CSV)", "table")
        self.cmb_opt_out.addItem("Gráfico e Tabela (PNG + CSV)", "both")
        grid_opts.addWidget(self.lbl_opt_out, 0, 0)
        grid_opts.addWidget(self.cmb_opt_out, 0, 1)

        # Opção contextual: Estilo de Gráfico Categórico
        self.lbl_opt_style = QLabel("Exibição do Gráfico:")
        self.cmb_opt_style = QComboBox()
        self.cmb_opt_style.addItem("Barras (Valores Absolutos)", "bars_abs")
        self.cmb_opt_style.addItem("Barras (Participação %)", "bars_pct")
        self.cmb_opt_style.addItem("Rosca / Proporção (%) (Último Ano)", "donut")
        grid_opts.addWidget(self.lbl_opt_style, 0, 2)
        grid_opts.addWidget(self.cmb_opt_style, 0, 3)

        # Opção contextual: Quantidade no Ranking (apenas quando item é Ranking Municipal!)
        self.lbl_opt_topn = QLabel("Tamanho do Ranking:")
        self.cmb_opt_topn = QComboBox()
        self.cmb_opt_topn.addItem("Top 5 Municípios", 5)
        self.cmb_opt_topn.addItem("Top 10 Municípios", 10)
        self.cmb_opt_topn.addItem("Top 15 Municípios", 15)
        self.cmb_opt_topn.addItem("Top 20 Municípios", 20)
        self.cmb_opt_topn.addItem("Top 30 Municípios", 30)
        self.cmb_opt_topn.setCurrentIndex(1)
        grid_opts.addWidget(self.lbl_opt_topn, 1, 0)
        grid_opts.addWidget(self.cmb_opt_topn, 1, 1)

        # Opção contextual: Estilo de Gráfico no Ranking Multi-Anos
        self.lbl_opt_rank_style = QLabel("Gráfico do Ranking:")
        self.cmb_opt_rank_style = QComboBox()
        self.cmb_opt_rank_style.addItem("Barras por Ano (Todos os Anos)", "bars")
        self.cmb_opt_rank_style.addItem("Linhas de Evolução Temporal", "lines")
        grid_opts.addWidget(self.lbl_opt_rank_style, 1, 2)
        grid_opts.addWidget(self.cmb_opt_rank_style, 1, 3)

        # Opção contextual: Divisão Regional IBGE (apenas quando item é Regional!)
        self.lbl_opt_region = QLabel("Divisão Regional IBGE:")
        self.cmb_opt_region = QComboBox()
        self.cmb_opt_region.addItem("Mesorregiões do IBGE", "meso")
        self.cmb_opt_region.addItem("Regiões Intermediárias IBGE", "interm")
        self.cmb_opt_region.addItem("Microrregiões do IBGE", "micro")
        grid_opts.addWidget(self.lbl_opt_region, 2, 0)
        grid_opts.addWidget(self.cmb_opt_region, 2, 1)

        # Opção contextual: Sub-visão do painel regional
        self.lbl_opt_reg_subview = QLabel("Gráfico Regional:")
        self.cmb_opt_reg_subview = QComboBox()
        self.cmb_opt_reg_subview.addItem("Painel Duplo (% + Porte Médio)", "painel_duplo")
        self.cmb_opt_reg_subview.addItem("Apenas Participação (%)", "apenas_participacao")
        self.cmb_opt_reg_subview.addItem("Apenas Porte Médio", "apenas_porte")
        grid_opts.addWidget(self.lbl_opt_reg_subview, 2, 2)
        grid_opts.addWidget(self.cmb_opt_reg_subview, 2, 3)

        # Opção contextual: Unidade Salarial + Escopo Salarial
        self.lbl_opt_wage_unit = QLabel("Unidade Monetária:")
        self.cmb_opt_wage_unit = QComboBox()
        self.cmb_opt_wage_unit.addItem("Reais Nominais (R$)", "BRL")
        self.cmb_opt_wage_unit.addItem("Salários Mínimos (SM)", "SM")
        grid_opts.addWidget(self.lbl_opt_wage_unit, 3, 0)
        grid_opts.addWidget(self.cmb_opt_wage_unit, 3, 1)

        self.lbl_opt_rem_scope = QLabel("Recorte da Comparação:")
        self.cmb_opt_rem_scope = QComboBox()
        self.cmb_opt_rem_scope.addItem("Série por Ano (Média Geral)", "serie_uf")
        self.cmb_opt_rem_scope.addItem("Por Região do IBGE (Último Ano)", "regiao_ibge")
        self.cmb_opt_rem_scope.currentIndexChanged.connect(self._on_rem_scope_changed)
        grid_opts.addWidget(self.lbl_opt_rem_scope, 3, 2)
        grid_opts.addWidget(self.cmb_opt_rem_scope, 3, 3)

        # Opção contextual: Base Vínculos vs Estabelecimentos (Natureza Jurídica / Simples)
        self.lbl_opt_cubo = QLabel("Unidade de Contagem:")
        self.cmb_opt_cubo = QComboBox()
        self.cmb_opt_cubo.addItem("Trabalhadores (RAIS Vínculos)", "rais_vinculos")
        self.cmb_opt_cubo.addItem("Empresas / Plantas (RAIS Estab.)", "rais_estabelecimentos")
        grid_opts.addWidget(self.lbl_opt_cubo, 4, 0)
        grid_opts.addWidget(self.cmb_opt_cubo, 4, 1)

        # Opção contextual: Apenas estrangeiros (Nacionalidade)
        self.chk_only_foreigners = QCheckBox("Ocultar nacionalidade brasileira (destacar apenas imigrantes)")
        self.chk_only_foreigners.setChecked(True)
        grid_opts.addWidget(self.chk_only_foreigners, 5, 0, 1, 4)

        grid_opts.setColumnStretch(1, 1)
        grid_opts.setColumnStretch(3, 1)
        vbox_spec.addWidget(self.wid_ctx_opts)

        # Conecta os sinais das sub-abas e listas somente após todos os controles contextuais existirem
        self.subtabs_reports.currentChanged.connect(self._update_contextual_options)
        for lst in self._subtab_lists:
            lst.currentRowChanged.connect(self._update_contextual_options)

        rep_layout.addWidget(grp_specific)

        # -------------------------------------------------------------
        # Bloco de Exportação e Ação (Compacto, botões sem esticar)
        # -------------------------------------------------------------
        grp_export = QGroupBox("4. Exportação")
        vbox_exp = QVBoxLayout(grp_export)
        vbox_exp.setContentsMargins(8, 6, 8, 6)
        vbox_exp.setSpacing(5)

        row_dir = QHBoxLayout()
        row_dir.setSpacing(6)
        default_rep_dir = os.path.join(os.path.expanduser("~"), "GeoTrabalho_Relatorios")
        row_dir.addWidget(QLabel("Pasta:"))
        self.txt_rep_out_dir = QLineEdit(default_rep_dir)
        btn_rep_dir = make_compact_button("Procurar...")
        btn_rep_dir.clicked.connect(self._choose_rep_out_dir)
        btn_open_dir = make_compact_button("Abrir Pasta")
        btn_open_dir.clicked.connect(self._open_rep_out_dir)
        row_dir.addWidget(self.txt_rep_out_dir, stretch=1)
        row_dir.addWidget(btn_rep_dir)
        row_dir.addWidget(btn_open_dir)
        vbox_exp.addLayout(row_dir)

        row_act = QHBoxLayout()
        row_act.setSpacing(8)
        self.chk_export_html = QCheckBox("Salvar também em página HTML")
        self.chk_export_html.setChecked(False)
        row_act.addWidget(self.chk_export_html)

        self.btn_open_html = make_compact_button("Abrir HTML")
        self.btn_open_html.setEnabled(False)
        self.btn_open_html.clicked.connect(self._open_last_html_report)
        row_act.addWidget(self.btn_open_html)

        row_act.addStretch(1)

        self.btn_generate_reports = make_compact_button("Gerar Item Selecionado", primary=True)
        self.btn_generate_reports.clicked.connect(self._on_generate_reports_clicked)
        row_act.addWidget(self.btn_generate_reports)
        vbox_exp.addLayout(row_act)

        rep_layout.addWidget(grp_export)

        # -------------------------------------------------------------
        # Painel de Pré-visualização Integrada
        # -------------------------------------------------------------
        grp_prev = QGroupBox("5. Pré-visualização do Resultado")
        vbox_prev = QVBoxLayout(grp_prev)
        vbox_prev.setContentsMargins(6, 6, 6, 6)
        vbox_prev.setSpacing(4)

        self.wid_prev_selector = QWidget()
        row_sel_prev = QHBoxLayout(self.wid_prev_selector)
        row_sel_prev.setContentsMargins(0, 0, 0, 0)
        row_sel_prev.addWidget(QLabel("Item gerado:"))
        self.cmb_preview_item = QComboBox()
        self._prevent_horizontal_stretch(self.cmb_preview_item, min_chars=20, popup_min_w=460)
        self.cmb_preview_item.currentIndexChanged.connect(self._on_preview_item_changed)
        row_sel_prev.addWidget(self.cmb_preview_item, stretch=1)
        self.wid_prev_selector.setVisible(False)
        vbox_prev.addWidget(self.wid_prev_selector)

        self.lbl_image_preview = QLabel(
            "Selecione o indicador desejado acima e clique em 'Gerar Item Selecionado' para visualizar o gráfico ou tabela aqui."
        )
        self.lbl_image_preview.setWordWrap(True)
        self.lbl_image_preview.setAlignment(
            Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter
        )
        self.lbl_image_preview.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; padding: 8px; color: #475569;")
        self.lbl_image_preview.setMinimumHeight(210)

        prev_img_scroll = QScrollArea()
        prev_img_scroll.setWidgetResizable(True)
        prev_img_scroll.setWidget(self.lbl_image_preview)
        vbox_prev.addWidget(prev_img_scroll, stretch=1)

        rep_layout.addWidget(grp_prev, stretch=1)

        rep_scroll.setWidget(rep_page)
        self.tabs.addTab(rep_scroll, "2. Relatórios, Tabelas e Gráficos")

    def _on_main_tab_changed(self, idx: int) -> None:
        if hasattr(self, "btn_run"):
            self.btn_run.setVisible(idx == 0)

    def _get_selected_years(self) -> List[str]:
        return [yr for yr in AVAILABLE_YEARS if self._year_checkboxes[yr].isChecked()]

    def _set_checked_years(self, target_years: List[str]) -> None:
        tset = set(target_years)
        for yr, chk in self._year_checkboxes.items():
            chk.blockSignals(True)
            chk.setChecked(yr in tset)
            chk.blockSignals(False)
        self._on_year_selection_changed()

    def _on_year_selection_changed(self) -> None:
        sel = self._get_selected_years()
        if not sel:
            self.lbl_years_summary.setText("Nenhum ano marcado")
        elif len(sel) <= 4:
            self.lbl_years_summary.setText(f"{len(sel)} ano(s): {', '.join(sel)}")
        else:
            self.lbl_years_summary.setText(f"{len(sel)} anos ({sel[0]} a {sel[-1]})")

    def _current_report_key(self) -> Optional[str]:
        tab_idx = self.subtabs_reports.currentIndex() if hasattr(self, "subtabs_reports") else 0
        if 0 <= tab_idx < len(self._subtab_lists):
            item = self._subtab_lists[tab_idx].currentItem()
            if item is not None:
                role = Qt.ItemDataRole.UserRole if hasattr(Qt, "ItemDataRole") else Qt.UserRole
                return item.data(role)
        return None

    def _on_rem_scope_changed(self) -> None:
        self._update_contextual_options(preserve_output_format=True)

    def _update_contextual_options(self, *args: Any, preserve_output_format: bool = False) -> None:
        if not hasattr(self, "cmb_opt_out"):
            return
        r_key = self._current_report_key()
        meta = self._report_meta_by_key.get(r_key or "", {})

        if not preserve_output_format and meta.get("default_out"):
            idx_out = self.cmb_opt_out.findData(meta["default_out"])
            if idx_out >= 0:
                self.cmb_opt_out.setCurrentIndex(idx_out)

        has_style = bool(meta.get("has_chart_style"))
        self.lbl_opt_style.setVisible(has_style)
        self.cmb_opt_style.setVisible(has_style)

        has_topn = bool(meta.get("has_topn"))
        self.lbl_opt_topn.setVisible(has_topn)
        self.cmb_opt_topn.setVisible(has_topn)

        has_rank_style = bool(meta.get("has_rank_style"))
        self.lbl_opt_rank_style.setVisible(has_rank_style)
        self.cmb_opt_rank_style.setVisible(has_rank_style)

        has_rem_scope = bool(meta.get("has_rem_scope"))
        self.lbl_opt_rem_scope.setVisible(has_rem_scope)
        self.cmb_opt_rem_scope.setVisible(has_rem_scope)

        need_region = bool(meta.get("has_region")) or (
            has_rem_scope and self.cmb_opt_rem_scope.currentData() == "regiao_ibge"
        )
        self.lbl_opt_region.setVisible(need_region)
        self.cmb_opt_region.setVisible(need_region)

        has_reg_sub = bool(meta.get("has_reg_subview"))
        self.lbl_opt_reg_subview.setVisible(has_reg_sub)
        self.cmb_opt_reg_subview.setVisible(has_reg_sub)

        has_wage = bool(meta.get("has_wage_unit"))
        self.lbl_opt_wage_unit.setVisible(has_wage)
        self.cmb_opt_wage_unit.setVisible(has_wage)

        has_cubo = bool(meta.get("has_cubo_choice"))
        self.lbl_opt_cubo.setVisible(has_cubo)
        self.cmb_opt_cubo.setVisible(has_cubo)

        has_foreign = bool(meta.get("has_foreign_toggle"))
        self.chk_only_foreigners.setVisible(has_foreign)

    def _on_rep_filtro_nivel_changed(self) -> None:
        lvl_key = self.cmb_rep_filtro_nivel.currentData() if hasattr(self, "cmb_rep_filtro_nivel") else "none"
        if not lvl_key:
            lvl_key = "none"
        self.cmb_rep_atividade.clear()
        if lvl_key == "none":
            self.cmb_rep_atividade.addItem("[Toda a Economia (Sem filtro setorial)]", None)
            self.cmb_rep_atividade.setEnabled(False)
            return
        self.cmb_rep_atividade.setEnabled(True)
        items = self._cnae_catalog.get(lvl_key, [])
        self.cmb_rep_atividade.addItem(f"[Todas as {len(items)} atividades deste nível]", None)
        for it in items:
            lbl = it.get("label", it.get("name", ""))
            self.cmb_rep_atividade.addItem(lbl, it)
        self.cmb_rep_atividade.setCurrentIndex(0)

    def _sync_from_tab1(self) -> None:
        self.cmb_rep_uf.setCurrentText(self.cmb_uf.currentText())
        lvl = self.cmb_filtro_nivel.currentData()
        idx_l = self.cmb_rep_filtro_nivel.findData(lvl)
        if idx_l >= 0:
            self.cmb_rep_filtro_nivel.setCurrentIndex(idx_l)
        self.cmb_rep_atividade.setCurrentText(self.cmb_atividade.currentText())
        ano_t1 = self.cmb_ano.currentData()
        if ano_t1 and not self._get_selected_years():
            self._set_checked_years([ano_t1])

    def _choose_rep_out_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Escolher Pasta para Exportar Relatórios",
            self.txt_rep_out_dir.text().strip(),
        )
        if folder:
            self.txt_rep_out_dir.setText(folder)

    def _open_rep_out_dir(self) -> None:
        folder = self.txt_rep_out_dir.text().strip()
        if folder:
            os.makedirs(folder, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_last_html_report(self) -> None:
        if self._last_report_export and self._last_report_export.get("html_path"):
            webbrowser.open(f"file:///{self._last_report_export['html_path'].replace(os.sep, '/')}")

    def _on_generate_reports_clicked(self) -> None:
        r_key = self._current_report_key()
        if not r_key:
            QMessageBox.information(self, "Selecionar Item", "Selecione um relatório ou gráfico na lista.")
            return

        sel_years = self._get_selected_years()
        if not sel_years:
            QMessageBox.warning(self, "Selecionar Anos", "Marque pelo menos um ano na seção '2. Seleção de Anos'.")
            return

        meta = self._report_meta_by_key.get(r_key, {})
        if meta.get("needs_2_years") and len(sel_years) < 2:
            QMessageBox.warning(
                self,
                "Período Insuficiente",
                "Esta análise compara variações entre anos. Marque pelo menos 2 anos na seção '2. Seleção de Anos'.",
            )
            return

        uf = self.cmb_rep_uf.currentData() or "SC"
        filtro_nivel = self.cmb_rep_filtro_nivel.currentData()
        filtro_obj = self.cmb_rep_atividade.currentData()
        filtro_codigo = None
        filtro_texto = None
        if isinstance(filtro_obj, dict):
            filtro_codigo = filtro_obj.get("code")
            filtro_texto = filtro_obj.get("label") or filtro_obj.get("name")
        elif isinstance(filtro_obj, str) and filtro_obj:
            filtro_texto = filtro_obj
        else:
            typed = self.cmb_rep_atividade.currentText().strip()
            if typed and not typed.startswith("[Tod"):
                filtro_texto = typed

        out_mode = self.cmb_opt_out.currentData() or "chart"
        include_charts = out_mode in ("chart", "both")
        include_tables = out_mode in ("table", "both")
        include_html = self.chk_export_html.isChecked()

        out_dir = self.txt_rep_out_dir.text().strip() or os.path.join(os.path.expanduser("~"), "GeoTrabalho_Relatorios")

        self.progress_bar.setValue(5)

        engine = self.analytics_engine
        rep_kwargs: Dict[str, Any] = dict(
            report_key=r_key,
            uf=uf,
            years=sel_years,
            filtro_nivel=filtro_nivel if filtro_nivel != "none" else None,
            filtro_codigo=filtro_codigo,
            filtro_texto=filtro_texto,
            top_n=int(self.cmb_opt_topn.currentData() or 10),
            region_mode=str(self.cmb_opt_region.currentData() or "meso"),
            chart_style=str(self.cmb_opt_style.currentData() or "bars_abs"),
            rank_chart_style=str(self.cmb_opt_rank_style.currentData() or "bars"),
            wage_unit=str(self.cmb_opt_wage_unit.currentData() or "BRL"),
            rem_scope=str(self.cmb_opt_rem_scope.currentData() or "serie_uf"),
            regional_subview=str(self.cmb_opt_reg_subview.currentData() or "painel_duplo"),
            base_cubo_override=str(self.cmb_opt_cubo.currentData() or "rais_vinculos"),
            only_foreigners=self.chk_only_foreigners.isChecked(),
        )

        # Consultas ao DardoWeb em segundo plano (podem ser várias: uma por ano selecionado)
        def job(report):
            return engine.run_specific_report(prog_cb=report, **rep_kwargs)

        def on_bundle_ready(bundle) -> None:
            self.progress_bar.setValue(95)
            self._log("Renderizando arquivos solicitados...")
            export_info = export_full_report_bundle(
                bundle,
                out_dir,
                include_tables=include_tables,
                include_charts=include_charts,
                include_html=include_html,
            )
            self._last_report_export = export_info
            self.btn_open_html.setEnabled(bool(export_info.get("html_path")))

            self._preview_items = []
            for title, path in export_info.get("chart_pngs", []):
                self._preview_items.append((f"[Gráfico] {title}", path))
            for title, path in export_info.get("table_pngs", []):
                self._preview_items.append((f"[Tabela] {title}", path))

            self.cmb_preview_item.blockSignals(True)
            self.cmb_preview_item.clear()
            for lbl, p in self._preview_items:
                self.cmb_preview_item.addItem(lbl, p)
            self.cmb_preview_item.blockSignals(False)

            self.wid_prev_selector.setVisible(len(self._preview_items) > 1)

            if self._preview_items:
                self.cmb_preview_item.setCurrentIndex(0)
                self._on_preview_item_changed()

            self.progress_bar.setValue(100)
            parts = []
            if export_info["chart_pngs"]:
                parts.append(f"{len(export_info['chart_pngs'])} gráfico(s) PNG")
            if export_info["table_pngs"]:
                parts.append(f"{len(export_info['table_pngs'])} tabela(s) PNG/CSV")
            if export_info.get("html_path"):
                parts.append("relatório HTML")

            msg_done = f"Concluído: {', '.join(parts)} salvo(s) em:\n{out_dir}"
            self._log(msg_done)
            QMessageBox.information(self, "Geração Concluída", msg_done)

        self._start_job(job, on_bundle_ready, "Iniciando consultas do relatório em segundo plano...")

    def _on_preview_item_changed(self) -> None:
        img_path = self.cmb_preview_item.currentData()
        if not img_path or not os.path.exists(img_path):
            return
        pix = QPixmap(img_path)
        if not pix.isNull():
            avail_w = max(580, self.lbl_image_preview.width() - 20)
            scaled = pix.scaledToWidth(
                min(avail_w, 860),
                Qt.TransformationMode.SmoothTransformation if hasattr(Qt, "TransformationMode") else Qt.SmoothTransformation,
            )
            self.lbl_image_preview.setPixmap(scaled)

    def _log(self, msg: str) -> None:
        self.lbl_status.setText(msg[:72] + ("..." if len(msg) > 72 else ""))
        self.txt_log.append(msg)

    def _on_ano_changed(self) -> None:
        ano_str = self.cmb_ano.currentText().strip()
        try:
            ano_val = int(ano_str)
        except ValueError:
            ano_val = 2025

        if ano_val <= 2005:
            self.lbl_ano_info.setText(
                f"Nota (Ano {ano_val}): Dados até 2005 utilizam a classificação CNAE 95 e Grau de Instrução. "
                "O GeoTrabalho faz a compatibilização automática."
            )
            self.lbl_ano_info.setVisible(True)
        else:
            self.lbl_ano_info.setVisible(False)

    def _on_coluna_changed(self) -> None:
        data_spec = self.cmb_coluna.currentData()
        lvl_key = data_spec[1] if isinstance(data_spec, tuple) else "none"
        if lvl_key in ("secoes", "divisoes", "grupos", "classes") and self.cmb_filtro_nivel.currentData() == "none":
            idx = self.cmb_filtro_nivel.findData(lvl_key)
            if idx >= 0:
                self.cmb_filtro_nivel.setCurrentIndex(idx)

    def _on_filtro_nivel_changed(self) -> None:
        lvl_key = self.cmb_filtro_nivel.currentData() if hasattr(self, "cmb_filtro_nivel") else "none"
        if not lvl_key:
            lvl_key = "none"

        self.cmb_atividade.clear()
        self.cmb_local_atividade.clear()

        if lvl_key == "none":
            self.cmb_atividade.addItem("[Toda a Economia (Sem filtro setorial)]", None)
            self.cmb_atividade.setEnabled(False)
            self.cmb_local_atividade.addItem("[Todas as Atividades]", "")
            return

        self.cmb_atividade.setEnabled(True)
        items = self._cnae_catalog.get(lvl_key, [])
        label_all = f"[Todas as {len(items)} atividades deste nível]"
        self.cmb_atividade.addItem(label_all, None)
        self.cmb_local_atividade.addItem(label_all, "")

        for it in items:
            lbl = it.get("label", it.get("name", ""))
            self.cmb_atividade.addItem(lbl, it)
            self.cmb_local_atividade.addItem(lbl, lbl)

        self.cmb_atividade.setCurrentIndex(0)
        self.cmb_local_atividade.setCurrentIndex(0)

    def _on_source_mode_changed(self) -> None:
        is_online = self.cmb_source_mode.currentData() == "online"
        self.wid_online.setVisible(is_online)
        self.wid_local.setVisible(not is_online)
        if is_online:
            self.btn_run.setText("Consultar e Gerar Camada")
        else:
            self.btn_run.setText("Importar e Espacializar")

    def _on_cubo_changed(self) -> None:
        cubo = self.cmb_cubo.currentData()
        if cubo == "caged":
            idx = self.cmb_symbology.findData("caged_divergent")
            if idx >= 0:
                self.cmb_symbology.setCurrentIndex(idx)
        else:
            idx = self.cmb_symbology.findData("auto")
            if idx >= 0:
                self.cmb_symbology.setCurrentIndex(idx)

    def _on_spatial_mode_changed(self) -> None:
        is_existing = self.cmb_spatial_mode.currentData() == "existing_layer"
        self.wid_existing.setVisible(is_existing)

    def _populate_project_layers(self) -> None:
        self.cmb_existing_layer.clear()
        self._layer_map.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid():
                self._layer_map[lyr.id()] = lyr
                self.cmb_existing_layer.addItem(lyr.name(), lyr.id())
        self._on_existing_layer_changed()

    def _on_existing_layer_changed(self) -> None:
        self.cmb_ibge_field.clear()
        layer_id = self.cmb_existing_layer.currentData()
        if not layer_id or layer_id not in self._layer_map:
            return
        lyr = self._layer_map[layer_id]
        fields = [f.name() for f in lyr.fields()]
        self.cmb_ibge_field.addItems(fields)
        for cand in ["CD_MUN", "CD_MUN_IBGE", "CODAREA", "COD_IBGE", "CD_IBGE"]:
            for idx, f in enumerate(fields):
                if f.upper() == cand:
                    self.cmb_ibge_field.setCurrentIndex(idx)
                    return

    def _on_browse_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar tabela HTML salva do DardoWeb",
            "",
            "Tabelas DardoWeb (*.html *.htm);;Todos os arquivos (*.*)",
        )
        if p:
            self.txt_local_file.setText(p)

    # ------------------------------------------------------------------
    # Execução em segundo plano (evita congelar o QGIS em consultas longas)
    # ------------------------------------------------------------------
    def _job_running(self) -> bool:
        return self._active_job is not None

    def _set_busy(self, busy: bool) -> None:
        self.btn_run.setEnabled(not busy)
        self.btn_generate_reports.setEnabled(not busy)
        self.btn_cancel_job.setVisible(busy)
        self.btn_cancel_job.setEnabled(busy)

    def _start_job(self, fn, on_success, description: str) -> None:
        if self._job_running():
            QMessageBox.information(self, "Processamento em andamento", "Aguarde a conclusão da consulta atual.")
            return
        job = BackgroundJob(fn)
        self._active_job = job
        job.progress.connect(self._on_job_progress)
        job.succeeded.connect(lambda payload: self._on_job_succeeded(payload, on_success))
        job.failed.connect(self._on_job_failed)
        job.cancelled.connect(self._on_job_cancelled)
        self._set_busy(True)
        self._log(description)
        job.start()

    def _on_job_progress(self, pct: int, msg: str) -> None:
        self.progress_bar.setValue(pct)
        self._log(msg)

    def _end_job(self) -> None:
        self._active_job = None
        self._set_busy(False)
        if self._close_after_job:
            self._close_after_job = False
            super().reject()

    def _on_job_succeeded(self, payload: Any, on_success) -> None:
        self._active_job = None
        try:
            if not self._close_after_job:
                on_success(payload)
        except Exception as exc:  # noqa: BLE001 - erro na montagem não pode derrubar o QGIS
            LOGGER.error("Erro ao finalizar processamento: %s\n%s", exc, traceback.format_exc())
            self._log(f"ERRO: {exc}")
            QMessageBox.critical(self, "Erro durante o processamento", str(exc))
        finally:
            self._end_job()

    def _on_job_failed(self, msg: str) -> None:
        self._active_job = None
        self.progress_bar.setValue(0)
        self._log(f"ERRO: {msg}")
        if not self._close_after_job:
            QMessageBox.critical(self, "Erro durante o processamento", msg)
        self._end_job()

    def _on_job_cancelled(self) -> None:
        self._active_job = None
        self.progress_bar.setValue(0)
        self._log("Processamento cancelado pelo usuário.")
        self._end_job()

    def _on_cancel_job_clicked(self) -> None:
        if self._active_job is not None:
            self._active_job.request_cancel()
            self.btn_cancel_job.setEnabled(False)
            self._log("Cancelamento solicitado. Aguardando a resposta atual do servidor terminar...")

    def reject(self) -> None:
        """Impede que a janela seja destruída com uma consulta ainda rodando (causa de crash)."""
        if self._job_running():
            resp = QMessageBox.question(
                self,
                "Processamento em andamento",
                "Há uma consulta em andamento. Deseja cancelá-la e fechar a janela assim que for interrompida?",
            )
            yes_btn = QMessageBox.StandardButton.Yes if hasattr(QMessageBox, "StandardButton") else QMessageBox.Yes
            if resp == yes_btn and self._active_job is not None:
                self._close_after_job = True
                self._active_job.request_cancel()
                self._log("Fechamento solicitado: aguardando a consulta atual ser interrompida...")
            return
        super().reject()

    # ------------------------------------------------------------------
    # Aba 1: Consulta e espacialização
    # ------------------------------------------------------------------
    def _on_run_clicked(self) -> None:
        source_mode = self.cmb_source_mode.currentData()
        spatial_mode = self.cmb_spatial_mode.currentData()
        self.progress_bar.setValue(5)

        # 1) Leitura de TODOS os parâmetros na thread principal (widgets não podem ser lidos na thread de trabalho)
        params: Dict[str, Any] = {"source_mode": source_mode, "spatial_mode": spatial_mode}

        if source_mode == "online":
            col_spec = self.cmb_coluna.currentData()
            indic_spec = self.cmb_indicador.currentData()
            if isinstance(indic_spec, tuple):
                indic, oper = indic_spec
            else:
                indic, oper = str(indic_spec), None

            filtro_obj = self.cmb_atividade.currentData()
            filtro_nivel = self.cmb_filtro_nivel.currentData() if hasattr(self, "cmb_filtro_nivel") else None
            filtro_codigo = None
            filtro_texto = None
            if isinstance(filtro_obj, dict):
                filtro_codigo = filtro_obj.get("code")
                filtro_texto = filtro_obj.get("label") or filtro_obj.get("name")
            elif isinstance(filtro_obj, str) and filtro_obj:
                filtro_texto = filtro_obj
            else:
                text_typed = self.cmb_atividade.currentText().strip()
                if text_typed and not any(text_typed.startswith(prefix) for prefix in ("[Todas", "[Todos", "[Total", "[Ambos")):
                    filtro_texto = text_typed

            params.update({
                "cubo": self.cmb_cubo.currentData(),
                "ano": self.cmb_ano.currentData(),
                "uf": self.cmb_uf.currentData(),
                "col": col_spec[0] if isinstance(col_spec, tuple) else str(col_spec),
                "indic": indic,
                "oper": oper,
                "filtro_nivel": filtro_nivel if filtro_nivel != "none" else None,
                "filtro_codigo": filtro_codigo,
                "filtro_texto": filtro_texto,
            })
        else:
            fpath = self.txt_local_file.text().strip()
            filtro = self.cmb_local_atividade.currentData() or ""
            if not filtro:
                text_typed = self.cmb_local_atividade.currentText().strip()
                if not any(text_typed.startswith(prefix) for prefix in ("[Todas", "[Todos", "[Total", "[Ambos")):
                    filtro = text_typed
            if not fpath or not os.path.exists(fpath):
                QMessageBox.warning(self, "Arquivo inválido", "Selecione um arquivo .html válido do DardoWeb.")
                return
            params.update({"fpath": fpath, "filtro_local": filtro or None})

        if spatial_mode == "existing_layer":
            layer_id = self.cmb_existing_layer.currentData()
            if not layer_id or layer_id not in self._layer_map:
                QMessageBox.warning(self, "Camada não selecionada", "Selecione a camada municipal aberta no QGIS.")
                return
            params["existing_layer_id"] = layer_id
            params["ibge_field"] = self.cmb_ibge_field.currentText()

        params["symbology"] = self.cmb_symbology.currentData()
        params["is_caged"] = source_mode == "online" and self.cmb_cubo.currentData() == "caged"

        client = self.client

        # 2) Trabalho pesado em segundo plano: consulta DardoWeb + download/cache da malha IBGE
        def job(report) -> Dict[str, Any]:
            if params["source_mode"] == "online":
                result = client.query_dardo(
                    base_cubo=params["cubo"],
                    ano=params["ano"],
                    uf=params["uf"],
                    coluna_cruzamento=params["col"],
                    indicador=params["indic"],
                    filtro_atividade=params["filtro_texto"],
                    filtro_cnae_nivel=params["filtro_nivel"],
                    filtro_cnae_codigo=params["filtro_codigo"],
                    operacao=params["oper"],
                    prog_cb=report,
                )
                tag_filtro = f"_{result.filter_applied[:10]}" if result.filter_applied else ""
                layer_suffix = f"{params['ano']}_{params['uf']}{tag_filtro}"
            else:
                report(20, f"Lendo arquivo: {os.path.basename(params['fpath'])}...")
                result = client.parse_local_file(params["fpath"], filtro_atividade=params["filtro_local"])
                tag_filtro = f"_{result.filter_applied[:10]}" if result.filter_applied else ""
                layer_suffix = f"Local{tag_filtro}"

            geojson_path = None
            if result.records and params["spatial_mode"] != "existing_layer":
                report(82, "Obtendo malha municipal do IBGE (cache local ou download)...")
                geojson_path = IbgeMalhasClient().fetch_geojson_for_ufs(
                    result.detected_ufs,
                    qualidade="auto",
                    progress_callback=report,
                )
            report(94, f"Dados prontos: {len(result.records):,} municípios. Montando a camada...".replace(",", "."))
            return {"result": result, "geojson_path": geojson_path, "layer_suffix": layer_suffix}

        self._start_job(
            job,
            lambda payload: self._finish_layer(payload, params),
            "Iniciando consulta em segundo plano (o QGIS continua utilizável durante o processamento)...",
        )

    def _finish_layer(self, payload: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Etapa final na thread principal: monta a camada, aplica simbologia e adiciona ao projeto."""
        result = payload["result"]
        if not result.records:
            QMessageBox.information(self, "Sem registros", "Nenhum município foi encontrado no resultado.")
            return

        if result.filter_applied:
            self._log(f"Atividade selecionada '{result.filter_applied}': {len(result.matched_columns)} colunas identificadas.")

        layer_name = f"GeoTrabalho_{result.base_name[:18]}_{payload['layer_suffix']}"

        if params["spatial_mode"] == "existing_layer":
            src_layer = self._layer_map.get(params["existing_layer_id"])
            if src_layer is None:
                raise RuntimeError("A camada municipal selecionada não está mais disponível no projeto.")
            out_layer = GeoTrabalhoLayerBuilder.build_layer_from_existing_layer(
                result=result,
                source_layer=src_layer,
                ibge_field=params["ibge_field"],
                layer_name=layer_name,
                keep_unmatched_polygons=True,
            )
        else:
            out_layer = GeoTrabalhoLayerBuilder.build_layer_from_ibge_api(
                result=result,
                layer_name=layer_name,
                keep_unmatched_polygons=True,
                geojson_path=payload["geojson_path"],
            )

        symb = params["symbology"]
        has_vinc_filtr = "VINC_FILTR" in [name for name, _ in result.field_specs]
        target_field = "VINC_FILTR" if has_vinc_filtr else "TOTAL_GERAL"
        pt_layer = None

        if symb.startswith("proportional_circles"):
            color_scheme = "ruby"
            if symb == "proportional_circles_blue":
                color_scheme = "blue"
            elif symb == "proportional_circles_green":
                color_scheme = "green"
            elif symb == "proportional_circles_amber":
                color_scheme = "amber"

            # 1. Estiliza a malha base poligonal com preenchimento neutro e contorno sutil
            GeoTrabalhoLayerBuilder.apply_base_polygon_symbology(out_layer)

            # 2. Constrói camada de pontos no centroide com desduplicação de partes insulares (ex: Florianópolis)
            pt_layer_name = f"{layer_name}_Circulos"
            pt_layer = GeoTrabalhoLayerBuilder.build_centroid_point_layer(
                poly_layer=out_layer,
                target_field=target_field,
                layer_name=pt_layer_name,
            )

            # 3. Aplica marcadores circulares graduados com ordenação decrescente (maiores no fundo, menores por cima)
            GeoTrabalhoLayerBuilder.apply_proportional_circles_symbology(
                pt_layer=pt_layer,
                target_field=target_field,
                color_scheme=color_scheme,
            )

            # 4. Adiciona ao projeto: primeiro a base poligonal, depois a camada de círculos no topo
            QgsProject.instance().addMapLayer(out_layer)
            QgsProject.instance().addMapLayer(pt_layer)
        else:
            if symb == "auto":
                if has_vinc_filtr:
                    GeoTrabalhoLayerBuilder.apply_activity_filter_symbology(out_layer, "VINC_FILTR", result.filter_applied)
                elif params["is_caged"]:
                    GeoTrabalhoLayerBuilder.apply_divergent_caged_symbology(out_layer, "TOTAL_GERAL")
                else:
                    GeoTrabalhoLayerBuilder.apply_predominance_symbology(out_layer, "PREDOMINANTE", result=result)
            elif symb == "predominance":
                GeoTrabalhoLayerBuilder.apply_predominance_symbology(out_layer, "PREDOMINANTE", result=result)
            elif symb == "graduated_green":
                GeoTrabalhoLayerBuilder.apply_graduated_symbology(out_layer, target_field, "green")
            elif symb == "graduated_blue":
                GeoTrabalhoLayerBuilder.apply_graduated_symbology(out_layer, target_field, "blue")
            elif symb == "caged_divergent":
                GeoTrabalhoLayerBuilder.apply_divergent_caged_symbology(out_layer, "TOTAL_GERAL")

            QgsProject.instance().addMapLayer(out_layer)

        try:
            if self.iface and self.iface.mapCanvas():
                canvas = self.iface.mapCanvas()
                canvas.setExtent(out_layer.extent().scaled(1.08))
                canvas.refresh()
        except (AttributeError, RuntimeError) as exc:
            self._log(f"Aviso ao ajustar visualização: {exc}")

        self.progress_bar.setValue(100)
        if pt_layer is not None:
            summary = (
                f"Sucesso! Camadas criadas com Círculos Proporcionais:\n"
                f"• Base Poligonal: '{out_layer.name()}' ({out_layer.featureCount():,} municípios)\n"
                f"• Círculos no Centroide: '{pt_layer.name()}' ({pt_layer.featureCount():,} municípios com registros)\n"
                f"Técnica cartográfica: símbolos circulares ordenados (maiores no fundo, menores no topo), "
                f"sem cortes de fronteiras e com centroide único por município."
            )
        else:
            summary = (
                f"Sucesso! Camada '{layer_name}' criada com {out_layer.featureCount():,} municípios.\n"
                f"Campos gerados: {len(result.field_specs)} colunas."
            )
        if result.filter_applied:
            summary += f"\nAtividade CNAE: '{result.filter_applied}' (armazenada em VINC_FILTR e PCT_FILTR)."
        self._log(summary)
        QMessageBox.information(self, "Camada Gerada com Sucesso", summary)
