"""
Módulo RadarHype - GTA6_ClipHunter
Implementa o sistema de gatilho duplo para detecção de momentos virais:
1. WebSocket do Chat da Kick (mensagens/segundo e palavras-chave virais)
2. Monitor contínuo de áudio PCM via FFmpeg (picos de energia RMS > 2.5x a média)
Totalmente resiliente a bloqueios de Cloudflare ou quedas de conexão.
"""

import sys
import os
import re
import time
import json
import uuid
import shutil
import asyncio
import logging
import subprocess
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Deque

import numpy as np
import aiohttp
import websockets

logger = logging.getLogger("ClipHunter.RadarHype")

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def obter_caminho_ffmpeg() -> str:
    """Busca executável do FFmpeg no PATH ou em diretórios WinGet."""
    cmd = shutil.which("ffmpeg")
    if cmd:
        return cmd
    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        pacotes = Path(user_profile) / "AppData/Local/Microsoft/WinGet/Packages"
        if pacotes.exists():
            for p in pacotes.glob("**/ffmpeg.exe"):
                if p.is_file():
                    return str(p)
    return "ffmpeg"


# Endpoints modernos de Realtime / Centrifugo da Kick e IRC WebSocket da Twitch
KICK_REALTIME_WS = "wss://realtime.us-east-1.platform.kick.com/connection/websocket"
KICK_AUTH_URL = "https://web.kick.com/api/v1/realtime/auth/connection"
TWITCH_IRC_WS = "wss://irc-ws.chat.twitch.tv:443"


class RadarHype:
    def __init__(
        self,
        stream_url: str,
        streamer_info: Dict[str, Any],
        config_geral: Dict[str, Any],
        on_hype_callback: Optional[Callable] = None,
        audio_url: Optional[str] = None
    ):
        self.stream_url = stream_url
        self.audio_url = audio_url
        self.streamer_info = streamer_info
        self.config_geral = config_geral
        self.on_hype_callback = on_hype_callback

        self.slug = streamer_info.get("slug", "")
        self.nome = streamer_info.get("nome", self.slug)
        self.palavras_gatilho = [p.upper() for p in streamer_info.get("palavras_gatilho_chat", [])]

        # Parâmetros de timing
        self.cooldown_segundos = config_geral.get("cooldown_entre_cortes_segundos", 60)
        self.segundos_depois_pico = config_geral.get("segundos_depois_do_pico", 15)
        self.intervalo_varredura_segundos = config_geral.get("amostragem_periodica_minutos", 4) * 60
        self.ultimo_corte_timestamp: float = time.time()

        # Modo de Teste: grava vídeos periodicamente sem depender de gatilhos
        self.modo_teste = (
            os.getenv("MODO_TESTE", "false").lower() in ("true", "1", "sim", "yes")
            or config_geral.get("modo_teste", False)
        )
        self.intervalo_teste = int(os.getenv("INTERVALO_TESTE_SEGUNDOS", config_geral.get("intervalo_teste_segundos", 45)))
        if self.modo_teste:
            self.cooldown_segundos = 30
            self.segundos_depois_pico = 3

        # Histórico de áudio RMS (janela móvel de 30 segundos)
        # Limiar de 1.8x pega conversas entusiasmadas, notícias, debates e reações
        self.historico_rms: Deque[float] = deque(maxlen=30)
        self.limiar_multiplicador_rms = 1.8
        self.piso_ruido_minimo_rms = 300.0

        # Palavras prioritárias específicas de GTA 6 (Modo Lançamento + Gameplay + Reações)
        self.gatilhos_especificos_gta6 = {
            "GTA6", "GTA 6", "GTAVI", "GTA VI", "VICE CITY", "LEONIDA", "LUCIA", "JASON",
            "ROCKSTAR", "TRAILER", "LANÇAMENTO", "MAPA", "PRAIA", "JACARE", "JACARÉ",
            "PANTANO", "PÂNTANO", "DETALHE", "DETALHES", "FISICA", "FÍSICA", "REALISMO",
            "REALISTA", "GRAFICO", "GRÁFICO", "GRAFICOS", "GRÁFICOS", "NPC", "NPCS",
            "AGUA", "ÁGUA", "CINEMA", "OBRA PRIMA", "GOTY", "SURREAL", "ABSURDO",
            "BUG", "BUGOU", "EASTER EGG", "SEGREDO", "CJ", "SAN ANDREAS", "TOMMY",
            "TREVOR", "CUTSCENE", "MISSAO", "MISSÃO", "QUE JOGO"
        }
        self.contagem_gta6_recentes: Deque[float] = deque(maxlen=20)

        # Histórico e métricas do chat + Detector de Explosão de Velocidade (msgs/5s)
        self.mensagens_recentes: Deque[str] = deque(maxlen=50)
        self.contagem_gatilhos_recentes: Deque[float] = deque(maxlen=20)
        self.timestamps_chat_geral: Deque[float] = deque(maxlen=400)
        self.historico_velocidade_chat: Deque[int] = deque(maxlen=12)
        self._ultimo_marco_velocidade: float = time.time()
        self._contador_janela_velocidade: int = 0
        self.chatroom_id: Optional[int] = None

        # Controle de estado
        self.rodando = False
        self.processo_audio_ffmpeg: Optional[asyncio.subprocess.Process] = None
        self.tarefas: List[asyncio.Task] = []

    async def iniciar(self) -> None:
        """Inicia os monitores: Áudio RMS, Chat WebSocket e Varredura Periódica de GTA 6."""
        self.rodando = True
        logger.info(f"Iniciando Radar de Conteúdo e Hype para {self.nome}...")

        # 1. Monitor de áudio contínuo (Picos de entusiasmo e reações)
        tarefa_audio = asyncio.create_task(self._monitorar_audio_rms())
        self.tarefas.append(tarefa_audio)

        # 2. Monitor de chat em tempo real (Twitch IRC, YouTube Live Chat ou Kick Centrifugo)
        url_canal = str(self.streamer_info.get("url", "")).lower()
        if "twitch.tv" in url_canal:
            tarefa_chat = asyncio.create_task(self._monitorar_chat_twitch())
        elif "youtube.com" in url_canal or "youtu.be" in url_canal:
            tarefa_chat = asyncio.create_task(self._monitorar_chat_youtube())
        else:
            tarefa_chat = asyncio.create_task(self._monitorar_chat_kick())
        self.tarefas.append(tarefa_chat)

        # 3. Varredura Inteligente Periódica (Não perde notícias ditas em tom calmo)
        tarefa_varredura = asyncio.create_task(self._varredura_periodica_conteudo())
        self.tarefas.append(tarefa_varredura)

        # 4. Modo de Teste Automático (dispara cortes a cada intervalo sem depender de chat ou picos)
        if self.modo_teste:
            tarefa_teste = asyncio.create_task(self._loop_modo_teste())
            self.tarefas.append(tarefa_teste)

    async def _loop_modo_teste(self) -> None:
        """
        Modo de Teste: Dispara cortes automaticamente em intervalos regulares
        (ex: 45s), permitindo testar e verificar a gravação e renderização dos vídeos
        sem necessitar de palavras-chave no chat ou picos de áudio.
        """
        logger.info(
            f"🧪 MODO DE TESTE ATIVO: Gravando cortes automaticamente a cada {self.intervalo_teste}s "
            "sem depender de palavras-chave ou chat!"
        )
        # Aguarda 35s inicialmente para garantir que os primeiros blocos de vídeo entrem no buffer
        espera_inicial = min(35, self.intervalo_teste)
        await asyncio.sleep(espera_inicial)

        while self.rodando:
            try:
                logger.info(f"⏱️ [Modo de Teste] Disparando captura automática de corte ({self.intervalo_teste}s decorridos)...")
                await self._disparar_evento_hype("MODO_TESTE_AUTOMATICO")
                await asyncio.sleep(self.intervalo_teste)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Erro no loop do modo de teste: {e}")
                await asyncio.sleep(10)

    async def _varredura_periodica_conteudo(self) -> None:
        """
        A cada X minutos (ex: 4min), caso nenhum pico tenha ocorrido,
        submete os últimos 45s para o Gemini verificar se houve assunto ou opinião sobre GTA 6
        mesmo que dita em tom calmo ou sem gritos.
        """
        logger.info(f"Radar Inteligente de Notícias: amostragem ativa a cada {self.intervalo_varredura_segundos // 60} minutos.")
        while self.rodando:
            try:
                await asyncio.sleep(45)
                tempo_desde_ultimo = time.time() - self.ultimo_corte_timestamp
                if tempo_desde_ultimo >= self.intervalo_varredura_segundos:
                    logger.info("📡 Varredura Periódica Ativa: analisando trecho recente em busca de novidades/opiniões sobre GTA 6...")
                    await self._disparar_evento_hype("VARREDURA_GTA6_NOTICIAS")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Erro na varredura periódica: {e}")

    async def _monitorar_audio_rms(self) -> None:
        """
        Extrai stream PCM 16kHz mono via FFmpeg stdout e calcula RMS a cada segundo.
        Usa -threads 2 e formato cru para zero overhead de CPU e consumo mínimo de RAM.
        """
        logger.info("Monitor de áudio RMS iniciado (16kHz mono PCM).")
        taxa_amostragem = 16000
        bytes_por_segundo = taxa_amostragem * 2  # 16-bit = 2 bytes por amostra

        fonte_audio = self.audio_url or self.stream_url
        cmd = [
            obter_caminho_ffmpeg(),
            "-loglevel", "quiet",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", fonte_audio,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(taxa_amostragem),
            "-ac", "1",
            "-threads", "2",
            "-f", "s16le",
            "-"
        ]

        while self.rodando:
            try:
                self.processo_audio_ffmpeg = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW
                )

                while self.rodando:
                    bloco = await self.processo_audio_ffmpeg.stdout.read(bytes_por_segundo)
                    if not bloco:
                        logger.warning("Stream de áudio pausou ou reconectando...")
                        await asyncio.sleep(2)
                        break

                    amostras = np.frombuffer(bloco, dtype=np.int16)
                    if len(amostras) == 0:
                        continue

                    # Cálculo do RMS (Root Mean Square)
                    rms = float(np.sqrt(np.mean(amostras.astype(np.float64) ** 2)))

                    if len(self.historico_rms) >= 10:
                        media_movel = float(np.mean(self.historico_rms))
                        if media_movel > 0:
                            fator = rms / media_movel
                            if fator >= self.limiar_multiplicador_rms and rms >= self.piso_ruido_minimo_rms:
                                logger.info(
                                    f"🔥 PICO DE ÁUDIO DETECTADO! RMS: {rms:.1f} | Média: {media_movel:.1f} "
                                    f"({fator:.1f}x acima da média)"
                                )
                                await self._disparar_evento_hype("PICO_AUDIO_RMS")

                    self.historico_rms.append(rms)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Erro momentâneo na leitura de áudio: {e}. Reconectando em 3s...")
                await asyncio.sleep(3)

    async def _obter_chatroom_id_kick(self) -> Optional[int]:
        """Tenta consultar o chatroom_id da Kick via API pública."""
        url = f"https://kick.com/api/v2/channels/{self.slug}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        try:
            timeout = aiohttp.ClientTimeout(total=4)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        dados = await resp.json()
                        chatroom = dados.get("chatroom", {})
                        cid = chatroom.get("id")
                        if cid:
                            return int(cid)
        except Exception:
            pass
        return None

    async def _obter_token_centrifugo(self) -> Optional[str]:
        """Obtém o token JWT de conexão ao Centrifugo da Kick."""
        client_id = str(uuid.uuid4())
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        payload = {"client_id": client_id}
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(KICK_AUTH_URL, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        dados = await resp.json()
                        token = dados.get("data", {}).get("token")
                        if token:
                            return token
        except Exception as e:
            logger.debug(f"Falha ao obter token Centrifugo: {e}")
        return None

    async def _monitorar_chat_kick(self) -> None:
        """
        Conecta ao WebSocket Centrifugo do chat da Kick em tempo real.
        Monitora palavras-gatilho virais e frequência de mensagens no chat.
        Totalmente resiliente a desconexões momentâneas.
        """
        self.chatroom_id = await self._obter_chatroom_id_kick()
        if not self.chatroom_id:
            logger.warning(
                f"[Aviso Amigável] Chatroom ID indisponível para '{self.slug}'. "
                "Radar operando via áudio RMS sem interrupções."
            )
            return

        canal_centrifugo = f"chatrooms.{self.chatroom_id}.v2"
        tentativas_falhas = 0

        while self.rodando:
            try:
                # 1. Obtém o token JWT de autenticação do Centrifugo
                token = await self._obter_token_centrifugo()
                if not token:
                    tentativas_falhas += 1
                    if tentativas_falhas >= 3:
                        logger.warning("Não foi possível autenticar no chat da Kick. Operando via áudio RMS.")
                        return
                    await asyncio.sleep(5)
                    continue

                logger.info(f"Conectando ao chat Centrifugo da Kick ({canal_centrifugo})...")

                async with websockets.connect(KICK_REALTIME_WS, ping_interval=25, ping_timeout=20) as ws:
                    # 2. Envia comando de conexão Centrifugo
                    connect_cmd = {"id": 1, "connect": {"token": token}}
                    await ws.send(json.dumps(connect_cmd))
                    resp_connect = await ws.recv()

                    # 3. Envia inscrição no canal do chatroom
                    sub_cmd = {"id": 2, "subscribe": {"channel": canal_centrifugo}}
                    await ws.send(json.dumps(sub_cmd))
                    await ws.recv()

                    logger.info(f"✅ Conectado com sucesso ao chat da Kick ({self.nome})!")
                    tentativas_falhas = 0

                    async for mensagem_crua in ws:
                        if not self.rodando:
                            break

                        try:
                            # Heartbeat vazio do Centrifugo
                            if not mensagem_crua or mensagem_crua == "{}":
                                await ws.send("{}")
                                continue

                            evento = json.loads(mensagem_crua)

                            # Mensagens transmitidas no canal vêm dentro de push -> pub -> data
                            push = evento.get("push", {})
                            pub = push.get("pub", {})
                            data_bloco = pub.get("data", {})

                            if isinstance(data_bloco, dict):
                                evento_tipo = data_bloco.get("event")
                                payload_cru = data_bloco.get("data", "{}")
                            else:
                                continue

                            if evento_tipo == "App\\Events\\ChatMessageEvent":
                                payload = json.loads(payload_cru) if isinstance(payload_cru, str) else payload_cru
                                conteudo = payload.get("content", "").strip()
                                sender = payload.get("sender", {}).get("username", "user")

                                if conteudo:
                                    await self._processar_mensagem_chat(sender, conteudo)

                        except json.JSONDecodeError:
                            continue

            except asyncio.CancelledError:
                break
            except Exception as e:
                tentativas_falhas += 1
                logger.debug(f"Desconexão do chat da Kick: {e}. Reconectando em 10s...")
                await asyncio.sleep(10)

    async def _monitorar_chat_twitch(self) -> None:
        """
        Conecta ao chat público da Twitch via IRC WebSocket anônimo (justinfan).
        Não exige login, token ou chave de API, e alimenta exatamente as mesmas
        3 camadas de detecção (GTA VI, reações e explosão de velocidade do chat).
        """
        canal = self.slug.lower().lstrip("#").strip()
        if not canal:
            logger.warning("Slug do canal da Twitch vazio. Operando via áudio RMS.")
            return

        nick_anonimo = f"justinfan{int(time.time()) % 90000 + 10000}"

        while self.rodando:
            try:
                logger.info(f"Conectando ao chat IRC WebSocket da Twitch (#{canal})...")
                async with websockets.connect(TWITCH_IRC_WS, ping_interval=30, ping_timeout=20) as ws:
                    await ws.send("PASS SCHMOOPIIE")
                    await ws.send(f"NICK {nick_anonimo}")
                    await ws.send(f"JOIN #{canal}")

                    logger.info(f"✅ Conectado com sucesso ao chat da Twitch ({self.nome})!")

                    async for pacote_cru in ws:
                        if not self.rodando:
                            break

                        # Pacotes IRC podem trazer múltiplas linhas separadas por \r\n
                        for linha in str(pacote_cru).splitlines():
                            linha = linha.strip()
                            if not linha:
                                continue

                            # Responde PING da Twitch para manter conexão viva indefinidamente
                            if linha.startswith("PING"):
                                resposta_pong = linha.replace("PING", "PONG", 1)
                                await ws.send(resposta_pong)
                                continue

                            # Formato padrão: :usuario!usuario@usuario.tmi.twitch.tv PRIVMSG #canal :mensagem
                            if " PRIVMSG #" in linha:
                                try:
                                    prefixo, resto = linha.split(" PRIVMSG #", 1)
                                    sender = prefixo.lstrip(":").split("!", 1)[0] or "viewer"
                                    if " :" in resto:
                                        conteudo = resto.split(" :", 1)[1].strip()
                                        if conteudo:
                                            await self._processar_mensagem_chat(sender, conteudo)
                                except Exception:
                                    continue

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Desconexão do chat da Twitch: {e}. Reconectando em 8s...")
                await asyncio.sleep(8)

    async def _monitorar_chat_youtube(self) -> None:
        """
        Conecta ao chat ao vivo do YouTube via endpoint público InnerTube (get_live_chat),
        sem precisar de chave de API nem login, alimentando todas as 3 camadas de detecção.
        """
        url_canal = str(self.streamer_info.get("url_live") or self.streamer_info.get("url", "")).strip()
        if not url_canal:
            logger.warning("URL do YouTube ausente para leitura de chat. Operando via áudio RMS.")
            return

        # Se for canal (sem watch?v=), resolve primeiro para a URL exata do vídeo ao vivo
        if "watch?v=" not in url_canal and "youtu.be/" not in url_canal:
            try:
                from agentes.vigia_stream import VigiaStream
                vigia_aux = VigiaStream()
                url_resolvida = await vigia_aux.resolver_video_ao_vivo_youtube(url_canal)
                if url_resolvida:
                    url_canal = url_resolvida
            except Exception:
                pass

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8"
        }

        while self.rodando:
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                    logger.info(f"Conectando ao chat ao vivo do YouTube ({self.nome})...")
                    async with session.get(url_canal) as resp:
                        html = await resp.text()

                    m_key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html)
                    m_cont = re.search(r'"liveChatRenderer".*?"continuation":"([^"]+)"', html)

                    if not m_cont:
                        m_vid = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                        if m_vid:
                            popout_url = f"https://www.youtube.com/live_chat?is_popout=1&v={m_vid.group(1)}"
                            async with session.get(popout_url) as r2:
                                html2 = await r2.text()
                            m_cont = re.search(r'"continuation":"([^"]+)"', html2)
                            if not m_key:
                                m_key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html2)

                    if not m_key or not m_cont:
                        logger.warning(
                            f"[Aviso Amigável] Chat ao vivo do YouTube indisponível para '{self.nome}'. "
                            "Radar operando via áudio RMS sem interrupções."
                        )
                        await asyncio.sleep(30)
                        continue

                    api_key = m_key.group(1)
                    continuation = m_cont.group(1)
                    api_url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}"

                    logger.info(f"✅ Conectado com sucesso ao chat do YouTube ({self.nome})!")

                    while self.rodando and continuation:
                        payload = {
                            "context": {
                                "client": {
                                    "clientName": "WEB",
                                    "clientVersion": "2.20260101.00.00"
                                }
                            },
                            "continuation": continuation
                        }
                        async with session.post(api_url, json=payload) as r3:
                            if r3.status != 200:
                                break
                            dados = await r3.json()

                        chat_cont = dados.get("continuationContents", {}).get("liveChatContinuation", {})
                        acoes = chat_cont.get("actions", [])
                        for acao in acoes:
                            if not self.rodando:
                                break
                            item = acao.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
                            if not item:
                                continue
                            autor = item.get("authorName", {}).get("simpleText", "viewer")
                            runs = item.get("message", {}).get("runs", [])
                            conteudo = "".join(r.get("text", "") for r in runs).strip()
                            if conteudo:
                                await self._processar_mensagem_chat(autor, conteudo)

                        # Próximo token de continuação e intervalo recomendado pelo YouTube
                        prox_cont = None
                        espera_ms = 2000
                        for c in chat_cont.get("continuations", []):
                            for chave in ("invalidationContinuationData", "timedContinuationData"):
                                bloco = c.get(chave)
                                if bloco and bloco.get("continuation"):
                                    prox_cont = bloco["continuation"]
                                    espera_ms = int(bloco.get("timeoutMs", 2000))
                                    break
                            if prox_cont:
                                break

                        continuation = prox_cont
                        await asyncio.sleep(max(1.0, min(5.0, espera_ms / 1000.0)))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Desconexão do chat do YouTube: {e}. Reconectando em 10s...")
                await asyncio.sleep(10)

    async def _processar_mensagem_chat(
        self,
        sender: str,
        conteudo: str,
        agora: Optional[float] = None
    ) -> Optional[str]:
        """
        Analisa cada mensagem recebida do chat usando 3 camadas de detecção:
        1. Assunto prioritário GTA VI (2 menções em 15s)
        2. Palavras-gatilho de reação/caos (3 menções em 10s)
        3. Explosão de velocidade do chat (volume >= 12 msgs em 5s e >= 2.5x acima da média)
        """
        agora = agora if agora is not None else time.time()
        msg_formatada = f"{sender}: {conteudo}"
        self.mensagens_recentes.append(msg_formatada)
        texto_upper = conteudo.upper()

        # Atualiza métricas de velocidade geral do chat (janelas de 5s)
        self.timestamps_chat_geral.append(agora)
        if (agora - self._ultimo_marco_velocidade) >= 5.0:
            self.historico_velocidade_chat.append(self._contador_janela_velocidade)
            self._contador_janela_velocidade = 1
            self._ultimo_marco_velocidade = agora
        else:
            self._contador_janela_velocidade += 1

        # 1. Prioridade Máxima: Gatilho de assunto/momento GTA VI (basta 2 menções em 15s)
        tem_gta6 = any(palavra in texto_upper for palavra in self.gatilhos_especificos_gta6)
        if tem_gta6:
            self.contagem_gta6_recentes.append(agora)
            gta6_recentes = [t for t in self.contagem_gta6_recentes if (agora - t) <= 15.0]
            if len(gta6_recentes) >= 2:
                logger.info(
                    f"🎯 ASSUNTO GTA 6 NO CHAT! ({len(gta6_recentes)} menções em 15s): '{conteudo}'"
                )
                await self._disparar_evento_hype("ASSUNTO_GTA6_CHAT")
                return "ASSUNTO_GTA6_CHAT"

        # 2. Gatilho de Reações Gerais (risadas, sustos, clipa - 3 menções em 10s)
        tem_gatilho = any(palavra in texto_upper for palavra in self.palavras_gatilho)
        if tem_gatilho:
            self.contagem_gatilhos_recentes.append(agora)
            gatilhos_recentes = [
                t for t in self.contagem_gatilhos_recentes
                if (agora - t) <= 10.0
            ]
            if len(gatilhos_recentes) >= 3:
                logger.info(
                    f"💬 REAÇÃO NO CHAT DETECTADA! ({len(gatilhos_recentes)} gatilhos em 10s): '{conteudo}'"
                )
                await self._disparar_evento_hype("PICO_CHAT_KICK")
                return "PICO_CHAT_KICK"

        # 3. Gatilho de Explosão de Velocidade do Chat (captura '????', '😱😱', 'W', 'F' e emotes)
        if len(self.historico_velocidade_chat) >= 3:
            msgs_ultimos_5s = sum(1 for t in self.timestamps_chat_geral if (agora - t) <= 5.0)
            media_5s = max(2.0, sum(self.historico_velocidade_chat) / len(self.historico_velocidade_chat))
            if msgs_ultimos_5s >= 12 and msgs_ultimos_5s >= (media_5s * 2.5):
                fator_vel = msgs_ultimos_5s / media_5s
                logger.info(
                    f"⚡ EXPLOSÃO NO CHAT! {msgs_ultimos_5s} msgs em 5s "
                    f"({fator_vel:.1f}x acima da média de {media_5s:.1f})"
                )
                await self._disparar_evento_hype("EXPLOSAO_VELOCIDADE_CHAT")
                return "EXPLOSAO_VELOCIDADE_CHAT"

        return None

    async def _disparar_evento_hype(self, origem: str) -> None:
        """
        Aplica cooldown entre cortes e agenda a execução da curadoria
        após 'segundos_depois_do_pico' para captura da reação completa.
        """
        agora = time.time()
        tempo_desde_ultimo = agora - self.ultimo_corte_timestamp

        if tempo_desde_ultimo < self.cooldown_segundos:
            logger.debug(
                f"Pico detectado ({origem}), mas em cooldown "
                f"({tempo_desde_ultimo:.0f}s / {self.cooldown_segundos}s)."
            )
            return

        # Registra timestamp do corte
        self.ultimo_corte_timestamp = agora
        logger.info(
            f"🎉 HYPE CONFIRMADO [{origem}]! Aguardando {self.segundos_depois_pico}s "
            "para capturar reação completa do streamer no buffer..."
        )

        # Aguarda a reação pós-pico terminar de entrar no buffer
        await asyncio.sleep(self.segundos_depois_pico)

        if self.on_hype_callback:
            contexto = {
                "origem": origem,
                "timestamp_pico": agora,
                "mensagens_chat": list(self.mensagens_recentes)
            }
            if asyncio.iscoroutinefunction(self.on_hype_callback):
                await self.on_hype_callback(contexto)
            else:
                self.on_hype_callback(contexto)

    async def parar(self) -> None:
        """Para todos os monitores e finaliza processos."""
        self.rodando = False
        for tarefa in self.tarefas:
            if not tarefa.done():
                tarefa.cancel()

        if self.processo_audio_ffmpeg:
            try:
                self.processo_audio_ffmpeg.terminate()
            except Exception:
                pass
            self.processo_audio_ffmpeg = None
        logger.info("Radar de Hype finalizado.")
