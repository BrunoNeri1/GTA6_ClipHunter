# 📖 Guia Completo de Uso - Publicação e Automação (ClipHunter AI / Canal Neri Clipes)

Este guia reúne todas as instruções e detalhes técnicos para operar a camada de publicação no YouTube Shorts, ponte mobile via Telegram e agendamento de envios do **ClipHunter AI**.

---

## 1. Conexão com a YouTube Data API v3 (Canal Neri Clipes)

### Passo 1: Obter o `client_secret.json`
1. Acesse o [Google Cloud Console](https://console.cloud.google.com/).
2. Crie ou selecione um projeto (ex: `Neri Clipes Automação`).
3. No menu **APIs e Serviços > Biblioteca**, pesquise por **YouTube Data API v3** e clique em **Ativar**.
4. Em **Tela de permissão OAuth**:
   - Tipo de usuário: **Externo**.
   - Preencha o nome do app (`ClipHunter AI`) e o seu e-mail.
   - Em **Usuários de teste**, adicione o e-mail da conta do canal **Neri Clipes**.
5. No menu **Credenciais**:
   - Clique em **+ Criar Credenciais > ID do cliente OAuth**.
   - Tipo de aplicativo: **Aplicativo para Computador** (*Desktop App*).
   - Clique em **Criar** e depois faça o download do arquivo JSON.
6. Renomeie o arquivo baixado para **`client_secret.json`** e cole-o na raiz do projeto (`c:\Projetos\GTA6_ClipHunter\client_secret.json`).
   *(Nota: O arquivo já está protegido no `.gitignore` para nunca vazar na internet).*

### Passo 2: Login com 1 Clique na Interface
1. Abra o programa:
   ```powershell
   .venv\Scripts\python.exe interface.py
   ```
2. No painel **Publicação Automática**, clique no botão **`🔑 Conectar Conta YouTube`**.
3. O navegador padrão será aberto automaticamente. Faça login com a conta do YouTube do canal **Neri Clipes** e autorize as permissões.
4. O programa criará o arquivo seguro `token_youtube.json`. O botão mudará para **`🔑 YouTube: Conectado ✅`**.
5. O token é renovado sozinho pela API sempre que expirar. Você não precisará fazer login novamente!

---

## 2. Regras de Proteção de Cota e Anti-Duplicidade

- **Limite Gratuito da API do YouTube:** 10.000 unidades por dia.
- **Consumo por Envio:** Cada chamada `videos.insert` gasta 1.600 unidades.
- **Limite Máximo Seguro:** **6 uploads diários** (1.600 × 6 = 9.600 unidades).
- **Janela Móvel de 24h:** O `AgentePublicador` calcula os envios nas últimas 24h de forma contínua. O indicador visual na tela mostra em tempo real: `📊 Cota: 0/6 hoje`.
- **Anti-Duplicidade:** Todo vídeo postado é registrado com ID e timestamp em `config/historico_uploads.json`. O programa nunca tentará reenviar um vídeo já postado, mesmo se reiniciar o computador.
- **Filtro de Nota Mínima:** No modo de upload automático ao vivo, você pode escolher se só publica vídeos **Nota 8+** (padrão equilibrado), **Nota 7+** (mais vídeos) ou **Nota 9+** (somente momentos épicos).

---

## 3. Fila de Envios em Lote ("Vídeos de Hoje")

Ideal para publicar de forma cadenciada cortes acumulados durante o dia ou a madrugada:

1. Clique no botão roxo **`📋 Fila de Envios / Vídeos de Hoje`**.
2. A janela modal exibirá todos os vídeos pendentes em `prontos_para_postar/` com nota, data e título.
3. Clique em **`✨ Marcar Todos de Hoje`** (ou marque individualmente os que preferir).
4. Escolha o intervalo entre postagens:
   - `Imediato (Sem intervalo)`
   - `30 minutos` (Recomendado para engajamento no algoritmo)
   - `1 hora`
   - `2 horas`
   - `3 horas`
5. Clique em **`🚀 Iniciar Fila Selecionada`**.
6. **Execução:**
   - O primeiro vídeo sobe na hora.
   - Os próximos aguardam o tempo configurado em segundo plano.
   - O progresso aparece na barra de status: `⏳ Fila Neri Clipes: 1/4 enviados | Próximo envio em 29m 45s`.
   - Se desejar interromper a qualquer momento, clique em **`⏹️ Cancelar Fila`**.

---

## 4. Ponte Mobile via Telegram (TikTok, Reels e Kwai)

Para publicar os mesmos cortes no Instagram Reels, TikTok e Kwai sem marca d'água:

1. Abra o arquivo `.env` na raiz do projeto e configure:
   ```env
   TELEGRAM_BOT_TOKEN=seu_token_do_botfather
   TELEGRAM_CHAT_ID=seu_chat_id_ou_canal_privado
   ```
2. Marque o checkbox **`📱 Enviar Cortes no Telegram (Reels/TikTok/Kwai)`** na interface.
3. Cada clipe finalizado será automaticamente enviado para o seu chat privado ou canal do Telegram com a legenda completa e hashtags prontas.
4. Basta abrir o Telegram no celular, baixar o vídeo e postar diretamente nos apps das outras redes.

---

## 5. Limpeza Visual e Organização de Pastas

Para manter a pasta `prontos_para_postar/` sempre limpa e organizada:
- Assim que um corte é publicado com sucesso no YouTube Shorts, o arquivo `.mp4` e o arquivo `.txt` correspondentes são movidos automaticamente para a subpasta:
  ```
  prontos_para_postar/postados/
  ```
- Na pasta principal ficam apenas os vídeos novos que ainda não foram publicados.

---

## 6. Auto-Encerramento por Inatividade (Auto-Stop)

- Se a live do streamer cair ou todos os canais configurados estiverem offline por **mais de 10 minutos consecutivos** (600 segundos), o Caçador encerra os processos em segundo plano automaticamente para economizar processamento e memória do seu computador.
- O evento fica registrado no histórico de logs da interface.

---

## 7. Atalho Rápido de Execução

- **Interface Gráfica Completa:**
  ```powershell
  .venv\Scripts\python.exe interface.py
  ```
- **Modo Terminal Direto:**
  ```powershell
  .venv\Scripts\python.exe main.py
  ```
- **Canal Específico via Terminal:**
  ```powershell
  .venv\Scripts\python.exe main.py paulinholokobr
  ```
