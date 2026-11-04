# -*- coding: utf-8 -*-
"""
Execução de tarefas pesadas (consultas ao DardoWeb e downloads do IBGE) em thread de segundo plano,
evitando que a interface do QGIS congele ("Não respondendo") e seja encerrada pelo Windows.

Regras de uso:
  - A função executada em segundo plano NÃO pode tocar em widgets nem em camadas do projeto QGIS.
  - O progresso é reportado por sinal (thread-safe); o resultado é entregue na thread principal.
  - Referências aos jobs ativos são mantidas em nível de módulo para que a QThread nunca seja
    destruída enquanto ainda está em execução (o que causaria crash do QGIS).
"""

import logging
import traceback
from typing import Any, Callable, Set

from qgis.PyQt.QtCore import QThread, pyqtSignal

LOGGER = logging.getLogger("GeoTrabalho")

_ACTIVE_JOBS: Set["BackgroundJob"] = set()


class JobCancelled(Exception):
    """Sinaliza que o usuário solicitou o cancelamento da tarefa."""


class BackgroundJob(QThread):
    """Executa `fn(report)` em segundo plano. `report(pct, msg)` emite progresso e verifica cancelamento."""

    progress = pyqtSignal(int, str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, fn: Callable[[Callable[[int, str], None]], Any]):
        super().__init__(None)
        self._fn = fn
        self._cancel_requested = False
        _ACTIVE_JOBS.add(self)
        self.finished.connect(self._release)

    def request_cancel(self) -> None:
        self._cancel_requested = True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def report(self, pct: int, msg: str) -> None:
        if self._cancel_requested:
            raise JobCancelled()
        self.progress.emit(int(pct), str(msg))

    def run(self) -> None:  # noqa: D401 - executado na thread de trabalho
        try:
            result = self._fn(self.report)
            if self._cancel_requested:
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except JobCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - qualquer falha deve voltar à interface, nunca derrubar o QGIS
            LOGGER.error("Falha na tarefa em segundo plano: %s\n%s", exc, traceback.format_exc())
            if self._cancel_requested:
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc) or exc.__class__.__name__)

    def _release(self) -> None:
        # Garante que a thread terminou por completo antes de liberar a última referência Python
        self.wait(10000)
        _ACTIVE_JOBS.discard(self)
