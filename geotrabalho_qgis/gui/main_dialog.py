# -*- coding: utf-8 -*-
"""
Interface gráfica do plugin GeoTrabalho - Espacializador RAIS/CAGED (DardoWeb).
Autor: Luís Eduardo Araújo de Souza
Compatível com QGIS 4 (PyQt6 / Qt6) e QGIS 3 (PyQt5 / Qt5).
"""

import json
import logging
import os
from typing import Dict, List, Optional

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtWidgets import (
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
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.dardoweb_client import DardoAggregationResult, DardoWebClient
from ..core.ibge_api import IbgeMalhasClient
from ..core.layer_builder import GeoTrabalhoLayerBuilder

LOGGER = logging.getLogger("GeoTrabalho")

BRAZIL_UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]


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
    """Diálogo compacto para consulta, espacialização e mapeamento temático do DardoWeb."""

    def __init__(self, iface, parent: Optional[QWidget] = None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.client = DardoWebClient()
        self._layer_map: Dict[str, QgsVectorLayer] = {}
        self._cnae_catalog = load_cnae_catalog()

        self.setWindowTitle("GeoTrabalho - Espacializador RAIS/CAGED (DardoWeb)")
        self._setup_ui()
        self._populate_project_layers()
        self._on_filtro_nivel_changed()
        self._adjust_to_screen()

    def _adjust_to_screen(self) -> None:
        self.setMinimumSize(850, 520)
        target_w, target_h = 920, 580
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_w = min(1050, max(900, int(avail.width() * 0.75)))
            target_h = min(720, max(560, int(avail.height() * 0.75)))
        self.resize(target_w, target_h)

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, stretch=1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        if hasattr(QFrame, "Shape"):
            scroll.setFrameShape(QFrame.Shape.NoFrame)
        else:
            scroll.setFrameShape(QFrame.NoFrame)

        main_page = QWidget()
        page_layout = QVBoxLayout(main_page)
        page_layout.setContentsMargins(4, 4, 4, 4)
        page_layout.setSpacing(6)

        # -------------------------------------------------------------
        # 1. Origem dos Dados do Ministério do Trabalho (DardoWeb)
        # -------------------------------------------------------------
        grp_source = QGroupBox("1. Origem dos Dados do Ministério do Trabalho (DardoWeb)")
        vbox_source = QVBoxLayout(grp_source)
        vbox_source.setContentsMargins(8, 6, 8, 6)
        vbox_source.setSpacing(4)

        row_src_mode = QHBoxLayout()
        row_src_mode.addWidget(QLabel("Modo:"))
        self.cmb_source_mode = QComboBox()
        self.cmb_source_mode.addItem("Consulta Online Direta ao DardoWeb (Automática)", "online")
        self.cmb_source_mode.addItem("Importar Arquivo Local Exportado (.html, .htm)", "local")
        self.cmb_source_mode.currentIndexChanged.connect(self._on_source_mode_changed)
        row_src_mode.addWidget(self.cmb_source_mode, stretch=1)
        vbox_source.addLayout(row_src_mode)

        # Painel Online
        self.wid_online = QWidget()
        vbox_online = QVBoxLayout(self.wid_online)
        vbox_online.setContentsMargins(0, 0, 0, 0)
        vbox_online.setSpacing(4)

        row_cubo = QHBoxLayout()
        row_cubo.addWidget(QLabel("Base / Módulo:"))
        self.cmb_cubo = QComboBox()
        self.cmb_cubo.addItem("RAIS Vínculos (Emprego formal, estoque de trabalhadores)", "rais_vinculos")
        self.cmb_cubo.addItem("RAIS Estabelecimentos (Empresas ativas, porte e setor)", "rais_estabelecimentos")
        self.cmb_cubo.addItem("CAGED (Movimentação de contratações e demissões)", "caged")
        self.cmb_cubo.currentIndexChanged.connect(self._on_cubo_changed)
        row_cubo.addWidget(self.cmb_cubo, stretch=3)

        row_cubo.addWidget(QLabel("Ano:"))
        self.cmb_ano = QComboBox()
        for y in range(2025, 2001, -1):
            self.cmb_ano.addItem(str(y), str(y))
        self.cmb_ano.setCurrentText("2025")
        self.cmb_ano.currentIndexChanged.connect(self._on_ano_changed)
        row_cubo.addWidget(self.cmb_ano, stretch=1)

        row_cubo.addWidget(QLabel("UF:"))
        self.cmb_uf = QComboBox()
        self.cmb_uf.addItem("TODAS (Brasil)", "BR")
        for u in sorted(BRAZIL_UFS):
            self.cmb_uf.addItem(u, u)
        self.cmb_uf.setCurrentText("SC")
        row_cubo.addWidget(self.cmb_uf, stretch=1)
        vbox_online.addLayout(row_cubo)

        self.lbl_ano_info = QLabel("")
        self.lbl_ano_info.setWordWrap(True)
        self.lbl_ano_info.setStyleSheet("color: #b45309; font-size: 11px; font-weight: bold; padding: 2px;")
        self.lbl_ano_info.setVisible(False)
        vbox_online.addWidget(self.lbl_ano_info)

        # Cruzamento (Colunas) e Indicador
        row_nivel = QHBoxLayout()
        row_nivel.addWidget(QLabel("Cruzamento (Colunas):"))
        self.cmb_coluna = QComboBox()
        self.cmb_coluna.addItem("CNAE 2.0 Seção (21 Grandes Setores Econômicos)", ("CNAE 2.0 Seção", "secoes"))
        self.cmb_coluna.addItem("CNAE 2.0 Divisão (87 Ramos de Atividade)", ("CNAE 2.0 Div", "divisoes"))
        self.cmb_coluna.addItem("CNAE 2.0 Grupo (285 Grupos Econômicos)", ("CNAE 2.0 Grupo", "grupos"))
        self.cmb_coluna.addItem("CNAE 2.0 Classe (673 Classes Específicas)", ("CNAE 2.0 Classe", "classes"))
        self.cmb_coluna.addItem("Sexo Trabalhador (Homens vs Mulheres)", ("Sexo Trabalhador", "sexo"))
        self.cmb_coluna.addItem("Tamanho do Estabelecimento (Porte por Faixa de Empregados)", ("Tamanho Estabelecimento", "porte"))
        self.cmb_coluna.addItem("Faixa Etária", ("Faixa Etária", "faixa_etaria"))
        self.cmb_coluna.addItem("Escolaridade após 2005", ("Escolaridade após 2005", "escolaridade"))
        self.cmb_coluna.addItem("Apenas Total por Município (Sem cruzamento)", ("---------Não---------", "none"))
        self.cmb_coluna.currentIndexChanged.connect(self._on_coluna_changed)
        row_nivel.addWidget(self.cmb_coluna, stretch=3)

        row_nivel.addWidget(QLabel("Indicador:"))
        self.cmb_indicador = QComboBox()
        self.cmb_indicador.addItem("Quantidade (Vínculos ou Empresas)", "->Frequência")
        self.cmb_indicador.addItem("Remuneração Média em Salários Mínimos", "Vl Remun Média (SM)")
        self.cmb_indicador.addItem("Remuneração Média em Reais (R$)", "Vl Remun Média Nom")
        row_nivel.addWidget(self.cmb_indicador, stretch=2)
        vbox_online.addLayout(row_nivel)

        # Filtro de Atividade Econômica (CNAE) - Aplicável a QUALQUER cruzamento!
        row_filtro = QHBoxLayout()
        row_filtro.addWidget(QLabel("Filtro Setorial / CNAE:"))
        self.cmb_filtro_nivel = QComboBox()
        self.cmb_filtro_nivel.addItem("[Toda a Economia (Sem filtro)]", "none")
        self.cmb_filtro_nivel.addItem("Filtrar por Seção (21 Grandes Setores)", "secoes")
        self.cmb_filtro_nivel.addItem("Filtrar por Divisão (87 Ramos)", "divisoes")
        self.cmb_filtro_nivel.addItem("Filtrar por Grupo (285 Grupos)", "grupos")
        self.cmb_filtro_nivel.addItem("Filtrar por Classe (673 Classes)", "classes")
        self.cmb_filtro_nivel.currentIndexChanged.connect(self._on_filtro_nivel_changed)
        row_filtro.addWidget(self.cmb_filtro_nivel, stretch=2)

        row_filtro.addWidget(QLabel("Atividade:"))
        self.cmb_atividade = QComboBox()
        self.cmb_atividade.setEditable(True)
        if hasattr(QComboBox, "InsertPolicy"):
            self.cmb_atividade.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        else:
            self.cmb_atividade.setInsertPolicy(QComboBox.NoInsert)
        comp = self.cmb_atividade.completer()
        if comp is not None:
            flag = getattr(getattr(Qt, "MatchFlag", Qt), "MatchContains", 1)
            comp.setFilterMode(flag)
        self.cmb_atividade.setToolTip(
            "Selecione uma atividade específica no menu ou digite para autocompletar.\n"
            "Permite filtrar cruzamentos como Sexo Trabalhador, Porte ou Totais por atividades como Pecuária, Laticínios, Calçados, etc."
        )
        row_filtro.addWidget(self.cmb_atividade, stretch=3)
        vbox_online.addLayout(row_filtro)

        vbox_source.addWidget(self.wid_online)

        # Painel Local
        self.wid_local = QWidget()
        vbox_local = QVBoxLayout(self.wid_local)
        vbox_local.setContentsMargins(0, 0, 0, 0)
        vbox_local.setSpacing(4)

        row_local_file = QHBoxLayout()
        row_local_file.addWidget(QLabel("Arquivo Local:"))
        self.txt_local_file = QLineEdit()
        self.txt_local_file.setPlaceholderText("Selecione o arquivo .html salvo pelo DardoWeb...")
        self.btn_browse = QPushButton("Procurar...")
        self.btn_browse.clicked.connect(self._on_browse_file)
        row_local_file.addWidget(self.txt_local_file, stretch=1)
        row_local_file.addWidget(self.btn_browse)
        vbox_local.addLayout(row_local_file)

        row_local_filter = QHBoxLayout()
        row_local_filter.addWidget(QLabel("Atividade / Filtro:"))
        self.cmb_local_atividade = QComboBox()
        self.cmb_local_atividade.setEditable(True)
        if hasattr(QComboBox, "InsertPolicy"):
            self.cmb_local_atividade.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        else:
            self.cmb_local_atividade.setInsertPolicy(QComboBox.NoInsert)
        comp_loc = self.cmb_local_atividade.completer()
        if comp_loc is not None:
            flag = getattr(getattr(Qt, "MatchFlag", Qt), "MatchContains", 1)
            comp_loc.setFilterMode(flag)
        row_local_filter.addWidget(self.cmb_local_atividade, stretch=1)
        vbox_local.addLayout(row_local_filter)

        self.wid_local.setVisible(False)
        vbox_source.addWidget(self.wid_local)

        page_layout.addWidget(grp_source)

        # -------------------------------------------------------------
        # 2. Espacialização (Malha IBGE v3 ou Camada Existente)
        # -------------------------------------------------------------
        grp_spatial = QGroupBox("2. Modo de Espacialização e Saída")
        vbox_spatial = QVBoxLayout(grp_spatial)
        vbox_spatial.setContentsMargins(8, 6, 8, 6)
        vbox_spatial.setSpacing(4)

        row_sp_mode = QHBoxLayout()
        row_sp_mode.addWidget(QLabel("Geometria:"))
        self.cmb_spatial_mode = QComboBox()
        self.cmb_spatial_mode.addItem("Baixar malha municipal automaticamente da API do IBGE (7 dígitos)", "ibge_api")
        self.cmb_spatial_mode.addItem("Unir (Join 1:1) com camada de municípios já aberta no QGIS", "existing_layer")
        self.cmb_spatial_mode.currentIndexChanged.connect(self._on_spatial_mode_changed)
        row_sp_mode.addWidget(self.cmb_spatial_mode, stretch=1)
        vbox_spatial.addLayout(row_sp_mode)

        self.wid_existing = QWidget()
        row_ex = QHBoxLayout(self.wid_existing)
        row_ex.setContentsMargins(0, 0, 0, 0)
        row_ex.addWidget(QLabel("Camada QGIS:"))
        self.cmb_existing_layer = QComboBox()
        self.cmb_existing_layer.currentIndexChanged.connect(self._on_existing_layer_changed)
        row_ex.addWidget(self.cmb_existing_layer, stretch=2)
        row_ex.addWidget(QLabel("Campo IBGE:"))
        self.cmb_ibge_field = QComboBox()
        row_ex.addWidget(self.cmb_ibge_field, stretch=1)
        self.wid_existing.setVisible(False)
        vbox_spatial.addWidget(self.wid_existing)

        # Simbologia
        row_symb = QHBoxLayout()
        row_symb.addWidget(QLabel("Simbologia Automática:"))
        self.cmb_symbology = QComboBox()
        self.cmb_symbology.addItem("Automática (Destaque para Atividade Filtrada ou Predominância)", "auto")
        self.cmb_symbology.addItem("Predominância Setorial / Categoria (Cores Econômicas Oficiais)", "predominance")
        self.cmb_symbology.addItem("Graduado em Tons Verdes (Volume da Atividade / Agro / Renda)", "graduated_green")
        self.cmb_symbology.addItem("Graduado em Tons Azuis (Volume Geral de Empregos)", "graduated_blue")
        self.cmb_symbology.addItem("Saldo Bipolar do CAGED (Vermelho < 0 < Azul)", "caged_divergent")
        self.cmb_symbology.addItem("Sem Simbologia Automática", "none")
        row_symb.addWidget(self.cmb_symbology, stretch=1)
        vbox_spatial.addLayout(row_symb)

        page_layout.addWidget(grp_spatial)
        page_layout.addStretch(1)

        scroll.setWidget(main_page)
        self.tabs.addTab(scroll, "1. Configuração e Espacialização")

        # Aba de Log
        log_page = QWidget()
        vbox_log = QVBoxLayout(log_page)
        vbox_log.setContentsMargins(6, 6, 6, 6)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        vbox_log.addWidget(self.txt_log)
        self.tabs.addTab(log_page, "2. Log de Execução")

        # Rodapé Fixo
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximumWidth(180)
        footer.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Pronto.")
        footer.addWidget(self.lbl_status, stretch=1)

        self.btn_run = QPushButton("Consultar e Gerar Camada no QGIS")
        self.btn_run.setMinimumHeight(32)
        self.btn_run.setStyleSheet("font-weight: bold; padding: 4px 14px;")
        self.btn_run.clicked.connect(self._on_run_clicked)
        footer.addWidget(self.btn_run)

        btn_close = QPushButton("Fechar")
        btn_close.setMinimumHeight(32)
        btn_close.clicked.connect(self.reject)
        footer.addWidget(btn_close)

        root_layout.addLayout(footer)

    def _log(self, msg: str) -> None:
        self.lbl_status.setText(msg[:85] + ("..." if len(msg) > 85 else ""))
        self.txt_log.append(msg)
        QCoreApplication.processEvents()

    def _on_ano_changed(self) -> None:
        """Orienta o usuário sobre a transição CONCLA CNAE 95 vs CNAE 2.0 (2005 para trás)."""
        ano_str = self.cmb_ano.currentText().strip()
        try:
            ano_val = int(ano_str)
        except ValueError:
            ano_val = 2025

        if ano_val <= 2005:
            self.lbl_ano_info.setText(
                f"ℹ️ Ano {ano_val}: Conforme Resolução CONCLA, dados até 2005 utilizam a classificação oficial CNAE 95 e Grau de Instrução. "
                "O GeoTrabalho faz a comutação e compatibilização automaticamente para evitar campos zerados ou 'IGNORADO'."
            )
            self.lbl_ano_info.setVisible(True)
        else:
            self.lbl_ano_info.setVisible(False)

    def _on_coluna_changed(self) -> None:
        """Sincroniza o nível de filtro caso o usuário mude para uma dimensão CNAE."""
        data_spec = self.cmb_coluna.currentData()
        lvl_key = data_spec[1] if isinstance(data_spec, tuple) else "none"

        # Se o usuário escolheu uma dimensão CNAE e o filtro ainda está desabilitado, ajusta o filtro para acompanhar
        if lvl_key in ("secoes", "divisoes", "grupos", "classes") and self.cmb_filtro_nivel.currentData() == "none":
            idx = self.cmb_filtro_nivel.findData(lvl_key)
            if idx >= 0:
                self.cmb_filtro_nivel.setCurrentIndex(idx)

    def _on_filtro_nivel_changed(self) -> None:
        """Atualiza dinamicamente as opções do menu dropdown de atividades com base no nível do filtro CNAE selecionado."""
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
            self.btn_run.setText("Consultar e Gerar Camada no QGIS")
        else:
            self.btn_run.setText("Importar e Espacializar Arquivo")

    def _on_cubo_changed(self) -> None:
        cubo = self.cmb_cubo.currentData()
        if cubo == "caged":
            self.cmb_symbology.setCurrentIndex(4)  # Saldo Bipolar do CAGED
        else:
            self.cmb_symbology.setCurrentIndex(0)  # Automática

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

    def _on_run_clicked(self) -> None:
        source_mode = self.cmb_source_mode.currentData()
        self.btn_run.setEnabled(False)
        self.progress_bar.setValue(5)

        try:
            def prog_cb(pct: int, msg: str) -> None:
                self.progress_bar.setValue(pct)
                self._log(msg)

            if source_mode == "online":
                cubo = self.cmb_cubo.currentData()
                ano = self.cmb_ano.currentData()
                uf = self.cmb_uf.currentData()

                col_spec = self.cmb_coluna.currentData()
                col = col_spec[0] if isinstance(col_spec, tuple) else str(col_spec)
                indic = self.cmb_indicador.currentData()

                # Obtém o filtro do dropdown de atividade
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

                result = self.client.query_dardo(
                    base_cubo=cubo,
                    ano=ano,
                    uf=uf,
                    coluna_cruzamento=col,
                    indicador=indic,
                    filtro_atividade=filtro_texto,
                    filtro_cnae_nivel=filtro_nivel if filtro_nivel != "none" else None,
                    filtro_cnae_codigo=filtro_codigo,
                    prog_cb=prog_cb,
                )
                tag_filtro = f"_{result.filter_applied[:10]}" if result.filter_applied else ""
                layer_suffix = f"{ano}_{uf}{tag_filtro}"
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
                prog_cb(20, f"Lendo arquivo: {os.path.basename(fpath)}...")
                result = self.client.parse_local_file(fpath, filtro_atividade=filtro if filtro else None)
                tag_filtro = f"_{result.filter_applied[:10]}" if result.filter_applied else ""
                layer_suffix = f"Local{tag_filtro}"

            if not result.records:
                QMessageBox.information(self, "Sem registros", "Nenhum município foi encontrado no resultado.")
                return

            if result.filter_applied:
                prog_cb(75, f"Atividade selecionada '{result.filter_applied}': {len(result.matched_columns)} colunas identificadas.")
                self._log(f"Colunas correspondentes: {', '.join(result.matched_columns)}")

            prog_cb(80, "Espacializando feições na malha municipal...")
            layer_name = f"GeoTrabalho_{result.base_name[:18]}_{layer_suffix}"

            if self.cmb_spatial_mode.currentData() == "existing_layer":
                src_layer = self._layer_map[self.cmb_existing_layer.currentData()]
                ibge_field = self.cmb_ibge_field.currentText()
                out_layer = GeoTrabalhoLayerBuilder.build_layer_from_existing_layer(
                    result=result,
                    source_layer=src_layer,
                    ibge_field=ibge_field,
                    layer_name=layer_name,
                    keep_unmatched_polygons=True,
                )
            else:
                out_layer = GeoTrabalhoLayerBuilder.build_layer_from_ibge_api(
                    result=result,
                    layer_name=layer_name,
                    keep_unmatched_polygons=True,
                    progress_callback=prog_cb,
                )

            # Aplicação da Simbologia
            symb = self.cmb_symbology.currentData()
            has_vinc_filtr = "VINC_FILTR" in [name for name, _ in result.field_specs]

            if symb == "auto":
                if has_vinc_filtr:
                    GeoTrabalhoLayerBuilder.apply_activity_filter_symbology(
                        out_layer, "VINC_FILTR", result.filter_applied
                    )
                elif source_mode == "online" and self.cmb_cubo.currentData() == "caged":
                    GeoTrabalhoLayerBuilder.apply_divergent_caged_symbology(out_layer, "TOTAL_GERAL")
                else:
                    GeoTrabalhoLayerBuilder.apply_predominance_symbology(out_layer, "PREDOMINANTE", result=result)
            elif symb == "predominance":
                GeoTrabalhoLayerBuilder.apply_predominance_symbology(out_layer, "PREDOMINANTE", result=result)
            elif symb == "graduated_green":
                target = "VINC_FILTR" if has_vinc_filtr else "TOTAL_GERAL"
                GeoTrabalhoLayerBuilder.apply_graduated_symbology(out_layer, target, "green")
            elif symb == "graduated_blue":
                target = "VINC_FILTR" if has_vinc_filtr else "TOTAL_GERAL"
                GeoTrabalhoLayerBuilder.apply_graduated_symbology(out_layer, target, "blue")
            elif symb == "caged_divergent":
                GeoTrabalhoLayerBuilder.apply_divergent_caged_symbology(out_layer, "TOTAL_GERAL")

            QgsProject.instance().addMapLayer(out_layer)

            # Ajusta zoom da visualização
            try:
                canvas = self.iface.mapCanvas()
                if canvas:
                    canvas.setExtent(out_layer.extent().scaled(1.08))
                    canvas.refresh()
            except (AttributeError, RuntimeError) as exc:
                self._log(f"Aviso ao ajustar visualização: {exc}")

            self.progress_bar.setValue(100)
            summary = (
                f"Sucesso! Camada '{layer_name}' criada com {out_layer.featureCount():,} municípios.\n"
                f"Campos gerados: {len(result.field_specs)} colunas."
            )
            if result.filter_applied:
                summary += f"\nAtividade CNAE: '{result.filter_applied}' (armazenada em VINC_FILTR e PCT_FILTR)."
            self._log(summary)
            QMessageBox.information(self, "Camada Gerada com Sucesso", summary)

        except Exception as e:
            self._log(f"ERRO: {e}")
            QMessageBox.critical(self, "Erro durante o processamento", str(e))
        finally:
            self.btn_run.setEnabled(True)
