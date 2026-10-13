import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

from app import analise, config, fonte, relatorio
from app.banco import Banco
from app.estado import EstadoCanal
from app.main import Monitor
from app.painel import estado, pagina_relatorios, pagina_status

T0 = datetime(2026, 10, 14, 9, 0)  # uma quarta-feira


class AlertasFalsos:
    def __init__(self):
        self.textos, self.arquivos = [], []

    def enviar(self, texto, dados=None):
        self.textos.append(texto)

    def enviar_arquivo(self, nome, conteudo, legenda):
        self.arquivos.append((nome, conteudo.decode("utf-8"), legenda))


def carregar_toml(texto):
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write(texto)
    try:
        return config.carregar(f.name)
    finally:
        os.unlink(f.name)


CONFIG = """
[geral]
cliente = "Câmara Teste"
falhas_para_alerta = 2
tolerancia_inicio_minutos = 10

[[canais]]
nome = "Câmara"
url = "https://www.youtube.com/@camara/live"
agenda = [{ dias = ["ter", "qua"], inicio = "09:00", fim = "10:00" }]

[[canais]]
nome = "Igreja"
url = "https://www.youtube.com/@igreja/live"
"""

SAIDA_NORMAL = """Input #0, hls, from 'x':
  Stream #0:0: Video: h264, yuv420p, 854x480, 30 fps
  Stream #0:1: Audio: aac, 44100 Hz, stereo
[Parsed_volumedetect_1 @ 0x1] mean_volume: -22.4 dB
[Parsed_volumedetect_1 @ 0x1] max_volume: -3.1 dB
"""


class TestAnalise(unittest.TestCase):
    def test_normal(self):
        r = analise.interpretar(SAIDA_NORMAL, 10)
        self.assertEqual(r["problemas"], [])
        self.assertEqual(r["volume"], -22.4)

    def test_tela_preta_inteira(self):
        saida = SAIDA_NORMAL + "[blackdetect @ 0x2] black_start:0 black_end:10 black_duration:10\n"
        self.assertEqual(analise.interpretar(saida, 10)["problemas"], ["preta"])

    def test_preta_curta_nao_conta(self):
        saida = SAIDA_NORMAL + "[blackdetect @ 0x2] black_start:2 black_end:4 black_duration:2\n"
        self.assertEqual(analise.interpretar(saida, 10)["problemas"], [])

    def test_congelada_sem_fim_vai_ate_o_fim_da_amostra(self):
        saida = SAIDA_NORMAL + "[freezedetect @ 0x3] lavfi.freezedetect.freeze_start: 2.5\n"
        r = analise.interpretar(saida, 10)
        self.assertEqual(r["congelada"], 7.5)
        self.assertEqual(r["problemas"], ["congelada"])

    def test_mudo_e_sem_audio(self):
        mudo = (SAIDA_NORMAL.replace("mean_volume: -22.4", "mean_volume: -91.0")
                .replace("max_volume: -3.1", "max_volume: -91.0") + "[silencedetect @ 0x4] silence_start: 0\n")
        self.assertEqual(analise.interpretar(mudo, 10)["problemas"], ["sem_audio"])
        zerado = SAIDA_NORMAL.replace("max_volume: -3.1 dB", "max_volume: -inf dB")
        self.assertEqual(analise.interpretar(zerado, 10)["problemas"], ["sem_audio"])
        sem_trilha = SAIDA_NORMAL.replace("  Stream #0:1: Audio: aac, 44100 Hz, stereo\n", "")
        self.assertIn("sem_audio", analise.interpretar(sem_trilha, 10)["problemas"])

    def test_silencio_com_sinal_nao_e_mudo(self):
        """Caso real (live de campeonato): narradores calados, pico -50,8 dB. É pausa, não microfone mudo."""
        pausa = (SAIDA_NORMAL.replace("mean_volume: -22.4", "mean_volume: -62.2")
                 .replace("max_volume: -3.1", "max_volume: -50.8") + "[silencedetect @ 0x4] silence_start: 0\n")
        self.assertEqual(analise.interpretar(pausa, 10)["problemas"], ["silencio"])
        curta = SAIDA_NORMAL + "[silencedetect @ 0x4] silence_start: 1.9\n"   # 8,1 s de 10: ainda é pausa
        self.assertEqual(analise.interpretar(curta, 10)["problemas"], ["silencio"])
        normal = SAIDA_NORMAL + "[silencedetect @ 0x4] silence_start: 4.4\n[silencedetect @ 0x4] silence_end: 7.7\n"
        self.assertEqual(analise.interpretar(normal, 10)["problemas"], [])

    def test_audio_estourando(self):
        saida = SAIDA_NORMAL.replace("mean_volume: -22.4", "mean_volume: -4.0")
        self.assertEqual(analise.interpretar(saida, 10)["problemas"], ["audio_alto"])

    def test_nao_abriu(self):
        r = analise.interpretar("https://x/live.m3u8: Server returned 403 Forbidden\n", 10)
        self.assertIn("403", r["erro"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg não instalado")
class TestFfmpegDeVerdade(unittest.TestCase):
    """Roda o ffmpeg de verdade sobre a live simulada (dentro do Docker)."""

    def test_cenas(self):
        for cena, esperado in (("ok", []), ("preta", ["preta"]), ("congelada", ["congelada"]),
                               ("sem_audio", ["sem_audio"])):
            with self.subTest(cena=cena):
                r = analise.analisar(f"lavfi:{cena}", segundos=6)
                self.assertEqual(r["erro"], "")
                self.assertEqual(r["problemas"], esperado)

    def test_trilhas_separadas_com_inicio_diferente_nao_viram_silencio(self):
        """Como no YouTube: vídeo e áudio em trilhas separadas (o áudio até começando 5 s depois)."""
        import subprocess
        with tempfile.TemporaryDirectory() as pasta:
            video, audio = os.path.join(pasta, "v.ts"), os.path.join(pasta, "a.ts")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                            "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", video], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                            "-t", "12", "-c:a", "aac", "-output_ts_offset", "5", audio], check=True)
            r = analise.analisar([video, audio], segundos=6)
            self.assertEqual(r["erro"], "")
            self.assertEqual(r["problemas"], [])
            self.assertLess(r["silencio"], 1)


class TestFonte(unittest.TestCase):
    def test_ciclo_simulado(self):
        self.assertEqual(fonte.cena_simulada(T0), "ok")
        self.assertEqual(fonte.cena_simulada(T0 + timedelta(minutes=2, seconds=30)), "preta")
        self.assertEqual(fonte.cena_simulada(T0 + timedelta(minutes=6, seconds=10)), "fora_do_ar")
        self.assertFalse(fonte.consultar("simulado", T0 + timedelta(minutes=6))["ao_vivo"])
        self.assertEqual(fonte.consultar("simulado", T0)["stream"], "lavfi:ok")

    def test_endereco_direto_nao_usa_yt_dlp(self):
        r = fonte.consultar("https://servidor/live/camara.m3u8")
        self.assertTrue(r["ao_vivo"])
        self.assertEqual(r["stream"], "https://servidor/live/camara.m3u8")


class TestConfig(unittest.TestCase):
    def test_agenda(self):
        cfg = carregar_toml(CONFIG)
        agenda = cfg["canais"][0]["agenda"]
        self.assertEqual(config.janela_atual(agenda, T0 + timedelta(minutes=30)),
                         (T0, T0 + timedelta(hours=1)))
        self.assertIsNone(config.janela_atual(agenda, T0 + timedelta(hours=1)))          # 10:00 já acabou
        self.assertIsNone(config.janela_atual(agenda, T0 + timedelta(days=1, minutes=5)))  # quinta
        self.assertEqual(cfg["canais"][1]["agenda"], [])

    def test_erros_claros(self):
        with self.assertRaisesRegex(ValueError, "dia inválido"):
            carregar_toml('[[canais]]\nnome="A"\nurl="x"\nagenda=[{dias=["segunda"], inicio="09:00", fim="10:00"}]')
        with self.assertRaisesRegex(ValueError, "precisa ser depois"):
            carregar_toml('[[canais]]\nnome="A"\nurl="x"\nagenda=[{inicio="10:00", fim="09:00"}]')
        with self.assertRaisesRegex(ValueError, "falta o link"):
            carregar_toml('[[canais]]\nnome="A"')


class TestEstado(unittest.TestCase):
    def test_alerta_so_depois_de_duas_e_resolvido(self):
        e = EstadoCanal(2)
        self.assertEqual(e.atualizar(T0, True, ["sem_audio"]), [])
        self.assertEqual(e.atualizar(T0 + timedelta(minutes=1), True, ["sem_audio"]), [("alerta", "sem_audio", T0)])
        self.assertEqual(e.atualizar(T0 + timedelta(minutes=2), True, ["sem_audio"]), [])  # não repete
        self.assertEqual(e.atualizar(T0 + timedelta(minutes=3), True, []), [("resolvido", "sem_audio", T0)])

    def test_silencio_so_alerta_depois_de_minutos(self):
        e = EstadoCanal(2, {"silencio": 5})
        for minuto in range(4):
            self.assertEqual(e.atualizar(T0 + timedelta(minutes=minuto), True, ["silencio"]), [])
        self.assertEqual(e.atualizar(T0 + timedelta(minutes=4), True, ["silencio"]), [("alerta", "silencio", T0)])
        e2 = EstadoCanal(2, {"silencio": 5})                       # uma fala no meio zera a contagem
        for minuto, problemas in enumerate([["silencio"]] * 3 + [[]] + [["silencio"]] * 3):
            self.assertEqual(e2.atualizar(T0 + timedelta(minutes=minuto), True, problemas), [])

    def test_soluco_nao_alerta_nem_resolve(self):
        e = EstadoCanal(2)
        e.atualizar(T0, True, ["preta"])
        self.assertEqual(e.atualizar(T0 + timedelta(minutes=1), True, []), [])

    def test_sem_verificacao_nao_resolve_os_outros(self):
        e = EstadoCanal(1)
        e.atualizar(T0, True, ["preta"])
        eventos = e.atualizar(T0 + timedelta(minutes=1), None, ["sem_verificacao"])
        self.assertEqual(eventos, [("alerta", "sem_verificacao", T0 + timedelta(minutes=1))])
        self.assertIn("preta", e.alertados)

    def test_fim_normal_fora_da_agenda(self):
        e = EstadoCanal(1)
        e.atualizar(T0, False, [])
        self.assertEqual(e.atualizar(T0 + timedelta(minutes=1), True, ["sem_audio"]),
                         [("comecou", None, T0 + timedelta(minutes=1)), ("alerta", "sem_audio", T0 + timedelta(minutes=1))])
        self.assertEqual(e.atualizar(T0 + timedelta(minutes=2), False, []), [("encerrou", None, T0 + timedelta(minutes=2))])
        self.assertEqual(e.alertados, set())


class TestMonitor(unittest.TestCase):
    """Simula uma manhã de sessão minuto a minuto."""

    def rodar(self, roteiro, canal_indice=0):
        cfg = carregar_toml(CONFIG)
        cfg["canais"] = [cfg["canais"][canal_indice]]
        banco, alertas = Banco(":memory:"), AlertasFalsos()
        estado = {}
        consultar = lambda url, agora: {"ao_vivo": estado["ao_vivo"], "stream": "x" if estado["ao_vivo"] else None,
                                        "titulo": "Sessão", "espectadores": 40 if estado["ao_vivo"] else None, "erro": ""}
        analisar = lambda *a: {"erro": "", "problemas": estado["problemas"], "volume": -20.0}
        with tempfile.TemporaryDirectory() as pasta:
            monitor = Monitor(cfg, banco, alertas, consultar, analisar, pasta_relatorios=pasta, log=lambda *_: None)
            for minuto, ao_vivo, problemas in roteiro:
                estado.update(ao_vivo=ao_vivo, problemas=problemas)
                monitor.ciclo(T0 + timedelta(minutes=minuto))
            arquivos = os.listdir(pasta)
        return alertas, banco, arquivos

    def test_sessao_com_atraso_falta_de_audio_e_queda(self):
        roteiro = [(-5, False, []), (5, False, []),                 # antes da tolerância: quieto
                   (10, False, []), (11, False, []),                # 09:11 → não começou
                   (12, True, []),                                  # começou
                   (20, True, ["sem_audio"]), (21, True, ["sem_audio"]), (22, True, []),
                   (30, False, []), (31, False, []), (32, True, []),  # caiu e voltou
                   (59, True, []), (60, False, [])]                 # 10:00: fim da sessão
        alertas, banco, arquivos = self.rodar(roteiro)
        t = alertas.textos
        self.assertIn("🔴 Câmara: a sessão estava marcada para 09:00 e a transmissão ainda não está no ar", t)
        self.assertIn("✅ Câmara: transmissão fora do ar resolvido às 09:12 (durou 2 min)", t)
        self.assertIn("🔇 Câmara: sem áudio desde 09:20", t)
        self.assertIn("✅ Câmara: sem áudio resolvido às 09:22 (durou 2 min)", t)
        self.assertIn("🔴 Câmara: transmissão fora do ar desde 09:30", t)
        self.assertEqual(sum("resolvido" in x for x in t), 3)        # o fim da sessão não vira "resolvido"
        self.assertEqual(len(alertas.arquivos), 1)                   # relatório da sessão
        nome, pagina, legenda = alertas.arquivos[0]
        self.assertIn("Relatório", legenda)
        self.assertIn("🔇 sem áudio: 2 min", legenda)
        self.assertIn("queda(s)", pagina)
        self.assertEqual(arquivos, [nome])

    def test_sem_agenda_relatorio_quando_encerra(self):
        roteiro = [(0, False, []), (1, True, []), (2, True, ["preta"]), (3, True, ["preta"]),
                   (4, True, []), (5, False, [])]
        alertas, _, _ = self.rodar(roteiro, canal_indice=1)
        self.assertIn("🟢 Igreja: transmissão no ar às 09:01 · Sessão", alertas.textos)
        self.assertIn("⬛ Igreja: tela preta desde 09:02", alertas.textos)
        self.assertIn("⚪ Igreja: transmissão encerrada às 09:05", alertas.textos)
        self.assertNotIn("fora do ar", " ".join(alertas.textos))    # encerrar não é queda
        self.assertEqual(len(alertas.arquivos), 1)

    def test_sessao_que_nem_comecou_nao_gera_relatorio_vazio(self):
        alertas, _, _ = self.rodar([(-5, False, []), (65, False, [])])
        self.assertEqual(alertas.arquivos, [])


class TestTelas(unittest.TestCase):
    def test_relatorio_e_painel(self):
        cfg = carregar_toml(CONFIG)
        banco = Banco(":memory:")
        for minuto in range(10):
            ao_vivo = minuto != 4
            banco.registrar("Câmara", T0 + timedelta(minutes=minuto), ao_vivo, 30 + minuto if ao_vivo else None,
                            [] if ao_vivo else ["fora_do_ar"], -20.0, "")
        banco.abrir_incidente("Câmara", "fora_do_ar", T0 + timedelta(minutes=4))
        banco.fechar_incidente("Câmara", "fora_do_ar", T0 + timedelta(minutes=5))
        r = relatorio.resumo(banco, "Câmara", T0, T0 + timedelta(minutes=10))
        self.assertEqual(r["percentual_no_ar"], 90.0)
        self.assertEqual((r["quedas"], r["pico"]), (1, 39))
        self.assertIn("<svg", relatorio.html(cfg["geral"], "Câmara", r))
        agora = T0 + timedelta(minutes=10)
        e = estado(cfg, banco, agora)
        camara, igreja = e["canais"]
        self.assertEqual((camara["situacao"], camara["espectadores"], camara["segundos"]), ("ok", 39, 60))
        self.assertEqual(len(camara["linha"]), 10)                              # última hora
        self.assertEqual(camara["incidentes"][0]["rotulo"], "transmissão fora do ar")
        self.assertEqual(camara["proxima"], "ter 20/10 09:00")  # agenda ter e qua: depois de quarta vem terça
        self.assertEqual(igreja["situacao"], "nunca")
        self.assertFalse(camara["parado"])
        self.assertTrue(estado(cfg, banco, agora + timedelta(minutes=10))["canais"][0]["parado"])
        pagina = pagina_status(cfg, banco, agora)
        self.assertIn("const DADOS = ", pagina)
        self.assertNotIn("</script><", pagina.split("const DADOS")[1].split("</script>")[0])

    def test_lista_de_relatorios(self):
        with tempfile.TemporaryDirectory() as pasta:
            self.assertIn("Nenhuma sessão encerrada", pagina_relatorios(pasta))
            open(os.path.join(pasta, "relatorio-Câmara-2026-10-14-0900.html"), "w").close()
            self.assertIn("/relatorios/relatorio-C%C3%A2mara-2026-10-14-0900.html", pagina_relatorios(pasta))


if __name__ == "__main__":
    unittest.main()
