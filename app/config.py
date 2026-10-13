"""Lê o config.toml (canais e agenda das sessões) e as variáveis de ambiente (segredos)."""
import os
import tomllib
from datetime import datetime, time, timedelta

DIAS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "sáb": 5, "dom": 6}


def _hora(texto, onde):
    try:
        h, m = str(texto).split(":")
        return time(int(h), int(m))
    except ValueError:
        raise ValueError(f"{onde}: horário '{texto}' inválido (use \"09:00\")") from None


def _agenda(itens, onde):
    agenda = []
    for i, item in enumerate(itens, 1):
        dias = item.get("dias", "todos")
        if dias == "todos":
            numeros = set(range(7))
        else:
            invalidos = [d for d in dias if d.lower() not in DIAS]
            if invalidos:
                raise ValueError(f"{onde}, agenda #{i}: dia inválido {invalidos} (use seg, ter, qua, qui, sex, sab, dom)")
            numeros = {DIAS[d.lower()] for d in dias}
        inicio = _hora(item.get("inicio", ""), f"{onde}, agenda #{i}")
        fim = _hora(item.get("fim", ""), f"{onde}, agenda #{i}")
        if fim <= inicio:
            raise ValueError(f"{onde}, agenda #{i}: o fim ({fim:%H:%M}) precisa ser depois do início ({inicio:%H:%M})")
        agenda.append({"dias": numeros, "inicio": inicio, "fim": fim})
    return agenda


def janela_atual(agenda, agora):
    """(início, fim) da sessão marcada que inclui 'agora', ou None."""
    for item in agenda:
        if agora.weekday() in item["dias"]:
            inicio = datetime.combine(agora.date(), item["inicio"])
            fim = datetime.combine(agora.date(), item["fim"])
            if inicio <= agora < fim:
                return inicio, fim
    return None


def carregar(caminho):
    try:
        with open(caminho, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        raise ValueError(f"Não achei o arquivo de configuração: {caminho} (copie o config.exemplo.toml)") from None
    except tomllib.TOMLDecodeError as erro:
        raise ValueError(f"Erro de digitação no config.toml: {erro}.\n"
                         "Dica: confira se todo texto está entre aspas \"assim\".") from None

    geral = cfg.setdefault("geral", {})
    geral.setdefault("cliente", "Cliente")
    geral.setdefault("responsavel", "Ítalo Fonteles · italofonteles.dev")
    geral.setdefault("intervalo_segundos", 60)
    geral.setdefault("amostra_segundos", 10)
    geral.setdefault("falhas_para_alerta", 2)
    geral.setdefault("tolerancia_inicio_minutos", 10)
    geral.setdefault("silencio_db", -50)
    geral.setdefault("volume_alto_db", -8)
    geral.setdefault("avisar_inicio_e_fim", True)

    erros = []
    nomes = set()
    for i, canal in enumerate(cfg.get("canais", []), 1):
        nome = canal.get("nome")
        if not nome:
            erros.append(f"canal #{i}: falta 'nome'")
        elif nome in nomes:
            erros.append(f"canal #{i}: nome repetido '{nome}'")
        nomes.add(nome)
        if not canal.get("url"):
            erros.append(f"canal #{i} ({nome}): falta 'url'")
        try:
            canal["agenda"] = _agenda(canal.get("agenda", []), f"canal '{nome}'")
        except ValueError as erro:
            erros.append(str(erro))
    if not cfg.get("canais"):
        erros.append("nenhum canal em [[canais]]")
    if erros:
        raise ValueError("Erro no config.toml:\n- " + "\n- ".join(erros))

    cfg["segredos"] = {
        "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "webhook_url": os.getenv("WEBHOOK_URL", ""),
        "heartbeat_url": os.getenv("HEARTBEAT_URL", ""),
        "modo_teste": os.getenv("MODO_TESTE", "true").lower() == "true",
    }
    return cfg


def tolerancia(cfg):
    return timedelta(minutes=cfg["geral"]["tolerancia_inicio_minutos"])
