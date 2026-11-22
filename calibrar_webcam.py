"""
Utilitário de Calibração de Webcam - GTA6_ClipHunter
Uso:
    python calibrar_webcam.py [slug_ou_url_ou_arquivo]

Exemplo:
    python calibrar_webcam.py coringa

Captura 1 frame da live atual, sobrepõe uma grade milimetrada de coordenadas (X, Y)
a cada 100 pixels com marcações numéricas e desenha o retângulo da webcam atual
para que você possa ajustar com precisão os valores de 'webcam_crop' no config/streamers.json.
Salva a imagem calibrada como 'calibracao_webcam.jpg'.
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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


def carregar_config_streamer(slug: str):
    """Carrega as configurações do streamer a partir do arquivo config/streamers.json."""
    caminho_config = Path("config/streamers.json")
    if not caminho_config.exists():
        return None

    try:
        with open(caminho_config, "r", encoding="utf-8") as f:
            dados = json.load(f)
            for s in dados.get("streamers", []):
                if s.get("slug", "").lower() == slug.lower():
                    return s
    except Exception:
        pass
    return None


def obter_url_stream(alvo: str) -> str:
    """Extrai URL do stream usando yt-dlp ou retorna o próprio caminho caso seja arquivo local."""
    if Path(alvo).exists() or alvo.startswith("http://") or alvo.startswith("https://") and ".m3u8" in alvo:
        return alvo

    url_canal = alvo if alvo.startswith("http") else f"https://kick.com/{alvo}"
    print(f"[*] Consultando stream da live via yt-dlp para '{url_canal}'...")

    try:
        res = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--get-url", "--no-playlist", "--no-warnings", url_canal],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=CREATE_NO_WINDOW
        )
        if res.returncode == 0:
            url_extraida = res.stdout.strip().split("\n")[0].strip()
            if url_extraida:
                return url_extraida
        else:
            print(f"[-] yt-dlp retornou erro: {res.stderr.strip()[:150]}")
    except Exception as e:
        print(f"[-] Erro ao executar yt-dlp: {e}")

    return url_canal


def capturar_frame(url_ou_arquivo: str, arquivo_saida_raw: Path) -> bool:
    """Captura 1 frame de vídeo usando FFmpeg."""
    ffmpeg_cmd = obter_caminho_ffmpeg()
    print(f"[*] Extraindo 1 frame da fonte de vídeo via FFmpeg...")

    cmd = [
        ffmpeg_cmd,
        "-y",
        "-loglevel", "error",
        "-i", url_ou_arquivo,
        "-vframes", "1",
        "-q:v", "2",
        str(arquivo_saida_raw.resolve())
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
        return res.returncode == 0 and arquivo_saida_raw.exists()
    except Exception as e:
        print(f"[-] Erro ao invocar FFmpeg: {e}")
        return False


def desenhar_grade_calibracao(caminho_imagem_raw: Path, caminho_final: Path, crop_config: dict = None) -> None:
    """Desenha linhas de coordenadas a cada 100px e destaca a área atual de webcam."""
    img = Image.open(caminho_imagem_raw).convert("RGB")
    largura, altura = img.size
    print(f"[*] Resolução do frame capturado: {largura}x{altura} pixels.")

    draw = ImageDraw.Draw(img)

    # Usa fonte padrão do Pillow
    fonte = ImageFont.load_default()

    # Desenha linhas verticais a cada 100 pixels
    for x in range(0, largura, 100):
        cor_linha = (0, 255, 128) if x % 200 == 0 else (0, 180, 100)
        draw.line([(x, 0), (x, altura)], fill=cor_linha, width=1)
        # Rótulo de coordenada X no topo e na base
        draw.text((x + 3, 5), f"X={x}", fill=(255, 255, 255), font=fonte)
        draw.text((x + 3, altura - 18), f"X={x}", fill=(255, 255, 255), font=fonte)

    # Desenha linhas horizontais a cada 100 pixels
    for y in range(0, altura, 100):
        cor_linha = (0, 255, 128) if y % 200 == 0 else (0, 180, 100)
        draw.line([(0, y), (largura, y)], fill=cor_linha, width=1)
        # Rótulo de coordenada Y na esquerda e na direita
        draw.text((5, y + 3), f"Y={y}", fill=(255, 255, 255), font=fonte)
        draw.text((largura - 45, y + 3), f"Y={y}", fill=(255, 255, 255), font=fonte)

    # Se houver configuração de crop existente, destaca em vermelho/amarelo
    if crop_config:
        x = crop_config.get("x", 20)
        y = crop_config.get("y", 720)
        w = crop_config.get("w", 360)
        h = crop_config.get("h", 240)

        caixa = [(x, y), (x + w, y + h)]
        # Desenha retângulo destacado
        draw.rectangle(caixa, outline=(255, 50, 50), width=4)
        texto_crop = f"WEBCAM ATUAL: x={x}, y={y}, w={w}, h={h}"
        draw.rectangle([(x, y - 22), (x + 320, y)], fill=(255, 50, 50))
        draw.text((x + 5, y - 18), texto_crop, fill=(255, 255, 255), font=fonte)

    img.save(caminho_final, "JPEG", quality=95)
    print(f"\n[+] Sucesso! Imagem de calibração gerada em: {caminho_final.resolve()}")
    print("=" * 70)
    print("COMO CALIBRAR A WEBCAM NO config/streamers.json:")
    print("1. Abra a imagem 'calibracao_webcam.jpg'.")
    print("2. Observe onde a webcam do streamer está localizada na imagem.")
    print("3. Identifique as coordenadas:")
    print("   - 'x': pixel horizontal onde a webcam começa (esquerda)")
    print("   - 'y': pixel vertical onde a webcam começa (topo)")
    print("   - 'w': largura total da webcam em pixels")
    print("   - 'h': altura total da webcam em pixels")
    print("4. Atualize a chave 'webcam_crop' do streamer correspondente.")
    print("=" * 70)


def main():
    slug_alvo = sys.argv[1] if len(sys.argv) > 1 else "coringa"
    streamer_info = carregar_config_streamer(slug_alvo)

    print("=" * 70)
    print(f"GTA6_ClipHunter - Calibrador de Webcam para: '{slug_alvo}'")
    print("=" * 70)

    url_ou_arquivo = obter_url_stream(slug_alvo)
    temp_raw = Path("buffer_temp/calibracao_raw.jpg")
    temp_raw.parent.mkdir(parents=True, exist_ok=True)
    saida_final = Path("calibracao_webcam.jpg")

    sucesso = capturar_frame(url_ou_arquivo, temp_raw)

    if not sucesso:
        print(f"\n[-] Não foi possível capturar frame ao vivo para '{slug_alvo}'.")
        print("    Verifique se a live está online ou passe o caminho de um arquivo .ts local:")
        print("    Exemplo: python calibrar_webcam.py buffer_temp/seg_00001.ts")
        sys.exit(1)

    crop_config = streamer_info.get("webcam_crop") if streamer_info else None
    desenhar_grade_calibracao(temp_raw, saida_final, crop_config)

    # Limpeza do temporário cru
    if temp_raw.exists():
        temp_raw.unlink()


if __name__ == "__main__":
    main()
