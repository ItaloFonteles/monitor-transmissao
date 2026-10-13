"""Estado de cada canal: decide quando avisar de um problema e quando avisar que resolveu.

Um problema só vira alerta depois de N verificações seguidas (falhas_para_alerta), para não
apitar por um soluço de 10 segundos. Quando some, sai o aviso de "resolvido" com a duração.
"""


class EstadoCanal:
    def __init__(self, falhas_para_alerta=2):
        self.n = falhas_para_alerta
        self.contagem = {}
        self.desde = {}
        self.alertados = set()
        self.ao_vivo = None            # None = ainda não sabemos (início do monitor)
        self.ultima_vez_no_ar = None
        self.sessao_inicio = None
        self.janela = None             # sessão marcada em andamento (início, fim)

    def limpar(self):
        """Esquece os problemas sem avisar nada (fim normal da transmissão ou da sessão)."""
        self.contagem.clear()
        self.desde.clear()
        self.alertados.clear()

    def atualizar(self, agora, ao_vivo, problemas, em_agenda=False):
        """Devolve eventos: ('alerta', problema, desde), ('resolvido', problema, desde),
        ('comecou', None, agora) e ('encerrou', None, agora)."""
        eventos = []
        if ao_vivo is None:
            # Não deu para verificar: só conta esse problema, sem "resolver" os outros.
            considerados, ativos = {"sem_verificacao"}, {"sem_verificacao"}
        else:
            considerados, ativos = None, set(problemas)
            if ao_vivo:
                self.ultima_vez_no_ar = agora
                if self.sessao_inicio is None:
                    self.sessao_inicio = agora
                if self.ao_vivo is False:
                    eventos.append(("comecou", None, agora))
            elif self.ao_vivo is True and not em_agenda:
                # Saiu do ar fora de uma sessão marcada: fim normal, não é queda.
                self.limpar()
                self.ao_vivo = False
                return [("encerrou", None, agora)]
            self.ao_vivo = ao_vivo

        for problema in ativos:
            self.contagem[problema] = self.contagem.get(problema, 0) + 1
            self.desde.setdefault(problema, agora)
            if self.contagem[problema] >= self.n and problema not in self.alertados:
                self.alertados.add(problema)
                eventos.append(("alerta", problema, self.desde[problema]))
        for problema in list(self.contagem):
            if problema in ativos or (considerados is not None and problema not in considerados):
                continue
            if problema in self.alertados:
                eventos.append(("resolvido", problema, self.desde[problema]))
                self.alertados.discard(problema)
            del self.contagem[problema]
            del self.desde[problema]
        return eventos
