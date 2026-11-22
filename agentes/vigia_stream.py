"""
Módulo VigiaStream - GTA6_ClipHunter
Responsável por verificar o status dos streamers na Kick por ordem de prioridade
e gerenciar o processo contínuo de gravação do stream em segmentos leves .ts
com buffer circular e controle rígido de espaço em disco SSD.
"""

import os
import re
import sys
import time
import json
import shutil
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

import aiohttp

logger = logging.getLogger("ClipHunter.VigiaStream")

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


PRESETS_WEBCAM = {
    "inferior_esquerdo": {"ativo": True, "x": 20, "y": 640, "w": 600, "h": 400},
    "inferior_direito": {"ativo": True, "x": 1240, "y": 640, "w": 640, "h": 400},
    "centro_direito": {"ativo": True, "x": 1490, "y": 272, "w": 422, "h": 263},
    "centro_esquerdo": {"ativo": True, "x": 20, "y": 272, "w": 422, "h": 263},
    "superior_esquerdo": {"ativo": True, "x": 20, "y": 20, "w": 600, "h": 400},
    "superior_direito": {"ativo": True, "x": 1240, "y": 20, "w": 640, "h": 400},
    "desativado": {"ativo": False, "x": 0, "y": 0, "w": 0, "h": 0}
}


class VigiaStream:
    def __init__(
        self,
        config_path: str = "config/streamers.json",
        buffer_dir: str = "buffer_temp",
        posicao_webcam: str = "inferior_esquerdo"
    ):
        self.config_path = Path(config_path)
        self.buffer_dir = Path(buffer_dir)
        self.posicao_webcam = posicao_webcam
        self.config: Dict[str, Any] = {}
        self.streamers: List[Dict[str, Any]] = []
        self.streamer_ativo: Optional[Dict[str, Any]] = None
        self.stream_url_ativa: Optional[str] = None
        self.audio_url_ativa: Optional[str] = None
        self.url_live_resolvida: Optional[str] = None
        self.processo_ffmpeg: Optional[asyncio.subprocess.Process] = None
        self.tarefa_limpeza: Optional[asyncio.Task] = None
        self.rodando: bool = False

        self.carregar_configuracao()
        self.buffer_dir.mkdir(parents=True, exist_ok=True)

    def carregar_configuracao(self) -> None:
        """Carrega e valida o arquivo de configuração de streamers."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.streamers = sorted(
            self.config.get("streamers", []),
            key=lambda x: x.get("prioridade", 999)
        )

        # Aplica a preferência de webcam para todos os streamers configurados
        for s in self.streamers:
            if self.posicao_webcam == "desativado":
                s["webcam_crop"] = {"ativo": False, "x": 0, "y": 0, "w": 0, "h": 0}
            elif self.posicao_webcam in PRESETS_WEBCAM and self.posicao_webcam != "auto":
                s["webcam_crop"] = dict(PRESETS_WEBCAM[self.posicao_webcam])

        self.config_geral = self.config.get("configuracoes_gerais", {})
        self.limite_disco_mb = self.config_geral.get("limite_disco_buffer_mb", 400)
        self.tempo_max_buffer_segundos = self.config_geral.get("buffer_tempo_maximo_minutos", 4) * 60
        self.segment_time = self.config_geral.get("segmento_tempo_segundos", 30)

        logger.info(
            f"Configuração carregada: {len(self.streamers)} streamers na lista de prioridade. "
            f"Limite de buffer: {self.limite_disco_mb}MB / {self.tempo_max_buffer_segundos}s | Webcam: {self.posicao_webcam}."
        )

    def definir_streamer_alvo(self, alvo: str, posicao_webcam: Optional[str] = None) -> None:
        """
        Permite testar e rodar o caçador em QUALQUER live avulsa sob demanda
        (ex: 'xqc', 'https://kick.com/xqc' ou qualquer streamer).
        Preserva ou aplica a configuração de webcam selecionada.
        """
        if posicao_webcam:
            self.posicao_webcam = posicao_webcam

        alvo_limpo = alvo.strip()
        alvo_lower = alvo_limpo.lower()

        # Tratamento inteligente para links do YouTube (watch?v=, youtu.be, /@canal, /channel/UC...)
        if "youtube.com" in alvo_lower or "youtu.be" in alvo_lower:
            url_completa = alvo_limpo.rstrip("/")
            if "v=" in alvo_limpo:
                vid_id = alvo_limpo.split("v=", 1)[1].split("&", 1)[0]
                slug = f"yt_{vid_id}"
                nome = f"YouTube ({vid_id})"
            elif "/@" in alvo_limpo:
                handle = alvo_limpo.split("/@", 1)[1].split("/", 1)[0].strip()
                slug = handle.lower()
                nome = handle
            elif "/channel/" in alvo_limpo:
                ch_id = alvo_limpo.split("/channel/", 1)[1].split("/", 1)[0].strip()
                slug = ch_id.lower()
                nome = f"YouTube ({ch_id[:8]})"
            else:
                slug = alvo_limpo.rstrip("/").split("/")[-1].split("?")[0].lower()
                nome = f"YouTube ({slug})"
        else:
            slug = alvo_limpo.rstrip("/").split("/")[-1].lower() if ("/" in alvo_limpo) else alvo_limpo.lower()
            url_completa = alvo_limpo if alvo_limpo.startswith("http") else f"https://kick.com/{slug}"
            nome = slug.upper()

        if self.posicao_webcam == "desativado":
            crop_config = {"ativo": False, "x": 0, "y": 0, "w": 0, "h": 0}
        elif self.posicao_webcam in PRESETS_WEBCAM and self.posicao_webcam != "auto":
            crop_config = dict(PRESETS_WEBCAM[self.posicao_webcam])
        else:
            crop_config = dict(PRESETS_WEBCAM["inferior_esquerdo"])

        # Procura se o streamer já existe na configuração salva
        streamer_cadastrado = next(
            (s for s in self.config.get("streamers", []) if s.get("slug") == slug),
            None
        )

        if streamer_cadastrado:
            streamer_custom = dict(streamer_cadastrado)
            # No modo 'auto', preserva o crop já calibrado do streamer em streamers.json
            if self.posicao_webcam != "auto" or not streamer_custom.get("webcam_crop"):
                streamer_custom["webcam_crop"] = dict(crop_config)
            if alvo_limpo.startswith("http"):
                streamer_custom["url"] = url_completa
        else:
            streamer_custom = {
                "prioridade": 1,
                "nome": nome,
                "slug": slug,
                "url": url_completa,
                "hashtags": f"#{slug} #gta6 #gtavi #gta6gameplay #vicecity #leonida #gta6brasil #nericlipes #shorts",
                "palavras_gatilho_chat": [
                    "GTA6", "GTA 6", "GTAVI", "GTA VI", "VICE CITY", "LEONIDA", "LUCIA", "JASON",
                    "DETALHE", "FISICA", "FÍSICA", "REALISMO", "REALISTA", "GRAFICO", "GRÁFICO",
                    "NPC", "CINEMA", "OBRA PRIMA", "GOTY", "SURREAL", "ABSURDO", "BUG", "BUGOU",
                    "EXPLODIU", "CAPOTOU", "POLICIA", "POLÍCIA", "FUGA", "MORREU", "CAOS",
                    "CLIP", "CLIPA", "SALVA", "CARALHO", "TAPORRA", "CARACA", "MEU DEUS", "MDS",
                    "QUE ISSO", "QUE JOGO", "BIZARRO", "LOUCURA", "KKKKK", "KAKAKA", "HAHAHA",
                    "OLHA ISSO", "MANO", "SOCORRO", "LMAO", "LOL", "WTF", "POG", "OMEGALUL", "GG"
                ],
                "webcam_crop": dict(crop_config)
            }

        self.streamers = [streamer_custom]
        status_webcam = f"Ativa ({self.posicao_webcam})" if streamer_custom["webcam_crop"].get("ativo") else "Desativada"
        logger.info(f"🎯 Canal configurado: '{streamer_custom['nome']}' ({streamer_custom['url']}) | Webcam: {status_webcam}")

    async def verificar_streamer_kick_api(self, slug: str) -> Optional[str]:
        """
        Tenta consultar a API pública da Kick para checar se o streamer está ao vivo
        e obter a URL HLS (.m3u8). Se bloqueado por Cloudflare, retorna None.
        """
        url_api = f"https://kick.com/api/v2/channels/{slug}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url_api, headers=headers) as resp:
                    if resp.status == 200:
                        dados = await resp.json()
                        livestream = dados.get("livestream")
                        if livestream and livestream.get("is_live", False):
                            playback_url = dados.get("playback_url")
                            if playback_url:
                                return playback_url
        except Exception as e:
            logger.debug(f"API Kick direta indisponível para {slug} ({e}). Usando yt-dlp como fallback.")
        return None

    async def resolver_video_ao_vivo_youtube(self, url_canal: str) -> Optional[str]:
        """
        Se url_canal for um canal do YouTube (/@canal, /channel/UC..., ou /live),
        varre os itens recentes usando yt-dlp para identificar o ID exato da transmissão ao vivo ativa.
        Isso contorna a limitação do YouTube onde o endpoint direto /live retorna 'The channel is not currently live'.
        """
        if "watch?v=" in url_canal or "youtu.be/" in url_canal:
            return url_canal

        canal_limpo = re.sub(r"/(live|streams)/?$", "", url_canal.strip())
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--dump-json",
            "--flat-playlist",
            "--playlist-end", "5",
            "--no-warnings",
            "--socket-timeout", "8",
            canal_limpo
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            if proc.returncode == 0:
                for linha in stdout.decode(errors="ignore").splitlines():
                    if not linha.strip():
                        continue
                    try:
                        dados = json.loads(linha)
                        if dados.get("is_live") or dados.get("live_status") == "is_live":
                            vid_id = dados.get("id")
                            if vid_id:
                                return f"https://www.youtube.com/watch?v={vid_id}"
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Aviso ao resolver live na raiz do YouTube {canal_limpo}: {e}")
        return None

    async def obter_stream_url_ytdlp(self, slug_ou_url: str) -> Optional[str]:
        """
        Usa yt-dlp de forma assíncrona para extrair a URL HLS direta (.m3u8) da live (Kick, YouTube, Twitch, etc.).
        Em lives do YouTube com vídeo e áudio separados, captura ambos (stream_url_ativa + audio_url_ativa).
        """
        url_canal = slug_ou_url if slug_ou_url.startswith("http") else f"https://kick.com/{slug_ou_url}"
        eh_youtube = "youtube.com" in url_canal.lower() or "youtu.be" in url_canal.lower()

        if eh_youtube:
            # Se for canal do YouTube (sem watch?v=), resolve primeiro a live ativa
            if "watch?v=" not in url_canal and "youtu.be/" not in url_canal:
                url_resolvida = await self.resolver_video_ao_vivo_youtube(url_canal)
                if url_resolvida:
                    logger.info(f"🔴 Live do YouTube identificada: {url_resolvida}")
                    url_canal = url_resolvida
                    self.url_live_resolvida = url_resolvida

        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--get-url",
            "--no-playlist",
            "--no-warnings",
            "--socket-timeout", "10",
        ]
        if eh_youtube:
            # YouTube Live entrega vídeo 1080p60 e áudio separados em HLS (.m3u8)
            cmd.extend(["-f", "bv[height<=1080][protocol*=m3u8]+ba[protocol*=m3u8]/b[height<=1080]/best"])
        cmd.append(url_canal)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25.0)

            if proc.returncode == 0:
                linhas = [l.strip() for l in stdout.decode(errors="ignore").splitlines() if l.strip()]
                if linhas and (".m3u8" in linhas[0] or "http" in linhas[0]):
                    self.audio_url_ativa = linhas[1] if len(linhas) >= 2 and linhas[1].startswith("http") else None
                    if self.audio_url_ativa:
                        logger.info("🔊 Fluxos separados de vídeo + áudio detectados (YouTube Live HLS).")
                    return linhas[0]
            else:
                logger.debug(f"yt-dlp indicou canal offline ou erro para {slug_ou_url}: {stderr.decode(errors='ignore').strip()[:120]}")
        except asyncio.TimeoutError:
            logger.debug(f"Timeout ao tentar extrair URL do canal {slug_ou_url} via yt-dlp.")
        except Exception as e:
            logger.error(f"Erro ao executar yt-dlp para {slug_ou_url}: {e}")
        return None

    async def encontrar_streamer_online(self) -> Optional[Dict[str, Any]]:
        """
        Varre os streamers por ordem de prioridade e retorna o primeiro que estiver ao vivo,
        junto da sua URL de stream (.m3u8).
        """
        for streamer in self.streamers:
            slug = streamer["slug"]
            nome = streamer["nome"]
            alvo = streamer.get("url", slug)
            logger.info(f"Verificando status de {nome} ({alvo})...")

            # 1. Tenta API direta apenas se for canal da Kick
            self.audio_url_ativa = None
            alvo_lower = str(alvo).lower()
            eh_kick = ("kick.com" in alvo_lower) or (not alvo_lower.startswith("http"))
            stream_url = await self.verificar_streamer_kick_api(slug) if eh_kick else None

            # 2. Fallback / Extrator universal via yt-dlp (Twitch, Kick, YouTube, etc.)
            if not stream_url:
                stream_url = await self.obter_stream_url_ytdlp(alvo)

            if stream_url:
                logger.info(f"🎯 Streamer AO VIVO encontrado: {nome}! Stream URL obtida com sucesso.")
                if self.url_live_resolvida:
                    streamer["url_live"] = self.url_live_resolvida
                self.streamer_ativo = streamer
                self.stream_url_ativa = stream_url
                return streamer

            logger.info(f"[-] {nome} está offline.")

        logger.warning("Nenhum dos streamers configurados está ao vivo no momento.")
        return None

    def buscar_video_recente_para_calibracao(self, slug_ou_nome: Optional[str] = None) -> Optional[Path]:
        """Localiza o vídeo mais recente na pasta prontos_para_postar (ou postados) para calibração offline."""
        pastas = [Path("prontos_para_postar"), Path("prontos_para_postar/postados")]
        todos_videos = []
        for p in pastas:
            if p.exists():
                todos_videos.extend([f for f in p.glob("*.mp4") if "preview" not in f.name.lower()])
        if not todos_videos:
            return None

        if slug_ou_nome:
            slug_clean = slug_ou_nome.lower().split("/")[-1].replace("https:", "").strip()
            termos = [slug_clean, slug_clean.replace("_yt", ""), "paulinho", "alanzoka", "coringa", "bkinho"]
            for termo in termos:
                if len(termo) >= 3:
                    filtrados = [v for v in todos_videos if termo in v.name.lower()]
                    if filtrados:
                        filtrados.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                        return filtrados[0]

        todos_videos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return todos_videos[0]

    async def detectar_webcam_ia(self, stream_url_ou_slug: str) -> Dict[str, Any]:
        """
        Extrai 1 frame da live (ou de gravação recente caso offline) e consulta o Gemini 3.5 Flash
        para identificar se existe webcam/facecam na tela e em qual canto ela se localiza.
        Totalmente leve (RAM < 10MB, CPU 0%), resposta em ~2 segundos.
        """
        caminho_local = Path(stream_url_ou_slug)
        caminho_frame = self.buffer_dir / f"calib_{int(time.time())}.jpg"
        ffmpeg_cmd = obter_caminho_ffmpeg()

        try:
            if caminho_local.is_file() and caminho_local.suffix.lower() in (".jpg", ".jpeg", ".png"):
                # Já é um frame estático
                shutil.copy(str(caminho_local.resolve()), str(caminho_frame.resolve()))
            elif caminho_local.is_file() and caminho_local.suffix.lower() in (".mp4", ".ts", ".mkv"):
                # É um vídeo local existente
                cmd = [
                    ffmpeg_cmd, "-y", "-ss", "00:00:05",
                    "-i", str(caminho_local.resolve()),
                    "-vframes", "1", "-vf", "scale=1920:1080", "-q:v", "2",
                    str(caminho_frame.resolve())
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
                )
                await asyncio.wait_for(proc.wait(), timeout=10.0)
            else:
                url_stream = stream_url_ou_slug
                if not url_stream.startswith("http") or ".m3u8" not in url_stream:
                    url_resolvida = await self.obter_stream_url_ytdlp(stream_url_ou_slug)
                    if url_resolvida:
                        url_stream = url_resolvida

                if url_stream and url_stream.startswith("http"):
                    cmd = [
                        ffmpeg_cmd, "-y", "-loglevel", "error",
                        "-rw_timeout", "8000000",
                        "-probesize", "2M", "-analyzeduration", "2M",
                        "-i", url_stream,
                        "-vframes", "1",
                        "-vf", "scale=1920:1080",
                        "-q:v", "2",
                        str(caminho_frame.resolve())
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
                    )
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=12.0)
                    except asyncio.TimeoutError:
                        logger.warning("Timeout (12s) ao extrair frame da live HLS. Tentando matar processo...")
                        try:
                            proc.kill()
                        except Exception:
                            pass

            # Fallback inteligente: se não conseguiu frame da live (ex: streamer offline), extrai de vídeo gravado
            if not caminho_frame.exists() or caminho_frame.stat().st_size == 0:
                logger.info("Live offline ou instável. Buscando vídeo gravado recente para autocalibração...")
                video_rec = self.buscar_video_recente_para_calibracao(stream_url_ou_slug)
                if video_rec and video_rec.exists():
                    logger.info(f"Extraindo frame de calibração do vídeo: {video_rec.name}")
                    cmd_v = [
                        ffmpeg_cmd, "-y", "-ss", "00:00:05",
                        "-i", str(video_rec.resolve()),
                        "-vframes", "1", "-vf", "scale=1920:1080", "-q:v", "2",
                        str(caminho_frame.resolve())
                    ]
                    p_v = await asyncio.create_subprocess_exec(
                        *cmd_v, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
                    )
                    await asyncio.wait_for(p_v.wait(), timeout=10.0)

            if not caminho_frame.exists() or caminho_frame.stat().st_size == 0:
                logger.warning("Não foi possível obter imagem da live nem de gravações para calibração da webcam.")
                return {"tem_webcam": False, "posicao": "desativado", "descricao": "Nenhuma imagem disponível para análise."}

            from google import genai
            from google.genai import types

            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key:
                return {"tem_webcam": False, "posicao": "desativado", "descricao": "GEMINI_API_KEY não configurada no .env."}

            client = genai.Client(api_key=api_key)
            with open(caminho_frame, "rb") as f:
                img_bytes = f.read()

            prompt = (
                "Analise esta imagem de 1920x1080 de uma transmissão ao vivo.\n"
                "Existe uma câmera/webcam de streamer (facecam) sobreposta na tela mostrando a pessoa?\n"
                "Se sim:\n"
                "1. Identifique a posição geral onde ela está:\n"
                "   - 'inferior_esquerdo', 'inferior_direito', 'centro_direito', 'centro_esquerdo', 'superior_esquerdo', 'superior_direito' ou 'desativado'\n"
                "   (Use 'centro_direito' ou 'centro_esquerdo' se a webcam estiver na metade vertical lateral, entre 20% e 65% da altura da tela!)\n"
                "2. Identifique a caixa delimitadora EXATA (bounding box) APENAS do retângulo da webcam (excluindo barras de texto/sub abaixo dela) em coordenadas normalizadas [0 a 1000]:\n"
                "   [ymin, xmin, ymax, xmax].\n\n"
                "Retorne estritamente um JSON com:\n"
                "{\n"
                '  "tem_webcam": bool,\n'
                '  "posicao": string,\n'
                '  "box_1000": [ymin, xmin, ymax, xmax],\n'
                '  "descricao": string\n'
                "}"
            )

            res = None
            for mod_tentativa in ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-3.1-flash-lite"]:
                try:
                    res = await asyncio.wait_for(
                        asyncio.to_thread(
                            client.models.generate_content,
                            model=mod_tentativa,
                            contents=[
                                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                                prompt
                            ],
                            config=types.GenerateContentConfig(response_mime_type="application/json")
                        ),
                        timeout=12.0
                    )
                    if res and res.text:
                        break
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout (12s) no modelo {mod_tentativa} durante autocalibração. Tentando próximo...")
                    continue
                except Exception as ex_mod:
                    logger.debug(f"Modelo {mod_tentativa} falhou na autocalibração: {ex_mod}")
                    continue

            if res and res.text:
                texto_limpo = res.text.strip()
                if texto_limpo.startswith("```"):
                    linhas = [l for l in texto_limpo.split("\n") if not l.strip().startswith("```")]
                    texto_limpo = "\n".join(linhas).strip()

                dados = json.loads(texto_limpo)
                if isinstance(dados, list) and len(dados) > 0:
                    dados = dados[0]
                pos = dados.get("posicao", "desativado")
                if pos not in PRESETS_WEBCAM:
                    pos = "desativado"
                dados["posicao"] = pos

                # Se a IA detectou uma caixa delimitadora precisa, converte para pixels reais
                box = dados.get("box_1000")
                if box and len(box) == 4 and dados.get("tem_webcam", True) and pos != "desativado":
                    ymin, xmin, ymax, xmax = [max(0, min(1000, int(v))) for v in box]
                    if xmax > xmin and ymax > ymin:
                        x = int(xmin * 1920 / 1000)
                        y = int(ymin * 1080 / 1000)
                        w = int((xmax - xmin) * 1920 / 1000)
                        h = int((ymax - ymin) * 1080 / 1000)

                        # Garante dimensões seguras sem invadir barras de sub abaixo da webcam
                        w = max(240, min(1920 - x, w))
                        h = max(180, min(1080 - y, h))
                        dados["crop"] = {"ativo": True, "x": x, "y": y, "w": w, "h": h}
                        logger.info(f"🎯 Auto-Calibração IA Precisa: Caixa detectada -> x={x}, y={y}, w={w}, h={h} ({pos})")
                    else:
                        dados["crop"] = dict(PRESETS_WEBCAM.get(pos, PRESETS_WEBCAM["desativado"]))
                else:
                    dados["crop"] = dict(PRESETS_WEBCAM.get(pos, PRESETS_WEBCAM["desativado"]))

                logger.info(f"🎯 Auto-Calibração IA: {dados.get('descricao')} -> Enquadramento adotado: '{pos}'")
                return dados

        except Exception as e:
            from config.logger_config import registrar_erro_detalhado
            registrar_erro_detalhado("VigiaStream.detectar_webcam_ia", f"Erro na autocalibração via IA: {e}", e)
        finally:
            if caminho_frame.exists():
                try:
                    caminho_frame.unlink()
                except Exception:
                    pass

        return {"tem_webcam": False, "posicao": "desativado", "descricao": "Detecção padrão aplicada."}

    async def iniciar_gravacao_buffer(self) -> bool:
        """
        Inicia a gravação contínua do stream em fatias .ts de 30 segundos usando FFmpeg
        com '-c copy' para 0% de uso de CPU e sem carregar o vídeo na memória RAM.
        """
        if not self.stream_url_ativa:
            logger.error("Tentativa de iniciar gravação sem stream URL ativa.")
            return False

        # Garante diretório limpo
        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        padrao_saida = str(self.buffer_dir / "seg_%05d.ts")

        if self.audio_url_ativa:
            # YouTube Live: muxa vídeo HLS + áudio HLS separados em tempo real com 0% CPU (-c copy)
            cmd = [
                obter_caminho_ffmpeg(),
                "-y",
                "-loglevel", "warning",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", self.stream_url_ativa,
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", self.audio_url_ativa,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c", "copy",
                "-f", "segment",
                "-segment_time", str(self.segment_time),
                "-reset_timestamps", "1",
                padrao_saida
            ]
        else:
            cmd = [
                obter_caminho_ffmpeg(),
                "-y",
                "-loglevel", "warning",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", self.stream_url_ativa,
                "-c", "copy",
                "-f", "segment",
                "-segment_time", str(self.segment_time),
                "-reset_timestamps", "1",
                padrao_saida
            ]

        logger.info(f"Iniciando gravação contínua em buffer circular via FFmpeg ({padrao_saida})...")

        try:
            self.processo_ffmpeg = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW
            )
            self.rodando = True
            # Inicia rotina periódica de limpeza de disco
            self.tarefa_limpeza = asyncio.create_task(self._rotina_limpeza_disco())
            return True
        except Exception as e:
            logger.error(f"Falha ao iniciar processo do FFmpeg para gravação do buffer: {e}")
            return False

    async def _rotina_limpeza_disco(self) -> None:
        """
        Rotina em segundo plano que roda a cada 15 segundos.
        Apaga segmentos mais antigos que 'tempo_max_buffer_segundos' (4 minutos)
        ou sempre que a pasta ultrapassar 'limite_disco_mb' (400MB).
        """
        logger.info("Rotina de limpeza de buffer SSD iniciada.")
        while self.rodando:
            try:
                await asyncio.sleep(15)
                self.executar_limpeza()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro na rotina de limpeza de buffer: {e}")

    def executar_limpeza(self) -> None:
        """Executa a verificação e remoção de segmentos velhos de disco."""
        if not self.buffer_dir.exists():
            return

        agora = time.time()
        arquivos_ts = sorted(
            [f for f in self.buffer_dir.glob("seg_*.ts") if f.is_file()],
            key=lambda x: x.stat().st_mtime
        )

        if not arquivos_ts:
            return

        tamanho_total_bytes = sum(f.stat().st_size for f in arquivos_ts)
        tamanho_total_mb = tamanho_total_bytes / (1024 * 1024)

        # Regra 1: Apagar arquivos com mais de 4 minutos (240s)
        # Sempre preservamos pelo menos os últimos 3 segmentos para nunca quebrar uma edição em curso
        arquivos_para_apagar = []
        for f in arquivos_ts[:-3]:
            idade = agora - f.stat().st_mtime
            if idade > self.tempo_max_buffer_segundos:
                arquivos_para_apagar.append(f)

        # Regra 2: Se ainda ultrapassar o limite em MB, apagar os mais velhos
        for f in arquivos_para_apagar:
            try:
                f.unlink(missing_ok=True)
                logger.debug(f"Segmento expirado removido do SSD: {f.name}")
            except Exception as e:
                logger.debug(f"Não foi possível apagar {f.name}: {e}")

        # Recalcula se ainda estourar a cota de disco
        arquivos_restantes = sorted(
            [f for f in self.buffer_dir.glob("seg_*.ts") if f.is_file()],
            key=lambda x: x.stat().st_mtime
        )
        tamanho_total_mb = sum(f.stat().st_size for f in arquivos_restantes) / (1024 * 1024)

        while tamanho_total_mb > self.limite_disco_mb and len(arquivos_restantes) > 3:
            mais_velho = arquivos_restantes.pop(0)
            try:
                mais_velho.unlink(missing_ok=True)
                logger.info(f"Limite de disco ({self.limite_disco_mb}MB) atingido. Segmento removido: {mais_velho.name}")
            except Exception as e:
                logger.debug(f"Erro ao remover {mais_velho.name}: {e}")
            tamanho_total_mb = sum(f.stat().st_size for f in arquivos_restantes) / (1024 * 1024)

    def obter_segmentos_recentes(self, quantidade: int = 3) -> List[Path]:
        """
        Retorna os N segmentos mais recentes gravados no buffer.
        Normalmente os últimos 2 a 3 segmentos de 30s cobrem 60 a 90 segundos.
        """
        arquivos_ts = sorted(
            [f for f in self.buffer_dir.glob("seg_*.ts") if f.is_file() and f.stat().st_size > 1024],
            key=lambda x: x.stat().st_mtime
        )
        return arquivos_ts[-quantidade:] if len(arquivos_ts) >= quantidade else arquivos_ts

    async def parar(self) -> None:
        """Encerra a gravação e cancela a tarefa de limpeza com segurança."""
        self.rodando = False
        if self.tarefa_limpeza and not self.tarefa_limpeza.done():
            self.tarefa_limpeza.cancel()
            try:
                await self.tarefa_limpeza
            except asyncio.CancelledError:
                pass

        if self.processo_ffmpeg:
            logger.info("Encerrando processo de gravação do FFmpeg...")
            try:
                self.processo_ffmpeg.terminate()
                await asyncio.wait_for(self.processo_ffmpeg.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.processo_ffmpeg.kill()
                except Exception:
                    pass
            self.processo_ffmpeg = None
            logger.info("Processo FFmpeg finalizado.")
