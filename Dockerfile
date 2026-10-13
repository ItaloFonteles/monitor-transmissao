FROM python:3.12-slim

# ffmpeg analisa imagem e som; yt-dlp descobre se a live do YouTube/Facebook está no ar.
# O YouTube muda com frequência: reconstrua a imagem (docker compose build) uma vez por mês.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -U yt-dlp

WORKDIR /monitor
COPY app ./app
COPY tests ./tests

ENV PYTHONUNBUFFERED=1 TZ=America/Boa_Vista
EXPOSE 8095
CMD ["python", "-m", "app.main"]
