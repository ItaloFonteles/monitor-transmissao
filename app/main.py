"""Laço principal: verifica cada canal, decide os alertas e fecha o relatório de cada sessão."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import analise, fonte, relatorio
from .alertas import Alertas
from .banco import Banco
from .config import carregar, janela_atual, tolerancia
from .estado import EstadoCanal
from .rotulos import duracao, icone, rotulo


def log(texto):
    print(f"{datetime.now():%d/%m %H:%M:%S} {texto}", flush=True)


class Monitor:
    def __init__(self, cfg, banco, alertas, consultar=fonte.consultar, analisar=analise.analisar,
                 pasta_relatorios="/dados/relatorios", log=log):
        self.cfg, self.geral = cfg, cfg["geral"]
        self.banco, self.alertas = banco, alertas
        self.consultar, self.analisar = consultar, analisar
        self.pasta = Path(pasta_relatorios)
        self.log = log
        self.estados = {c["nome"]: EstadoCanal(self.geral["falhas_para_alerta"]) for c in cfg["canais"]}

    # ---------- verificação ----------
    def verificar(self, canal, agora):
        r = {**self.consultar(canal["url"], agora), "problemas": [], "volume": None}
        if r["ao_vivo"] and r["stream"]:
            a = self.analisar(r["stream"], self.geral["amostra_segundos"],
                              self.geral["silencio_db"], self.geral["volume_alto_db"])
            if a["erro"]:
                r["ao_vivo"], r["erro"] = None, a["erro"]
            else:
                r["problemas"], r["volume"] = a["problemas"], a.get("volume")
        return r

    def ciclo(self, agora=None):
        agora = agora or datetime.now().replace(microsecond=0)
        canais = self.cfg["canais"]
        with ThreadPoolExecutor(max_workers=min(4, len(canais))) as executor:
            resultados = list(executor.map(lambda c: self.verificar(c, agora), canais))
        for canal, r in zip(canais, resultados):
            self.processar(canal, r, agora)

    # ---------- decisões ----------
    def processar(self, canal, r, agora):
        nome, estado = canal["nome"], self.estados[canal["nome"]]
        janela = janela_atual(canal["agenda"], agora)

        if estado.janela and estado.janela != janela:  # a sessão marcada acabou
            self.fechar_sessao(canal, *estado.janela)
            estado.limpar()
            self.banco.fechar_abertos(nome, agora)
        if janela and estado.janela != janela:
            estado.sessao_inicio = janela[0]
        estado.janela = janela

        problemas = list(r["problemas"])
        if r["ao_vivo"] is None:
            problemas = ["sem_verificacao"]
        elif r["ao_vivo"] is False and janela:
            atrasada = agora >= janela[0] + tolerancia(self.cfg)
            caiu = estado.ultima_vez_no_ar is not None and estado.ultima_vez_no_ar >= janela[0]
            if atrasada or caiu:
                problemas = ["fora_do_ar"]

        eventos = estado.atualizar(agora, r["ao_vivo"], problemas, em_agenda=bool(janela))
        self.banco.registrar(nome, agora, r["ao_vivo"], r["espectadores"], problemas, r["volume"], r["erro"],
                             r.get("titulo") or "")

        for tipo, problema, desde in eventos:
            if tipo == "alerta":
                self.banco.abrir_incidente(nome, problema, desde)
                self.alertas.enviar(self._texto_alerta(nome, problema, desde, janela, estado, r),
                                    {"canal": nome, "problema": problema, "situacao": "alerta"})
            elif tipo == "resolvido":
                self.banco.fechar_incidente(nome, problema, agora)
                self.alertas.enviar(f"✅ {nome}: {rotulo(problema)} resolvido às {agora:%H:%M} "
                                    f"(durou {duracao(agora - desde)})",
                                    {"canal": nome, "problema": problema, "situacao": "resolvido"})
            elif tipo == "comecou" and self.geral["avisar_inicio_e_fim"]:
                titulo = f" · {r['titulo']}" if r.get("titulo") else ""
                self.alertas.enviar(f"🟢 {nome}: transmissão no ar às {agora:%H:%M}{titulo}")
            elif tipo == "encerrou":
                self.banco.fechar_abertos(nome, agora)
                if self.geral["avisar_inicio_e_fim"]:
                    self.alertas.enviar(f"⚪ {nome}: transmissão encerrada às {agora:%H:%M}")
                if not canal["agenda"]:
                    self.fechar_sessao(canal, estado.sessao_inicio or agora, agora)

    def _texto_alerta(self, nome, problema, desde, janela, estado, r):
        if problema == "fora_do_ar" and janela and (estado.ultima_vez_no_ar is None
                                                    or estado.ultima_vez_no_ar < janela[0]):
            return (f"🔴 {nome}: a sessão estava marcada para {janela[0]:%H:%M} "
                    "e a transmissão ainda não está no ar")
        if problema == "sem_verificacao":
            return f"⚠️ {nome}: não consigo verificar a transmissão desde {desde:%H:%M} ({r['erro']})"
        return f"{icone(problema)} {nome}: {rotulo(problema)} desde {desde:%H:%M}"

    def fechar_sessao(self, canal, inicio, fim):
        nome = canal["nome"]
        self.estados[nome].sessao_inicio = None
        r = relatorio.resumo(self.banco, nome, inicio, fim)
        if not any(v["ao_vivo"] for v in r["verificacoes"]) and not r["incidentes"]:
            return  # nem chegou a transmitir e ninguém precisava ser avisado
        pagina = relatorio.html(self.geral, nome, r)
        arquivo = f"relatorio-{nome}-{inicio:%Y-%m-%d-%H%M}.html".replace(" ", "-").replace("/", "-")
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            (self.pasta / arquivo).write_text(pagina, encoding="utf-8")
        except OSError as erro:
            self.log(f"[ERRO] não consegui salvar o relatório: {erro}")
        self.alertas.enviar_arquivo(arquivo, pagina.encode("utf-8"), relatorio.texto(nome, r))


def main():
    from .painel import criar_servidor

    cfg = carregar(os.getenv("CONFIG", "/config/config.toml"))
    banco = Banco(os.getenv("BANCO", "/dados/monitor.db"))
    s = cfg["segredos"]
    alertas = Alertas(s["telegram_token"], s["telegram_chat_id"], s["webhook_url"], s["modo_teste"], log)
    monitor = Monitor(cfg, banco, alertas)
    # Incidentes que ficaram abertos quando o monitor foi desligado: o estado em memória
    # se perdeu, então fecham agora; se o problema continuar, reabrem na próxima verificação.
    for canal in cfg["canais"]:
        banco.fechar_abertos(canal["nome"], datetime.now().replace(microsecond=0))

    porta = int(os.getenv("PORTA", "8095"))
    servidor = criar_servidor(cfg, banco, porta, pasta_relatorios=monitor.pasta)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    log(f"Monitor de transmissão · {len(cfg['canais'])} canal(is) · painel na porta {porta}"
        f"{' · MODO_TESTE (alertas só no log)' if s['modo_teste'] else ''}")

    while True:
        inicio = time.monotonic()
        try:
            monitor.ciclo()
        except Exception as erro:  # um erro inesperado não pode parar o monitor
            log(f"[ERRO] {erro!r}")
        alertas.heartbeat(s["heartbeat_url"])
        time.sleep(max(1, cfg["geral"]["intervalo_segundos"] - (time.monotonic() - inicio)))


if __name__ == "__main__":
    main()
