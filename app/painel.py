"""Painel ao vivo (atualiza sozinho) e relatório do dia de cada canal."""
from datetime import datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import relatorio
from .rotulos import icone, rotulo

ESTILO = """:root{--bg:#f7f5f0;--card:#fff;--txt:#1d1b16;--mut:#6b675e;--bor:#e3ded3}
@media (prefers-color-scheme:dark){:root{--bg:#16140f;--card:#211e18;--txt:#ece7dc;--mut:#a39e92;--bor:#38332a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 system-ui,sans-serif}
header{padding:16px;border-bottom:1px solid var(--bor)}h1{margin:0;font-size:20px}.mut{color:var(--mut);font-size:13px}
main{padding:16px;display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.canal{background:var(--card);border:1px solid var(--bor);border-left:6px solid var(--cor);border-radius:12px;padding:14px}
.canal h2{margin:0 0 4px;font-size:17px}.sit{font-weight:600;color:var(--cor)}ul{margin:8px 0 0;padding-left:18px;font-size:14px}
a{color:inherit}"""

SITUACOES = {
    "ok": ("#2e9e5b", "🟢 No ar, tudo certo"),
    "problema": ("#e0a100", "🟡 No ar, com problema"),
    "fora_agenda": ("#c0392b", "🔴 Fora do ar (sessão marcada)"),
    "fora": ("#9a968d", "⚪ Fora do ar"),
    "sem": ("#9a968d", "⚠️ Sem verificação"),
    "nunca": ("#9a968d", "… aguardando a primeira verificação"),
}


def situacao(ultima):
    if not ultima:
        return "nunca", []
    problemas = [p for p in (ultima["problemas"] or "").split(",") if p]
    if "fora_do_ar" in problemas:
        return "fora_agenda", problemas
    if ultima["ao_vivo"] is None:
        return "sem", problemas
    if not ultima["ao_vivo"]:
        return "fora", []
    return ("problema" if problemas else "ok"), problemas


def pagina_status(cfg, banco, agora):
    hoje = agora.replace(hour=0, minute=0, second=0)
    cartoes = []
    for canal in cfg["canais"]:
        nome = canal["nome"]
        ultima = banco.ultima(nome)
        chave, problemas = situacao(ultima)
        cor, texto = SITUACOES[chave]
        detalhes = []
        if ultima:
            detalhes.append(f"verificado às {ultima['quando'][11:19]}")
            if ultima["espectadores"] is not None:
                detalhes.append(f"👥 {ultima['espectadores']} assistindo")
            if ultima["volume"] is not None:
                detalhes.append(f"volume médio {ultima['volume']:.0f} dB")
            if ultima["erro"]:
                detalhes.append(escape(ultima["erro"][:120]))
        incidentes = banco.incidentes(nome, hoje, agora + timedelta(seconds=1))
        lista = "".join(
            f"<li>{icone(i['problema'])} {escape(rotulo(i['problema']))}: {i['inicio'][11:16]}–"
            f"{i['fim'][11:16] if i['fim'] else '<b>agora</b>'}</li>" for i in incidentes
        ) or "<li>Nenhum problema hoje ✅</li>"
        agenda = ", ".join(f"{a['inicio']:%H:%M}–{a['fim']:%H:%M}" for a in canal["agenda"]) or "sem agenda"
        cartoes.append(f"""<section class="canal" style="--cor:{cor}">
<h2>{escape(nome)}</h2><div class="sit">{texto}</div>
{''.join(f'<div>{icone(p)} {escape(rotulo(p))}</div>' for p in problemas)}
<div class="mut">{' · '.join(detalhes)}</div><div class="mut">Sessões: {agenda}</div>
<ul>{lista}</ul>
<p class="mut"><a href="/relatorio?canal={quote(nome)}&data={agora:%Y-%m-%d}">Relatório de hoje</a></p></section>""")
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="15">
<title>Monitor de transmissão</title><style>{ESTILO}</style></head><body>
<header><h1>Monitor de transmissão · {escape(cfg['geral']['cliente'])}</h1>
<div class="mut">Atualiza sozinho a cada 15 s · {agora:%d/%m/%Y %H:%M:%S}</div></header>
<main>{''.join(cartoes)}</main></body></html>"""


def criar_servidor(cfg, banco, porta=8095, host="0.0.0.0"):
    nomes = {c["nome"] for c in cfg["canais"]}

    class Painel(BaseHTTPRequestHandler):
        def _enviar(self, codigo, corpo):
            dados = corpo.encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            url = urlparse(self.path)
            agora = datetime.now().replace(microsecond=0)
            if url.path == "/":
                return self._enviar(200, pagina_status(cfg, banco, agora))
            if url.path == "/relatorio":
                q = parse_qs(url.query)
                canal = q.get("canal", [""])[0]
                if canal not in nomes:
                    return self._enviar(404, "Canal não encontrado")
                try:
                    dia = datetime.strptime(q.get("data", [f"{agora:%Y-%m-%d}"])[0], "%Y-%m-%d")
                except ValueError:
                    return self._enviar(400, "Data inválida (use AAAA-MM-DD)")
                fim = min(dia + timedelta(days=1), agora)
                r = relatorio.resumo(banco, canal, dia, fim)
                return self._enviar(200, relatorio.html(cfg["geral"], canal, r))
            self._enviar(404, "Não encontrado")

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, porta), Painel)
