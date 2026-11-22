"""
Módulo AgenteCurador - GTA6_ClipHunter
Extrai áudio mono leve (32kbps) do trecho de 45 segundos e avalia com
Google Gemini 3.8 Flash (com fallback resiliente para 2.5 Flash ou aprovação automática).
Zero uso de modelos locais pesados (sem Whisper local), mantendo consumo de RAM < 1.5GB.
"""

import os
import sys
import json
import shutil
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

logger = logging.getLogger("ClipHunter.AgenteCurador")

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def obter_caminho_ffmpeg() -> str:
    """Busca o executável do ffmpeg no PATH ou em diretórios WinGet."""
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


class AgenteCurador:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        fallback_model: Optional[str] = None,
        temp_dir: str = "buffer_temp"
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.fallback_model = fallback_model or os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.client = None
        self.modo_teste = os.getenv("MODO_TESTE", "false").lower() in ("true", "1", "sim", "yes")
        self.auto_aprovar = self.modo_teste or (os.getenv("AUTO_APROVAR", "false").lower() in ("true", "1", "sim", "yes"))
        if self.auto_aprovar:
            logger.info("Modo de Aprovação Ativa habilitado: Todos os momentos analisados serão aprovados e editados.")
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"Cliente Gemini inicializado com modelo {self.model_name}.")
            except Exception as e:
                logger.warning(f"Falha ao instanciar cliente Gemini: {e}")
        else:
            logger.warning("GEMINI_API_KEY não configurada no .env. Operando em modo de contingência (Aprovação Automática).")

    async def extrair_audio_mono_leve(
        self,
        segmentos_ts: List[Path],
        duracao_segundos: int = 45,
        trecho_pronto: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Extrai um arquivo de áudio leve (.mp3 mono, 32kbps) de exatamente 'duracao_segundos'.
        Se 'trecho_pronto' for fornecido, extrai diretamente desse arquivo congelado para garantir
        sincronia absoluta (0.000s a 45.000s) entre as legendas da IA e o vídeo renderizado.
        """
        if not trecho_pronto and not segmentos_ts:
            logger.error("Nenhum segmento .ts fornecido para extração de áudio.")
            return None

        caminho_mp3 = self.temp_dir / f"curadoria_temp_{int(asyncio.get_event_loop().time())}.mp3"
        caminho_concat_txt = self.temp_dir / f"concat_audio_{int(asyncio.get_event_loop().time())}.txt"

        try:
            if trecho_pronto and trecho_pronto.exists():
                cmd = [
                    obter_caminho_ffmpeg(),
                    "-y",
                    "-loglevel", "error",
                    "-i", str(trecho_pronto.resolve()),
                    "-t", str(duracao_segundos),
                    "-vn",
                    "-af", "asetpts=PTS-STARTPTS",
                    "-acodec", "libmp3lame",
                    "-b:a", "32k",
                    "-ac", "1",
                    "-ar", "16000",
                    "-threads", "2",
                    str(caminho_mp3.resolve())
                ]
            else:
                with open(caminho_concat_txt, "w", encoding="utf-8") as f:
                    for seg in segmentos_ts:
                        linha = f"file '{seg.resolve().as_posix()}'\n"
                        f.write(linha)

                cmd = [
                    obter_caminho_ffmpeg(),
                    "-y",
                    "-loglevel", "error",
                    "-f", "concat",
                    "-safe", "0",
                    "-sseof", f"-{duracao_segundos}",
                    "-i", str(caminho_concat_txt.resolve()),
                    "-t", str(duracao_segundos),
                    "-vn",
                    "-af", "asetpts=PTS-STARTPTS",
                    "-acodec", "libmp3lame",
                    "-b:a", "32k",
                    "-ac", "1",
                    "-ar", "16000",
                    "-threads", "2",
                    str(caminho_mp3.resolve())
                ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"Erro ao extrair áudio MP3: {stderr.decode().strip()}")
                return None

            if caminho_mp3.exists() and caminho_mp3.stat().st_size > 0:
                logger.info(f"Áudio leve extraído com sucesso: {caminho_mp3.name} ({caminho_mp3.stat().st_size / 1024:.1f} KB).")
                return caminho_mp3

        except Exception as e:
            logger.error(f"Exceção ao extrair áudio do clipe: {e}")
        finally:
            if caminho_concat_txt.exists():
                try:
                    caminho_concat_txt.unlink()
                except Exception:
                    pass

        return None

    async def avaliar_clipe(
        self,
        caminho_audio: Optional[Path],
        streamer_info: Dict[str, Any],
        mensagens_chat: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Envia o áudio de 45s + chat para o Gemini 3.8 Flash e obtém JSON estruturado.
        Se ocorrer 404/503, tenta fallback para gemini-2.5-flash.
        Se ocorrer 429, timeout ou ausência de chave, retorna aprovação segura de contingência.
        """
        nome_streamer = streamer_info.get("nome", "Streamer")
        hashtags = streamer_info.get("hashtags", "#gta6 #clips")

        titulo_padrao = f"MOMENTO INSANO NA LIVE DO {nome_streamer.upper()}!"
        # Fallback padrão garantido para nunca perder um momento
        decisao_contingencia = {
            "aprovado": True,
            "nota_viralidade": 8,
            "titulo_shorts": titulo_padrao,
            "descricao_post": f"Olha o que aconteceu ao vivo na live do {nome_streamer} jogando GTA 6!\nAssista até o fim!\n{hashtags}",
            "legendas": [
                {"inicio": 0.5, "fim": 4.5, "texto": titulo_padrao}
            ],
            "metadados": {"modelo_usado": "contingencia_local", "fallback": True}
        }

        if not self.client or not caminho_audio or not caminho_audio.exists():
            logger.warning("Gemini Client ou áudio indisponível. Aplicando aprovação de contingência.")
            return decisao_contingencia

        try:
            chat_formatado = "\n".join(mensagens_chat[-20:]) if mensagens_chat else "Sem mensagens no chat."

            prompt_texto = f"""Você é o ClipHunter AI, um editor sênior e estrategista de conteúdo focado em viralizar no YouTube Shorts e TikTok com os melhores cortes e momentos épicos de lives de streamers (gameplay, reações, humor, novidades de lançamentos e opiniões marcantes).

Analise o áudio deste trecho de 45 segundos da live do streamer '{nome_streamer}'.
MENSAGENS RECENTES DO CHAT NO MOMENTO DO CORTE:
{chat_formatado}

CRITÉRIOS DE AVALIAÇÃO (SE QUALQUER UM FOR VERDADEIRO, APROVE = TRUE):
1. **GAMEPLAY INTENSA, JOGADAS OU DESFECHOS MARCANTES:**
   - Tiroteios, clutches, perseguições com a polícia, mortes inesperadas, acidentes hilários, bugs bizarros ou vitórias épicas.
2. **MODO LANÇAMENTO GTA VI (PRIORIDADE MÁXIMA — NOTA 9 A 10):**
   - Primeiras impressões do mapa (Vice City, Leonida, praias, pântanos, Lucia e Jason), choque com gráficos/física/realismo de NPCs e água.
   - Bugs engraçados de Dia 1, mecânicas novas descobertas ao vivo, easter eggs/referências a GTAs antigos (CJ, Tommy, Trevor) e reações a cutscenes ou missões marcantes.
   -> SE FOR QUALQUER DESCOBERTA, REAÇÃO OU MOMENTO MARCANTE DE GTA VI, APROVE IMEDIATAMENTE E DÊ NOTA 9 OU 10!
3. **HUMOR, ZOALHEIRA E REAÇÕES ESPONTÂNEAS:**
   - Risadas explosivas, sustos, gritos, choques, zoações ou comemorações.
4. **OPINIÃO SINCERA OU DEBATE POLÊMICO:**
   - Streamer expressando opiniões fortes sobre o jogo, indústria gamer ou interagindo com o público de forma que gere muitos comentários.

QUANDO REPROVAR (aprovado = false):
- Apenas silêncio absoluto ou música de fundo sem nenhuma fala relevante.
- Streamer ausente da cadeira (AFK) ou tela de carregamento longa sem comentário.
- Conversa sobre assuntos burocráticos ou totalmente sem relação com games/entretenimento/humor.

5. **TRANSCRIÇÃO DE FALAS REAIS PARA LEGENDAS SINCRONIZADAS (ESTILO SHORTS / TIKTOK):**
   - Transcreva com fidelidade absoluta as falas e conversas REAIS e EXATAS que você escutar no áudio (streamer, pessoas no jogo, Discord, etc.).
   - PROIBIDO gerar legendas genéricas, clichês ou frases de efeito inventadas (como 'MOMENTO ÉPICO', 'ASSISTA ATÉ O FINAL', 'OLHA ISSO', 'INSANO NA LIVE'). Transcreva ESTRITAMENTE o que foi falado no áudio!
   - Divida em blocos curtos e dinâmicos (de 2 a 5 palavras por bloco) em MAIÚSCULAS.
   - **SINCRONIA REAL DE TIMESTAMPS (MUITO IMPORTANTE):** O áudio tem duração total aproximada de 45 segundos (de 0.0s até 45.0s). Respeite com rigor o segundo EXATO em que cada frase começa ("inicio") e termina ("fim") ao longo de TODO o áudio (inclusive depois dos 20s, 30s e 40s!). NUNCA acumule todas as falas nos primeiros segundos se houver pausas ou silêncios entre elas.
   - Se houver silêncio ou música sem fala, deixe o intervalo vazio (não invente legenda).
   - **AUTOCENSURA LEVE ANTI-RESTRIÇÃO (TIKTOK / YOUTUBE / REELS):** Nas legendas, substitua uma vogal por `*` em palavras sensíveis de armas, violência explícita, drogas ou palavrões pesados (ex.: `F*ZIL`, `P*STOLA`, `ARM*`, `T*RO`, `M*TA`, `M*TOU`, `M*RREU`, `S*NGUE`, `DR*GA`, `P*RRA`, `C*RALHO`, `F*DA`, `M*RDA`, `P*TA`). Mantenha a leitura natural e fluida.

ESTRUTURA DOS METADADOS DE SAÍDA:
- "aprovado": booleano (true ou false)
- "nota_viralidade": número inteiro de 1 a 10 (se for momento empolgante ou assunto hype, dê pelo menos nota 8!)
- "titulo_shorts": string curta (MÁXIMO 60 CARACTERES), com gancho magnético de alta curiosidade, **SEM palavrões e SEM palavras como 'matar', 'arma', 'fuzil', 'tiro' ou 'sangue'** (use termos limpos como "AMASSOU", "DEITOU GERAL", "CAOS TOTAL", "REAÇÃO INSANA", "ISSO REALMENTE ACONTECEU?!")
- "descricao_post": string com 2 linhas curtas atiçando a discussão nos comentários + as hashtags:
{hashtags}
- "legendas": lista de objetos contendo "inicio" (float em segundos), "fim" (float em segundos) e "texto" (string curta em MAIÚSCULAS)

Responda OBRIGATORIAMENTE em formato JSON válido contendo exatamente estas chaves:
- "aprovado": booleano (true ou false)
- "nota_viralidade": número inteiro (1 a 10)
- "titulo_shorts": string (máximo 60 caracteres)
- "descricao_post": string (texto + hashtags)
- "legendas": array de objetos [{{"inicio": float, "fim": float, "texto": string}}]
"""

            # Leitura dos bytes do MP3
            try:
                with open(caminho_audio, "rb") as f:
                    audio_bytes = f.read()
            except Exception as e:
                logger.error(f"Erro ao ler arquivo de áudio {caminho_audio}: {e}")
                return decisao_contingencia

            # Tentativa com cascata inteligente de modelos para garantir legendagem real e contornar cotas 429/503
            candidatos = [
                self.model_name,
                self.fallback_model,
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
                "gemini-3.8-flash"
            ]
            modelos_para_tentar = [m for i, m in enumerate(candidatos) if m and m not in candidatos[:i]]

            for modelo in modelos_para_tentar:
                try:
                    logger.info(f"Enviando trecho para análise com o modelo '{modelo}'...")
                    from google.genai import types

                    partes = [
                        types.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3"),
                        prompt_texto
                    ]

                    config = types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )

                    # Chamada assíncrona não-bloqueante com timeout de 25s
                    resposta = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.client.models.generate_content,
                            model=modelo,
                            contents=partes,
                            config=config
                        ),
                        timeout=25.0
                    )

                    if resposta and resposta.text:
                        texto_limpo = resposta.text.strip()
                        if texto_limpo.startswith("```"):
                            linhas_json = [l for l in texto_limpo.split("\n") if not l.strip().startswith("```")]
                            texto_limpo = "\n".join(linhas_json).strip()

                        resultado = json.loads(texto_limpo)
                        resultado.setdefault("legendas", [])
                        if self.auto_aprovar:
                            resultado["aprovado"] = True
                            if not resultado.get("titulo_shorts"):
                                resultado["titulo_shorts"] = f"MOMENTO INSANO NA LIVE DO {nome_streamer.upper()}!"
                            if resultado.get("nota_viralidade", 0) < 7:
                                resultado["nota_viralidade"] = 8

                        # Se não gerou legendas mas tem título, gera legenda com o título do vídeo nos primeiros segundos
                        if not resultado.get("legendas"):
                            tit = resultado.get("titulo_shorts", f"AO VIVO COM {nome_streamer.upper()}")
                            resultado["legendas"] = [
                                {"inicio": 0.5, "fim": 4.0, "texto": tit.upper()}
                            ]

                        resultado["metadados"] = {"modelo_usado": modelo, "fallback": (modelo != self.model_name)}
                        num_legendas = len(resultado.get("legendas", []))
                        logger.info(
                            f"Avaliação concluída por {modelo}: Aprovado={resultado.get('aprovado')} "
                            f"| Nota={resultado.get('nota_viralidade')} | Título='{resultado.get('titulo_shorts')}' "
                            f"| {num_legendas} falas legendadas"
                        )
                        return resultado

                except Exception as e:
                    msg_erro = str(e)
                    logger.warning(f"Erro ao consultar modelo {modelo}: {msg_erro}")
                    logger.info("Tentando próximo modelo de IA da cascata...")
                    continue

            logger.warning("Falha em todos os modelos de IA ou API offline. Recorrendo à aprovação automática.")
            return decisao_contingencia
        except Exception as e:
            logger.error(f"Erro inesperado no AgenteCurador: {e}. Usando aprovação de contingência.")
            return decisao_contingencia
