# -*- coding: utf-8 -*-
"""
GeoTrabalho - Espacializador RAIS/CAGED (DardoWeb) para QGIS 4 / QGIS 3
Autor: Luís Eduardo Araújo de Souza
"""

import importlib
import logging
import sys

LOGGER = logging.getLogger("GeoTrabalho")


def _reload_submodules() -> None:
    order = [
        "geotrabalho_qgis.core.municipality_mapper",
        "geotrabalho_qgis.core.ibge_api",
        "geotrabalho_qgis.core.dardoweb_client",
        "geotrabalho_qgis.core.layer_builder",
        "geotrabalho_qgis.gui.main_dialog",
        "geotrabalho_qgis.plugin",
    ]
    for mod_name in order:
        mod_obj = sys.modules.get(mod_name)
        if mod_obj is not None:
            try:
                importlib.reload(mod_obj)
            except ImportError as exc:
                LOGGER.debug("Submódulo não recarregado (%s): %s", mod_name, exc)


def classFactory(iface):
    _reload_submodules()
    from .plugin import GeoTrabalhoPlugin
    return GeoTrabalhoPlugin(iface)
