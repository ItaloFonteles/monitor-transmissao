"""Envio de alertas: Telegram, webhook (ex.: n8n → WhatsApp) e sinal de vida (heartbeat).

Em MODO_TESTE=true nada sai para a internet: as mensagens só aparecem no log.
Uma falha de envio nunca derruba o monitor.
"""
import json
import urllib.request
import uuid


class Alertas:
    def __init__(self, telegram_token="", telegram_chat_id="", webhook_url="", modo_teste=True, log=print):
        self.token = telegram_token
        self.chat_id = telegram_chat_id
        self.webhook_url = webhook_url
        self.modo_teste = modo_teste
        self.log = log

    def enviar(self, texto: str, dados: dict | None = None):
        self.log(f"[ALERTA] {texto}")
        if self.modo_teste:
            return
        if self.token and self.chat_id:
            self._tentar("Telegram", self._telegram, texto)
        if self.webhook_url:
            self._tentar("webhook", self._webhook, {"texto": texto, **(dados or {})})

    def enviar_arquivo(self, nome: str, conteudo: bytes, legenda: str):
        self.log(f"[ARQUIVO] {nome} ({len(conteudo)} bytes) · {legenda.splitlines()[0]}")
        if self.modo_teste or not (self.token and self.chat_id):
            return
        self._tentar("Telegram (arquivo)", self._telegram_arquivo, nome, conteudo, legenda)

    def heartbeat(self, url: str):
        """Avisa um serviço externo (ex.: healthchecks.io) que o monitor está vivo.
        Se o local ficar sem energia/internet, é esse serviço que dispara o alerta."""
        if url and not self.modo_teste:
            try:
                urllib.request.urlopen(url, timeout=5).close()
            except OSError:
                pass  # sem internet: justamente o caso que o serviço externo vai perceber

    # --- envio -------------------------------------------------------------
    def _tentar(self, canal, funcao, *args):
        try:
            funcao(*args)
        except Exception as erro:
            self.log(f"[ERRO] não consegui enviar pelo {canal}: {erro}")

    def _post_json(self, url, dados):
        req = urllib.request.Request(url, data=json.dumps(dados).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).close()

    def _telegram(self, texto):
        self._post_json(f"https://api.telegram.org/bot{self.token}/sendMessage",
                        {"chat_id": self.chat_id, "text": texto, "disable_web_page_preview": True})

    def _webhook(self, dados):
        self._post_json(self.webhook_url, dados)

    def _telegram_arquivo(self, nome, conteudo, legenda):
        limite = uuid.uuid4().hex
        partes = []
        for campo, valor in (("chat_id", self.chat_id), ("caption", legenda[:1000])):
            partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{campo}"\r\n\r\n{valor}\r\n'.encode())
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="document"; filename="{nome}"\r\n'
                      f"Content-Type: text/html\r\n\r\n".encode() + conteudo + b"\r\n")
        corpo = b"".join(partes) + f"--{limite}--\r\n".encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendDocument", data=corpo,
                                     headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
        urllib.request.urlopen(req, timeout=30).close()
