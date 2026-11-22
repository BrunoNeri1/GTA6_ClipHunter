"""
Módulo AgentePublicador - ClipHunter AI
Gerencia a autenticação, controle de cota diária (máx. 6 vídeos/24h),
anti-duplicidade e publicação automatizada no YouTube Shorts (Canal Neri Clipes),
além da ponte mobile via Telegram para TikTok, Instagram Reels e Kwai.
"""

import os
import sys
import json
import time
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

logger = logging.getLogger("ClipHunter.AgentePublicador")

# Escopos do YouTube Data API v3
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# Cota da API: 10.000 unidades/dia. Cada videos.insert consome 1.600 unidades.
# 10.000 / 1.600 = 6 uploads diários seguros.
LIMITE_DIARIO_UPLOADS = 6


class AgentePublicador:
    def __init__(
        self,
        config_dir: str = "config",
        output_dir: str = "prontos_para_postar",
        client_secret_path: Optional[str] = None,
        token_path: str = "token_youtube.json"
    ):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pasta_postados = self.output_dir / "postados"
        self.pasta_postados.mkdir(parents=True, exist_ok=True)

        self.historico_path = self.config_dir / "historico_uploads.json"
        self.token_path = Path(token_path)
        self.client_secret_path = self._localizar_client_secret(client_secret_path)

        # Telegram
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        # Cache de serviço autenticado
        self._servico_youtube = None

    def _localizar_client_secret(self, caminho_especifico: Optional[str]) -> Optional[Path]:
        """Localiza o client_secret.json na raiz do projeto ou caminho configurado."""
        if caminho_especifico and Path(caminho_especifico).exists():
            return Path(caminho_especifico)

        raiz = Path(".")
        padrao = list(raiz.glob("client_secret*.json"))
        if padrao:
            return padrao[0]

        return None

    # -------------------------------------------------------------
    # GESTÃO DE COTA E HISTÓRICO ANTI-DUPLICIDADE
    # -------------------------------------------------------------

    def _carregar_historico(self) -> Dict[str, Any]:
        """Lê o histórico persistido de uploads em config/historico_uploads.json."""
        if not self.historico_path.exists():
            return {"uploads": []}
        try:
            with open(self.historico_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao ler histórico de uploads: {e}. Criando novo.")
            return {"uploads": []}

    def _salvar_historico(self, historico: Dict[str, Any]) -> None:
        """Salva o histórico de uploads no disco."""
        try:
            with open(self.historico_path, "w", encoding="utf-8") as f:
                json.dump(historico, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao salvar histórico de uploads: {e}")

    def obter_envios_ultimas_24h(self) -> int:
        """Calcula quantos uploads foram feitos com sucesso na janela móvel de 24 horas."""
        historico = self._carregar_historico()
        limite_tempo = time.time() - 86400  # 24 horas atrás
        contador = 0
        for item in historico.get("uploads", []):
            if item.get("status") == "sucesso" and item.get("timestamp", 0) >= limite_tempo:
                contador += 1
        return contador

    def cota_restante(self) -> int:
        """Retorna a cota disponível para hoje (máx 6)."""
        usados = self.obter_envios_ultimas_24h()
        return max(0, LIMITE_DIARIO_UPLOADS - usados)

    def pode_publicar(self) -> bool:
        """Verifica se ainda há cota diária disponível."""
        return self.cota_restante() > 0

    def ja_publicado(self, caminho_video: Path) -> bool:
        """Verifica se o vídeo já foi publicado anteriormente (anti-duplicidade)."""
        nome_arquivo = caminho_video.name
        # 1. Checa se o arquivo já está na pasta de postados
        if (self.pasta_postados / nome_arquivo).exists():
            return True

        # 2. Checa o registro no histórico JSON
        historico = self._carregar_historico()
        for item in historico.get("uploads", []):
            if item.get("arquivo") == nome_arquivo and item.get("status") == "sucesso":
                return True
        return False

    def registrar_sucesso_upload(
        self,
        caminho_video: Path,
        video_id: str,
        titulo: str,
        nota: int,
        privacidade: str
    ) -> None:
        """Registra o upload bem-sucedido no histórico."""
        historico = self._carregar_historico()
        registro = {
            "video_id": video_id,
            "url": f"https://youtube.com/shorts/{video_id}",
            "titulo": titulo,
            "arquivo": caminho_video.name,
            "data_iso": datetime.now().isoformat(),
            "timestamp": time.time(),
            "nota": nota,
            "status": "sucesso",
            "privacidade": privacidade
        }
        historico.setdefault("uploads", []).append(registro)
        self._salvar_historico(historico)
        logger.info(f"Registro de upload salvo: {caminho_video.name} -> ID: {video_id}")

    # -------------------------------------------------------------
    # AUTENTICAÇÃO OAUTH2 COM YOUTUBE DATA API V3
    # -------------------------------------------------------------

    def esta_autenticado(self) -> bool:
        """Verifica se o token existe e é válido ou renovável."""
        if not self.token_path.exists():
            return False
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            creds = Credentials.from_authorized_user_file(str(self.token_path), YOUTUBE_SCOPES)
            if creds and creds.valid:
                return True
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self.token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())
                return True
        except Exception as e:
            logger.warning(f"Verificação de autenticação YouTube falhou: {e}")
        return False

    def autenticar_interativo(self) -> Tuple[bool, str]:
        """
        Inicia o fluxo OAuth2 abrindo o navegador do usuário para login.
        Salva as credenciais em token_youtube.json.
        """
        self.client_secret_path = self._localizar_client_secret(self.client_secret_path)
        if not self.client_secret_path or not self.client_secret_path.exists():
            msg = (
                "Arquivo 'client_secret.json' não encontrado na raiz do projeto!\n"
                "Baixe o arquivo de credenciais OAuth 2.0 do Google Cloud Console "
                "e coloque-o na pasta do projeto."
            )
            logger.error(msg)
            return False, msg

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow

            logger.info("Iniciando fluxo OAuth2 no navegador local...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_path),
                YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

            with open(self.token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

            self._servico_youtube = None  # Força recriação
            logger.info("Conta do YouTube conectada e token salvo com sucesso!")
            return True, "Conta do YouTube conectada com sucesso!"
        except Exception as e:
            msg = f"Erro durante a autenticação OAuth2: {e}"
            logger.error(msg, exc_info=True)
            return False, msg

    def _obter_servico(self):
        """Retorna a instância do serviço do YouTube Data API v3 autenticada."""
        if self._servico_youtube:
            return self._servico_youtube

        if not self.token_path.exists():
            raise FileNotFoundError(
                "Token do YouTube não encontrado. Clique em 'Conectar Conta YouTube' na interface."
            )

        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(self.token_path), YOUTUBE_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(self.token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

        if not creds or not creds.valid:
            raise PermissionError("Credenciais inválidas. Faça login novamente.")

        self._servico_youtube = build("youtube", "v3", credentials=creds)
        return self._servico_youtube

    # -------------------------------------------------------------
    # EXTRAÇÃO DE METADADOS DO .TXT DO CORTE
    # -------------------------------------------------------------

    def extrair_metadados(self, caminho_video: Path, caminho_txt: Optional[Path] = None) -> Dict[str, Any]:
        """
        Extrai título, descrição, hashtags e nota a partir do .txt correspondente ao vídeo.
        Garante conformidade com SEO de Shorts de Games.
        """
        if not caminho_txt or not caminho_txt.exists():
            caminho_txt = caminho_video.with_suffix(".txt")

        titulo = caminho_video.stem
        descricao_linhas = []
        tags = ["Shorts", "GTA6", "Neri Clipes", "Games", "Clipes"]
        nota = 8
        nota_encontrada_txt = False

        if caminho_txt and caminho_txt.exists():
            try:
                conteudo = caminho_txt.read_text(encoding="utf-8", errors="ignore").strip()
                linhas = [l.strip() for l in conteudo.splitlines() if l.strip()]

                if linhas:
                    titulo = linhas[0]

                # Coleta descrição até '--- Detalhes'
                desc_coleta = []
                for linha in linhas[1:]:
                    if "--- Detalhes" in linha:
                        break
                    desc_coleta.append(linha)
                    # Extrai hashtags
                    palavras = linha.split()
                    for p in palavras:
                        if p.startswith("#") and len(p) > 2:
                            tag_limpa = p.lstrip("#").replace(",", "").strip()
                            if tag_limpa and tag_limpa not in tags:
                                tags.append(tag_limpa)

                if desc_coleta:
                    descricao_linhas = desc_coleta

                # Procura a nota no texto
                for linha in linhas:
                    if "Nota Viralidade:" in linha:
                        partes = linha.split(":")[-1].strip().split("/")
                        try:
                            nota = int(partes[0].strip())
                            nota_encontrada_txt = True
                        except ValueError:
                            pass
            except Exception as e:
                logger.warning(f"Erro ao extrair metadados do txt: {e}")

        # Se não encontrou a nota no txt, tenta achar no nome do arquivo (ex: [Nota9]... ou ..._nota9.mp4)
        if not nota_encontrada_txt:
            import re
            match_nota = re.search(r"nota\s*(\d+)", caminho_video.stem, re.IGNORECASE)
            if match_nota:
                try:
                    nota = int(match_nota.group(1))
                except ValueError:
                    pass

        # Garante #Shorts no título respeitando limite de 100 caracteres do YouTube
        if "#Shorts" not in titulo and "#shorts" not in titulo.lower():
            if len(titulo) + 9 <= 100:
                titulo = f"{titulo} #Shorts"
            else:
                titulo = f"{titulo[:89].strip()}... #Shorts"

        # Garante descrição formatada com SEO e canal Neri Clipes
        if not descricao_linhas:
            descricao_linhas = [
                f"{titulo}",
                "",
                "O melhor das lives de GTA e Games você vê aqui no Neri Clipes!",
                "Inscreva-se e ative as notificações para mais cortes diários! 🔔",
                "",
                "#Shorts #GTA6 #NeriClipes #Clipes #Games"
            ]
        else:
            # Adiciona assinatura do canal se ainda não houver
            texto_desc = "\n".join(descricao_linhas)
            if "Neri Clipes" not in texto_desc:
                descricao_linhas.append("\n🎬 Canal Neri Clipes - O melhor das lives em formato Shorts!")
            if "#Shorts" not in texto_desc:
                descricao_linhas.append("#Shorts #NeriClipes")

        return {
            "titulo": titulo[:100],
            "descricao": "\n".join(descricao_linhas),
            "tags": tags[:20],
            "nota": nota
        }

    # -------------------------------------------------------------
    # PUBLICAÇÃO NO YOUTUBE (RESUMABLE UPLOAD)
    # -------------------------------------------------------------

    def publicar_short(
        self,
        caminho_video: Path,
        caminho_txt: Optional[Path] = None,
        privacidade: str = "unlisted",
        callback_progresso = None
    ) -> Dict[str, Any]:
        """
        Publica um vídeo vertical no YouTube Shorts com controle de cota e anti-duplicidade.
        privacidade: 'unlisted' (Não Listado), 'public' (Público), 'private' (Privado).
        """
        caminho_video = Path(caminho_video)
        if not caminho_video.exists():
            return {"sucesso": False, "erro": f"Arquivo de vídeo não encontrado: {caminho_video}"}

        # 1. Anti-duplicidade
        if self.ja_publicado(caminho_video):
            logger.warning(f"Vídeo já publicado anteriormente: {caminho_video.name}. Ignorando.")
            return {"sucesso": False, "erro": "Vídeo já consta como publicado anteriormente."}

        # 2. Cota diária
        if not self.pode_publicar():
            logger.error("Limite diário de cota atingido (máx 6 uploads nas últimas 24h).")
            return {"sucesso": False, "erro": "Limite diário de cota atingido (6/6)."}

        # 3. Metadados
        metadados = self.extrair_metadados(caminho_video, caminho_txt)
        titulo = metadados["titulo"]
        descricao = metadados["descricao"]
        tags = metadados["tags"]
        nota = metadados["nota"]

        # Mapeamento seguro de privacidade
        priv_map = {
            "não listado": "unlisted",
            "nao listado": "unlisted",
            "unlisted": "unlisted",
            "público": "public",
            "publico": "public",
            "public": "public",
            "privado": "private",
            "private": "private"
        }
        priv_formatada = priv_map.get(privacidade.lower().strip(), "unlisted")

        logger.info(f"Iniciando upload para YouTube Shorts: '{titulo}' [Privacidade: {priv_formatada}]")

        try:
            from googleapiclient.http import MediaFileUpload

            youtube = self._obter_servico()

            corpo_video = {
                "snippet": {
                    "title": titulo,
                    "description": descricao,
                    "tags": tags,
                    "categoryId": "20",  # Gaming
                    "defaultLanguage": "pt",
                    "defaultAudioLanguage": "pt"
                },
                "status": {
                    "privacyStatus": priv_formatada,
                    "selfDeclaredMadeForKids": False
                }
            }

            media = MediaFileUpload(
                str(caminho_video),
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024 * 2  # Chunks de 2MB
            )

            requisicao = youtube.videos().insert(
                part="snippet,status",
                body=corpo_video,
                media_body=media
            )

            resposta = None
            while resposta is None:
                status, resposta = requisicao.next_chunk()
                if status and callback_progresso:
                    progresso = int(status.progress() * 100)
                    callback_progresso(progresso)

            video_id = resposta.get("id")
            if not video_id:
                raise RuntimeError(f"Resposta da API não continha ID do vídeo: {resposta}")

            url_short = f"https://youtube.com/shorts/{video_id}"
            logger.info(f"✅ Vídeo publicado com sucesso no YouTube! URL: {url_short}")

            # Fecha descritor de arquivo aberto pelo MediaFileUpload no Windows
            try:
                if hasattr(media, "_fd") and media._fd:
                    media._fd.close()
            except Exception:
                pass
            del media
            del requisicao
            time.sleep(0.5)

            # Registra no histórico anti-duplicidade
            self.registrar_sucesso_upload(
                caminho_video=caminho_video,
                video_id=video_id,
                titulo=titulo,
                nota=nota,
                privacidade=priv_formatada
            )

            # Move os arquivos para prontos_para_postar/postados/
            self.organizar_postado(caminho_video, caminho_txt)

            return {
                "sucesso": True,
                "video_id": video_id,
                "url": url_short,
                "titulo": titulo,
                "cota_restante": self.cota_restante()
            }

        except Exception as e:
            logger.error(f"Erro ao publicar vídeo no YouTube: {e}", exc_info=True)
            try:
                from config.logger_config import registrar_erro_detalhado
                registrar_erro_detalhado(
                    "AgentePublicador.publicar_short",
                    f"Falha ao enviar vídeo '{titulo}' ({caminho_video.name})",
                    exc=e
                )
            except Exception:
                pass

            msg_erro = str(e)
            try:
                from googleapiclient.errors import HttpError
                if isinstance(e, HttpError):
                    import json
                    detalhes = json.loads(e.content.decode("utf-8", errors="ignore"))
                    erros_lista = detalhes.get("error", {}).get("errors", [])
                    razao = erros_lista[0].get("reason", "") if erros_lista else ""
                    msg_api = erros_lista[0].get("message", "") if erros_lista else ""

                    if razao == "uploadLimitExceeded":
                        msg_erro = "Limite diário de uploads atingido pelo canal no YouTube (uploadLimitExceeded). Canais novos ou não verificados têm limite estrito de 1 a 5 vídeos por dia."
                    elif razao == "quotaExceeded":
                        msg_erro = "Cota diária da API do Google Cloud excedida (quotaExceeded - 10.000 pontos). A cota reinicia à meia-noite (Horário do Pacífico)."
                    elif razao == "invalid_grant" or e.resp.status == 401:
                        msg_erro = "Sessão do YouTube expirada ou revogada (invalid_grant). Clique em 'Conectar Conta YouTube' na interface para refazer o login."
                    elif razao == "rateLimitExceeded":
                        msg_erro = "Limite temporário de taxa de requisições excedido. Aguarde alguns minutos antes de tentar novamente."
                    elif msg_api:
                        msg_erro = f"YouTube API ({razao or e.resp.status}): {msg_api}"
            except Exception:
                pass

            return {"sucesso": False, "erro": msg_erro}

    # -------------------------------------------------------------
    # ORGANIZAÇÃO DE PASTAS PÓS-ENVIO
    # -------------------------------------------------------------

    def organizar_postado(self, caminho_video: Path, caminho_txt: Optional[Path] = None) -> None:
        """Move o .mp4 e o .txt para a pasta prontos_para_postar/postados/ com retentativa segura."""
        self.pasta_postados.mkdir(parents=True, exist_ok=True)

        for caminho, tipo in [(caminho_video, "Vídeo"), (caminho_txt or caminho_video.with_suffix(".txt"), "Metadados")]:
            if caminho and Path(caminho).exists():
                destino = self.pasta_postados / Path(caminho).name
                movido = False
                for tentativa in range(5):
                    try:
                        shutil.move(str(caminho), str(destino))
                        logger.info(f"{tipo} arquivado com sucesso em: {destino}")
                        movido = True
                        break
                    except Exception as e:
                        time.sleep(0.6)
                if not movido:
                    try:
                        # Fallback: cópia + remoção posterior
                        shutil.copy2(str(caminho), str(destino))
                        os.remove(str(caminho))
                        logger.info(f"{tipo} arquivado via copy/remove em: {destino}")
                    except Exception as e_final:
                        logger.warning(f"Não foi possível mover {tipo} ({caminho.name}): {e_final}")

    # -------------------------------------------------------------
    # PONTE MOBILE VIA TELEGRAM BOT
    # -------------------------------------------------------------

    def _otimizar_video_para_telegram(self, caminho_video: Path) -> Optional[Path]:
        """
        Compacta de forma ultra-rápida um vídeo que excede 49MB para caber no limite de 50MB da Bot API do Telegram.
        Mantém resolução 1080x1920 e excelente qualidade na tela do celular.
        """
        try:
            import subprocess
            from agentes.agente_curador import obter_caminho_ffmpeg

            temp_dir = Path("buffer_temp")
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_saida = temp_dir / f"tg_opt_{int(time.time())}_{caminho_video.stem[:25]}.mp4"

            ffmpeg_bin = obter_caminho_ffmpeg()
            cmd = [
                ffmpeg_bin, "-y",
                "-i", str(caminho_video),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "27",
                "-maxrate", "5000k",
                "-bufsize", "10000k",
                "-c:a", "aac",
                "-b:a", "128k",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(temp_saida)
            ]

            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW

            logger.info(f"Compactando vídeo para o Telegram ({caminho_video.name})...")
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            if res.returncode == 0 and temp_saida.exists() and temp_saida.stat().st_size <= 49 * 1024 * 1024:
                logger.info(f"Vídeo otimizado para o Telegram: {temp_saida.stat().st_size / (1024*1024):.1f} MB")
                return temp_saida
        except Exception as e:
            logger.warning(f"Falha ao otimizar vídeo para o Telegram: {e}")
        return None

    def enviar_telegram(self, caminho_video: Path, caminho_txt: Optional[Path] = None) -> Dict[str, Any]:
        """
        Envia o .mp4 limpo e o texto correspondente para o chat/canal do Telegram.
        Permite postar rapidamente pelo celular no TikTok, Instagram Reels e Kwai sem marca d'água.
        Otimiza automaticamente vídeos maiores que 49MB para respeitar a cota de 50MB da Bot API.
        """
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.info("Envio Telegram ignorado: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não definidos no .env.")
            return {"sucesso": False, "erro": "Credenciais do Telegram não configuradas no .env."}

        caminho_video = Path(caminho_video)
        if not caminho_video.exists():
            candidato_postado = self.pasta_postados / caminho_video.name
            if candidato_postado.exists():
                caminho_video = candidato_postado
            else:
                return {"sucesso": False, "erro": f"Arquivo não encontrado: {caminho_video}"}

        tamanho_bytes = caminho_video.stat().st_size
        video_final = caminho_video
        temp_otimizado: Optional[Path] = None

        # Limite da Bot API do Telegram para envio direto é de 50MB (52.428.800 bytes)
        if tamanho_bytes > 49 * 1024 * 1024:
            logger.info(f"Vídeo possui {tamanho_bytes / (1024*1024):.1f} MB (> 49 MB). Otimizando cópia temporária para o Telegram...")
            temp_otimizado = self._otimizar_video_para_telegram(caminho_video)
            if temp_otimizado and temp_otimizado.exists():
                video_final = temp_otimizado
            else:
                msg = f"Arquivo muito grande para o Telegram ({tamanho_bytes / (1024*1024):.1f} MB > 50 MB)."
                logger.warning(msg)
                return {"sucesso": False, "erro": msg}

        metadados = self.extrair_metadados(caminho_video, caminho_txt)
        legenda = f"🎬 <b>{metadados['titulo']}</b>\n\n{metadados['descricao'][:800]}"

        import requests

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendVideo"
        logger.info(f"Enviando vídeo para o Telegram ({caminho_video.name})...")

        try:
            with open(video_final, "rb") as arq:
                dados = {
                    "chat_id": self.telegram_chat_id,
                    "caption": legenda,
                    "parse_mode": "HTML",
                    "supports_streaming": "true"
                }
                arquivos = {
                    "video": (caminho_video.name, arq, "video/mp4")
                }
                resp = requests.post(url, data=dados, files=arquivos, timeout=180)
                resultado = resp.json()

            if resultado.get("ok"):
                logger.info(f"✅ Vídeo enviado com sucesso para o Telegram (Chat ID: {self.telegram_chat_id})!")
                return {"sucesso": True}
            else:
                erro_desc = resultado.get("description", "Erro desconhecido")
                logger.error(f"Telegram API retornou erro: {erro_desc}")
                return {"sucesso": False, "erro": erro_desc}

        except Exception as e:
            logger.error(f"Erro na requisição para o Telegram: {e}")
            try:
                from config.logger_config import registrar_erro_detalhado
                registrar_erro_detalhado("AgentePublicador.enviar_telegram", f"Erro ao enviar {caminho_video.name} ao Telegram", exc=e)
            except Exception:
                pass
            return {"sucesso": False, "erro": str(e)}
        finally:
            if temp_otimizado and temp_otimizado.exists():
                try:
                    temp_otimizado.unlink(missing_ok=True)
                except Exception:
                    pass
