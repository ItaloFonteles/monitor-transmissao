"""Descobre se a transmissão está no ar e de onde puxar o vídeo.

- YouTube, Facebook e afins: yt-dlp (sem chave de API). Também traz quantas pessoas assistem.
- Endereço direto (.m3u8, rtmp://, srt://, arquivo): vai direto para o ffmpeg.
- "simulado": uma live de mentira gerada pelo ffmpeg, que cai, fica preta e fica muda
  de propósito, para testar e demonstrar os alertas.
"""
import math
from datetime import datetime

DIRETOS = ("rtmp://", "rtmps://", "rtsp://", "srt://", "udp://", "file:", "/")

# Live simulada: um ciclo de 8 minutos com um problema de cada tipo.
CICLO_SIMULADO = [
    (120, "ok"), (60, "preta"), (60, "ok"), (60, "sem_audio"),
    (60, "congelada"), (60, "fora_do_ar"), (60, "ok"),
]


def cena_simulada(agora):
    segundo = (agora.minute * 60 + agora.second) % sum(d for d, _ in CICLO_SIMULADO)
    for duracao, cena in CICLO_SIMULADO:
        if segundo < duracao:
            return cena
        segundo -= duracao
    return "ok"


def consultar(url, agora=None):
    """{'ao_vivo': True/False/None, 'stream', 'titulo', 'espectadores', 'erro'}.
    ao_vivo=None quando não deu para saber (erro de consulta, YouTube pedindo login…)."""
    if url.startswith("simulado"):
        cena = cena_simulada(agora or datetime.now())
        if cena == "fora_do_ar":
            return {"ao_vivo": False, "stream": None, "titulo": "", "espectadores": None, "erro": ""}
        minuto = (agora or datetime.now()).minute
        return {"ao_vivo": True, "stream": f"lavfi:{cena}", "titulo": "Sessão simulada",
                "espectadores": int(50 + 30 * math.sin(minuto / 5)), "erro": ""}

    if url.startswith(DIRETOS) or url.split("?")[0].endswith((".m3u8", ".mp4", ".ts", ".flv")):
        return {"ao_vivo": True, "stream": url, "titulo": "", "espectadores": None, "erro": ""}

    return _yt_dlp(url)


FORA_DO_AR = ("not currently live", "will begin", "premieres in", "is offline", "no video formats",
              "this live event", "has ended", "offline")


class _Calado:
    """O yt-dlp escreve os erros na tela mesmo em modo quieto; aqui eles viram resultado."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _yt_dlp(url):
    import yt_dlp  # só carrega quando precisa (os testes não dependem dele)

    opcoes = {"quiet": True, "no_warnings": True, "logger": _Calado(), "skip_download": True, "noplaylist": True,
              # O YouTube manda imagem e som em trilhas separadas: 360p basta para analisar.
              "format": "bv*[height<=360]+ba/b[height<=480]/b", "socket_timeout": 20}
    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as erro:  # yt-dlp levanta DownloadError e outros
        texto = str(erro).lower()
        if any(t in texto for t in FORA_DO_AR):
            return {"ao_vivo": False, "stream": None, "titulo": "", "espectadores": None, "erro": ""}
        return {"ao_vivo": None, "stream": None, "titulo": "", "espectadores": None,
                "erro": str(erro).replace("ERROR: ", "")[:300]}

    ao_vivo = info.get("live_status") == "is_live" or bool(info.get("is_live"))
    return {
        "ao_vivo": ao_vivo,
        "stream": [f["url"] for f in info.get("requested_formats") or [info]] if ao_vivo else None,
        "titulo": info.get("title") or "",
        "espectadores": info.get("concurrent_view_count"),
        "erro": "",
    }
