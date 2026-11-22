"""
Módulo de Configuração de Logs Persistentes - ClipHunter AI
Garante que todas as ações, diagnósticos e erros sejam salvos em arquivos .log no disco:
- logs/cliphunter.log: histórico geral de operações e atividades
- logs/erros.log: registro exclusivo de falhas e exceções com traceback completo
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

PASTA_LOGS = Path("logs")
LOG_GERAL = PASTA_LOGS / "cliphunter.log"
LOG_ERROS = PASTA_LOGS / "erros.log"

_configurado = False


def configurar_logging_geral(nivel_padrao: int = logging.INFO) -> None:
    """Configura formatadores e handlers rotativos em disco para todo o sistema."""
    global _configurado
    if _configurado:
        return

    PASTA_LOGS.mkdir(parents=True, exist_ok=True)

    formato_geral = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Handler Geral (até 5MB cada, até 3 arquivos)
    handler_geral = RotatingFileHandler(
        str(LOG_GERAL),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    handler_geral.setLevel(nivel_padrao)
    handler_geral.setFormatter(formato_geral)

    # 2. Handler Específico de Erros (registra apenas WARNING, ERROR e CRITICAL)
    handler_erros = RotatingFileHandler(
        str(LOG_ERROS),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    handler_erros.setLevel(logging.WARNING)
    handler_erros.setFormatter(formato_geral)

    # 3. Anexa aos loggers da aplicação
    nomes_loggers = [
        "ClipHunter",
        "GTA6_ClipHunter",
        "ClipHunter.VigiaStream",
        "ClipHunter.RadarHype",
        "ClipHunter.AgenteCurador",
        "ClipHunter.AgenteEditor",
        "ClipHunter.AgentePublicador"
    ]

    for nome in nomes_loggers:
        log = logging.getLogger(nome)
        log.setLevel(nivel_padrao)
        log.addHandler(handler_geral)
        log.addHandler(handler_erros)

    _configurado = True
    logging.getLogger("ClipHunter").info("=== Sistema de Logs Persistentes Inicializado (logs/cliphunter.log | logs/erros.log) ===")


def registrar_erro_detalhado(origem: str, mensagem: str, excecao: Exception = None, exc: Exception = None) -> None:
    """Registra uma falha com detalhes legíveis e traceback técnico nos arquivos de log."""
    erro = excecao or exc
    log = logging.getLogger("ClipHunter")
    if erro:
        log.error(f"[{origem}] {mensagem} | Detalhes: {erro}", exc_info=erro)
    else:
        log.error(f"[{origem}] {mensagem}")


def abrir_pasta_logs() -> bool:
    """Abre o diretório logs/ no Explorador de Arquivos do Windows."""
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(PASTA_LOGS.resolve()))
            return True
    except Exception as e:
        logging.getLogger("ClipHunter").error(f"Erro ao abrir pasta de logs: {e}")
    return False
