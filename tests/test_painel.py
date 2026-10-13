import base64
import http.client
import json
import os
import tempfile
import threading
import unittest
from datetime import timedelta

from app import fonte
from app.banco import Banco
from app.canais import Cadastro
from app.main import Monitor
from app.painel import criar_servidor
from tests.test_monitor import CONFIG, T0, AlertasFalsos, carregar_toml


class TestLinks(unittest.TestCase):
    def test_normalizar(self):
        n = fonte.normalizar_url
        self.assertEqual(n("@camarabv"), "https://www.youtube.com/@camarabv/live")
        self.assertEqual(n("youtube.com/@camarabv"), "https://www.youtube.com/@camarabv/live")
        self.assertEqual(n("https://www.youtube.com/@camarabv/videos"), "https://www.youtube.com/@camarabv/live")
        self.assertEqual(n("https://m.youtube.com/channel/UC123abc/streams"), "https://www.youtube.com/channel/UC123abc/live")
        self.assertEqual(n(" https://www.youtube.com/@x/live "), "https://www.youtube.com/@x/live")
        for igual in ("simulado", "rtmp://servidor/live", "https://servidor/camara.m3u8",
                      "https://www.youtube.com/watch?v=eAvZOvmJDsg"):
            self.assertEqual(n(igual), igual)

    def test_link_de_video(self):
        self.assertTrue(fonte.eh_video("https://www.youtube.com/watch?v=eAvZOvmJDsg"))
        self.assertTrue(fonte.eh_video("https://youtu.be/eAvZOvmJDsg"))
        self.assertTrue(fonte.eh_video("https://www.youtube.com/live/eAvZOvmJDsg"))
        self.assertFalse(fonte.eh_video("https://www.youtube.com/@camara/live"))


class TestCadastro(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.arquivo = os.path.join(self.pasta.name, "canais.json")
        self.cfg = carregar_toml(CONFIG)

    def tearDown(self):
        self.pasta.cleanup()

    def test_comeca_pelo_config_e_depois_vale_o_arquivo(self):
        cadastro = Cadastro(self.cfg, self.arquivo)
        self.assertEqual([c["nome"] for c in cadastro.lista()], ["Câmara", "Igreja"])
        self.assertFalse(os.path.exists(self.arquivo))            # só grava na primeira mudança
        cadastro.salvar({"nome": "Assembleia", "url": "@assembleia",
                         "agenda": [{"dias": ["seg"], "inicio": "14:00", "fim": "18:00"}]})
        self.assertEqual(self.cfg["canais"][-1]["url"], "https://www.youtube.com/@assembleia/live")
        outro_cfg = carregar_toml(CONFIG)                          # reinício: o arquivo manda
        Cadastro(outro_cfg, self.arquivo)
        self.assertEqual([c["nome"] for c in outro_cfg["canais"]], ["Câmara", "Igreja", "Assembleia"])
        self.assertEqual(outro_cfg["canais"][-1]["agenda"][0]["dias"], {0})

    def test_editar_renomear_e_remover(self):
        cadastro = Cadastro(self.cfg, self.arquivo)
        lista_original = self.cfg["canais"]
        cadastro.salvar({"nome": "Igreja Central", "url": "@igrejacentral"}, original="Igreja")
        self.assertIs(self.cfg["canais"], lista_original)          # muda no lugar: o monitor enxerga
        self.assertEqual([c["nome"] for c in cadastro.lista()], ["Câmara", "Igreja Central"])
        cadastro.remover("Câmara")
        self.assertEqual([c["nome"] for c in cadastro.lista()], ["Igreja Central"])
        with self.assertRaisesRegex(ValueError, "não existe"):
            cadastro.remover("Câmara")

    def test_erros(self):
        cadastro = Cadastro(self.cfg, self.arquivo)
        with self.assertRaisesRegex(ValueError, "já existe"):
            cadastro.salvar({"nome": "Igreja", "url": "@x"})
        with self.assertRaisesRegex(ValueError, "falta o link"):
            cadastro.salvar({"nome": "Nova", "url": "  "})
        with self.assertRaisesRegex(ValueError, "precisa ser depois"):
            cadastro.salvar({"nome": "Nova", "url": "@x", "agenda": [{"dias": ["seg"], "inicio": "10:00", "fim": "09:00"}]})
        self.assertEqual(len(cadastro.lista()), 2)                 # nada mudou


class TestMonitorComCadastro(unittest.TestCase):
    def test_canal_novo_e_link_trocado_sem_reiniciar(self):
        cfg = carregar_toml(CONFIG)
        cfg["canais"][:] = cfg["canais"][1:]                        # só a Igreja
        consultados = []

        def consultar(url, agora):
            consultados.append(url)
            return {"ao_vivo": True, "stream": "x", "titulo": "", "espectadores": 10, "erro": ""}

        analisar = lambda *a: {"erro": "", "problemas": ["sem_audio"], "volume": -70.0}
        with tempfile.TemporaryDirectory() as pasta:
            cadastro = Cadastro(cfg, os.path.join(pasta, "canais.json"))
            alertas = AlertasFalsos()
            monitor = Monitor(cfg, Banco(":memory:"), alertas, consultar, analisar, pasta, log=lambda *_: None)
            monitor.ciclo(T0)
            cadastro.salvar({"nome": "Nova", "url": "@nova"})
            monitor.ciclo(T0 + timedelta(minutes=1))
            self.assertIn("https://www.youtube.com/@nova/live", consultados)
            self.assertIn("🔇 Igreja: sem áudio desde 09:00", alertas.textos)
            # trocar o link da Igreja recomeça o estado dela (o alerta antigo não "resolve")
            cadastro.salvar({"nome": "Igreja", "url": "@outra"}, original="Igreja")
            monitor.ciclo(T0 + timedelta(minutes=2))
            self.assertFalse(any("resolvido" in t for t in alertas.textos))


class TestServidor(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.cfg = carregar_toml(CONFIG)
        self.banco = Banco(":memory:")
        self.cadastro = Cadastro(self.cfg, os.path.join(self.pasta.name, "canais.json"))

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.pasta.cleanup()

    def subir(self, senha=""):
        consultar = lambda url, agora: {"ao_vivo": False, "stream": None, "titulo": "", "espectadores": None, "erro": ""}
        sugerir = lambda url: {"url": "https://www.youtube.com/@Lkdotero/live", "nome": "LKDotero"}
        self.servidor = criar_servidor(self.cfg, self.banco, 0, "127.0.0.1", self.pasta.name,
                                       self.cadastro, senha, consultar, sugerir)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def pedir(self, metodo, caminho, corpo=None, tipo="application/json", senha=None):
        con = http.client.HTTPConnection("127.0.0.1", self.servidor.server_address[1], timeout=5)
        cabecalhos = {"Content-Type": tipo}
        if senha is not None:
            cabecalhos["Authorization"] = "Basic " + base64.b64encode(f"x:{senha}".encode()).decode()
        con.request(metodo, caminho, body=json.dumps(corpo) if corpo is not None else None, headers=cabecalhos)
        r = con.getresponse()
        dados = r.read().decode("utf-8")
        con.close()
        return r.status, dados

    def test_salvar_testar_e_remover(self):
        self.subir()
        status, _ = self.pedir("POST", "/api/canais/salvar",
                               {"original": None, "canal": {"nome": "LK", "url": "youtube.com/@Lkdotero", "agenda": []}})
        self.assertEqual(status, 200)
        status, corpo = self.pedir("GET", "/api/estado")
        nomes = [c["nome"] for c in json.loads(corpo)["canais"]]
        self.assertEqual(nomes, ["Câmara", "Igreja", "LK"])
        status, corpo = self.pedir("POST", "/api/canais/salvar", {"original": None, "canal": {"nome": "LK", "url": "@y"}})
        self.assertEqual((status, json.loads(corpo)["erro"]), (400, "canal: já existe um canal chamado 'LK'"))
        status, corpo = self.pedir("POST", "/api/testar", {"url": "https://www.youtube.com/watch?v=eAvZOvmJDsg"})
        teste = json.loads(corpo)
        self.assertEqual((teste["ao_vivo"], teste["sugestao"]["url"]), (False, "https://www.youtube.com/@Lkdotero/live"))
        status, _ = self.pedir("POST", "/api/canais/remover", {"nome": "LK"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.cfg["canais"]), 2)

    def test_so_aceita_json(self):
        self.subir()
        status, _ = self.pedir("POST", "/api/canais/remover", None, tipo="application/x-www-form-urlencoded")
        self.assertEqual(status, 415)

    def test_senha(self):
        self.subir(senha="segredo")
        self.assertEqual(self.pedir("GET", "/")[0], 401)
        self.assertEqual(self.pedir("GET", "/", senha="errada")[0], 401)
        self.assertEqual(self.pedir("POST", "/api/canais/remover", {"nome": "Igreja"}, senha="errada")[0], 401)
        self.assertEqual(len(self.cfg["canais"]), 2)
        status, pagina = self.pedir("GET", "/", senha="segredo")
        self.assertEqual(status, 200)
        self.assertIn("+ Adicionar canal", pagina)


if __name__ == "__main__":
    unittest.main()
