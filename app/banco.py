"""Histórico em SQLite: cada verificação e cada incidente (problema com início e fim)."""
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS verificacoes (
    canal TEXT, quando TEXT, ao_vivo INTEGER, espectadores INTEGER,
    problemas TEXT, volume REAL, erro TEXT
);
CREATE INDEX IF NOT EXISTS idx_verif ON verificacoes (canal, quando);
CREATE TABLE IF NOT EXISTS incidentes (
    id INTEGER PRIMARY KEY, canal TEXT, problema TEXT, inicio TEXT, fim TEXT
);
"""


def _iso(momento):
    return momento.isoformat(timespec="seconds")


class Banco:
    def __init__(self, caminho):
        if caminho != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(caminho, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.trava = threading.Lock()  # o painel lê de outra thread

    def _executar(self, sql, parametros=()):
        with self.trava:
            cursor = self.con.execute(sql, parametros)
            self.con.commit()
            return [dict(l) for l in cursor.fetchall()]

    def registrar(self, canal, quando, ao_vivo, espectadores, problemas, volume, erro):
        self._executar(
            "INSERT INTO verificacoes VALUES (?,?,?,?,?,?,?)",
            (canal, _iso(quando), None if ao_vivo is None else int(ao_vivo), espectadores,
             ",".join(problemas), volume, erro),
        )

    def abrir_incidente(self, canal, problema, inicio):
        self._executar("INSERT INTO incidentes (canal, problema, inicio) VALUES (?,?,?)",
                       (canal, problema, _iso(inicio)))

    def fechar_incidente(self, canal, problema, fim):
        self._executar("UPDATE incidentes SET fim=? WHERE canal=? AND problema=? AND fim IS NULL",
                       (_iso(fim), canal, problema))

    def fechar_abertos(self, canal, fim):
        self._executar("UPDATE incidentes SET fim=? WHERE canal=? AND fim IS NULL", (_iso(fim), canal))

    def verificacoes(self, canal, inicio, fim):
        return self._executar(
            "SELECT * FROM verificacoes WHERE canal=? AND quando>=? AND quando<? ORDER BY quando",
            (canal, _iso(inicio), _iso(fim)),
        )

    def incidentes(self, canal, inicio, fim):
        """Incidentes que encostam no período (inclusive os ainda abertos)."""
        return self._executar(
            "SELECT * FROM incidentes WHERE canal=? AND inicio<? AND (fim IS NULL OR fim>?) ORDER BY inicio",
            (canal, _iso(fim), _iso(inicio)),
        )

    def ultima(self, canal):
        linhas = self._executar(
            "SELECT * FROM verificacoes WHERE canal=? ORDER BY quando DESC LIMIT 1", (canal,))
        return linhas[0] if linhas else None
