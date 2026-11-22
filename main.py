"""
Orquestrador Principal - GTA6_ClipHunter
Responsável por coordenar o VigiaStream, RadarHype, AgenteCurador e AgenteEditor
em um loop assíncrono não-bloqueante com tratamento robusto de erros e desligamento gracioso.
"""

import os
import sys
import shutil
import signal
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()

# Configuração de logging estruturado
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ClipHunter.Main")

# Importação dos módulos de agentes
from agentes.vigia_stream import VigiaStream, PRESETS_WEBCAM
from agentes.radar_hype import RadarHype
from agentes.agente_curador import AgenteCurador
from agentes.agente_editor import AgenteEditor
from agentes.agente_publicador import AgentePublicador


def verificar_e_configurar_ffmpeg() -> bool:
    """Verifica se o FFmpeg está acessível e adiciona ao PATH se necessário."""
    cmd = shutil.which("ffmpeg")
    if cmd:
        logger.info(f"FFmpeg detectado no PATH: {cmd}")
        return True

    # Procura no diretório WinGet
    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        pacotes = Path(user_profile) / "AppData/Local/Microsoft/WinGet/Packages"
        if pacotes.exists():
            for p in pacotes.glob("**/ffmpeg.exe"):
                if p.is_file():
                    bin_dir = str(p.parent)
                    os.environ["PATH"] = f"{bin_dir};" + os.environ.get("PATH", "")
                    logger.info(f"FFmpeg localizado e adicionado ao PATH de execução: {bin_dir}")
                    return True

    logger.critical(
        "FFmpeg não foi encontrado no sistema. Por favor, instale o FFmpeg ou execute:\n"
        "winget install -e --id Gyan.FFmpeg"
    )
    return False


class OrquestradorClipHunter:
    def __init__(
        self,
        config_path: str = "config/streamers.json",
        alvo_direto: Optional[str] = None,
        posicao_webcam: str = "inferior_esquerdo",
        habilitar_legendas: bool = True,
        alerta_sonoro: bool = True,
        upload_automatico_youtube: bool = False,
        privacidade_youtube: str = "unlisted",
        nota_minima_upload: int = 8,
        enviar_telegram: bool = False,
        nota_minima_salvar: int = 7
    ):
        self.config_path = config_path
        self.alvo_direto = alvo_direto
        self.posicao_webcam = posicao_webcam
        self.habilitar_legendas = habilitar_legendas
        self.alerta_sonoro = alerta_sonoro
        self.upload_automatico_youtube = upload_automatico_youtube
        self.privacidade_youtube = privacidade_youtube
        self.nota_minima_upload = nota_minima_upload
        self.enviar_telegram = enviar_telegram
        self.nota_minima_salvar = nota_minima_salvar

        self.buffer_dir = os.getenv("BUFFER_DIR", "buffer_temp")
        self.output_dir = os.getenv("OUTPUT_DIR", "prontos_para_postar")

        # Criação de pastas necessárias
        Path(self.buffer_dir).mkdir(parents=True, exist_ok=True)
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        self.vigia: Optional[VigiaStream] = None
        self.radar: Optional[RadarHype] = None
        self.curador: Optional[AgenteCurador] = None
        self.editor: Optional[AgenteEditor] = None
        self.publicador: Optional[AgentePublicador] = AgentePublicador(output_dir=self.output_dir)

        # Fila desacoplada assíncrona para uploads (nunca bloqueia captura ou edição)
        self.fila_upload: asyncio.Queue = asyncio.Queue()
        self.tarefa_worker_upload: Optional[asyncio.Task] = None

        self.rodando = False
        self.bloqueio_processamento = asyncio.Lock()

    async def _worker_fila_upload(self) -> None:
        """
        Worker assíncrono em segundo plano para envio de vídeos ao YouTube e Telegram.
        Executa totalmente desacoplado do Lock de captura e FFmpeg.
        """
        logger.info("Fila assíncrona de publicação ativada em segundo plano.")
        while self.rodando:
            try:
                item = await self.fila_upload.get()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1)
                continue

            try:
                caminho_video = Path(item["caminho_video"])
                caminho_txt = Path(item.get("caminho_txt", caminho_video.with_suffix(".txt")))
                nota = item.get("nota", 8)
                privacidade = item.get("privacidade", self.privacidade_youtube)
                enviar_yt = item.get("upload_youtube", self.upload_automatico_youtube)
                enviar_tg = item.get("enviar_telegram", self.enviar_telegram)
                nota_min = item.get("nota_minima", self.nota_minima_upload)

                logger.info(f"📤 Processando item da fila de publicação: {caminho_video.name}")

                # 1. Envio para o YouTube (se habilitado)
                if enviar_yt:
                    if nota < nota_min:
                        logger.info(
                            f"Upload YouTube ignorado para {caminho_video.name}: "
                            f"Nota {nota}/10 menor que a nota mínima exigida ({nota_min}/10)."
                        )
                    elif not self.publicador.pode_publicar():
                        logger.warning(
                            f"Limite diário de cota do YouTube atingido (6/6). "
                            f"Upload de {caminho_video.name} pausado para evitar erro de cota."
                        )
                    elif not self.publicador.esta_autenticado():
                        logger.warning(
                            "Conta YouTube não autenticada. "
                            "Clique em 'Conectar Conta YouTube' na interface para autorizar o canal Neri Clipes."
                        )
                    else:
                        logger.info(f"Iniciando upload para o YouTube Shorts (Canal Neri Clipes) [{privacidade}]...")
                        loop = asyncio.get_running_loop()
                        res_yt = await loop.run_in_executor(
                            None,
                            self.publicador.publicar_short,
                            caminho_video,
                            caminho_txt,
                            privacidade
                        )
                        if res_yt.get("sucesso"):
                            logger.info(f"✅ Upload concluído com sucesso: {res_yt.get('url')}")
                            caminho_postado = self.publicador.pasta_postados / caminho_video.name
                            if caminho_postado.exists():
                                caminho_video = caminho_postado
                                caminho_txt = caminho_video.with_suffix(".txt")
                        else:
                            logger.error(f"❌ Falha no upload para YouTube: {res_yt.get('erro')}")

                # 2. Envio para o Telegram (se habilitado)
                if enviar_tg:
                    logger.info(f"Iniciando envio para o Telegram ({caminho_video.name})...")
                    loop = asyncio.get_running_loop()
                    res_tg = await loop.run_in_executor(
                        None,
                        self.publicador.enviar_telegram,
                        caminho_video,
                        caminho_txt
                    )
                    if res_tg.get("sucesso"):
                        logger.info("✅ Vídeo enviado para o Telegram com sucesso!")
                    else:
                        logger.warning(f"Aviso no envio Telegram: {res_tg.get('erro')}")

            except Exception as e:
                logger.error(f"Erro ao processar publicação da fila: {e}", exc_info=True)
            finally:
                self.fila_upload.task_done()

    async def _dormir_interrompivel(self, segundos: float) -> None:
        """Dorme em intervalos curtos de 0.5s para responder imediatamente a interrupções."""
        passos = max(1, int(segundos / 0.5))
        for _ in range(passos):
            if not self.rodando:
                break
            await asyncio.sleep(0.5)

    async def pipeline_processar_hype(self, contexto_hype: Dict[str, Any]) -> None:
        """
        Executa a esteira completa quando um momento de hype é validado pelo radar:
        1. Resgata segmentos .ts recentes do buffer SSD.
        2. Extrai áudio leve mono (32kbps).
        3. Envia para o AgenteCurador (Gemini 3.8 Flash).
        4. Se aprovado, o AgenteEditor monta e renderiza o Short 9:16 (1080x1920).
        """
        if self.bloqueio_processamento.locked():
            logger.debug("Processamento de clipagem já em andamento. Descartando gatilho simultâneo.")
            return

        async with self.bloqueio_processamento:
            caminho_mp3 = None
            trecho_45s = None
            try:
                origem = contexto_hype.get("origem", "RADAR")
                mensagens = contexto_hype.get("mensagens_chat", [])
                streamer = dict(self.vigia.streamer_ativo) if self.vigia and self.vigia.streamer_ativo else {}

                # Aplica estritamente a posição da webcam configurada pelo usuário
                if self.posicao_webcam == "desativado":
                    streamer["webcam_crop"] = {"ativo": False, "x": 0, "y": 0, "w": 0, "h": 0}
                elif self.posicao_webcam in PRESETS_WEBCAM and self.posicao_webcam != "auto":
                    # Se o perfil do streamer ou a IA já definiu coordenadas refinadas de crop, preserva-as!
                    crop_atual = streamer.get("webcam_crop", {})
                    if not crop_atual or not crop_atual.get("ativo") or crop_atual.get("w", 0) == 0:
                        streamer["webcam_crop"] = dict(PRESETS_WEBCAM[self.posicao_webcam])

                logger.info("=" * 60)
                logger.info(f"🎬 INICIANDO PIPELINE DE CLIPAGEM (Origem: {origem})")
                logger.info(f"Streamer: {streamer.get('nome')} | Mensagens no Chat: {len(mensagens)}")
                logger.info("=" * 60)

                # 1. Recupera segmentos recentes do buffer
                segmentos = self.vigia.obter_segmentos_recentes(quantidade=3)
                if not segmentos:
                    logger.warning("⏳ Buffer de vídeo ainda está iniciando (0 segmentos prontos). Aguardando próximo bloco...")
                    return

                tamanho_total = sum(s.stat().st_size for s in segmentos if s.exists())
                if tamanho_total < 300 * 1024:
                    logger.warning("⏳ Buffer de vídeo ainda acumulando primeiros segundos... Aguardando próximo ciclo.")
                    return

                logger.info(f"🎞️ {len(segmentos)} segmento(s) de vídeo resgatados do buffer ({tamanho_total / 1024:.0f} KB) para curadoria.")

                # 1.5. Congela UM trecho exato de 45s (garante 100% de sincronia entre áudio da IA e vídeo final!)
                trecho_45s = await self.editor.preparar_trecho_exato(segmentos, duracao_segundos=45)
                if not trecho_45s or not trecho_45s.exists():
                    logger.warning("⏳ Não foi possível congelar trecho de 45s ainda. Aguardando próximo ciclo.")
                    return

                # 2. Extrai áudio leve de 45 segundos EXATAMENTE do trecho congelado
                caminho_mp3 = await self.curador.extrair_audio_mono_leve(
                    segmentos, duracao_segundos=45, trecho_pronto=trecho_45s
                )

                # 3. Curadoria com Gemini (com fallback e resiliência)
                decisao_curadoria = await self.curador.avaliar_clipe(
                    caminho_audio=caminho_mp3,
                    streamer_info=streamer,
                    mensagens_chat=mensagens
                )
                decisao_curadoria["origem_gatilho"] = origem

                # 4. Avalia decisão da IA
                aprovado = decisao_curadoria.get("aprovado", True)
                nota = decisao_curadoria.get("nota_viralidade", 8)
                titulo = decisao_curadoria.get("titulo_shorts", "")

                if not aprovado:
                    logger.info(f"❌ Corte reprovado pelo Curador IA (Nota: {nota}/10). Motivo: conteúdo sem potencial viral.")
                elif nota < self.nota_minima_salvar:
                    logger.info(
                        f"🗑️ Corte descartado pelo filtro de armazenamento (Nota {nota}/10 < Mínimo exigido {self.nota_minima_salvar}/10). "
                        f"Economizando espaço em disco e processamento!"
                    )
                else:
                    logger.info(f"✅ CORTE APROVADO! Nota: {nota}/10 | Título: '{titulo}'")
                    logger.info("Encaminhando para o Agente Editor...")

                    # 5. Edição e renderização do Short 1080x1920 EXATAMENTE a partir do mesmo trecho congelado
                    caminho_video = await self.editor.renderizar_corte(
                        segmentos_ts=segmentos,
                        curadoria=decisao_curadoria,
                        streamer_info=streamer,
                        duracao_segundos=45,
                        habilitar_legendas=self.habilitar_legendas,
                        trecho_pronto=trecho_45s
                    )

                    if caminho_video:
                        logger.info(f"🚀 SHORT 100% PRONTO PARA POSTAGEM: {caminho_video}")
                        # Enfileira para publicação assíncrona se YouTube ou Telegram estiverem habilitados
                        if self.upload_automatico_youtube or self.enviar_telegram:
                            item_upload = {
                                "caminho_video": caminho_video,
                                "caminho_txt": caminho_video.with_suffix(".txt"),
                                "nota": nota,
                                "privacidade": self.privacidade_youtube,
                                "upload_youtube": self.upload_automatico_youtube,
                                "enviar_telegram": self.enviar_telegram,
                                "nota_minima": self.nota_minima_upload
                            }
                            await self.fila_upload.put(item_upload)
                            logger.info("📤 Vídeo adicionado à fila assíncrona de publicação!")
                    else:
                        logger.error("Falha ao renderizar vídeo do corte.")

            except Exception as e:
                logger.error(f"Erro durante pipeline de processamento de corte: {e}", exc_info=True)
            finally:
                # Limpeza dos arquivos temporários (áudio + trecho congelado)
                for tmp_f in (caminho_mp3, trecho_45s):
                    if tmp_f and tmp_f.exists():
                        try:
                            tmp_f.unlink()
                        except Exception:
                            pass

                logger.info("=" * 60)
                logger.info("Pronto para novos momentos virais. Buffer ativo.")
                logger.info("=" * 60)

    async def iniciar(self) -> None:
        """Loop principal do orquestrador."""
        self.rodando = True
        logger.info("=" * 70)
        logger.info("ClipHunter AI - Caçador Inteligente de Cortes ao Vivo")
        logger.info("Arquitetura: Stream Buffer Circular + Dual Hype Radar + Gemini AI")
        logger.info("Restrições Ativas: RAM < 1.5GB | FFmpeg ultrafast -threads 2 | SSD Protegido")
        logger.info("=" * 70)

        self.curador = AgenteCurador(temp_dir=self.buffer_dir)
        self.editor = AgenteEditor(
            output_dir=self.output_dir,
            temp_dir=self.buffer_dir,
            alerta_sonoro=self.alerta_sonoro
        )

        # Inicia o worker assíncrono de publicação
        self.tarefa_worker_upload = asyncio.create_task(self._worker_fila_upload())

        # Contador de tempo offline consecutivo (limite: 10 minutos = 600 segundos)
        tempo_offline_acumulado = 0.0

        while self.rodando:
            try:
                # 1. Instancia vigia e procura streamer ao vivo
                self.vigia = VigiaStream(
                    config_path=self.config_path,
                    buffer_dir=self.buffer_dir,
                    posicao_webcam=self.posicao_webcam
                )
                if self.alvo_direto:
                    self.vigia.definir_streamer_alvo(self.alvo_direto, posicao_webcam=self.posicao_webcam)

                streamer_online = await self.vigia.encontrar_streamer_online()

                if not streamer_online:
                    tempo_offline_acumulado += 30.0
                    logger.info(
                        f"Aguardando 30 segundos antes de nova varredura de streamers... "
                        f"(Offline há {int(tempo_offline_acumulado)}s/600s)"
                    )
                    if tempo_offline_acumulado >= 600.0:
                        logger.warning(
                            "⏰ Stream offline por mais de 10 minutos consecutivos. "
                            "Auto-Encerramento ativado para economizar recursos."
                        )
                        self.rodando = False
                        break

                    await self._dormir_interrompivel(30)
                    continue

                # Streamer encontrado: reseta o temporizador de offline
                tempo_offline_acumulado = 0.0

                nome = streamer_online.get("nome")
                slug = streamer_online.get("slug")
                url_canal = streamer_online.get("url", f"kick.com/{slug}")
                logger.info(f"Conectando ao canal de {nome} ({url_canal})...")

                # 2. Inicia gravação contínua no buffer circular IMEDIATAMENTE (sem travar na IA)
                gravando = await self.vigia.iniciar_gravacao_buffer()
                if not gravando:
                    logger.error("Não foi possível iniciar o buffer de gravação. Tentando novamente em 15s...")
                    await self._dormir_interrompivel(15)
                    continue

                # 3. Inicia o radar de hype (Áudio RMS + Chat ao vivo) IMEDIATAMENTE
                self.radar = RadarHype(
                    stream_url=self.vigia.stream_url_ativa,
                    streamer_info=streamer_online,
                    config_geral=self.vigia.config_geral,
                    on_hype_callback=self.pipeline_processar_hype,
                    audio_url=self.vigia.audio_url_ativa
                )
                await self.radar.iniciar()

                # 4. Se o modo Auto IA estiver ativo, calibra a webcam em segundo plano (nunca bloqueia gravação/chat!)
                if self.posicao_webcam == "auto" and self.vigia.stream_url_ativa:
                    async def _calibrar_em_segundo_plano(vigia_ref, streamer_ref, url_ref):
                        try:
                            logger.info("🎯 Executando Auto-Calibração Inteligente da Webcam com IA em segundo plano...")
                            calib_ia = await asyncio.wait_for(
                                vigia_ref.detectar_webcam_ia(url_ref),
                                timeout=20.0
                            )
                            pos_detectada = calib_ia.get("posicao", "desativado")
                            crop_detectado = dict(calib_ia.get("crop", {"ativo": False}))

                            crop_salvo = streamer_ref.get("webcam_crop", {}) if streamer_ref else {}
                            if not crop_detectado.get("ativo") and crop_salvo.get("ativo") and crop_salvo.get("w", 0) > 0:
                                crop_detectado = dict(crop_salvo)
                                pos_detectada = "perfil_calibrado"
                                logger.info(f"🎯 Mantendo enquadramento calibrado do perfil do streamer: {crop_detectado}")

                            vigia_ref.posicao_webcam = pos_detectada
                            if vigia_ref.streamer_ativo:
                                vigia_ref.streamer_ativo["webcam_crop"] = crop_detectado
                            if streamer_ref:
                                streamer_ref["webcam_crop"] = crop_detectado
                            logger.info(f"🎯 Auto-Calibração IA: Enquadramento adotado -> '{pos_detectada}' (crop: {crop_detectado})")
                        except asyncio.TimeoutError:
                            logger.warning("⏳ Auto-Calibração IA excedeu 20s; mantendo enquadramento calibrado do perfil.")
                        except Exception as ex_calib:
                            logger.warning(f"Auto-Calibração IA em segundo plano falhou: {ex_calib}")

                    asyncio.create_task(_calibrar_em_segundo_plano(self.vigia, streamer_online, self.vigia.stream_url_ativa))

                logger.info(f"Sistema 100% operacional monitorando {nome}! Pressione Ctrl+C para encerrar.")

                # 4. Monitora a integridade do processo de gravação do FFmpeg
                while self.rodando:
                    await self._dormir_interrompivel(5)
                    if not self.rodando:
                        break
                    if self.vigia and self.vigia.processo_ffmpeg and self.vigia.processo_ffmpeg.returncode is not None:
                        logger.warning("Stream de vídeo foi encerrado ou caiu. Reiniciando ciclo de busca...")
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no ciclo principal: {e}", exc_info=True)
                await self._dormir_interrompivel(10)
            finally:
                await self.parar_streamer_atual()

        logger.info("Orquestrador encerrado com sucesso.")

    async def parar_streamer_atual(self) -> None:
        """Para os agentes do streamer atual."""
        if self.radar:
            await self.radar.parar()
            self.radar = None
        if self.vigia:
            await self.vigia.parar()
            self.vigia = None

    async def parar_geral(self) -> None:
        """Encerra todo o sistema graciosamente."""
        logger.info("Sinal de interrupção recebido. Desligando agentes...")
        self.rodando = False
        if self.tarefa_worker_upload and not self.tarefa_worker_upload.done():
            self.tarefa_worker_upload.cancel()
            try:
                await self.tarefa_worker_upload
            except asyncio.CancelledError:
                pass
        await self.parar_streamer_atual()


async def main_async():
    if not verificar_e_configurar_ffmpeg():
        sys.exit(1)

    alvo_direto = sys.argv[1].strip() if len(sys.argv) > 1 else None
    if alvo_direto:
        logger.info(f"Argumento fornecido na linha de comando: '{alvo_direto}'.")

    orquestrador = OrquestradorClipHunter(alvo_direto=alvo_direto)

    # Tratamento de sinais para Windows e Unix
    loop = asyncio.get_running_loop()
    parada_evento = asyncio.Event()

    def solicitar_parada():
        parada_evento.set()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, solicitar_parada)
            except NotImplementedError:
                # Windows pode não suportar add_signal_handler em certos loops
                pass
    except Exception:
        pass

    tarefa_orquestrador = asyncio.create_task(orquestrador.iniciar())

    try:
        while not parada_evento.is_set():
            await asyncio.sleep(1)
            if tarefa_orquestrador.done():
                break
    except KeyboardInterrupt:
        logger.info("Ctrl+C detectado!")
    finally:
        await orquestrador.parar_geral()
        if not tarefa_orquestrador.done():
            tarefa_orquestrador.cancel()
            try:
                await tarefa_orquestrador
            except asyncio.CancelledError:
                pass


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
