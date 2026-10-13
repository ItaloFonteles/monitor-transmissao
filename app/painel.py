"""Painel ao vivo: situação de cada canal, linha do tempo da última hora, audiência, volume
e incidentes do dia. A página se atualiza sozinha (busca /api/estado a cada 10 s).
Também serve o relatório do dia e os relatórios das sessões já encerradas."""
import json
import re
from datetime import datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import relatorio
from .rotulos import icone, rotulo

SITUACOES = {
    "ok": ("ok", "No ar, tudo certo"),
    "problema": ("alerta", "No ar, com problema"),
    "fora_agenda": ("erro", "Fora do ar na sessão marcada"),
    "fora": ("neutro", "Fora do ar"),
    "sem": ("alerta", "Sem verificação"),
    "nunca": ("neutro", "Aguardando a primeira verificação"),
}
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


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


def _situacao_ponto(v):
    chave, _ = situacao(v)
    return {"ok": "ok", "problema": "alerta", "sem": "alerta", "fora_agenda": "erro"}.get(chave, "neutro")


def proxima_sessao(agenda, agora):
    for dias in range(8):
        dia = agora.date() + timedelta(days=dias)
        inicios = sorted(datetime.combine(dia, a["inicio"]) for a in agenda if dia.weekday() in a["dias"])
        for inicio in inicios:
            if inicio > agora:
                return inicio
    return None


def _descrever_agenda(agenda):
    partes = []
    for a in agenda:
        dias = "todos os dias" if len(a["dias"]) == 7 else ", ".join(DIAS[d] for d in sorted(a["dias"]))
        partes.append(f"{dias} · {a['inicio']:%H:%M}–{a['fim']:%H:%M}")
    return partes


def estado(cfg, banco, agora):
    hoje = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    intervalo = cfg["geral"]["intervalo_segundos"]
    canais = []
    for canal in cfg["canais"]:
        nome = canal["nome"]
        ultima = banco.ultima(nome)
        chave, problemas = situacao(ultima)
        tom, texto = SITUACOES[chave]
        ultima_hora = banco.verificacoes(nome, agora - timedelta(hours=1), agora + timedelta(seconds=1))
        atraso = (agora - datetime.fromisoformat(ultima["quando"])).total_seconds() if ultima else None
        proxima = proxima_sessao(canal["agenda"], agora) if canal["agenda"] else None
        canais.append({
            "nome": nome,
            "link": canal["url"] if canal["url"].startswith("http") else None,
            "situacao": chave, "tom": tom, "texto": texto,
            "problemas": [{"icone": icone(p), "rotulo": rotulo(p)} for p in problemas],
            "titulo": (ultima or {}).get("titulo") or "",
            "espectadores": (ultima or {}).get("espectadores"),
            "volume": (ultima or {}).get("volume"),
            "erro": (ultima or {}).get("erro") or "",
            "verificado": ultima["quando"][11:19] if ultima else None,
            "segundos": round(atraso) if atraso is not None else None,
            "parado": atraso is not None and atraso > 3 * intervalo + 30,
            "agenda": _descrever_agenda(canal["agenda"]),
            "proxima": f"{DIAS[proxima.weekday()]} {proxima:%d/%m %H:%M}" if proxima else None,
            "linha": [{"m": round((datetime.fromisoformat(v["quando"]) - agora).total_seconds() / 60, 2),
                       "s": _situacao_ponto(v), "n": v["espectadores"],
                       "h": v["quando"][11:16]} for v in ultima_hora],
            "incidentes": [{"icone": icone(i["problema"]), "rotulo": rotulo(i["problema"]),
                            "inicio": i["inicio"][11:16], "fim": i["fim"][11:16] if i["fim"] else None}
                           for i in banco.incidentes(nome, hoje, agora + timedelta(seconds=1))],
            "relatorio": f"/relatorio?canal={quote(nome)}&data={agora:%Y-%m-%d}",
        })
    return {
        "cliente": cfg["geral"]["cliente"],
        "agora": f"{agora:%d/%m/%Y %H:%M:%S}",
        "intervalo": intervalo,
        "silencio_db": cfg["geral"]["silencio_db"],
        "volume_alto_db": cfg["geral"]["volume_alto_db"],
        "canais": canais,
    }


ESTILO = """
:root{--bg:#f6f4ef;--card:#fff;--txt:#1d1b16;--mut:#6b675e;--bor:#e4dfd4;--sutil:#f1ede5;
--ok:#1f8a4c;--alerta:#c98a00;--erro:#c0392b;--neutro:#8a867c;--marca:#7a1f2b}
@media (prefers-color-scheme:dark){:root{--bg:#14120e;--card:#1f1c17;--txt:#ece7dc;--mut:#a39e92;--bor:#36312a;
--sutil:#29251f;--ok:#3fbf73;--alerta:#e6ac2e;--erro:#ec6a5c;--neutro:#8f8a7f;--marca:#e0a3ab}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--marca)}.mut{color:var(--mut)}
header{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid var(--bor)}
h1{margin:0;font-size:20px;letter-spacing:-.01em}.sub{font-size:13px;color:var(--mut)}
.resumo{display:flex;gap:8px;flex-wrap:wrap}.pilula{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--bor);background:var(--card);border-radius:99px;padding:4px 12px;font-size:13px}
.ponto{width:9px;height:9px;border-radius:50%;background:var(--c,var(--neutro));flex:none}
main{padding:20px;display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));max-width:1400px;margin:0 auto}
.canal{background:var(--card);border:1px solid var(--bor);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.faixa{height:5px;background:var(--c)}
.corpo{padding:16px 18px;display:grid;gap:12px}
.topo{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.topo h2{margin:0;font-size:17px;line-height:1.3}.titulo{font-size:13px;color:var(--mut);margin-top:2px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.selo{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-size:13px;font-weight:600;color:var(--c);background:color-mix(in srgb,var(--c) 12%,transparent);border-radius:99px;padding:3px 10px}
.ao-vivo .ponto{animation:pulso 1.6s ease-in-out infinite}
@keyframes pulso{50%{box-shadow:0 0 0 5px color-mix(in srgb,var(--c) 25%,transparent)}}
@media (prefers-reduced-motion:reduce){.ao-vivo .ponto{animation:none}}
.problemas{display:grid;gap:4px;background:color-mix(in srgb,var(--alerta) 10%,transparent);border-radius:10px;padding:8px 12px;font-weight:600}
.problemas.erro{background:color-mix(in srgb,var(--erro) 10%,transparent)}
.metricas{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.metrica{background:var(--sutil);border-radius:10px;padding:8px 10px;min-width:0}.metrica b{display:block;font-size:20px;font-variant-numeric:tabular-nums;line-height:1.3}
.metrica span{font-size:12px;color:var(--mut)}
.medidor{position:relative;height:6px;border-radius:3px;background:var(--bor);margin:8px 0 2px}
.medidor i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--c)}
.medidor u{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--mut);opacity:.5}
.tempo svg{width:100%;height:auto;display:block}.eixo{display:flex;justify-content:space-between;font-size:11px;color:var(--mut)}
.secao{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 4px}
ul{margin:0;padding:0;list-style:none;display:grid;gap:3px;font-size:14px}
.rodape{margin-top:auto;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;border-top:1px solid var(--bor);padding:10px 18px;font-size:13px;color:var(--mut)}
.aviso{background:color-mix(in srgb,var(--erro) 12%,transparent);color:var(--erro);border-radius:10px;padding:8px 12px;font-size:14px;font-weight:600}
footer{text-align:center;font-size:12px;color:var(--mut);padding:8px 20px 28px}
@media (max-width:420px){main{padding:12px;grid-template-columns:1fr}.metrica b{font-size:17px}}
"""

SCRIPT = r"""
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const COR = {ok:"var(--ok)", alerta:"var(--alerta)", erro:"var(--erro)", neutro:"var(--neutro)"};
let dados = DADOS, recebido = Date.now();

function linhaDoTempo(c){
  const L = 300, A = 46, F = 10;
  const x = m => Math.max(0, Math.min(L, (60 + m) / 60 * L));
  const passo = L / 60 * (dados.intervalo / 60);
  const barras = c.linha.map(p => `<rect x="${x(p.m).toFixed(1)}" y="${A}" width="${Math.max(1.5, passo).toFixed(1)}" height="${F}" rx="1" fill="${COR[p.s]}"><title>${p.h}</title></rect>`).join("");
  const pub = c.linha.filter(p => p.n != null);
  const max = Math.max(1, ...pub.map(p => p.n));
  const y = n => (A - 6) - (A - 12) * n / max;
  const linha = pub.length > 1 ? `<polyline points="${pub.map(p => `${x(p.m).toFixed(1)},${y(p.n).toFixed(1)}`).join(" ")}" fill="none" stroke="var(--marca)" stroke-width="1.6" stroke-linejoin="round"/>` : "";
  const topo = pub.length ? `<text x="2" y="9" font-size="9" fill="var(--mut)">${max} assistindo (máx.)</text>` : `<text x="2" y="${A/2}" font-size="10" fill="var(--mut)">Sem dados de audiência na última hora</text>`;
  return `<svg viewBox="0 0 ${L} ${A + F}" role="img" aria-label="Última hora de ${esc(c.nome)}">
    <rect x="0" y="${A}" width="${L}" height="${F}" rx="2" fill="var(--sutil)"/>${barras}${linha}${topo}</svg>
    <div class="eixo"><span>há 60 min</span><span>há 30 min</span><span>agora</span></div>`;
}

function medidor(v){
  if (v == null) return `<b>—</b><span>volume</span>`;
  const pct = db => Math.max(0, Math.min(100, (db + 60) / 60 * 100));
  const cor = v <= dados.silencio_db ? "var(--alerta)" : v >= dados.volume_alto_db ? "var(--erro)" : "var(--ok)";
  return `<b>${Math.round(v)} dB</b><div class="medidor" style="--c:${cor}"><i style="width:${pct(v)}%"></i>
    <u style="left:${pct(dados.silencio_db)}%"></u><u style="left:${pct(dados.volume_alto_db)}%"></u></div><span>volume médio</span>`;
}

function haQuanto(s){
  if (s == null) return "—";
  s += Math.round((Date.now() - recebido) / 1000);
  return s < 60 ? `há ${s} s` : s < 3600 ? `há ${Math.floor(s/60)} min` : `há ${Math.floor(s/3600)} h`;
}

function cartao(c){
  const cor = COR[c.tom];
  const probs = c.problemas.length ? `<div class="problemas ${c.situacao === "fora_agenda" ? "erro" : ""}">${c.problemas.map(p => `<div>${p.icone} ${esc(p.rotulo)}</div>`).join("")}</div>` : "";
  const parado = c.parado ? `<div class="aviso">⚠️ Última verificação ${haQuanto(c.segundos)}: o monitor pode ter parado.</div>` : "";
  const erro = c.erro ? `<div class="mut" style="font-size:13px">${esc(c.erro)}</div>` : "";
  const incid = c.incidentes.length ? c.incidentes.map(i => `<li>${i.icone} ${esc(i.rotulo)} · ${i.inicio}–${i.fim ?? "<b>agora</b>"}</li>`).join("") : `<li class="mut">Nenhum problema hoje ✅</li>`;
  const sessao = c.agenda.length ? `Sessões: ${c.agenda.map(esc).join(" · ")}${c.proxima ? ` · próxima ${esc(c.proxima)}` : ""}` : "Sem agenda: avisa quando entra e sai do ar";
  return `<article class="canal ${c.situacao === "ok" || c.situacao === "problema" ? "ao-vivo" : ""}" style="--c:${cor}">
    <div class="faixa"></div><div class="corpo">
      <div class="topo"><div><h2>${esc(c.nome)}</h2>${c.titulo ? `<div class="titulo">${esc(c.titulo)}</div>` : ""}</div>
        <span class="selo"><span class="ponto"></span>${esc(c.texto)}</span></div>
      ${parado}${probs}${erro}
      <div class="metricas">
        <div class="metrica"><b>${c.espectadores ?? "—"}</b><span>assistindo</span></div>
        <div class="metrica">${medidor(c.volume)}</div>
        <div class="metrica"><b data-segundos="${c.segundos ?? ""}">${haQuanto(c.segundos)}</b><span>última verificação</span></div>
      </div>
      <div class="tempo"><p class="secao">Última hora</p>${linhaDoTempo(c)}</div>
      <div><p class="secao">Hoje</p><ul>${incid}</ul></div>
    </div>
    <div class="rodape"><span>${sessao}</span><span><a href="${esc(c.relatorio)}">Relatório de hoje</a>${c.link ? ` · <a href="${esc(c.link)}" target="_blank" rel="noopener">Abrir live ↗</a>` : ""}</span></div>
  </article>`;
}

function desenhar(){
  const conta = t => dados.canais.filter(c => t.includes(c.situacao)).length;
  document.getElementById("resumo").innerHTML = [
    ["var(--ok)", conta(["ok"]), "no ar"], ["var(--alerta)", conta(["problema", "sem"]), "com problema"],
    ["var(--erro)", conta(["fora_agenda"]), "fora do ar na sessão"], ["var(--neutro)", conta(["fora", "nunca"]), "sem transmissão"],
  ].map(([c, n, t]) => `<span class="pilula"><span class="ponto" style="--c:${c}"></span><b>${n}</b> ${t}</span>`).join("");
  document.getElementById("canais").innerHTML = dados.canais.map(cartao).join("");
  document.getElementById("hora").textContent = dados.agora;
}

async function atualizar(){
  try {
    const r = await fetch("/api/estado", {cache: "no-store"});
    if (r.ok) { dados = await r.json(); recebido = Date.now(); desenhar(); }
    document.getElementById("conexao").textContent = "";
  } catch (e) { document.getElementById("conexao").textContent = " · sem conexão com o monitor"; }
}
desenhar();
setInterval(atualizar, 10000);
setInterval(() => document.querySelectorAll("[data-segundos]").forEach(b => { if (b.dataset.segundos !== "") b.textContent = haQuanto(+b.dataset.segundos); }), 1000);
"""


def pagina_status(cfg, banco, agora):
    dados = json.dumps(estado(cfg, banco, agora), ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monitor de transmissão · {escape(cfg['geral']['cliente'])}</title><style>{ESTILO}</style></head><body>
<header><div><h1>Monitor de transmissão</h1>
<div class="sub">{escape(cfg['geral']['cliente'])} · atualizado em <span id="hora"></span><span id="conexao"></span> · <a href="/relatorios">Relatórios</a></div></div>
<div class="resumo" id="resumo"></div></header>
<main id="canais"></main>
<footer>Verifica cada canal a cada {cfg['geral']['intervalo_segundos']} s · {escape(cfg['geral']['responsavel'])}</footer>
<script>const DADOS = {dados};{SCRIPT}</script></body></html>"""


def pagina_relatorios(pasta):
    arquivos = sorted(Path(pasta).glob("relatorio-*.html"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if Path(pasta).is_dir() else []
    itens = "".join(
        f'<li><a href="/relatorios/{quote(a.name)}">{escape(a.stem.removeprefix("relatorio-").replace("-", " "))}</a> '
        f'<span class="mut">· {datetime.fromtimestamp(a.stat().st_mtime):%d/%m/%Y %H:%M}</span></li>' for a in arquivos
    ) or '<li class="mut">Nenhuma sessão encerrada ainda. O relatório sai sozinho no fim de cada transmissão.</li>'
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Relatórios das sessões</title>
<style>{ESTILO} main{{display:block;max-width:760px}} li{{padding:6px 0;border-bottom:1px solid var(--bor)}}</style></head><body>
<header><div><h1>Relatórios das sessões</h1><div class="sub"><a href="/">← Voltar ao painel</a></div></div></header>
<main><ul>{itens}</ul></main></body></html>"""


def criar_servidor(cfg, banco, porta=8095, host="0.0.0.0", pasta_relatorios="/dados/relatorios"):
    nomes = {c["nome"] for c in cfg["canais"]}
    pasta = Path(pasta_relatorios)

    class Painel(BaseHTTPRequestHandler):
        def _enviar(self, codigo, corpo, tipo="text/html; charset=utf-8"):
            dados = corpo.encode("utf-8") if isinstance(corpo, str) else corpo
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            url = urlparse(self.path)
            agora = datetime.now().replace(microsecond=0)
            if url.path == "/":
                return self._enviar(200, pagina_status(cfg, banco, agora))
            if url.path == "/api/estado":
                return self._enviar(200, json.dumps(estado(cfg, banco, agora), ensure_ascii=False),
                                    "application/json; charset=utf-8")
            if url.path == "/relatorios":
                return self._enviar(200, pagina_relatorios(pasta))
            if url.path.startswith("/relatorios/"):
                nome = unquote(url.path.removeprefix("/relatorios/"))
                arquivo = pasta / nome
                if not re.fullmatch(r"relatorio-[\w.\-]+\.html", nome) or not arquivo.is_file():
                    return self._enviar(404, "Relatório não encontrado")
                return self._enviar(200, arquivo.read_bytes())
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
                return self._enviar(200, relatorio.html(cfg["geral"], canal, relatorio.resumo(banco, canal, dia, fim)))
            self._enviar(404, "Não encontrado")

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, porta), Painel)
