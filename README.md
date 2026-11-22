# ClipHunter AI 🎬⚡

> **Caçador Autônomo e Inteligente de Cortes Virais para YouTube Shorts, Reels e TikTok**

O **ClipHunter AI** é um sistema multiagente autônomo e assíncrono em Python desenvolvido para monitorar streams ao vivo (YouTube Live, Kick e Twitch), detectar momentos virais em tempo real via **Gatilho Duplo** (Picos de energia sonora RMS + Análise de mensagens do chat), avaliar e transcrever o contexto com IA multimodal do **Google Gemini** e renderizar automaticamente vídeos verticais 9:16 (1080x1920) com legendas dinâmicas e enquadramento inteligente de webcam.

Além da edição, o sistema possui integração nativa para **publicação direta no YouTube Shorts** (com controle rigoroso de cota de API) e **ponte mobile via Telegram** para postagem em 1 toque no Instagram Reels e TikTok.

---

## 🚀 Principais Funcionalidades

- **📡 Monitoramento Multiplataforma:** Suporte a streams ao vivo no YouTube, Kick e Twitch com resolução dinâmica via `yt-dlp`.
- **⚡ Gatilho Duplo de Hype:**
  - **Sensor de Áudio Contínuo:** Algoritmo matemático via `numpy` detecta gritos, gargalhadas e reações sonoras (RMS > 2.5x a média móvel).
  - **Sensor de Chat em Tempo Real:** Conexão assíncrona com o chat para medir volume de mensagens/segundo e detectar termos-chave (`CLIP`, `CARALHO`, `KKKKK`, etc.).
- **🧠 Curadoria e Legendas por IA (Google Gemini):**
  - Avaliação de viralidade com nota de 1 a 10 e títulos magnéticos.
  - Transcrição real e sincronizada das falas em português.
  - Sistema de resiliência com cascata de modelos (`gemini-3.5-flash` $\rightarrow$ `gemini-3.5-flash-lite`) contra estouro de cota.
- **🎯 Visão Computacional para Webcam:**
  - Calibração automática da câmera do streamer via IA (bounding box do rosto/câmera).
  - Ajuste manual e presets pré-configurados por criador.
- **🎬 Edição Automatizada 9:16 (FFmpeg):**
  - Layout empilhado: Webcam no topo (1080x672) e Gameplay centralizada na base (1080x1248).
  - Legendas dinâmicas estilizadas (`.ass`) com destaque visual amarelo e contorno preto grosso.
- **📤 Publicação Automática no YouTube Shorts:**
  - Autenticação OAuth2 com renovação automática de token.
  - Proteção de cota diária da API do YouTube (limite seguro de 6 envios/dia).
  - Fila de envios programada com intervalos configuráveis (30min, 1h, 2h).
- **📱 Ponte Mobile via Telegram:**
  - Disparo instantâneo do vídeo renderizado + descrição + hashtags para o Telegram pessoal do operador, facilitando a postagem manual no Reels e TikTok sem compressão ou marcas d'água.
- **💻 Interface Gráfica Moderna (Windows):**
  - Desenvolvida em CustomTkinter (tema escuro), com visualizador de áudio em tempo real, seletor de prioridade, botões de prévia e histórico de eventos.

---

## ⚙️ Otimização para Hardware de Entrada

O ClipHunter AI foi projetado especificamente para operar em computadores convencionais sem GPU dedicada:

- **Consumo de Memória:** Mantém-se estritamente abaixo de **~1.5 GB de RAM**.
- **Buffer Circular Contínuo:** Fatias leves de 30 segundos (`seg_%05d.ts`) gravadas com `-c copy` (zero consumo de CPU).
- **Proteção de SSD:** Rotina em segundo plano que recicla fatias com mais de 4 minutos ou se o diretório de buffer exceder 500MB.
- **Renderização Econômica:** Comandos FFmpeg executados com `-preset ultrafast -threads 2` e flags de ocultação de processo no Windows (`CREATE_NO_WINDOW`).
- **Sem Dependência de Whisper Local:** A transcrição é realizada remotamente via API multimodal com envio de arquivos de áudio mono ultra-leves a 32kbps (~180KB).

---

## 📁 Estrutura do Projeto

```text
GTA6_ClipHunter/
├── agentes/
│   ├── __init__.py              # Pacote de agentes
│   ├── vigia_stream.py          # Monitoramento de stream e buffer circular .ts
│   ├── radar_hype.py            # Gatilho duplo (Chat + Medidor de Áudio RMS)
│   ├── agente_curador.py        # Curadoria e legendas via Google Gemini
│   ├── agente_editor.py         # Montagem do vídeo 9:16 e renderização FFmpeg
│   └── agente_publicador.py     # Upload YouTube Shorts e ponte Telegram
├── config/
│   ├── logger_config.py         # Configuração de rotação de logs
│   └── streamers.json           # Lista de streamers e coordenadas de webcam
├── buffer_temp/                 # Diretório temporário de fatias .ts (volátil)
├── logs/                        # Logs de execução e depuração
├── prontos_para_postar/         # Vídeos finais .mp4 e metadados .txt prontos
├── .env.example                 # Modelo de variáveis de ambiente
├── requirements.txt             # Dependências Python
├── abrir_janela.bat             # Atalho de inicialização rápida no Windows
├── interface.py                 # Interface Gráfica (GUI) em CustomTkinter
├── main.py                      # Orquestrador assíncrono via linha de comando
└── calibrar_webcam.py           # Ferramenta auxiliar de calibração de webcam
```

---

## 🛠️ Instalação e Configuração

### 1. Pré-requisitos
- **Python 3.11 ou superior**
- **FFmpeg 6.0+** instalado no PATH do Windows. (Instalação rápida via PowerShell: `winget install -e --id Gyan.FFmpeg`)
- **Git**

### 2. Clonar o Repositório e Criar Ambiente Virtual
```powershell
git clone https://github.com/SEU_USUARIO/GTA6_ClipHunter.git
cd GTA6_ClipHunter

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configurar as Variáveis de Ambiente
Copie o arquivo de exemplo e crie seu `.env`:
```powershell
copy .env.example .env
```

Abra o arquivo `.env` e configure suas chaves:
```env
# Google AI Studio (Obrigatório para IA e Curadoria)
GEMINI_API_KEY=sua_chave_gemini_aqui
GEMINI_MODEL=gemini-3.5-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite

# Configurações de Trabalho
BUFFER_DIR=buffer_temp
OUTPUT_DIR=prontos_para_postar
MODO_TESTE=false
LOG_LEVEL=INFO

# Telegram Bot (Opcional - Para receber cortes no celular)
TELEGRAM_BOT_TOKEN=seu_bot_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui
```

### 4. Configurar Upload no YouTube (Opcional)
Para habilitar uploads automáticos no YouTube Shorts:
1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) e crie um projeto.
2. Ative a **YouTube Data API v3**.
3. Em **Credenciais**, crie um **ID do cliente OAuth** (Tipo: *Aplicativo para Computador*).
4. Baixe o arquivo JSON, renomeie-o para **`client_secret.json`** e salve-o na raiz do projeto.
5. Na interface do ClipHunter, clique em **`🔑 Conectar Conta YouTube`** para autorizar no navegador. O token seguro será armazenado localmente em `token_youtube.json` (já protegido no `.gitignore`).

---

## ▶️ Como Executar

### Opção A: Interface Gráfica (Recomendada)
Dê um duplo clique no arquivo **`abrir_janela.bat`** ou execute:
```powershell
.\.venv\Scripts\python.exe interface.py
```

### Opção B: Linha de Comando (CLI)
Para iniciar a varredura automática por ordem de prioridade definida em `config/streamers.json`:
```powershell
.\.venv\Scripts\python.exe main.py
```

Para monitorar um canal ou URL específica diretamente:
```powershell
.\.venv\Scripts\python.exe main.py paulinholokobr
.\.venv\Scripts\python.exe main.py https://kick.com/coringa
```

---

## 🔒 Segurança e Privacidade

- **Proteção de Chaves:** O arquivo `.env`, credenciais OAuth (`client_secret*.json`, `token_youtube*.json`), históricos e logs estão rigorosamente isolados pelo `.gitignore`.
- **Zero Vazamento:** Nenhuma chave de API ou credencial privada é comitada no controle de versão.
- **Armazenamento Local:** Todos os dados processados e vídeos renderizados permanecem exclusivamente em seu computador.

---

## 📄 Licença

Este projeto é disponibilizado para fins educacionais e de automação de conteúdo. Consulte os termos de serviço das plataformas monitoradas ao utilizar este software.
