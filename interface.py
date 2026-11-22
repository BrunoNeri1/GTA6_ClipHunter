"""
Interface Gráfica Clean para Windows - ClipHunter AI v3.0
Desenvolvida com CustomTkinter (Tema Escuro Clean por Abas - CTkTabview).
Organização limpa e moderna:
- Aba 🎮 Monitor Ao Vivo: Foco na captura, canal ativo, radar de hype e logs limpos.
- Aba 🚀 Publicação & Fila: Automação YouTube Shorts (Canal Neri Clipes), cota diária e agendamento em lote.
- Aba 📐 Enquadramento 9:16: Configuração de webcam, autocalibração com IA e legendas.
- Aba 📁 Cortes Salvos: Galeria de vídeos prontos e atalho para o Explorer.
"""

import os
import sys
import time
import json
import queue
import shutil
import asyncio
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

import customtkinter as ctk

# Configuração global de aparência do CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Importa o orquestrador e agentes do projeto
from main import OrquestradorClipHunter, verificar_e_configurar_ffmpeg
from agentes.agente_publicador import AgentePublicador, LIMITE_DIARIO_UPLOADS
from config.logger_config import (
    configurar_logging_geral,
    abrir_pasta_logs,
    registrar_erro_detalhado
)


MAPA_WEBCAM = {
    "🎯 Auto-Calibrar via IA (Detecta enquadramento da live)": "auto",
    "Desativado (Sem Webcam - Apenas Gameplay 9:16)": "desativado",
    "Direita Central (Padrão Alanzoka / Twitch)": "centro_direito",
    "Esquerda Central": "centro_esquerdo",
    "Canto Inferior Esquerdo (Padrão Kick / GTA)": "inferior_esquerdo",
    "Canto Inferior Direito": "inferior_direito",
    "Canto Superior Esquerdo": "superior_esquerdo",
    "Canto Superior Direito": "superior_direito"
}

MAPA_WEBCAM_REVERSO = {v: k for k, v in MAPA_WEBCAM.items()}

PREFERENCIAS_PADRAO = {
    "canal_selecionado": "Lista Automática (Todos por Prioridade)",
    "posicao_webcam": "🎯 Auto-Calibrar via IA (Detecta enquadramento da live)",
    "legendas_ativas": True,
    "modo_teste": False,
    "som_ativo": True,
    "upload_youtube_ativo": False,
    "privacidade_youtube": "Não Listado (Recomendado)",
    "nota_minima_upload": "Nota 8+ (Equilibrado)",
    "telegram_ativo": False,
    "nota_minima_salvar": "Salvar Todos (Nota 7+)"
}


def filtrar_e_formatar_mensagem(msg: str, level: str) -> Optional[str]:
    """Filtra o log técnico interno e retorna apenas mensagens amigáveis com ícones."""
    msg_strip = msg.strip()

    if "Streamer AO VIVO encontrado" in msg:
        nome = msg.split("encontrado:")[-1].split("!")[0].strip()
        return f"🎯 Streamer AO VIVO encontrado: {nome}!"
    if "Conectando ao canal de" in msg:
        nome = msg.split("ao canal de")[-1].split("(")[0].strip()
        return f"🔗 Conectando ao stream de {nome}..."
    if "Iniciando gravação contínua em buffer circular" in msg:
        return "📹 Gravação iniciada no buffer circular (SSD protegido, 30s)."
    if "Conectado com sucesso ao chat da Kick" in msg:
        nome = msg.split("(")[-1].split(")")[0].strip()
        return f"💬 Chat da Kick conectado ({nome})!"
    if "Conectado com sucesso ao chat da Twitch" in msg:
        nome = msg.split("(")[-1].split(")")[0].strip()
        return f"💬 Chat da Twitch conectado ({nome})!"
    if "Conectado com sucesso ao chat do YouTube" in msg:
        nome = msg.split("(")[-1].split(")")[0].strip()
        return f"💬 Chat do YouTube conectado ({nome})!"
    if "Auto-Calibração IA" in msg:
        return f"🎯 {msg.split('🎯')[-1].strip()}"
    if "MODO DE TESTE ATIVO" in msg:
        return "🧪 Modo de Teste Rápido ativo (corte a cada 45s)."
    if "ASSUNTO GTA 6 NO CHAT!" in msg:
        return f"🎯 ASSUNTO GTA 6 NO CHAT: {msg.split(':')[-1].strip()}"
    if "PICO DE ÁUDIO DETECTADO!" in msg:
        return "🔥 Pico de áudio/reação intensa detectada na live!"
    if "REAÇÃO NO CHAT DETECTADA!" in msg:
        return f"💬 Reação intensa de espectadores: {msg.split(':')[-1].strip()}"
    if "EXPLOSÃO NO CHAT!" in msg:
        return f"⚡ {msg.split('⚡')[-1].strip()}"
    if "HYPE CONFIRMADO" in msg:
        return "🎉 Momento empolgante confirmado! Capturando reação..."
    if "INICIANDO PIPELINE DE CLIPAGEM" in msg:
        return "✂️ Cortando trecho recente de 45 segundos para análise da IA..."
    if "Enviando trecho para análise com o modelo" in msg:
        return "🤖 Google Gemini analisando áudio, contexto e potencial viral..."
    if "CORTE APROVADO!" in msg:
        detalhes = msg.split("CORTE APROVADO!")[-1].strip()
        return f"✅ CORTE APROVADO! {detalhes}"
    if "Corte descartado pelo filtro de armazenamento" in msg:
        return f"🗑️ {msg.strip()}"
    if "Corte reprovado pelo Curador IA" in msg or "Corte descartado" in msg:
        return "❌ Momento descartado pelo Gemini (conversa comum sem ação relevante)."
    if "Renderizando Short 9:16 com webcam e legendas" in msg or "Renderizando Short 9:16 via FFmpeg" in msg:
        return "⚙️ Renderizando Short vertical 9:16 com webcam e legendas dinâmicas..."
    if "SHORT 100% PRONTO PARA POSTAGEM" in msg:
        return f"🚀 VÍDEO SALVO COM SUCESSO! -> {Path(msg.split(':')[-1].strip()).name}"
    if "Iniciando upload para o YouTube Shorts" in msg or "Iniciando upload para YouTube Shorts" in msg:
        return "🚀 Enviando vídeo para o YouTube Shorts (Canal Neri Clipes)..."
    if "Upload concluído com sucesso" in msg:
        return f"✅ Publicado no YouTube Shorts com sucesso! ({msg.split('sucesso:')[-1].strip()})"
    if "Iniciando envio para o Telegram" in msg:
        return "📱 Enviando cópia limpa para o Telegram (TikTok/Reels/Kwai)..."
    if "Vídeo enviado para o Telegram com sucesso" in msg:
        return "✅ Vídeo entregue no Telegram para postagem mobile!"
    if "Limite diário de cota do YouTube atingido" in msg:
        return "⚠️ Cota diária do YouTube atingida (6/6). Envios pausados para segurança."
    if "Stream offline por mais de 10 minutos" in msg:
        return "⏰ Streamer offline há mais de 10 minutos consecutivos. Caçador encerrado automaticamente."
    if "Aguardando 30 segundos antes de nova varredura" in msg:
        return "⏳ Aguardando 30 segundos para nova busca de lives..."
    if "Stream de vídeo foi encerrado ou caiu" in msg:
        return "⚠️ Live encerrada pelo streamer. Buscando outro canal..."
    if "Orquestrador encerrado com sucesso" in msg or "Sinal de interrupção recebido" in msg:
        return "⏹️ Bot parado com sucesso."

    if level in ("ERROR", "CRITICAL"):
        resumo = msg.split("\n")[0].strip()
        if not resumo:
            resumo = "Erro interno no processamento."
        return f"❌ {resumo}"

    return None


class CustomQueueHandler(logging.Handler):
    """Intercepta logs do projeto e envia mensagens limpas para a fila da GUI."""
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            msg = record.getMessage()
            aviso = filtrar_e_formatar_mensagem(msg, record.levelname)
            if aviso:
                hora = time.strftime("%H:%M:%S")
                self.log_queue.put((record.levelname, f"[{hora}] {aviso}"))
        except Exception:
            pass


class BotRunner:
    """Gerencia a execução assíncrona do OrquestradorClipHunter em uma thread isolada."""
    def __init__(
        self,
        alvo_direto: Optional[str],
        log_queue: queue.Queue,
        posicao_webcam: str = "inferior_esquerdo",
        habilitar_legendas: bool = True,
        alerta_sonoro: bool = True,
        upload_automatico_youtube: bool = False,
        privacidade_youtube: str = "unlisted",
        nota_minima_upload: int = 8,
        enviar_telegram: bool = False,
        nota_minima_salvar: int = 7
    ):
        self.alvo_direto = alvo_direto
        self.log_queue = log_queue
        self.posicao_webcam = posicao_webcam
        self.habilitar_legendas = habilitar_legendas
        self.alerta_sonoro = alerta_sonoro
        self.upload_automatico_youtube = upload_automatico_youtube
        self.privacidade_youtube = privacidade_youtube
        self.nota_minima_upload = nota_minima_upload
        self.enviar_telegram = enviar_telegram
        self.nota_minima_salvar = nota_minima_salvar

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.orquestrador: Optional[OrquestradorClipHunter] = None
        self.thread: Optional[threading.Thread] = None
        self.rodando = False

    def iniciar(self) -> None:
        self.rodando = True
        self.thread = threading.Thread(target=self._executar_loop, daemon=True)
        self.thread.start()

    def _executar_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        verificar_e_configurar_ffmpeg()

        self.orquestrador = OrquestradorClipHunter(
            alvo_direto=self.alvo_direto,
            posicao_webcam=self.posicao_webcam,
            habilitar_legendas=self.habilitar_legendas,
            alerta_sonoro=self.alerta_sonoro,
            upload_automatico_youtube=self.upload_automatico_youtube,
            privacidade_youtube=self.privacidade_youtube,
            nota_minima_upload=self.nota_minima_upload,
            enviar_telegram=self.enviar_telegram,
            nota_minima_salvar=self.nota_minima_salvar
        )

        try:
            self.loop.run_until_complete(self.orquestrador.iniciar())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            hora = time.strftime("%H:%M:%S")
            self.log_queue.put(("ERROR", f"[{hora}] ❌ Erro na execução do bot: {e}"))
        finally:
            self.rodando = False

    def parar(self) -> None:
        if not self.rodando:
            return
        self.rodando = False

        if self.orquestrador:
            self.orquestrador.rodando = False

        if self.orquestrador and self.loop and self.loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self.orquestrador.parar_geral(), self.loop)
                fut.result(timeout=4.0)
            except Exception:
                pass

        if self.orquestrador and self.orquestrador.vigia:
            if self.orquestrador.vigia.processo_ffmpeg:
                try:
                    self.orquestrador.vigia.processo_ffmpeg.terminate()
                except Exception:
                    pass

        if self.orquestrador and self.orquestrador.radar:
            if self.orquestrador.radar.processo_audio_ffmpeg:
                try:
                    self.orquestrador.radar.processo_audio_ffmpeg.terminate()
                except Exception:
                    pass

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


class JanelaClipHunter(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Configura sistema de logs persistentes (logs/cliphunter.log e logs/erros.log)
        try:
            configurar_logging_geral()
        except Exception:
            pass

        # Configurações básicas da Janela
        self.title("ClipHunter AI - Caçador Inteligente de Cortes de Lives")
        self.geometry("900x680")
        self.minsize(840, 600)

        # Agente Publicador para YouTube e Telegram
        self.publicador = AgentePublicador()

        # Fila de comunicação thread-safe para logs e status
        self.log_queue: queue.Queue = queue.Queue()
        self.bot_runner: Optional[BotRunner] = None
        self.total_cortes_salvos = 0

        # Controle da Fila em Lote
        self.cancelar_fila_evento = threading.Event()
        self.fila_lote_thread: Optional[threading.Thread] = None
        self.itens_fila_selecionados: List[Tuple[ctk.BooleanVar, Path, datetime, int, str]] = []

        # Carrega preferências salvas do disco
        self.prefs = self._carregar_preferencias()

        # VARIÁVEIS DE ESTADO E PREFERÊNCIAS (SEMPRE INICIALIZADAS NO INÍCIO)
        self.var_legendas = ctk.BooleanVar(value=self.prefs.get("legendas_ativas", True))
        self.var_modo_teste = ctk.BooleanVar(value=self.prefs.get("modo_teste", False))
        self.var_som = ctk.BooleanVar(value=self.prefs.get("som_ativo", True))
        self.var_upload_youtube = ctk.BooleanVar(value=self.prefs.get("upload_youtube_ativo", False))
        self.var_telegram = ctk.BooleanVar(value=self.prefs.get("telegram_ativo", False))

        # Conecta interceptador de logs
        self.handler_logs = CustomQueueHandler(self.log_queue)
        for log_nome in ["ClipHunter", "GTA6_ClipHunter"]:
            logging.getLogger(log_nome).addHandler(self.handler_logs)
            logging.getLogger(log_nome).setLevel(logging.INFO)

        # Constrói a interface com layout limpo por abas
        self._construir_interface()

        # Inicia leitura da fila de mensagens (100ms)
        self.after(100, self._processar_fila_logs)

        # Atualiza badge de cota
        self.after(400, self._atualizar_badge_cota)

        # Protocolo de fechamento
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar_janela)

    def _carregar_preferencias(self) -> Dict[str, Any]:
        caminho = Path("config/preferencias.json")
        prefs = dict(PREFERENCIAS_PADRAO)
        if caminho.exists():
            try:
                with open(caminho, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    prefs.update(dados)
            except Exception:
                pass
        return prefs

    def _salvar_preferencias(self) -> None:
        caminho = Path("config/preferencias.json")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            dados = {
                "canal_selecionado": self.combo_canal.get() if hasattr(self, "combo_canal") else PREFERENCIAS_PADRAO["canal_selecionado"],
                "posicao_webcam": self.combo_webcam.get() if hasattr(self, "combo_webcam") else PREFERENCIAS_PADRAO["posicao_webcam"],
                "legendas_ativas": self.var_legendas.get() if hasattr(self, "var_legendas") else True,
                "modo_teste": self.var_modo_teste.get() if hasattr(self, "var_modo_teste") else False,
                "som_ativo": self.var_som.get() if hasattr(self, "var_som") else True,
                "upload_youtube_ativo": self.var_upload_youtube.get() if hasattr(self, "var_upload_youtube") else False,
                "privacidade_youtube": self.combo_privacidade.get() if hasattr(self, "combo_privacidade") else "Não Listado (Recomendado)",
                "nota_minima_upload": self.combo_nota_minima.get() if hasattr(self, "combo_nota_minima") else "Nota 8+ (Equilibrado)",
                "telegram_ativo": self.var_telegram.get() if hasattr(self, "var_telegram") else False,
                "nota_minima_salvar": self.combo_filtro_salvar.get() if hasattr(self, "combo_filtro_salvar") else "Salvar Todos (Nota 7+)"
            }
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.getLogger("ClipHunter").error(f"Erro ao salvar preferências: {e}")

    def _ao_alterar_preferencias(self) -> None:
        self._salvar_preferencias()

    def _carregar_opcoes_streamers(self) -> List[str]:
        opcoes = ["Lista Automática (Todos por Prioridade)"]
        caminho_config = Path("config/streamers.json")
        if caminho_config.exists():
            try:
                with open(caminho_config, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    for s in dados.get("streamers", []):
                        nome = s.get("nome", "Streamer")
                        slug = s.get("slug", "")
                        opcoes.append(f"{nome} ({slug})")
            except Exception:
                pass
        return opcoes

    def _construir_interface(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ------------------- 1. CABEÇALHO CLEAN MINIMALISTA -------------------
        frame_cabecalho = ctk.CTkFrame(self, fg_color="#18181b", corner_radius=10)
        frame_cabecalho.grid(row=0, column=0, padx=15, pady=(12, 6), sticky="ew")
        frame_cabecalho.grid_columnconfigure(0, weight=1)

        # Lado Esquerdo: Identidade do App
        frame_identidade = ctk.CTkFrame(frame_cabecalho, fg_color="transparent")
        frame_identidade.grid(row=0, column=0, padx=15, pady=8, sticky="w")

        lbl_logo = ctk.CTkLabel(
            frame_identidade,
            text="🎯 ClipHunter AI",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        lbl_logo.grid(row=0, column=0, sticky="w")

        lbl_sub = ctk.CTkLabel(
            frame_identidade,
            text="Caçador Inteligente de Cortes de Lives • Canal Neri Clipes",
            font=ctk.CTkFont(size=12),
            text_color="#A1A1AA"
        )
        lbl_sub.grid(row=1, column=0, sticky="w")

        # Lado Direito: Pílula de Status & Botão Iniciar Principal
        frame_acoes_topo = ctk.CTkFrame(frame_cabecalho, fg_color="transparent")
        frame_acoes_topo.grid(row=0, column=1, padx=15, pady=8, sticky="e")

        self.badge_status = ctk.CTkLabel(
            frame_acoes_topo,
            text="● PARADO",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#3F3F46",
            text_color="#FAFAFA",
            corner_radius=6,
            width=110,
            height=30
        )
        self.badge_status.grid(row=0, column=0, padx=(0, 10))

        self.btn_iniciar = ctk.CTkButton(
            frame_acoes_topo,
            text="▶  Iniciar Caçador",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#22C55E",
            hover_color="#16A34A",
            height=34,
            command=self._ao_clicar_iniciar
        )
        self.btn_iniciar.grid(row=0, column=1, padx=(0, 5))

        self.btn_parar = ctk.CTkButton(
            frame_acoes_topo,
            text="⏹  Parar",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#EF4444",
            hover_color="#DC2626",
            height=34,
            width=80,
            state="disabled",
            command=self._ao_clicar_parar
        )
        self.btn_parar.grid(row=0, column=2)

        # ------------------- 2. NAVEGAÇÃO PRINCIPAL POR ABAS (CTKTABVIEW) -------------------
        self.tabview = ctk.CTkTabview(
            self,
            fg_color="#18181b",
            segmented_button_selected_color="#7C3AED",
            segmented_button_selected_hover_color="#6D28D9",
            segmented_button_unselected_color="#27272a",
            segmented_button_unselected_hover_color="#3F3F46",
            corner_radius=10
        )
        self.tabview.grid(row=1, column=0, padx=15, pady=4, sticky="nsew")

        # Criação das 4 abas organizadas
        self.tab_aovivo = self.tabview.add("🎮 Monitor Ao Vivo")
        self.tab_publicacao = self.tabview.add("🚀 Publicação & Fila")
        self.tab_enquadramento = self.tabview.add("📐 Enquadramento 9:16")
        self.tab_cortes = self.tabview.add("📁 Cortes Salvos")

        # Constrói o conteúdo de cada aba
        self._construir_aba_aovivo()
        self._construir_aba_publicacao()
        self._construir_aba_enquadramento()
        self._construir_aba_cortes()

        # ------------------- 3. RODAPÉ MINIMALISTA -------------------
        frame_rodape = ctk.CTkFrame(self, fg_color="transparent")
        frame_rodape.grid(row=2, column=0, padx=20, pady=(4, 8), sticky="ew")
        frame_rodape.grid_columnconfigure(0, weight=1)

        lbl_hardware = ctk.CTkLabel(
            frame_rodape,
            text="⚡ RAM < 1.5GB | FFmpeg ultrafast -threads 2 | Auto-Stop (10m offline)",
            font=ctk.CTkFont(size=11),
            text_color="#71717A"
        )
        lbl_hardware.grid(row=0, column=0, sticky="w")

        btn_logs_rodape = ctk.CTkButton(
            frame_rodape,
            text="📁 Abrir Logs",
            font=ctk.CTkFont(size=11),
            fg_color="#27272a",
            hover_color="#3F3F46",
            width=85,
            height=24,
            command=self._ao_clicar_abrir_logs
        )
        btn_logs_rodape.grid(row=0, column=1, padx=(10, 15), sticky="w")

        self.lbl_rodape_cota = ctk.CTkLabel(
            frame_rodape,
            text="📊 YouTube: 0/6 hoje • Canal Neri Clipes",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#10B981"
        )
        self.lbl_rodape_cota.grid(row=0, column=2, sticky="e")

    def _ao_clicar_abrir_logs(self) -> None:
        """Abre o diretório logs/ no Windows Explorer para fácil diagnóstico de erros."""
        try:
            abrir_pasta_logs()
        except Exception as e:
            self._adicionar_aviso(f"❌ Não foi possível abrir pasta de logs: {e}")

    # =============================================================
    # ABA 1: MONITOR AO VIVO
    # =============================================================
    def _construir_aba_aovivo(self) -> None:
        tab = self.tab_aovivo
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        # Linha 1: Seletor de Streamer e Filtro de Armazenamento no Disco
        frame_canal = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_canal.grid(row=0, column=0, padx=10, pady=(6, 6), sticky="ew")
        frame_canal.grid_columnconfigure(1, weight=1)
        frame_canal.grid_columnconfigure(3, weight=1)

        lbl_c = ctk.CTkLabel(frame_canal, text="Canal:", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_c.grid(row=0, column=0, padx=(12, 6), pady=8, sticky="w")

        opcoes_streamers = self._carregar_opcoes_streamers()
        self.combo_canal = ctk.CTkComboBox(
            frame_canal,
            values=opcoes_streamers,
            font=ctk.CTkFont(size=12),
            dropdown_font=ctk.CTkFont(size=11),
            height=32,
            command=lambda _: self._ao_alterar_preferencias()
        )
        self.combo_canal.grid(row=0, column=1, padx=6, pady=8, sticky="ew")
        canal_salvo = self.prefs.get("canal_selecionado", opcoes_streamers[0])
        self.combo_canal.set(canal_salvo if canal_salvo in opcoes_streamers else opcoes_streamers[0])

        lbl_filtro = ctk.CTkLabel(frame_canal, text="💾 Salvar no Disco:", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_filtro.grid(row=0, column=2, padx=(12, 6), pady=8, sticky="w")

        opcoes_filtro_salvar = [
            "Salvar Todos (Nota 7+)",
            "Apenas Nota 8+ (Equilibrado)",
            "Apenas Nota 9+ (Momentos Épicos)",
            "Apenas Nota 10 (Somente Lendários)"
        ]
        self.combo_filtro_salvar = ctk.CTkComboBox(
            frame_canal,
            values=opcoes_filtro_salvar,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            height=32,
            command=lambda _: self._ao_alterar_preferencias()
        )
        self.combo_filtro_salvar.grid(row=0, column=3, padx=(4, 12), pady=8, sticky="ew")
        salvar_salvo = self.prefs.get("nota_minima_salvar", opcoes_filtro_salvar[0])
        self.combo_filtro_salvar.set(salvar_salvo if salvar_salvo in opcoes_filtro_salvar else opcoes_filtro_salvar[0])

        # Linha 2: Termômetro Discreto de Hype
        frame_hype = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_hype.grid(row=1, column=0, padx=10, pady=4, sticky="ew")
        frame_hype.grid_columnconfigure(0, weight=1)

        frame_hype_topo = ctk.CTkFrame(frame_hype, fg_color="transparent")
        frame_hype_topo.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")
        frame_hype_topo.grid_columnconfigure(0, weight=1)

        lbl_h_tit = ctk.CTkLabel(
            frame_hype_topo,
            text="🔥  Radar de Hype em Tempo Real (Picos de Áudio RMS + Chat)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F4F4F5"
        )
        lbl_h_tit.grid(row=0, column=0, sticky="w")

        self.lbl_hype_status = ctk.CTkLabel(
            frame_hype_topo,
            text="Sensibilidade: 85% para disparar corte",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA"
        )
        self.lbl_hype_status.grid(row=0, column=1, sticky="e")

        self.bar_hype = ctk.CTkProgressBar(
            frame_hype,
            height=8,
            progress_color="#EC4899",
            fg_color="#09090b"
        )
        self.bar_hype.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")
        self.bar_hype.set(0.0)

        # Linha 3: Caixa de Avisos em Tempo Real (Logs Limpos)
        frame_logs = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_logs.grid(row=2, column=0, padx=10, pady=(4, 6), sticky="nsew")
        frame_logs.grid_columnconfigure(0, weight=1)
        frame_logs.grid_rowconfigure(1, weight=1)

        frame_topo_logs = ctk.CTkFrame(frame_logs, fg_color="transparent")
        frame_topo_logs.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")
        frame_topo_logs.grid_columnconfigure(0, weight=1)

        lbl_l = ctk.CTkLabel(frame_topo_logs, text="📋  Atividades e Notificações", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_l.grid(row=0, column=0, sticky="w")

        btn_logs_aba1 = ctk.CTkButton(
            frame_topo_logs,
            text="📂 Abrir Pasta de Logs",
            font=ctk.CTkFont(size=11),
            fg_color="#3F3F46",
            hover_color="#52525B",
            width=135,
            height=22,
            command=self._ao_clicar_abrir_logs
        )
        btn_logs_aba1.grid(row=0, column=1, padx=(0, 6), sticky="e")

        btn_limpar = ctk.CTkButton(
            frame_topo_logs,
            text="Limpar",
            font=ctk.CTkFont(size=11),
            fg_color="#3F3F46",
            hover_color="#52525B",
            width=60,
            height=22,
            command=self._ao_clicar_limpar
        )
        btn_limpar.grid(row=0, column=2, sticky="e")

        self.txt_logs = ctk.CTkTextbox(
            frame_logs,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#09090b",
            text_color="#F4F4F5",
            corner_radius=6,
            wrap="word"
        )
        self.txt_logs.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="nsew")
        self.txt_logs.configure(state="disabled")

        self._adicionar_aviso("👋 Bem-vindo ao ClipHunter AI! Escolha um canal e clique em 'Iniciar Caçador'.")

    # =============================================================
    # ABA 2: PUBLICAÇÃO & FILA (CANAL NERI CLIPES)
    # =============================================================
    def _construir_aba_publicacao(self) -> None:
        tab = self.tab_publicacao
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        # 1. Cartão de Conta e Cota do YouTube
        frame_conta = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_conta.grid(row=0, column=0, padx=10, pady=(6, 6), sticky="ew")
        frame_conta.grid_columnconfigure(0, weight=1)

        frame_conta_linha = ctk.CTkFrame(frame_conta, fg_color="transparent")
        frame_conta_linha.grid(row=0, column=0, padx=12, pady=(10, 4), sticky="ew")
        frame_conta_linha.grid_columnconfigure(1, weight=1)

        # Indicador de Conta
        ja_autenticado = self.publicador.esta_autenticado()
        self.btn_conectar_youtube = ctk.CTkButton(
            frame_conta_linha,
            text="🔑 YouTube: Conectado ✅" if ja_autenticado else "🔑 Conectar Conta YouTube",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#10B981" if ja_autenticado else "#0284C7",
            hover_color="#059669" if ja_autenticado else "#0369A1",
            height=28,
            command=self._ao_clicar_conectar_youtube
        )
        self.btn_conectar_youtube.grid(row=0, column=0, sticky="w")

        lbl_info_canal = ctk.CTkLabel(
            frame_conta_linha,
            text="Canal Neri Clipes • YouTube Data API v3 (OAuth2)",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA"
        )
        lbl_info_canal.grid(row=0, column=1, padx=10, sticky="w")

        # Badge de Cota
        self.lbl_cota_badge = ctk.CTkLabel(
            frame_conta_linha,
            text="📊 Cota: 0/6 hoje",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#10B981",
            text_color="#FAFAFA",
            corner_radius=6,
            width=115,
            height=26
        )
        self.lbl_cota_badge.grid(row=0, column=2, sticky="e")

        # Feedback de Status da Conexão YouTube na Própria Aba
        self.lbl_status_auth = ctk.CTkLabel(
            frame_conta,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#FACC15"
        )
        self.lbl_status_auth.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        # 2. Configurações de Postagem Direta ao Vivo
        frame_opcoes_post = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_opcoes_post.grid(row=1, column=0, padx=10, pady=4, sticky="ew")
        frame_opcoes_post.grid_columnconfigure(0, weight=1)
        frame_opcoes_post.grid_columnconfigure(1, weight=1)
        frame_opcoes_post.grid_columnconfigure(2, weight=1)

        # Auto-Upload Switch
        self.chk_upload_youtube = ctk.CTkCheckBox(
            frame_opcoes_post,
            text="🔴 Auto-Upload YouTube Shorts",
            variable=self.var_upload_youtube,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#EF4444",
            checkmark_color="#0F172A",
            fg_color="#EF4444",
            hover_color="#DC2626",
            command=self._ao_alterar_preferencias
        )
        self.chk_upload_youtube.grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        # Privacidade
        opcoes_priv = ["Não Listado (Recomendado)", "Público", "Privado"]
        self.combo_privacidade = ctk.CTkComboBox(
            frame_opcoes_post,
            values=opcoes_priv,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            height=28,
            command=lambda _: self._ao_alterar_preferencias()
        )
        self.combo_privacidade.grid(row=0, column=1, padx=6, pady=(10, 4), sticky="ew")
        priv_salva = self.prefs.get("privacidade_youtube", opcoes_priv[0])
        self.combo_privacidade.set(priv_salva if priv_salva in opcoes_priv else opcoes_priv[0])

        # Nota Mínima
        opcoes_nota = ["Nota 8+ (Equilibrado)", "Nota 7+ (Mais Vídeos)", "Nota 9+ (Apenas Épicos)"]
        self.combo_nota_minima = ctk.CTkComboBox(
            frame_opcoes_post,
            values=opcoes_nota,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            height=28,
            command=lambda _: self._ao_alterar_preferencias()
        )
        self.combo_nota_minima.grid(row=0, column=2, padx=(6, 12), pady=(10, 4), sticky="ew")
        nota_salva = self.prefs.get("nota_minima_upload", opcoes_nota[0])
        self.combo_nota_minima.set(nota_salva if nota_salva in opcoes_nota else opcoes_nota[0])

        # Checkbox Telegram (Ponte Mobile)
        self.chk_telegram = ctk.CTkCheckBox(
            frame_opcoes_post,
            text="📱 Enviar Cortes no Telegram (Reels/TikTok/Kwai)",
            variable=self.var_telegram,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38BDF8",
            checkmark_color="#0F172A",
            fg_color="#0284C7",
            hover_color="#0369A1",
            command=self._ao_alterar_preferencias
        )
        self.chk_telegram.grid(row=1, column=0, columnspan=3, padx=12, pady=(4, 10), sticky="w")

        # 3. Fila de Envios em Lote ("Vídeos de Hoje")
        frame_lote = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_lote.grid(row=2, column=0, padx=10, pady=(4, 6), sticky="nsew")
        frame_lote.grid_columnconfigure(0, weight=1)
        frame_lote.grid_rowconfigure(1, weight=1)

        # Barra Superior da Fila
        frame_lote_topo = ctk.CTkFrame(frame_lote, fg_color="transparent")
        frame_lote_topo.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")
        frame_lote_topo.grid_columnconfigure(1, weight=1)

        lbl_lote_tit = ctk.CTkLabel(
            frame_lote_topo,
            text="📋 Agendamento em Lote (Cortes Prontos)",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_lote_tit.grid(row=0, column=0, sticky="w")

        # Botões de Ação da Fila
        frame_acoes_fila = ctk.CTkFrame(frame_lote_topo, fg_color="transparent")
        frame_acoes_fila.grid(row=0, column=2, sticky="e")

        btn_marcar = ctk.CTkButton(
            frame_acoes_fila,
            text="Marcar Todos de Hoje",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#0284C7",
            hover_color="#0369A1",
            height=24,
            command=self._marcar_todos_fila_hoje
        )
        btn_marcar.grid(row=0, column=0, padx=(0, 4))

        opcoes_interv = ["Imediato", "30 minutos", "1 hora", "2 horas"]
        self.combo_intervalo_fila = ctk.CTkComboBox(
            frame_acoes_fila,
            values=opcoes_interv,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            height=24,
            width=110
        )
        self.combo_intervalo_fila.grid(row=0, column=1, padx=(0, 4))
        self.combo_intervalo_fila.set(opcoes_interv[1])

        self.btn_disparar_fila = ctk.CTkButton(
            frame_acoes_fila,
            text="🚀 Disparar Fila (YouTube)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#7C3AED",
            hover_color="#6D28D9",
            height=24,
            command=self._ao_clicar_disparar_fila
        )
        self.btn_disparar_fila.grid(row=0, column=2, padx=(0, 4))

        self.btn_disparar_tg = ctk.CTkButton(
            frame_acoes_fila,
            text="📱 Enviar Fila p/ Telegram",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0284C7",
            hover_color="#0369A1",
            height=24,
            command=self._ao_clicar_enviar_telegram_fila
        )
        self.btn_disparar_tg.grid(row=0, column=3)

        # Scrollable Frame com Lista dos Vídeos Pendentes
        self.scroll_fila = ctk.CTkScrollableFrame(
            frame_lote,
            fg_color="#09090b",
            corner_radius=6
        )
        self.scroll_fila.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        self.scroll_fila.grid_columnconfigure(0, weight=1)

        self._carregar_lista_fila()

        # Rodapé da Fila com Status em Tempo Real
        frame_status_fila = ctk.CTkFrame(frame_lote, fg_color="transparent")
        frame_status_fila.grid(row=2, column=0, padx=12, pady=(4, 8), sticky="ew")
        frame_status_fila.grid_columnconfigure(0, weight=1)

        self.lbl_status_fila = ctk.CTkLabel(
            frame_status_fila,
            text="Fila inativa (Nenhum lote agendado)",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA"
        )
        self.lbl_status_fila.grid(row=0, column=0, sticky="w")

        self.btn_cancelar_fila = ctk.CTkButton(
            frame_status_fila,
            text="⏹ Cancelar Fila",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#EF4444",
            hover_color="#DC2626",
            height=24,
            state="disabled",
            command=self._ao_clicar_cancelar_fila
        )
        self.btn_cancelar_fila.grid(row=0, column=1, sticky="e")

    # =============================================================
    # ABA 3: ENQUADRAMENTO & ESTILO 9:16
    # =============================================================
    def _construir_aba_enquadramento(self) -> None:
        tab = self.tab_enquadramento
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)

        # Coluna 0: Configurações de Webcam
        frame_cam = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_cam.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")
        frame_cam.grid_columnconfigure(0, weight=1)

        lbl_cam_tit = ctk.CTkLabel(
            frame_cam,
            text="📷  Enquadramento da Webcam (Topo do Short)",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_cam_tit.grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        opcoes_webcam = list(MAPA_WEBCAM.keys())
        self.combo_webcam = ctk.CTkComboBox(
            frame_cam,
            values=opcoes_webcam,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            height=32,
            command=lambda _: self._ao_alterar_preferencias()
        )
        self.combo_webcam.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        webcam_salva = self.prefs.get("posicao_webcam", opcoes_webcam[0])
        self.combo_webcam.set(webcam_salva if webcam_salva in opcoes_webcam else opcoes_webcam[0])

        self.btn_auto_calibrar = ctk.CTkButton(
            frame_cam,
            text="🎯  Detectar Webcam com IA Agora",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0284C7",
            hover_color="#0369A1",
            height=30,
            command=self._ao_clicar_auto_calibrar
        )
        self.btn_auto_calibrar.grid(row=2, column=0, padx=12, pady=(0, 4), sticky="ew")

        self.lbl_status_calib = ctk.CTkLabel(
            frame_cam,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA"
        )
        self.lbl_status_calib.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="w")

        # Coluna 1: Legendas e Áudio
        frame_leg = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_leg.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")
        frame_leg.grid_columnconfigure(0, weight=1)

        lbl_leg_tit = ctk.CTkLabel(
            frame_leg,
            text="🔤  Legendas & Áudio",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_leg_tit.grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        self.chk_legendas = ctk.CTkCheckBox(
            frame_leg,
            text="🔤 Legendas Amarelas Dinâmicas (Shorts/TikTok)",
            variable=self.var_legendas,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FACC15",
            checkmark_color="#0F172A",
            fg_color="#FACC15",
            hover_color="#EAB308",
            command=self._ao_alterar_preferencias
        )
        self.chk_legendas.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        som_ativo = self.var_som.get()
        self.btn_som = ctk.CTkButton(
            frame_leg,
            text="🔔 Bip de Conclusão: LIGADO" if som_ativo else "🔕 Bip de Conclusão: DESLIGADO",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#10B981" if som_ativo else "#4B5563",
            hover_color="#059669" if som_ativo else "#374151",
            height=28,
            command=self._ao_alternar_som
        )
        self.btn_som.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="ew")

        # Linha 1: Botões de Ação de Teste
        frame_acoes_estilo = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_acoes_estilo.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        frame_acoes_estilo.grid_columnconfigure(0, weight=1)
        frame_acoes_estilo.grid_columnconfigure(1, weight=1)

        self.chk_modo_teste = ctk.CTkCheckBox(
            frame_acoes_estilo,
            text="🧪 Modo de Teste Rápido (Gravar cortes a cada 45s)",
            variable=self.var_modo_teste,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38BDF8",
            checkmark_color="#0F172A",
            fg_color="#38BDF8",
            hover_color="#0EA5E9",
            command=self._ao_alterar_preferencias
        )
        self.chk_modo_teste.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        frame_previa_bloco = ctk.CTkFrame(frame_acoes_estilo, fg_color="transparent")
        frame_previa_bloco.grid(row=0, column=1, padx=12, pady=6, sticky="e")

        self.btn_previa = ctk.CTkButton(
            frame_previa_bloco,
            text="👁️  Gerar Prévia Rápida (5s)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#8B5CF6",
            hover_color="#7C3AED",
            height=30,
            command=self._ao_clicar_previa
        )
        self.btn_previa.grid(row=0, column=0, sticky="e")

        self.lbl_status_previa = ctk.CTkLabel(
            frame_previa_bloco,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#A1A1AA"
        )
        self.lbl_status_previa.grid(row=1, column=0, sticky="e")

    # =============================================================
    # ABA 4: CORTES SALVOS (HISTÓRICO)
    # =============================================================
    def _construir_aba_cortes(self) -> None:
        tab = self.tab_cortes
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        frame_topo_cortes = ctk.CTkFrame(tab, fg_color="#27272a", corner_radius=8)
        frame_topo_cortes.grid(row=0, column=0, padx=10, pady=(6, 6), sticky="ew")
        frame_topo_cortes.grid_columnconfigure(0, weight=1)

        lbl_dir = ctk.CTkLabel(
            frame_topo_cortes,
            text="📁 Pasta: prontos_para_postar/ (postados/)",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_dir.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        frame_botoes_cortes = ctk.CTkFrame(frame_topo_cortes, fg_color="transparent")
        frame_botoes_cortes.grid(row=0, column=1, padx=12, pady=8, sticky="e")

        btn_atualizar = ctk.CTkButton(
            frame_botoes_cortes,
            text="🔄 Atualizar Lista",
            font=ctk.CTkFont(size=11),
            fg_color="#3F3F46",
            hover_color="#52525B",
            height=26,
            command=self._atualizar_galeria_cortes
        )
        btn_atualizar.grid(row=0, column=0, padx=(0, 6))

        btn_pasta = ctk.CTkButton(
            frame_botoes_cortes,
            text="📂 Abrir no Explorer",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#3B82F6",
            hover_color="#2563EB",
            height=26,
            command=self._ao_clicar_abrir_pasta
        )
        btn_pasta.grid(row=0, column=1)

        self.scroll_galeria = ctk.CTkScrollableFrame(
            tab,
            fg_color="#09090b",
            corner_radius=8
        )
        self.scroll_galeria.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="nsew")
        self.scroll_galeria.grid_columnconfigure(0, weight=1)

        self._atualizar_galeria_cortes()

    # =============================================================
    # MÉTODOS DE FILA EM LOTE E CARREGAMENTO
    # =============================================================
    def _carregar_lista_fila(self) -> None:
        """Carrega os vídeos pendentes em prontos_para_postar/ para agendamento na Aba 2."""
        for widget in self.scroll_fila.winfo_children():
            widget.destroy()

        self.itens_fila_selecionados.clear()
        pasta = Path("prontos_para_postar")
        if not pasta.exists():
            return

        arquivos_mp4 = [
            f for f in pasta.glob("*.mp4")
            if f.is_file() and f.parent.name != "postados" and "preview" not in f.name.lower()
        ]
        arquivos_mp4.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        hoje = datetime.now().date()

        for idx, arq in enumerate(arquivos_mp4):
            dt_criacao = datetime.fromtimestamp(arq.stat().st_mtime)
            eh_hoje = dt_criacao.date() == hoje
            tamanho_mb = arq.stat().st_size / (1024 * 1024)

            meta = self.publicador.extrair_metadados(arq)
            titulo = meta.get("titulo", arq.stem)
            nota = meta.get("nota", 8)

            var_check = ctk.BooleanVar(value=eh_hoje)

            card = ctk.CTkFrame(self.scroll_fila, fg_color="#18181b", corner_radius=6)
            card.grid(row=idx, column=0, padx=4, pady=3, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            texto = f"🌟 [Nota {nota}/10]  {titulo}  |  📅 {dt_criacao.strftime('%d/%m %H:%M')}  ({tamanho_mb:.0f} MB)"
            chk = ctk.CTkCheckBox(
                card,
                text=texto,
                variable=var_check,
                font=ctk.CTkFont(size=11),
                text_color="#F4F4F5",
                checkmark_color="#0F172A",
                fg_color="#7C3AED",
                hover_color="#6D28D9"
            )
            chk.grid(row=0, column=0, padx=8, pady=6, sticky="w")

            self.itens_fila_selecionados.append((var_check, arq, dt_criacao, nota, titulo))

        if not arquivos_mp4:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_fila,
                text="Nenhum vídeo novo pendente em prontos_para_postar/.",
                font=ctk.CTkFont(size=11),
                text_color="#71717A"
            )
            lbl_vazio.grid(row=0, column=0, pady=20)

    def _marcar_todos_fila_hoje(self) -> None:
        hoje = datetime.now().date()
        for var, _, dt, _, _ in self.itens_fila_selecionados:
            var.set(dt.date() == hoje)

    def _ao_clicar_disparar_fila(self) -> None:
        selecionados = [arq for var, arq, _, _, _ in self.itens_fila_selecionados if var.get()]
        if not selecionados:
            self.lbl_status_fila.configure(text="⚠️ Selecione ao menos 1 vídeo da lista para iniciar a fila.", text_color="#EF4444")
            self._adicionar_aviso("⚠️ Nenhum vídeo selecionado para a fila de envios.")
            return

        cota = self.publicador.cota_restante()
        if len(selecionados) > cota:
            self.lbl_status_fila.configure(
                text=f"⚠️ {len(selecionados)} marcados > cota restante ({cota}/6)!",
                text_color="#F59E0B"
            )
            self._adicionar_aviso(
                f"⚠️ Atenção: Você marcou {len(selecionados)} vídeos, mas a cota do YouTube "
                f"hoje permite apenas mais {cota} envios."
            )

        mapa_intervalo = {
            "Imediato": 0,
            "30 minutos": 1800,
            "1 hora": 3600,
            "2 horas": 7200
        }
        intervalo_txt = self.combo_intervalo_fila.get().strip()
        segundos_intervalo = mapa_intervalo.get(intervalo_txt, 1800)

        self.iniciar_fila_lote(selecionados, segundos_intervalo)

    def iniciar_fila_lote(self, videos: List[Path], intervalo_segundos: int) -> None:
        if not videos:
            return

        self.cancelar_fila_evento.clear()
        privacidade = self._obter_privacidade_codigo()

        self.btn_disparar_fila.configure(state="disabled")
        self.btn_cancelar_fila.configure(state="normal")

        self.fila_lote_thread = threading.Thread(
            target=self._executar_fila_lote,
            args=(videos, intervalo_segundos, privacidade),
            daemon=True
        )
        self.fila_lote_thread.start()

    def _executar_fila_lote(self, videos: List[Path], intervalo_segundos: int, privacidade: str) -> None:
        total = len(videos)
        self._adicionar_aviso(f"🚀 Fila de envios iniciada ({total} vídeo(s) na fila | Intervalo: {intervalo_segundos//60} min).")

        for i, video_path in enumerate(videos):
            if self.cancelar_fila_evento.is_set():
                self._adicionar_aviso("⏹️ Fila de envios cancelada pelo usuário.")
                break

            if i > 0 and intervalo_segundos > 0:
                segundos_restantes = intervalo_segundos
                while segundos_restantes > 0 and not self.cancelar_fila_evento.is_set():
                    minutos = segundos_restantes // 60
                    segs = segundos_restantes % 60
                    tempo_str = f"{minutos:02d}m {segs:02d}s" if minutos > 0 else f"{segs:02d}s"
                    texto_status = f"⏳ Fila Neri Clipes: {i}/{total} enviados | Próximo envio em {tempo_str}"
                    self.after(0, lambda t=texto_status: self.lbl_status_fila.configure(text=t, text_color="#A855F7"))
                    time.sleep(1)
                    segundos_restantes -= 1

            if self.cancelar_fila_evento.is_set():
                self._adicionar_aviso("⏹️ Fila de envios cancelada pelo usuário.")
                break

            texto_status = f"🚀 Enviando vídeo {i+1}/{total}: {video_path.name}..."
            self.after(0, lambda t=texto_status: self.lbl_status_fila.configure(text=t, text_color="#38BDF8"))

            # Envio YouTube Shorts
            res_yt = self.publicador.publicar_short(
                caminho_video=video_path,
                privacidade=privacidade
            )
            if res_yt.get("sucesso"):
                self._adicionar_aviso(f"✅ Vídeo {i+1}/{total} postado no YouTube Shorts! {res_yt.get('url')}")
                # Atualiza caminho_video pois o publicador move o arquivo para postados/
                caminho_postado = self.publicador.pasta_postados / video_path.name
                if caminho_postado.exists():
                    video_path = caminho_postado
            else:
                self._adicionar_aviso(f"❌ Erro ao enviar vídeo {i+1}/{total} ao YouTube: {res_yt.get('erro')}")

            # Envio Telegram (se ativo)
            env_tg = self.var_telegram.get() if hasattr(self, "var_telegram") else False
            if env_tg:
                res_tg = self.publicador.enviar_telegram(caminho_video=video_path)
                if res_tg.get("sucesso"):
                    self._adicionar_aviso(f"✅ Vídeo {i+1}/{total} entregue no Telegram!")
                else:
                    self._adicionar_aviso(f"❌ Erro ao enviar vídeo {i+1}/{total} ao Telegram: {res_tg.get('erro')}")

            self.after(0, self._atualizar_badge_cota)
            self.after(0, self._carregar_lista_fila)
            self.after(0, self._atualizar_galeria_cortes)

        if not self.cancelar_fila_evento.is_set():
            self.after(0, lambda: self.lbl_status_fila.configure(text="✅ Todos os vídeos da fila foram concluídos!", text_color="#10B981"))
            self._adicionar_aviso("🎉 Fila de envios em lote concluída com sucesso!")
        else:
            self.after(0, lambda: self.lbl_status_fila.configure(text="⏹️ Fila cancelada.", text_color="#EF4444"))

        self.after(0, lambda: self.btn_disparar_fila.configure(state="normal"))
        self.after(0, lambda: self.btn_cancelar_fila.configure(state="disabled"))

    def _ao_clicar_cancelar_fila(self) -> None:
        self.cancelar_fila_evento.set()
        self.btn_cancelar_fila.configure(state="disabled")
        self.lbl_status_fila.configure(text="⏹️ Cancelando fila...", text_color="#EF4444")

    def _atualizar_galeria_cortes(self) -> None:
        """Atualiza a lista de cartões na Aba 4."""
        for widget in self.scroll_galeria.winfo_children():
            widget.destroy()

        pasta = Path("prontos_para_postar")
        if not pasta.exists():
            return

        arquivos_mp4 = [
            f for f in (list(pasta.glob("*.mp4")) + list((pasta / "postados").glob("*.mp4")))
            if "preview" not in f.name.lower()
        ]
        arquivos_mp4.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        for idx, arq in enumerate(arquivos_mp4):
            dt_criacao = datetime.fromtimestamp(arq.stat().st_mtime)
            tamanho_mb = arq.stat().st_size / (1024 * 1024)
            ja_postado = arq.parent.name == "postados"

            meta = self.publicador.extrair_metadados(arq)
            titulo = meta.get("titulo", arq.stem)
            nota = meta.get("nota", 8)

            card = ctk.CTkFrame(self.scroll_galeria, fg_color="#18181b", corner_radius=6)
            card.grid(row=idx, column=0, padx=4, pady=3, sticky="ew")
            card.grid_columnconfigure(1, weight=1)

            lbl_badge_nota = ctk.CTkLabel(
                card,
                text=f"Nota {nota}/10",
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#10B981" if nota >= 9 else "#F59E0B",
                text_color="#FAFAFA",
                corner_radius=4,
                width=65,
                height=22
            )
            lbl_badge_nota.grid(row=0, column=0, padx=8, pady=8)

            lbl_txt = ctk.CTkLabel(
                card,
                text=f"{titulo}\n📅 {dt_criacao.strftime('%d/%m/%Y %H:%M')}  •  {tamanho_mb:.1f} MB",
                font=ctk.CTkFont(size=11),
                justify="left"
            )
            lbl_txt.grid(row=0, column=1, padx=6, pady=8, sticky="w")

            # Ações e Status do Cartão
            frame_card_acoes = ctk.CTkFrame(card, fg_color="transparent")
            frame_card_acoes.grid(row=0, column=2, padx=8, pady=6, sticky="e")

            btn_play = ctk.CTkButton(
                frame_card_acoes,
                text="▶ Assistir",
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#3F3F46",
                hover_color="#52525B",
                width=72,
                height=26,
                command=lambda p=arq: self._ao_clicar_reproduzir_video(p)
            )
            btn_play.grid(row=0, column=0, padx=(0, 4))

            btn_tg = ctk.CTkButton(
                frame_card_acoes,
                text="📱 Telegram",
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#0284C7",
                hover_color="#0369A1",
                width=80,
                height=26
            )
            btn_tg.configure(command=lambda p=arq, b=btn_tg: self._enviar_video_telegram_individual(p, b))
            btn_tg.grid(row=0, column=1, padx=(0, 6))

            status_txt = "Postado ✅" if ja_postado else "Pendente ⏳"
            status_cor = "#7C3AED" if ja_postado else "#A1A1AA"
            lbl_status = ctk.CTkLabel(
                frame_card_acoes,
                text=status_txt,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=status_cor
            )
            lbl_status.grid(row=0, column=2, padx=(2, 4))

        if not arquivos_mp4:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_galeria,
                text="Nenhum vídeo renderizado ainda.",
                font=ctk.CTkFont(size=11),
                text_color="#71717A"
            )
            lbl_vazio.grid(row=0, column=0, pady=20)

    # =============================================================
    # GERENCIAMENTO DE LOGS, COTA E CONTROLES
    # =============================================================
    def _atualizar_badge_cota(self) -> None:
        usados = self.publicador.obter_envios_ultimas_24h()
        cor = "#EF4444" if usados >= LIMITE_DIARIO_UPLOADS else ("#F59E0B" if usados >= 4 else "#10B981")
        texto = f"📊 Cota: {usados}/{LIMITE_DIARIO_UPLOADS} hoje"
        if hasattr(self, "lbl_cota_badge"):
            self.lbl_cota_badge.configure(text=texto, fg_color=cor)
        if hasattr(self, "lbl_rodape_cota"):
            self.lbl_rodape_cota.configure(text=f"{texto} • Canal Neri Clipes", text_color=cor)

    def _adicionar_aviso(self, texto: str) -> None:
        self.txt_logs.configure(state="normal")
        self.txt_logs.insert("end", texto + "\n\n")
        self.txt_logs.see("end")
        self.txt_logs.configure(state="disabled")

    def _definir_status(self, texto: str, cor_fundo: str) -> None:
        self.badge_status.configure(text=texto, fg_color=cor_fundo)

    def _obter_alvo_selecionado(self) -> Optional[str]:
        valor = self.combo_canal.get().strip()
        if not valor or "Lista Automática" in valor:
            return None
        if "(" in valor and valor.endswith(")"):
            return valor.split("(")[-1].rstrip(")").strip()
        return valor

    def _obter_posicao_webcam_codigo(self) -> str:
        valor = self.combo_webcam.get().strip()
        return MAPA_WEBCAM.get(valor, "inferior_esquerdo")

    def _obter_nota_minima_int(self) -> int:
        valor = self.combo_nota_minima.get().strip()
        if "7" in valor:
            return 7
        if "9" in valor:
            return 9
        return 8

    def _obter_nota_minima_salvar_int(self) -> int:
        valor = self.combo_filtro_salvar.get().strip() if hasattr(self, "combo_filtro_salvar") else "7"
        if "10" in valor:
            return 10
        if "9" in valor:
            return 9
        if "8" in valor:
            return 8
        return 7

    def _obter_privacidade_codigo(self) -> str:
        valor = self.combo_privacidade.get().strip().lower()
        if "público" in valor or "publico" in valor:
            return "public"
        if "privado" in valor:
            return "private"
        return "unlisted"

    def _ao_clicar_conectar_youtube(self) -> None:
        self._adicionar_aviso("🔑 Abrindo navegador para autenticação do canal YouTube...")
        self.btn_conectar_youtube.configure(state="disabled", text="⏳ Aguardando...")
        self.lbl_status_auth.configure(text="⏳ Aguardando login no navegador...", text_color="#38BDF8")

        def _tarefa_auth():
            sucesso, msg = self.publicador.autenticar_interativo()
            def _concluir():
                self.btn_conectar_youtube.configure(state="normal")
                if sucesso:
                    self.btn_conectar_youtube.configure(
                        text="🔑 YouTube: Conectado ✅",
                        fg_color="#10B981",
                        hover_color="#059669"
                    )
                    self.lbl_status_auth.configure(text="✅ Conta conectada e autorizada com sucesso!", text_color="#10B981")
                    self._adicionar_aviso("✅ Canal do YouTube conectado com sucesso!")
                else:
                    self.btn_conectar_youtube.configure(
                        text="🔑 Conectar Conta YouTube",
                        fg_color="#0284C7",
                        hover_color="#0369A1"
                    )
                    # Exibe o motivo exato (ex: falta de client_secret.json) na tela
                    resumo_msg = msg.split("\n")[0]
                    self.lbl_status_auth.configure(text=f"⚠️ {resumo_msg}", text_color="#EF4444")
                    self._adicionar_aviso(f"❌ Falha no login do YouTube:\n{msg}")
                self._atualizar_badge_cota()
            self.after(0, _concluir)

        threading.Thread(target=_tarefa_auth, daemon=True).start()

    def _ao_clicar_previa(self) -> None:
        pos_codigo = self._obter_posicao_webcam_codigo()
        com_leg = self.var_legendas.get()
        alvo = self._obter_alvo_selecionado()

        self._adicionar_aviso("👁️ Iniciando gravação de prévia rápida (5s)...")
        self.btn_previa.configure(state="disabled")
        self.lbl_status_previa.configure(text="⏳ Buscando live para gravar 5s...", text_color="#38BDF8")

        def _tarefa_previa():
            loop = asyncio.new_event_loop()
            try:
                from agentes.agente_editor import AgenteEditor
                from agentes.vigia_stream import VigiaStream, PRESETS_WEBCAM

                editor = AgenteEditor()
                stream_url = None
                audio_url = None
                streamer_info = None
                fonte_ao_vivo = False
                caminho_video_origem = None

                # 1. Reaproveita a live já conectada se o caçador estiver rodando
                if (
                    self.bot_runner
                    and self.bot_runner.rodando
                    and self.bot_runner.orquestrador
                    and self.bot_runner.orquestrador.vigia
                    and self.bot_runner.orquestrador.vigia.stream_url_ativa
                ):
                    vigia_ativa = self.bot_runner.orquestrador.vigia
                    stream_url = vigia_ativa.stream_url_ativa
                    audio_url = getattr(vigia_ativa, "audio_url_ativa", None)
                    if vigia_ativa.streamer_ativo:
                        streamer_info = dict(vigia_ativa.streamer_ativo)
                    fonte_ao_vivo = True
                else:
                    # 2. Procura o streamer selecionado (ou da lista de prioridade) ao vivo (Kick / Twitch / YouTube)
                    vigia = VigiaStream(posicao_webcam=pos_codigo)
                    if alvo:
                        vigia.definir_streamer_alvo(alvo, posicao_webcam=pos_codigo)

                    streamer_online = loop.run_until_complete(vigia.encontrar_streamer_online())
                    if streamer_online and vigia.stream_url_ativa:
                        stream_url = vigia.stream_url_ativa
                        audio_url = getattr(vigia, "audio_url_ativa", None)
                        streamer_info = dict(streamer_online)
                        fonte_ao_vivo = True
                    else:
                        # Streamer offline: busca gravação recente de clipe como fonte de prévia
                        video_offline = vigia.buscar_video_recente_para_calibracao(alvo)
                        if video_offline:
                            caminho_video_origem = video_offline

                # Se o modo Auto IA estiver selecionado, calibra o enquadramento no frame real
                if pos_codigo == "auto":
                    self.after(0, lambda: self.lbl_status_previa.configure(
                        text="🎯 Calibrando webcam com IA...", text_color="#A855F7"
                    ))
                    caminho_detectar = stream_url or (str(caminho_video_origem.resolve()) if caminho_video_origem else None)
                    if caminho_detectar:
                        vigia_detector = VigiaStream()
                        res_ia = loop.run_until_complete(vigia_detector.detectar_webcam_ia(caminho_detectar))
                        if not streamer_info:
                            streamer_info = {"slug": "preview", "nome": "PREVIEW"}
                        if res_ia.get("crop"):
                            streamer_info["webcam_crop"] = res_ia["crop"]
                        else:
                            pos_ia = res_ia.get("posicao", "inferior_esquerdo")
                            streamer_info["webcam_crop"] = dict(
                                PRESETS_WEBCAM.get(pos_ia, PRESETS_WEBCAM["inferior_esquerdo"])
                            )

                # Garante webcam_crop coerente com a escolha do usuário
                if not streamer_info:
                    crop = dict(PRESETS_WEBCAM.get(pos_codigo, PRESETS_WEBCAM["inferior_esquerdo"]))
                    streamer_info = {"slug": "preview", "nome": "PREVIEW", "webcam_crop": crop}
                elif pos_codigo == "desativado":
                    streamer_info["webcam_crop"] = {"ativo": False, "x": 0, "y": 0, "w": 0, "h": 0}
                elif pos_codigo in PRESETS_WEBCAM and pos_codigo != "auto":
                    streamer_info["webcam_crop"] = dict(PRESETS_WEBCAM[pos_codigo])

                if fonte_ao_vivo and stream_url:
                    nome_st = streamer_info.get("nome", "Live")
                    self.after(0, lambda n=nome_st: self.lbl_status_previa.configure(
                        text=f"🔴 Gravando 5s ao vivo ({n})...", text_color="#EF4444"
                    ))
                    hora = time.strftime("%H:%M:%S")
                    self.log_queue.put(("INFO", f"[{hora}] 🔴 Gravando 5 segundos ao vivo de {nome_st} para prévia..."))
                else:
                    origem_msg = f"gravação de {caminho_video_origem.name[:20]}" if caminho_video_origem else "buffer/teste"
                    self.after(0, lambda m=origem_msg: self.lbl_status_previa.configure(
                        text=f"⏳ Live offline. Gerando prévia via {m}...", text_color="#F59E0B"
                    ))
                    hora = time.strftime("%H:%M:%S")
                    self.log_queue.put(("WARNING", f"[{hora}] ⏳ Streamer offline. Gerando prévia de 5s via {origem_msg}..."))

                video_previa = loop.run_until_complete(
                    editor.gerar_video_previa(
                        streamer_info=streamer_info,
                        caminho_video_origem=caminho_video_origem,
                        com_legendas=com_leg,
                        stream_url=stream_url,
                        audio_url=audio_url
                    )
                )

                if video_previa and video_previa.exists():
                    hora = time.strftime("%H:%M:%S")
                    origem_txt = "AO VIVO" if fonte_ao_vivo else ("Gravação" if caminho_video_origem else "Buffer/Teste")
                    self.log_queue.put(("INFO", f"[{hora}] ✨ Prévia ({origem_txt}) gravada com sucesso! Abrindo no player..."))
                    self.after(0, lambda o=origem_txt: self.lbl_status_previa.configure(
                        text=f"✨ Prévia ({o}) aberta!", text_color="#10B981"
                    ))
                    os.startfile(str(video_previa.resolve()))
                else:
                    hora = time.strftime("%H:%M:%S")
                    self.log_queue.put(("ERROR", f"[{hora}] ❌ Não foi possível gerar a pré-visualização."))
                    self.after(0, lambda: self.lbl_status_previa.configure(text="❌ Falha ao gerar vídeo.", text_color="#EF4444"))
            except Exception as e:
                hora = time.strftime("%H:%M:%S")
                self.log_queue.put(("ERROR", f"[{hora}] ❌ Erro ao criar prévia: {e}"))
                self.after(0, lambda err=str(e): self.lbl_status_previa.configure(text=f"❌ Erro: {err[:30]}", text_color="#EF4444"))
                try:
                    registrar_erro_detalhado("InterfaceApp._ao_clicar_previa", "Erro ao gerar prévia de 5 segundos", exc=e)
                except Exception:
                    pass
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                self.after(0, lambda: self.btn_previa.configure(state="normal"))

        threading.Thread(target=_tarefa_previa, daemon=True).start()

    def _ao_clicar_auto_calibrar(self) -> None:
        alvo = self._obter_alvo_selecionado()
        alvo_nome = alvo if alvo else "Lista Automática de Streamers"

        self._adicionar_aviso(f"🎯 Iniciando detecção automática de webcam com IA para: {alvo_nome}...")
        self.btn_auto_calibrar.configure(state="disabled")
        self.lbl_status_calib.configure(text="⏳ Buscando live e detectando com IA...", text_color="#38BDF8")

        def _tarefa_calib():
            loop = asyncio.new_event_loop()
            try:
                from agentes.vigia_stream import VigiaStream
                vigia = VigiaStream()
                if alvo:
                    vigia.definir_streamer_alvo(alvo)

                stream_url = None
                origem_tipo = "ao vivo"

                # 1. Se o bot já estiver rodando e com live ativa, reaproveita a stream_url
                if (
                    self.bot_runner
                    and self.bot_runner.rodando
                    and self.bot_runner.orquestrador
                    and self.bot_runner.orquestrador.vigia
                    and self.bot_runner.orquestrador.vigia.stream_url_ativa
                ):
                    stream_url = self.bot_runner.orquestrador.vigia.stream_url_ativa
                else:
                    streamer = loop.run_until_complete(vigia.encontrar_streamer_online())
                    if streamer and vigia.stream_url_ativa:
                        stream_url = vigia.stream_url_ativa

                caminho_para_detectar = stream_url
                if not caminho_para_detectar:
                    # Streamer offline: busca gravação recente (.mp4) para calibrar!
                    self.after(0, lambda: self.lbl_status_calib.configure(
                        text="⏳ Live offline. Buscando gravação recente...", text_color="#F59E0B"
                    ))
                    video_recente = vigia.buscar_video_recente_para_calibracao(alvo)
                    if video_recente:
                        caminho_para_detectar = str(video_recente.resolve())
                        origem_tipo = f"gravação: {video_recente.name[:25]}..."
                    else:
                        hora = time.strftime("%H:%M:%S")
                        msg_aviso = "Streamer offline e nenhum vídeo recente encontrado para calibrar."
                        self.log_queue.put(("WARNING", f"[{hora}] ⚠️ {msg_aviso}"))
                        self.after(0, lambda: self.lbl_status_calib.configure(
                            text="⚠️ Offline e sem gravação recente.", text_color="#F59E0B"
                        ))
                        return

                self.after(0, lambda: self.lbl_status_calib.configure(
                    text="🎯 Analisando frame com Visão Computacional / IA...", text_color="#A855F7"
                ))
                res = loop.run_until_complete(vigia.detectar_webcam_ia(caminho_para_detectar))

                pos = res.get("posicao", "desativado")
                desc = res.get("descricao", "")
                label_combo = MAPA_WEBCAM_REVERSO.get(pos, "Desativado (Sem Webcam - Apenas Gameplay 9:16)")

                self.after(0, lambda: self.combo_webcam.set(label_combo))
                self.after(0, self._ao_alterar_preferencias)

                hora = time.strftime("%H:%M:%S")
                self.log_queue.put(("INFO", f"[{hora}] 🎯 Auto-Calibração IA ({origem_tipo}): {desc}"))
                self.log_queue.put(("INFO", f"[{hora}] 👉 Enquadramento ajustado para: '{label_combo}'"))
                self.after(0, lambda: self.lbl_status_calib.configure(
                    text=f"✅ Detectado: {label_combo.split('(')[0].strip()}", text_color="#10B981"
                ))
            except Exception as e:
                hora = time.strftime("%H:%M:%S")
                self.log_queue.put(("ERROR", f"[{hora}] ❌ Erro na autocalibração: {e}"))
                self.after(0, lambda err=str(e): self.lbl_status_calib.configure(text=f"❌ Erro: {err[:30]}", text_color="#EF4444"))
                try:
                    registrar_erro_detalhado("InterfaceApp._ao_clicar_auto_calibrar", f"Erro ao autocalibrar {alvo}", exc=e)
                except Exception:
                    pass
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                self.after(0, lambda: self.btn_auto_calibrar.configure(state="normal"))

        threading.Thread(target=_tarefa_calib, daemon=True).start()

    def _ao_alternar_som(self) -> None:
        novo_estado = not self.var_som.get()
        self.var_som.set(novo_estado)
        self._ao_alterar_preferencias()

        if novo_estado:
            self.btn_som.configure(text="🔔 Bip de Conclusão: LIGADO", fg_color="#10B981", hover_color="#059669")
            self._adicionar_aviso("🔔 Bip sonoro ATIVADO.")
            try:
                if sys.platform == "win32":
                    import winsound
                    winsound.Beep(1000, 150)
            except Exception:
                pass
        else:
            self.btn_som.configure(text="🔕 Bip de Conclusão: DESLIGADO", fg_color="#4B5563", hover_color="#374151")
            self._adicionar_aviso("🔕 Bip sonoro DESLIGADO.")

        if self.bot_runner:
            self.bot_runner.alerta_sonoro = novo_estado
            if self.bot_runner.orquestrador and self.bot_runner.orquestrador.editor:
                self.bot_runner.orquestrador.editor.alerta_sonoro = novo_estado

    def _ao_clicar_iniciar(self) -> None:
        if self.bot_runner and self.bot_runner.rodando:
            return

        try:
            self._salvar_preferencias()

            teste_ativo = self.var_modo_teste.get() if hasattr(self, "var_modo_teste") else False
            os.environ["MODO_TESTE"] = "true" if teste_ativo else "false"
            os.environ["AUTO_APROVAR"] = "true" if teste_ativo else "false"

            alvo = self._obter_alvo_selecionado()
            nome_exibicao = alvo if alvo else "Lista Automática de Streamers"
            pos_webcam = self._obter_posicao_webcam_codigo()
            leg_ativa = self.var_legendas.get() if hasattr(self, "var_legendas") else True
            upload_yt = self.var_upload_youtube.get() if hasattr(self, "var_upload_youtube") else False
            priv_yt = self._obter_privacidade_codigo()
            nota_min = self._obter_nota_minima_int()
            nota_salvar = self._obter_nota_minima_salvar_int()
            env_tg = self.var_telegram.get() if hasattr(self, "var_telegram") else False

            self._adicionar_aviso(f"🚀 Iniciando caçador para: {nome_exibicao} (Filtro: Salvar Nota {nota_salvar}+)...")
            self._definir_status("● INICIANDO...", "#CA8A04")

            self.btn_iniciar.configure(state="disabled")
            self.btn_parar.configure(state="normal")
            if hasattr(self, "combo_canal"):
                self.combo_canal.configure(state="disabled")
            if hasattr(self, "combo_filtro_salvar"):
                self.combo_filtro_salvar.configure(state="disabled")

            self.bot_runner = BotRunner(
                alvo_direto=alvo,
                log_queue=self.log_queue,
                posicao_webcam=pos_webcam,
                habilitar_legendas=leg_ativa,
                alerta_sonoro=self.var_som.get() if hasattr(self, "var_som") else True,
                upload_automatico_youtube=upload_yt,
                privacidade_youtube=priv_yt,
                nota_minima_upload=nota_min,
                enviar_telegram=env_tg,
                nota_minima_salvar=nota_salvar
            )
            self.bot_runner.iniciar()

        except Exception as e:
            self._adicionar_aviso(f"❌ Erro ao iniciar caçador: {e}")
            self._concluir_parada()

    def _ao_clicar_parar(self) -> None:
        if not self.bot_runner or not self.bot_runner.rodando:
            return

        self._adicionar_aviso("⏹️ Parando o bot com segurança...")
        self._definir_status("● PARANDO...", "#DC2626")
        self.btn_parar.configure(state="disabled")

        def _tarefa_parar():
            if self.bot_runner:
                self.bot_runner.parar()
                self.bot_runner = None
            self.after(0, self._concluir_parada)

        threading.Thread(target=_tarefa_parar, daemon=True).start()

    def _concluir_parada(self) -> None:
        self.btn_iniciar.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        if hasattr(self, "combo_canal"):
            self.combo_canal.configure(state="normal")
        if hasattr(self, "combo_filtro_salvar"):
            self.combo_filtro_salvar.configure(state="normal")
        self._definir_status("● PARADO", "#3F3F46")
        self._adicionar_aviso("✅ Bot finalizado com sucesso.")
        self._atualizar_badge_cota()
        self._carregar_lista_fila()
        self._atualizar_galeria_cortes()

    def _ao_clicar_abrir_pasta(self) -> None:
        pasta_saida = Path(os.getenv("OUTPUT_DIR", "prontos_para_postar")).resolve()
        pasta_saida.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(pasta_saida))
            self._adicionar_aviso(f"📂 Abrindo pasta no Explorer: {pasta_saida}")
        except Exception as e:
            self._adicionar_aviso(f"❌ Erro ao abrir pasta: {e}")

    def _ao_clicar_reproduzir_video(self, caminho_video: Path) -> None:
        """Abre o vídeo selecionado no player padrão do sistema."""
        try:
            if caminho_video.exists():
                os.startfile(str(caminho_video))
                self._adicionar_aviso(f"▶ Reproduzindo vídeo: {caminho_video.name}")
            else:
                self._adicionar_aviso(f"⚠️ Arquivo não encontrado: {caminho_video.name}")
        except Exception as e:
            self._adicionar_aviso(f"❌ Erro ao abrir vídeo: {e}")

    def _enviar_video_telegram_individual(self, caminho_video: Path, btn_origem: Optional[ctk.CTkButton] = None) -> None:
        """Envia um vídeo individual para o Telegram via Bot em thread em segundo plano."""
        if not self.publicador.telegram_bot_token or not self.publicador.telegram_chat_id:
            self._adicionar_aviso("⚠️ Telegram não configurado no .env (TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID vazios).")
            return

        if not caminho_video.exists():
            self._adicionar_aviso(f"⚠️ Vídeo não encontrado no disco: {caminho_video.name}")
            return

        if btn_origem:
            btn_origem.configure(text="⏳ Enviando...", state="disabled", fg_color="#F59E0B")

        def _tarefa_envio():
            self._adicionar_aviso(f"📱 Enviando clipe ao Telegram ({caminho_video.name})...")
            res = self.publicador.enviar_telegram(caminho_video)
            if res.get("sucesso"):
                self._adicionar_aviso(f"✅ Clipe entregue no Telegram com sucesso: {caminho_video.name}")
                if btn_origem:
                    self.after(0, lambda: btn_origem.configure(text="✅ Enviado", fg_color="#10B981", state="normal"))
            else:
                erro = res.get("erro", "Erro desconhecido")
                self._adicionar_aviso(f"❌ Falha no envio ao Telegram: {erro}")
                if btn_origem:
                    self.after(0, lambda: btn_origem.configure(text="❌ Erro", fg_color="#EF4444", state="normal"))

        threading.Thread(target=_tarefa_envio, daemon=True).start()

    def _ao_clicar_enviar_telegram_fila(self) -> None:
        """Envia todos os vídeos marcados na lista da Aba 2 diretamente para o Telegram."""
        selecionados = [arq for var, arq, _, _, _ in self.itens_fila_selecionados if var.get()]
        if not selecionados:
            self.lbl_status_fila.configure(text="⚠️ Selecione ao menos 1 vídeo para enviar ao Telegram.", text_color="#EF4444")
            self._adicionar_aviso("⚠️ Nenhum vídeo selecionado para envio ao Telegram.")
            return

        if not self.publicador.telegram_bot_token or not self.publicador.telegram_chat_id:
            self.lbl_status_fila.configure(text="⚠️ Telegram não configurado no .env!", text_color="#EF4444")
            self._adicionar_aviso("⚠️ Telegram não configurado no .env!")
            return

        self.btn_disparar_tg.configure(state="disabled")

        def _tarefa_lote_tg():
            total = len(selecionados)
            self._adicionar_aviso(f"📱 Iniciando envio de {total} vídeo(s) para o Telegram...")
            enviados_ok = 0
            for i, arq in enumerate(selecionados):
                self.after(0, lambda idx=i+1, tot=total, n=arq.name: self.lbl_status_fila.configure(
                    text=f"📱 Enviando {idx}/{tot} para Telegram: {n}...", text_color="#38BDF8"
                ))
                res = self.publicador.enviar_telegram(arq)
                if res.get("sucesso"):
                    enviados_ok += 1
                    self._adicionar_aviso(f"✅ ({i+1}/{total}) Entregue no Telegram: {arq.name}")
                else:
                    self._adicionar_aviso(f"❌ ({i+1}/{total}) Falha no Telegram: {res.get('erro')}")
                time.sleep(1)

            self.after(0, lambda: self.lbl_status_fila.configure(
                text=f"✅ {enviados_ok}/{total} vídeo(s) entregues no Telegram!", text_color="#10B981"
            ))
            self.after(0, lambda: self.btn_disparar_tg.configure(state="normal"))

        threading.Thread(target=_tarefa_lote_tg, daemon=True).start()

    def _ao_clicar_limpar(self) -> None:
        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.configure(state="disabled")

    def _processar_fila_logs(self) -> None:
        while not self.log_queue.empty():
            try:
                nivel, aviso = self.log_queue.get_nowait()
                self._adicionar_aviso(aviso)

                if "Streamer AO VIVO" in aviso or "Conectando ao stream" in aviso:
                    self._definir_status("● AO VIVO", "#16A34A")
                elif "Cortando trecho" in aviso or "Gemini analisando" in aviso:
                    self._definir_status("● ANALISANDO IA", "#2563EB")
                    self.bar_hype.set(0.7)
                elif "Renderizando Short" in aviso:
                    self._definir_status("● RENDERIZANDO", "#D97706")
                    self.bar_hype.set(0.9)
                elif "VÍDEO SALVO COM SUCESSO" in aviso:
                    self.total_cortes_salvos += 1
                    self._definir_status(f"● SALVOU ({self.total_cortes_salvos})", "#9333EA")
                    self.bar_hype.set(1.0)
                    self.after(3000, lambda: self.bar_hype.set(0.0))
                    self._carregar_lista_fila()
                    self._atualizar_galeria_cortes()
                elif "Publicado no YouTube Shorts" in aviso:
                    self._atualizar_badge_cota()
                    self._carregar_lista_fila()
                    self._atualizar_galeria_cortes()
                elif "A live caiu" in aviso or "Nenhum dos canais" in aviso:
                    self._definir_status("● PROCURANDO...", "#CA8A04")
                    self.bar_hype.set(0.1)

            except queue.Empty:
                break

        self.after(100, self._processar_fila_logs)

    def _ao_fechar_janela(self) -> None:
        self._salvar_preferencias()
        self.cancelar_fila_evento.set()
        if self.bot_runner and self.bot_runner.rodando:
            self.bot_runner.parar()
        self.destroy()


def main():
    app = JanelaClipHunter()
    app.mainloop()


if __name__ == "__main__":
    main()
