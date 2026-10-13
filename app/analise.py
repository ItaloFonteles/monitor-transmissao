"""Analisa alguns segundos da transmissão com o ffmpeg: tela preta, imagem congelada,
silêncio e volume. Os detectores são do próprio ffmpeg (blackdetect, freezedetect,
silencedetect e volumedetect); aqui só lemos o que ele escreve."""
import re
import subprocess

# Um problema conta quando ocupa pelo menos esta fração da amostra (ex.: 6 de 10 s).
FRACAO = 0.6
# Silêncio é mais exigente: numa sessão há pausas normais (votação, troca de orador).
FRACAO_SILENCIO = 0.8
# Abaixo disso não há sinal nenhum: o encoder perdeu o som (mudo de verdade).
PICO_MUDO_DB = -70

CENAS = {
    "ok": ("testsrc2=size=320x180:rate=10", "sine=frequency=440:sample_rate=44100"),
    "preta": ("color=black:size=320x180:rate=10", "sine=frequency=440:sample_rate=44100"),
    "congelada": ("color=0x335577:size=320x180:rate=10", "sine=frequency=440:sample_rate=44100"),
    "sem_audio": ("testsrc2=size=320x180:rate=10", "anullsrc=r=44100:cl=mono"),
}


def comando(stream, segundos, silencio_db):
    """stream: um endereço, uma lista (vídeo e áudio separados, como no YouTube) ou "lavfi:cena"."""
    if isinstance(stream, str) and stream.startswith("lavfi:"):
        video, audio = CENAS[stream[6:]]
        entrada = ["-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio]
    else:
        entrada = []
        for endereco in [stream] if isinstance(stream, str) else stream:
            entrada += (["-rw_timeout", "20000000"] if endereco.startswith("http") else []) + ["-i", endereco]
    return [
        "ffmpeg", "-hide_banner", "-nostats", *entrada, "-t", str(segundos),
        "-vf", "blackdetect=d=1:pix_th=0.10,freezedetect=n=-60dB:d=2",
        "-af", f"silencedetect=n={silencio_db}dB:d=2,volumedetect",
        "-f", "null", "-",
    ]


def _duracao(saida, inicio_re, fim_re, segundos):
    """Soma os trechos detectados; um trecho sem fim vai até o fim da amostra."""
    inicios = [float(x) for x in re.findall(inicio_re, saida)]
    fins = [float(x) for x in re.findall(fim_re, saida)]
    total = 0.0
    for i, inicio in enumerate(inicios):
        fim = fins[i] if i < len(fins) else segundos
        total += max(0.0, min(fim, segundos) - inicio)
    return round(min(total, segundos), 1)


def interpretar(saida, segundos, volume_alto_db=-8):
    tem_video = bool(re.search(r"Stream #\S+.*: Video:", saida))
    tem_audio = bool(re.search(r"Stream #\S+.*: Audio:", saida))
    if not tem_video and not tem_audio:
        ultima = [l for l in saida.strip().splitlines() if l.strip()][-1:] or [""]
        return {"erro": f"não consegui abrir o vídeo: {ultima[0][:200]}", "problemas": []}

    preta = _duracao(saida, r"black_start:([\d.]+)", r"black_end:([\d.]+)", segundos)
    congelada = _duracao(saida, r"freeze_start: ([\d.]+)", r"freeze_end: ([\d.]+)", segundos)
    silencio = _duracao(saida, r"silence_start: (-?[\d.]+)", r"silence_end: ([\d.]+)", segundos)
    media = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", saida)
    maximo = re.search(r"max_volume: (-?[\d.]+|-inf) dB", saida)
    volume = float(media.group(1)) if media and media.group(1) != "-inf" else None
    pico = float(maximo.group(1)) if maximo and maximo.group(1) != "-inf" else None

    problemas = []
    if not tem_video:
        problemas.append("sem_video")
    elif preta >= FRACAO * segundos:
        problemas.append("preta")
    elif congelada >= FRACAO * segundos:
        problemas.append("congelada")
    if not tem_audio or pico is None or pico <= PICO_MUDO_DB:
        problemas.append("sem_audio")     # mudo: avisa rápido
    elif silencio >= FRACAO_SILENCIO * segundos:
        problemas.append("silencio")      # há sinal, mas baixo: só avisa se durar (minutos_silencio)
    elif volume >= volume_alto_db:
        problemas.append("audio_alto")

    return {"erro": "", "problemas": problemas, "preta": preta, "congelada": congelada,
            "silencio": silencio, "volume": volume, "pico": pico}


def analisar(stream, segundos=10, silencio_db=-50, volume_alto_db=-8):
    try:
        processo = subprocess.run(comando(stream, segundos, silencio_db), capture_output=True,
                                  text=True, errors="replace", timeout=segundos + 40)
    except subprocess.TimeoutExpired:
        return {"erro": "o vídeo não respondeu (tempo esgotado)", "problemas": []}
    except FileNotFoundError:
        return {"erro": "ffmpeg não está instalado", "problemas": []}
    return interpretar(processo.stderr, segundos, volume_alto_db)
