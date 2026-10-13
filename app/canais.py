"""Cadastro de canais editável pelo painel, salvo em /dados/canais.json.

Na primeira vez, os canais vêm do config.toml. Depois, o painel passa a mandar: cada mudança
é gravada no arquivo e altera a lista cfg["canais"] no lugar, então o monitor já usa o canal
novo na próxima verificação, sem reiniciar.
"""
import json
import os
import threading
from pathlib import Path

from .config import agenda_para_texto, validar_canal


class Cadastro:
    def __init__(self, cfg, caminho):
        self.cfg = cfg
        self.caminho = Path(caminho)
        self.trava = threading.Lock()
        if self.caminho.exists():
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            canais = []
            for i, canal in enumerate(dados, 1):
                canais.append(validar_canal(canal, {c["nome"] for c in canais}, f"canais.json, canal #{i}"))
            cfg["canais"][:] = canais

    def lista(self):
        with self.trava:
            return [{"nome": c["nome"], "url": c["url"], "agenda": agenda_para_texto(c["agenda"])}
                    for c in self.cfg["canais"]]

    def salvar(self, dados, original=None):
        """Cria um canal (original=None) ou altera o canal chamado 'original'."""
        with self.trava:
            canais = self.cfg["canais"]
            posicao = next((i for i, c in enumerate(canais) if c["nome"] == original), None)
            if original is not None and posicao is None:
                raise ValueError(f"o canal '{original}' não existe mais (outra pessoa pode ter removido)")
            outros = {c["nome"] for i, c in enumerate(canais) if i != posicao}
            canal = validar_canal(dados, outros)
            novos = list(canais)
            if posicao is None:
                novos.append(canal)
            else:
                novos[posicao] = canal
            self._gravar(novos)
            canais[:] = novos
            return canal

    def remover(self, nome):
        with self.trava:
            novos = [c for c in self.cfg["canais"] if c["nome"] != nome]
            if len(novos) == len(self.cfg["canais"]):
                raise ValueError(f"o canal '{nome}' não existe")
            self._gravar(novos)
            self.cfg["canais"][:] = novos

    def _gravar(self, canais):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho.with_suffix(".tmp")
        conteudo = [{"nome": c["nome"], "url": c["url"], "agenda": agenda_para_texto(c["agenda"])} for c in canais]
        temporario.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporario, self.caminho)  # troca de uma vez: um desligamento no meio não corrompe
