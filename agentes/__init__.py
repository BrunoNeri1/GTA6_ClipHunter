"""
Módulo de agentes para o GTA6_ClipHunter.

Contém:
- VigiaStream: Monitora lives na Kick e mantém o buffer circular .ts.
- RadarHype: Gatilho duplo (Chat WebSocket + Picos de áudio RMS).
- AgenteCurador: Avalia clipes usando Gemini 3.8 Flash (com fallback resiliente).
- AgenteEditor: Renderiza Shorts 9:16 (1080x1920) com webcam e gameplay.
- AgentePublicador: Automação e publicação YouTube Shorts e Telegram.
"""

from .vigia_stream import VigiaStream
from .radar_hype import RadarHype
from .agente_curador import AgenteCurador
from .agente_editor import AgenteEditor
from .agente_publicador import AgentePublicador

__all__ = [
    "VigiaStream",
    "RadarHype",
    "AgenteCurador",
    "AgenteEditor",
    "AgentePublicador",
]
