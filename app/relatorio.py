"""Relatório de uma sessão: tempo no ar, quedas, problemas, audiência e gráfico.
HTML independente (abre no navegador; Ctrl+P → Salvar como PDF)."""
from datetime import datetime, timedelta
from html import escape

from .rotulos import duracao, icone, rotulo

CORES = {"ok": "#2e9e5b", "problema": "#e0a100", "fora": "#c0392b", "sem": "#9a968d"}


def _situacao(v):
    problemas = [p for p in (v["problemas"] or "").split(",") if p]
    if "fora_do_ar" in problemas:
        return "fora"
    if v["ao_vivo"] is None or "sem_verificacao" in problemas:
        return "sem"
    if not v["ao_vivo"]:
        return "fora"
    return "problema" if problemas else "ok"


def resumo(banco, canal, inicio, fim):
    verificacoes = banco.verificacoes(canal, inicio, fim)
    conhecidas = [v for v in verificacoes if v["ao_vivo"] is not None]
    no_ar = [v for v in conhecidas if v["ao_vivo"]]
    publico = [v["espectadores"] for v in no_ar if v["espectadores"] is not None]

    por_problema = {}
    quedas = 0
    for inc in banco.incidentes(canal, inicio, fim):
        ini = max(datetime.fromisoformat(inc["inicio"]), inicio)
        fi = min(datetime.fromisoformat(inc["fim"]) if inc["fim"] else fim, fim)
        por_problema[inc["problema"]] = por_problema.get(inc["problema"], 0) + max(0, (fi - ini).total_seconds())
        quedas += inc["problema"] == "fora_do_ar"

    return {
        "inicio": inicio, "fim": fim, "verificacoes": verificacoes,
        "percentual_no_ar": round(100 * len(no_ar) / len(conhecidas), 1) if conhecidas else None,
        "quedas": quedas,
        "problemas": por_problema,
        "incidentes": banco.incidentes(canal, inicio, fim),
        "pico": max(publico) if publico else None,
        "media": round(sum(publico) / len(publico)) if publico else None,
    }


def texto(canal, r):
    linhas = [f"📋 Relatório · {canal}",
              f"{r['inicio']:%d/%m %H:%M} – {r['fim']:%H:%M}"]
    if r["percentual_no_ar"] is not None:
        linhas.append(f"No ar: {r['percentual_no_ar']:.0f}% do tempo".replace(".", ","))
    if r["problemas"]:
        for problema, segundos in r["problemas"].items():
            linhas.append(f"{icone(problema)} {rotulo(problema)}: {duracao_s(segundos)}")
    else:
        linhas.append("✅ Nenhum problema")
    if r["pico"] is not None:
        linhas.append(f"👥 Audiência: pico {r['pico']}, média {r['media']}")
    return "\n".join(linhas)


def duracao_s(segundos):
    return duracao(timedelta(seconds=segundos))


def _grafico(r):
    verificacoes = r["verificacoes"]
    if not verificacoes:
        return "<p>Sem verificações neste período.</p>"
    largura, altura, faixa = 700, 140, 14
    total = max(1, (r["fim"] - r["inicio"]).total_seconds())
    x = lambda v: round(40 + (datetime.fromisoformat(v["quando"]) - r["inicio"]).total_seconds() / total * (largura - 50), 1)
    publico = [v for v in verificacoes if v["espectadores"] is not None]
    maximo = max([v["espectadores"] for v in publico] + [1])
    y = lambda n: round(10 + (altura - 20) * (1 - n / maximo), 1)
    partes = [f'<svg viewBox="0 0 {largura} {altura + faixa + 30}" role="img" aria-label="Audiência e situação">']
    partes.append(f'<line x1="40" y1="{altura - 10}" x2="{largura - 10}" y2="{altura - 10}" stroke="#ccc"/>')
    partes.append(f'<text x="34" y="{y(maximo) + 4}" text-anchor="end" font-size="11" fill="#777">{maximo}</text>')
    partes.append(f'<text x="34" y="{altura - 6}" text-anchor="end" font-size="11" fill="#777">0</text>')
    if publico:
        pontos = " ".join(f"{x(v)},{y(v['espectadores'])}" for v in publico)
        partes.append(f'<polyline points="{pontos}" fill="none" stroke="#7a1f2b" stroke-width="2"/>')
    passo = (largura - 50) / max(1, len(verificacoes))
    for v in verificacoes:
        partes.append(f'<rect x="{x(v)}" y="{altura}" width="{max(1.5, passo):.1f}" height="{faixa}" '
                      f'fill="{CORES[_situacao(v)]}"><title>{v["quando"][11:16]} · {escape(v["problemas"] or "ok")}</title></rect>')
    partes.append(f'<text x="40" y="{altura + faixa + 20}" font-size="11" fill="#777">{r["inicio"]:%H:%M}</text>')
    partes.append(f'<text x="{largura - 10}" y="{altura + faixa + 20}" font-size="11" fill="#777" text-anchor="end">{r["fim"]:%H:%M}</text>')
    partes.append("</svg>")
    return "".join(partes)


def html(geral, canal, r):
    no_ar = "—" if r["percentual_no_ar"] is None else f"{r['percentual_no_ar']:.1f}%".replace(".", ",")
    linhas = "".join(
        f"<tr><td>{icone(i['problema'])} {escape(rotulo(i['problema']))}</td><td>{i['inicio'][11:16]}</td>"
        f"<td>{i['fim'][11:16] if i['fim'] else 'em aberto'}</td>"
        f"<td>{duracao_s(((datetime.fromisoformat(i['fim']) if i['fim'] else r['fim']) - datetime.fromisoformat(i['inicio'])).total_seconds())}</td></tr>"
        for i in r["incidentes"]
    ) or '<tr><td colspan="4">Nenhum problema registrado. ✅</td></tr>'
    legenda = " ".join(f'<span><i style="background:{c}"></i>{n}</span>' for n, c in
                       (("no ar", CORES["ok"]), ("com problema", CORES["problema"]),
                        ("fora do ar", CORES["fora"]), ("sem verificação", CORES["sem"])))
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Relatório · {escape(canal)}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;color:#1d1b16;max-width:820px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0}}.sub{{color:#6b675e}}.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}}
.kpi{{border:1px solid #e3ded3;border-radius:10px;padding:10px 12px}}.kpi b{{display:block;font-size:24px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e3ded3;padding:6px 8px;text-align:left}}
.leg span{{margin-right:14px;font-size:13px;color:#6b675e}}.leg i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}}
footer{{margin-top:28px;color:#6b675e;font-size:13px}}</style></head><body>
<h1>Relatório da transmissão · {escape(canal)}</h1>
<div class="sub">{escape(geral['cliente'])} · {r['inicio']:%d/%m/%Y} das {r['inicio']:%H:%M} às {r['fim']:%H:%M}</div>
<div class="kpis"><div class="kpi"><b>{no_ar}</b>do tempo no ar</div>
<div class="kpi"><b>{r['quedas']}</b>queda(s)</div>
<div class="kpi"><b>{r['pico'] if r['pico'] is not None else '—'}</b>pico de audiência</div>
<div class="kpi"><b>{r['media'] if r['media'] is not None else '—'}</b>audiência média</div></div>
<h2 style="font-size:17px">Audiência e situação</h2>{_grafico(r)}<div class="leg">{legenda}</div>
<h2 style="font-size:17px">Problemas</h2><table><tr><th>Problema</th><th>Início</th><th>Fim</th><th>Duração</th></tr>{linhas}</table>
<footer>Monitoramento: {escape(geral['responsavel'])} · verificação a cada {geral['intervalo_segundos']} s</footer>
</body></html>"""
