"""
Módulo AgenteEditor - GTA6_ClipHunter
Responsável pela edição automatizada e renderização dos Shorts verticais (1080x1920) 9:16.
Aplica recorte da webcam no topo (1080x672) e gameplay na base (1080x1248).
Cumpre estritamente as regras de hardware: '-preset ultrafast -threads 2' para evitar travamentos de CPU.
Gera o vídeo final .mp4 e o arquivo de metadados .txt para publicação imediata.
"""

import os
import re
import sys
import shutil
import time
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger("ClipHunter.AgenteEditor")

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Rede de segurança para autocensura leve nas legendas (proteção TikTok / YouTube / Reels)
# Mascara apenas uma vogal (ex.: FUZIL -> F*ZIL, MATA -> M*TA, PORRA -> P*RRA) mantendo leitura natural.
REGEX_PALAVRAS_SENSIVEIS = re.compile(
    r"\b("
    r"FUZ(?:IL|IS)|PISTOL(?:A|AS)|ARM(?:A|AS)|REV[OÓ]LVER(?:ES)?|RIFLE(?:S)?|"
    r"SNIPER(?:S)?|ESCOPET(?:A|AS)|ESPINGARD(?:A|AS)|METRALHADOR(?:A|AS)|GLOCK|AK-?47|"
    r"GRANAD(?:A|AS)|BOMB(?:A|AS)|"
    r"TIRO(?:S)?|TIROTEIO(?:S)?|ATIR(?:A|AR|EI|OU|ANDO|AM)|BAL(?:A|AS)|"
    r"MAT(?:A|AR|EI|OU|AM|ANDO|ARAM|AVA|EM)|MORR(?:E|ER|EU|ENDO|ERAM|AM)|MORT(?:E|O|A|OS|AS)|"
    r"SANGUE|CAD[AÁ]VER(?:ES)?|ASSASSIN(?:O|A|ATO|AR)|HOMIC[IÍ]DIO|SUIC[IÍ]DIO|"
    r"SEQUESTR(?:O|AR|OU|ANDO)|ASSALT(?:O|AR|OU|ANDO|ANTE)|"
    r"DROG(?:A|AS)|MACONH(?:A|EIRO)|COCA[IÍ]NA|TR[AÁ]FICO|"
    r"CARALH(?:O|OS|A)|PORR(?:A|AS|ADA)|PUT(?:A|AS|O|OS|ARIA|EIRO)|"
    r"MERD(?:A|AS)|FOD(?:A|E|EU|ER|IDO|IDA|ENDO|ASE)|FUD(?:EU|ER|IDO|IDA|ENDO)|"
    r"CUZ[AÃ]O|ARROMBAD(?:O|A|OS|AS)|DESGRA[CÇ](?:A|ADO|ADA)|"
    r"VAGABUND(?:O|A|OS|AS)|BUCET(?:A|AS)|PIROC(?:A|AS)"
    r")\b",
    re.IGNORECASE,
)


def censurar_texto_legenda(texto: str) -> str:
    """Aplica autocensura leve (substitui 1 vogal por '*') em palavras sensíveis na legenda."""
    def _mascarar(match: re.Match) -> str:
        palavra = match.group(0)
        vogais = "AEIOUÁÉÍÓÚÂÊÎÔÛÃÕaeiouáéíóúâêîôûãõ"
        for idx in range(1, len(palavra)):
            if palavra[idx] in vogais:
                return palavra[:idx] + "*" + palavra[idx + 1:]
        if len(palavra) > 1:
            return palavra[0] + "*" + palavra[2:]
        return "*"

    return REGEX_PALAVRAS_SENSIVEIS.sub(_mascarar, texto)


def sanitizar_nome_arquivo(texto: str, max_len: int = 45) -> str:
    """
    Limpa um título/texto para gerar nome de arquivo seguro e legível no Windows Explorer.
    Remove hashtags, emojis e caracteres proibidos, mantendo acentos e leitura clara.
    """
    if not texto:
        return "Corte_GTA6"

    # Remove hashtags (#Shorts, #GTA6, etc.)
    limpo = re.sub(r"#\S+", "", str(texto))
    # Mantém apenas letras (incluindo acentuadas), números, espaços e hífens
    limpo = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ\s\-]", "", limpo)
    # Colapsa espaços repetidos e limpa bordas
    limpo = re.sub(r"\s+", " ", limpo).strip(" -")

    if not limpo:
        return "Corte_GTA6"

    # Se vier tudo em MAIÚSCULAS da IA, converte para formato mais legível
    if limpo.isupper():
        limpo = limpo.title()

    if len(limpo) > max_len:
        limpo = limpo[:max_len].rsplit(" ", 1)[0].strip(" -") or limpo[:max_len].strip(" -")

    return limpo or "Corte_GTA6"


def obter_caminho_ffmpeg() -> str:
    """
    Retorna o executável do ffmpeg. Se não estiver no PATH ativo do processo,
    procura nos locais padrão de instalação do WinGet no Windows.
    """
    cmd = shutil.which("ffmpeg")
    if cmd:
        return cmd

    # Busca em locais comuns de WinGet no Windows
    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        pacotes_winget = Path(user_profile) / "AppData/Local/Microsoft/WinGet/Packages"
        if pacotes_winget.exists():
            for p in pacotes_winget.glob("**/ffmpeg.exe"):
                if p.is_file():
                    caminho_bin = str(p.parent)
                    os.environ["PATH"] = f"{caminho_bin};" + os.environ.get("PATH", "")
                    return str(p)

    return "ffmpeg"


class AgenteEditor:
    def __init__(
        self,
        output_dir: str = "prontos_para_postar",
        temp_dir: str = "buffer_temp",
        alerta_sonoro: bool = True
    ):
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir)
        self.alerta_sonoro = alerta_sonoro
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_cmd = obter_caminho_ffmpeg()

    def emitir_alerta_sonoro(self) -> None:
        """Emite aviso sonoro no Windows indicando que um novo corte foi finalizado."""
        if not self.alerta_sonoro:
            return
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(1000, 400)
        except Exception as e:
            logger.debug(f"Não foi possível emitir som de notificação: {e}")

    @staticmethod
    def formatar_tempo_ass(segundos: float) -> str:
        """Formata segundos float para formato H:MM:SS.cs aceito pelo padrão ASS."""
        segundos = max(0.0, float(segundos))
        horas = int(segundos // 3600)
        minutos = int((segundos % 3600) // 60)
        segs = int(segundos % 60)
        centisegundos = int(round((segundos - int(segundos)) * 100))
        if centisegundos >= 100:
            centisegundos = 99
        return f"{horas}:{minutos:02d}:{segs:02d}.{centisegundos:02d}"

    def gerar_arquivo_ass(self, legendas: List[Dict[str, Any]], caminho_ass: Path) -> bool:
        """
        Gera arquivo de legendas .ass estilizado para Shorts/TikTok:
        Fonte Arial Black, Amarelo vibrante (&H0000FFFF), contorno preto grosso (Outline 4.5),
        centralizado e elevado para leitura perfeita em qualquer celular.
        """
        if not legendas:
            return False

        linhas = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: ShortsYellow,Arial Black,54,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,4.5,2.0,2,40,40,280,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        for item in legendas:
            ini = float(item.get("inicio", 0.0))
            fim = float(item.get("fim", ini + 1.8))
            if fim <= ini:
                fim = ini + 1.8
            texto = censurar_texto_legenda(
                str(item.get("texto", "")).strip().replace("\n", " ").upper()
            )
            if texto:
                t_ini = self.formatar_tempo_ass(ini)
                t_fim = self.formatar_tempo_ass(fim)
                linhas.append(f"Dialogue: 0,{t_ini},{t_fim},ShortsYellow,,0,0,0,,{texto}")

        try:
            with open(caminho_ass, "w", encoding="utf-8") as f:
                f.write("\n".join(linhas) + "\n")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo de legendas .ass: {e}")
            return False

    async def obter_duracao_video(self, caminho_arquivo: Path) -> float:
        """Retorna a duração exata em segundos de um arquivo de vídeo/áudio via ffprobe."""
        ffprobe_cmd = str(Path(self.ffmpeg_cmd).with_name("ffprobe.exe"))
        if not Path(ffprobe_cmd).exists():
            ffprobe_cmd = shutil.which("ffprobe") or "ffprobe"
        try:
            proc = await asyncio.create_subprocess_exec(
                ffprobe_cmd,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(caminho_arquivo.resolve()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            val = stdout.decode(errors="ignore").strip()
            return float(val) if val else 0.0
        except Exception:
            return 0.0

    async def preparar_trecho_exato(
        self,
        segmentos_ts: List[Path],
        duracao_segundos: int = 45
    ) -> Optional[Path]:
        """
        Congela e recorta exatamente os últimos 'duracao_segundos' (ex: 45s) dos segmentos .ts
        com timestamps zerados (0.000s), garantindo que o áudio enviado ao Gemini e o vídeo
        renderizado sejam 100% idênticos em início, duração e sincronia de legendas.
        """
        if not segmentos_ts:
            return None

        ts_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000}"
        concat_txt = self.temp_dir / f"concat_exato_{ts_id}.txt"
        concat_full = self.temp_dir / f"full_{ts_id}.ts"
        trecho_final = self.temp_dir / f"trecho_{duracao_segundos}s_{ts_id}.ts"

        try:
            with open(concat_txt, "w", encoding="utf-8") as f:
                for seg in segmentos_ts:
                    if seg.exists():
                        f.write(f"file '{seg.resolve().as_posix()}'\n")

            # 1. Concatena os blocos rapidamente sem re-encodar (-c copy)
            proc1 = await asyncio.create_subprocess_exec(
                self.ffmpeg_cmd, "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_txt.resolve()),
                "-c", "copy",
                str(concat_full.resolve()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            await proc1.communicate()
            if proc1.returncode != 0 or not concat_full.exists():
                return None

            # 2. Mede duração total real e recorta os últimos 'duracao_segundos' exatos
            dur_total = await self.obter_duracao_video(concat_full)
            inicio_corte = max(0.0, dur_total - float(duracao_segundos))

            proc2 = await asyncio.create_subprocess_exec(
                self.ffmpeg_cmd, "-y", "-loglevel", "error",
                "-ss", f"{inicio_corte:.3f}",
                "-i", str(concat_full.resolve()),
                "-t", str(duracao_segundos),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                str(trecho_final.resolve()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            await proc2.communicate()
            if proc2.returncode == 0 and trecho_final.exists() and trecho_final.stat().st_size > 0:
                return trecho_final
        except Exception as e:
            logger.error(f"Erro ao preparar trecho exato de {duracao_segundos}s: {e}")
        finally:
            for tmp in (concat_txt, concat_full):
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
        return None

    async def renderizar_corte(
        self,
        segmentos_ts: List[Path],
        curadoria: Dict[str, Any],
        streamer_info: Dict[str, Any],
        duracao_segundos: int = 45,
        habilitar_legendas: bool = True,
        trecho_pronto: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Renderiza o Short 9:16 (1080x1920) com duração exata e timestamps normalizados em 0.000s,
        garantindo sincronia perfeita entre fala, vídeo e legendas dinâmicas.
        """
        if not trecho_pronto and not segmentos_ts:
            logger.error("Nenhum segmento .ts disponível para renderização.")
            return None

        slug = streamer_info.get("slug", "streamer")
        nome_streamer = sanitizar_nome_arquivo(
            streamer_info.get("nome", slug), max_len=18
        )
        nota = curadoria.get("nota_viralidade", 8)
        titulo_bruto = (
            curadoria.get("titulo_shorts")
            or curadoria.get("titulo_sugerido")
            or f"Momento {nome_streamer}"
        )
        titulo_limpo = sanitizar_nome_arquivo(titulo_bruto, max_len=45)
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        hora_str = time.strftime("%Hh%Mm%Ss")
        nome_base = f"[Nota{nota}] {nome_streamer} - {titulo_limpo} ({hora_str})"
        caminho_saida_mp4 = self.output_dir / f"{nome_base}.mp4"
        caminho_saida_txt = self.output_dir / f"{nome_base}.txt"

        # Arquivos temporários (ASCII puro para FFmpeg)
        concat_txt = self.temp_dir / f"concat_{timestamp_str}.txt"
        trecho_bruto = trecho_pronto if (trecho_pronto and trecho_pronto.exists()) else None
        criou_trecho_local = False
        video_temp = self.temp_dir / f"render_{timestamp_str}.mp4"
        caminho_ass = self.temp_dir / f"legendas_{timestamp_str}.ass"
        usar_ass = False

        try:
            logger.info(f"Iniciando montagem do corte para {streamer_info.get('nome')} ({nome_base})...")

            # 1-2. Usa o trecho já congelado (idêntico ao áudio analisado pelo Gemini) ou cria agora
            if not trecho_bruto:
                trecho_bruto = await self.preparar_trecho_exato(segmentos_ts, duracao_segundos=duracao_segundos)
                criou_trecho_local = True
                if not trecho_bruto or not trecho_bruto.exists():
                    logger.error("Erro na preparação do trecho exato de vídeo.")
                    return None

            # 3. Cria arquivo de legendas .ass caso habilitado
            legendas = curadoria.get("legendas", [])
            filtro_ass = ""
            if habilitar_legendas and legendas:
                if self.gerar_arquivo_ass(legendas, caminho_ass):
                    usar_ass = True
                    ass_escaped = str(caminho_ass.resolve()).replace("\\", "/").replace(":", "\\:")
                    filtro_ass = f",ass='{ass_escaped}'"
                    logger.info(f"🔤 {len(legendas)} legendas sincronizadas preparadas para queima no vídeo.")

            # 4. Monta o filtro complexo para resolução 1080x1920 (Shorts 9:16)
            # setpts=PTS-STARTPTS zera o relógio do vídeo em 0.000s antes do filtro ass=
            webcam_crop = streamer_info.get("webcam_crop", {})
            webcam_ativo = webcam_crop.get("ativo", True)

            if webcam_ativo:
                wx = webcam_crop.get("x", 20)
                wy = webcam_crop.get("y", 750)
                ww = webcam_crop.get("w", 460)
                wh = webcam_crop.get("h", 320)

                alinhamento_cam_y = "(in_h-672)/2"
                filter_complex = (
                    f"[0:v]setpts=PTS-STARTPTS,scale=1920:1080,split=2[cam_src][game_src];"
                    f"[cam_src]crop={ww}:{wh}:{wx}:{wy},scale=1080:672:force_original_aspect_ratio=increase,crop=1080:672:(in_w-1080)/2:{alinhamento_cam_y}[cam];"
                    f"[game_src]scale=1080:1248:force_original_aspect_ratio=increase,crop=1080:1248[game];"
                    f"[cam][game]vstack=inputs=2{filtro_ass}[v]"
                )
            else:
                filter_complex = (
                    f"[0:v]setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,"
                    f"crop=1080:1920:(iw-1080)/2:(ih-1920)/2{filtro_ass}[v]"
                )

            # 5. Renderização final: duração cravada em 'duracao_segundos', áudio/vídeo zerados em 0.000s
            cmd_render = [
                self.ffmpeg_cmd,
                "-y",
                "-loglevel", "warning",
                "-i", str(trecho_bruto.resolve()),
                "-t", str(duracao_segundos),
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "0:a?",
                "-af", "asetpts=PTS-STARTPTS",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "25",
                "-maxrate", "6000k",
                "-bufsize", "12000k",
                "-threads", "2",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                str(video_temp.resolve())
            ]

            modo_webcam_str = "com webcam no topo" if webcam_ativo else "sem webcam (tela cheia)"
            modo_leg_str = f"e {len(legendas)} legendas dinâmicas" if usar_ass else "sem legendas"
            logger.info(f"Renderizando Short 9:16 {modo_webcam_str} {modo_leg_str} (FFmpeg ultrafast, threads=2)...")
            proc_render = await asyncio.create_subprocess_exec(
                *cmd_render,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            _, stderr_render = await proc_render.communicate()

            if proc_render.returncode != 0 or not video_temp.exists():
                logger.error(f"Erro na renderização final do vídeo: {stderr_render.decode().strip()}")
                return None

            # Move o arquivo renderizado de forma atômica para a pasta de saída
            shutil.move(str(video_temp.resolve()), str(caminho_saida_mp4.resolve()))

            # 6. Salva arquivo de metadados (.txt)
            titulo = curadoria.get("titulo_shorts", f"Momento Épico na live do {slug.upper()}!")
            descricao = curadoria.get("descricao_post", f"Confira esse momento insano de GTA 6!\n{streamer_info.get('hashtags', '')}")

            conteudo_txt = (
                f"{titulo}\n\n"
                f"{descricao}\n\n"
                f"--- Detalhes do Corte ---\n"
                f"Streamer: {streamer_info.get('nome')} (@{slug})\n"
                f"Nota Viralidade: {nota}/10\n"
                f"Data/Hora: {time.strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"Origem do Gatilho: {curadoria.get('origem_gatilho', 'Radar Hype')}\n"
                f"Legendas Sincronizadas: {'Sim' if usar_ass else 'Não'}\n"
            )

            with open(caminho_saida_txt, "w", encoding="utf-8") as f:
                f.write(conteudo_txt)

            logger.info(f"✨ Vídeo Short salvo em: {caminho_saida_mp4.name} ({caminho_saida_mp4.stat().st_size / (1024*1024):.2f} MB)")
            logger.info(f"📄 Metadados salvos em: {caminho_saida_txt.name}")

            # 7. Alerta sonoro de conclusão no Windows
            self.emitir_alerta_sonoro()
            return caminho_saida_mp4

        except Exception as e:
            logger.error(f"Exceção durante a edição do corte: {e}")
            return None
        finally:
            # Limpeza de arquivos intermediários
            for tmp in [concat_txt, trecho_bruto, video_temp, caminho_ass]:
                if tmp and tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass

    async def gerar_video_previa(
        self,
        streamer_info: Dict[str, Any],
        caminho_video_origem: Optional[Path] = None,
        com_legendas: bool = True,
        stream_url: Optional[str] = None,
        audio_url: Optional[str] = None
    ) -> Optional[Path]:
        """
        Gera um clipe de 5 segundos de pré-visualização para que o usuário
        possa verificar imediatamente se o enquadramento da webcam e as legendas
        ficaram no lugar perfeito antes de iniciar as gravações completas.
        Prioridade de origem:
        1. stream_url ao vivo (grava 5s reais da transmissão atual)
        2. caminho_video_origem específico
        3. Segmento bruto 16:9 mais recente no buffer (seg_*.ts)
        4. Vídeo sintético 16:9 (testsrc)
        """
        # Limpa prévias antigas na pasta temporária (ignora se alguma estiver aberta no player)
        for antiga in self.temp_dir.glob("preview_enquadramento_*.mp4"):
            try:
                antiga.unlink()
            except Exception:
                pass

        # Remove resquício antigo da pasta de saída para não poluir fila de publicação
        previa_legada = self.output_dir / "preview_teste_enquadramento.mp4"
        if previa_legada.exists():
            try:
                previa_legada.unlink()
            except Exception:
                pass

        timestamp_previa = int(time.time())
        caminho_saida_previa = self.temp_dir / f"preview_enquadramento_{timestamp_previa}.mp4"
        caminho_ass = self.temp_dir / f"preview_legendas_{timestamp_previa}.ass"
        filtro_ass = ""

        webcam_crop = streamer_info.get("webcam_crop", {})
        webcam_ativo = webcam_crop.get("ativo", True)

        if com_legendas:
            texto_exemplo = "WEBCAM NO TOPO E GAMEPLAY NA BASE" if webcam_ativo else "MODO TELA CHEIA (SEM WEBCAM)"
            legendas_teste = [
                {"inicio": 0.0, "fim": 2.2, "texto": "TESTE DE ENQUADRAMENTO!"},
                {"inicio": 2.2, "fim": 4.8, "texto": texto_exemplo}
            ]
            if self.gerar_arquivo_ass(legendas_teste, caminho_ass):
                ass_escaped = str(caminho_ass.resolve()).replace("\\", "/").replace(":", "\\:")
                filtro_ass = f",ass='{ass_escaped}'"

        if webcam_ativo:
            wx = webcam_crop.get("x", 20)
            wy = webcam_crop.get("y", 640)
            ww = webcam_crop.get("w", 600)
            wh = webcam_crop.get("h", 400)
            alinhamento_cam_y = "(in_h-672)/2"
            filter_complex = (
                f"[0:v]scale=1920:1080,split=2[cam_src][game_src];"
                f"[cam_src]crop={ww}:{wh}:{wx}:{wy},scale=1080:672:force_original_aspect_ratio=increase,crop=1080:672:(in_w-1080)/2:{alinhamento_cam_y}[cam];"
                f"[game_src]scale=1080:1248:force_original_aspect_ratio=increase,crop=1080:1248[game];"
                f"[cam][game]vstack=inputs=2{filtro_ass}[v]"
            )
        else:
            filter_complex = (
                f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920:(iw-1080)/2:(ih-1920)/2{filtro_ass}[v]"
            )

        temp_raw_ts = self.temp_dir / f"prev_raw_{timestamp_previa}.ts"
        origem_str = None

        if stream_url:
            # Captura 5 segundos brutos (-c copy) diretamente da transmissão ao vivo.
            # O processo de cópia pura é quase instantâneo (~1 a 2s) e não trava a decodificação de filtros.
            logger.info("Capturando 5 segundos brutos da transmissão ao vivo...")
            cmd_copia = [
                self.ffmpeg_cmd,
                "-y",
                "-rw_timeout", "8000000",
                "-probesize", "2M",
                "-analyzeduration", "2M",
                "-i", stream_url,
                "-t", "5",
                "-c", "copy",
                str(temp_raw_ts.resolve())
            ]
            try:
                proc_copia = await asyncio.create_subprocess_exec(
                    *cmd_copia,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=CREATE_NO_WINDOW
                )
                _, stderr_copia = await asyncio.wait_for(proc_copia.communicate(), timeout=14.0)
                if temp_raw_ts.exists() and temp_raw_ts.stat().st_size > 10 * 1024:
                    origem_str = str(temp_raw_ts.resolve())
                    logger.info("Captura bruta de 5s da live concluída com sucesso.")
                else:
                    logger.warning(f"Captura bruta da live retornou vazia: {stderr_copia.decode(errors='ignore')[:100]}")
            except asyncio.TimeoutError:
                logger.warning("Timeout na conexão da live para captura de 5s. Usando fallback.")
                try:
                    proc_copia.kill()
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Aviso na captura bruta da live: {e}")

        if not origem_str:
            if caminho_video_origem and Path(caminho_video_origem).exists():
                origem_str = str(Path(caminho_video_origem).resolve())
            else:
                # Usa segmento bruto 16:9 mais recente do buffer (seg_*.ts)
                segmentos_ts = sorted(
                    [f for f in self.temp_dir.glob("seg_*.ts") if f.is_file() and f.stat().st_size > 100 * 1024],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True
                )
                if segmentos_ts:
                    origem_str = str(segmentos_ts[0].resolve())

        if origem_str:
            cmd = [
                self.ffmpeg_cmd,
                "-y",
                "-ss", "00:00:01",
                "-i", origem_str,
                "-t", "5",
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-threads", "2",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                str(caminho_saida_previa.resolve())
            ]
        else:
            # Fallback sintético limpo 16:9 (1920x1080)
            cmd = [
                self.ffmpeg_cmd,
                "-y",
                "-f", "lavfi", "-i", "testsrc=duration=5:size=1920x1080:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=1000:duration=5",
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "1:a?",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-threads", "2",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                str(caminho_saida_previa.resolve())
            ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=35.0)
            if proc.returncode == 0 and caminho_saida_previa.exists():
                logger.info(f"Prévia gerada com sucesso: {caminho_saida_previa.name}")
                return caminho_saida_previa
            else:
                msg_err = stderr.decode(errors='ignore')
                logger.error(f"Erro ao gerar prévia: {msg_err}")
                try:
                    from config.logger_config import registrar_erro_detalhado
                    registrar_erro_detalhado("AgenteEditor.gerar_video_previa", f"Falha no FFmpeg ao gerar prévia: {msg_err}")
                except Exception:
                    pass
        except asyncio.TimeoutError:
            logger.error("Timeout ao renderizar prévia de 5 segundos.")
            try:
                proc.kill()
            except Exception:
                pass
            try:
                from config.logger_config import registrar_erro_detalhado
                registrar_erro_detalhado("AgenteEditor.gerar_video_previa", "Timeout (35s) ao renderizar prévia.")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Exceção ao gerar prévia: {e}")
            try:
                from config.logger_config import registrar_erro_detalhado
                registrar_erro_detalhado("AgenteEditor.gerar_video_previa", "Exceção ao gerar prévia", exc=e)
            except Exception:
                pass
        finally:
            if caminho_ass.exists():
                try:
                    caminho_ass.unlink()
                except Exception:
                    pass
            if temp_raw_ts.exists():
                try:
                    temp_raw_ts.unlink()
                except Exception:
                    pass
        return None
