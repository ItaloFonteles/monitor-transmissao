# Monitor de Transmissão

Vigia **transmissões ao vivo** (YouTube, Facebook ou endereço direto) e **avisa na hora** pelo Telegram ou WhatsApp quando a live:

- **cai** ou **não começa** no horário da sessão;
- fica com **tela preta** ou **imagem congelada**;
- fica **sem áudio** (microfone mudo) ou com **áudio estourando**.

Quando o problema some, chega o aviso de **resolvido**, com quanto tempo durou. No fim de cada sessão sai um **relatório**: tempo no ar, quedas, problemas e audiência, com gráfico.

Feito para **câmaras municipais**, assembleias, igrejas, eventos e formaturas: quem opera a transmissão fica sabendo antes de alguém reclamar.

**Stack:** Python 3.12 · ffmpeg · yt-dlp · SQLite · Docker

---

## Como usar

```bash
cp .env.example .env
cp config.exemplo.toml config.toml     # já vem com uma transmissão simulada
docker compose up -d --build
docker compose logs -f monitor         # alertas aparecem aqui em MODO_TESTE
```

Painel: **http://localhost:8095** (atualiza sozinho a cada 15 s).

### Exemplo de alertas

```
🔴 Câmara Municipal: a sessão estava marcada para 09:00 e a transmissão ainda não está no ar
🟢 Câmara Municipal: transmissão no ar às 09:12 · Sessão Ordinária
✅ Câmara Municipal: transmissão fora do ar resolvido às 09:12 (durou 2 min)
🔇 Câmara Municipal: sem áudio desde 10:20
✅ Câmara Municipal: sem áudio resolvido às 10:23 (durou 3 min)
📋 Relatório · Câmara Municipal   (arquivo HTML anexado)
```

## Configuração (`config.toml`)

```toml
[[canais]]
nome = "Câmara Municipal"
url = "https://www.youtube.com/@NOME_DO_CANAL/live"   # o /live sempre aponta para a live atual
agenda = [
  { dias = ["ter", "qua", "qui"], inicio = "09:00", fim = "13:00" },
]
```

- **Com agenda:** dentro do horário, estar fora do ar é problema. O aviso de "não começou" sai depois de `tolerancia_inicio_minutos`. Fora do horário, ficar fora do ar é normal. O relatório sai no fim de cada sessão marcada.
- **Sem agenda:** avisa quando a live entra e sai do ar, e o relatório sai quando ela encerra.
- **`url`** pode ser YouTube, Facebook (via yt-dlp) ou um endereço direto (`.m3u8`, `rtmp://`, `srt://`), como o servidor de transmissão da própria câmara.
- **`url = "simulado"`:** uma live de mentira que, num ciclo de 8 minutos, fica preta, muda, congelada e cai. Serve para testar os alertas e para **demonstrar para o cliente**.

Ajustes em `[geral]`:

| Opção | Padrão | Para quê |
|---|---|---|
| `intervalo_segundos` | 60 | de quanto em quanto tempo verificar |
| `amostra_segundos` | 10 | quantos segundos de vídeo analisar a cada vez |
| `falhas_para_alerta` | 2 | verificações seguidas com problema antes de avisar (evita alarme por um soluço) |
| `tolerancia_inicio_minutos` | 10 | atraso aceito no começo da sessão |
| `silencio_db` / `volume_alto_db` | −50 / −8 | limites de silêncio e de áudio estourando |

**Alertas** (`.env`): Telegram (`TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`) e/ou um webhook (`WEBHOOK_URL`), por exemplo um fluxo do n8n que manda para o WhatsApp. Com `MODO_TESTE=true`, os alertas só aparecem no log.

## Como funciona

1. **Está no ar?** O **yt-dlp** consulta o link `/live` do canal, sem chave de API, e traz também o título e **quantas pessoas estão assistindo**.
2. **Imagem e som:** o **ffmpeg** lê 10 segundos da live (360p, para gastar pouca internet) com os detectores dele:
   - `blackdetect` → tela preta;
   - `freezedetect` → imagem congelada;
   - `silencedetect` e `volumedetect` → silêncio e volume.
   Um problema só conta se ocupar pelo menos 60% da amostra.
3. **Decisão:** cada canal tem um estado. O alerta sai depois de N verificações seguidas, o "resolvido" sai quando o problema some, e erros de consulta (YouTube fora, internet caída) viram "não consigo verificar", sem serem confundidos com queda.
4. **Histórico** em SQLite, com relatório por sessão e relatório do dia no painel.

> ⚠️ O YouTube muda com frequência. Reconstrua a imagem uma vez por mês (`docker compose build --pull`) para atualizar o yt-dlp.

## Testes

```bash
docker compose run --rm --no-deps monitor python -m unittest -v
```

20 testes cobrem:
- leitura do ffmpeg (tela preta, congelada, silêncio, volume, trecho sem fim);
- **ffmpeg de verdade** sobre a live simulada;
- agenda e mensagens de erro do config;
- estados (alerta só depois de N falhas, soluço não alerta, "não consigo verificar" não apaga os outros problemas);
- uma manhã de sessão simulada minuto a minuto (atraso, falta de áudio, queda e relatório);
- live sem agenda (início, fim e relatório);
- relatório e painel.

---

Feito por **Ítalo Fonteles** · [italofonteles.dev](https://italofonteles.dev)
