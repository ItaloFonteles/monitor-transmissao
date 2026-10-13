"""Nomes e ícones dos problemas, usados nos alertas, no painel e no relatório."""

PROBLEMAS = {
    "fora_do_ar": ("🔴", "transmissão fora do ar"),
    "preta": ("⬛", "tela preta"),
    "sem_video": ("⬛", "sem imagem"),
    "congelada": ("🧊", "imagem congelada"),
    "sem_audio": ("🔇", "sem áudio"),
    "silencio": ("🤫", "silêncio prolongado"),
    "audio_alto": ("📢", "áudio estourando (volume muito alto)"),
    "sem_verificacao": ("⚠️", "não consigo verificar a transmissão"),
}


def rotulo(problema):
    return PROBLEMAS.get(problema, ("⚠️", problema))[1]


def icone(problema):
    return PROBLEMAS.get(problema, ("⚠️", problema))[0]


def duracao(delta):
    segundos = int(delta.total_seconds())
    if segundos < 60:
        return f"{segundos} s"
    horas, minutos = divmod(segundos // 60, 60)
    return f"{horas} h {minutos:02d} min" if horas else f"{minutos} min"
