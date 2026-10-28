# -*- coding: utf-8 -*-
"""
Classe principal do plugin GeoTrabalho - Espacializador RAIS/CAGED (DardoWeb).
Autor: Luís Eduardo Araújo de Souza
"""

import os
from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from . import _reload_submodules


class GeoTrabalhoPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.action = None
        self.dialog = None
        self.menu_name = "&GeoTrabalho - RAIS/CAGED"

    def initGui(self) -> None:
        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        self.action = QAction(
            QIcon(icon_path),
            "GeoTrabalho - Espacializador RAIS/CAGED (DardoWeb)...",
            self.iface.mainWindow(),
        )
        self.action.setToolTip(
            "Consulta, conecta e espacializa dados da RAIS e CAGED (DardoWeb) por município"
        )
        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu(self.menu_name, self.action)

    def unload(self) -> None:
        if self.action is not None:
            self.iface.removePluginVectorMenu(self.menu_name, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self) -> None:
        _reload_submodules()
        from .gui.main_dialog import GeoTrabalhoDialog
        self.dialog = GeoTrabalhoDialog(self.iface)
        self.dialog.exec()
