FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY kodi-nowplaying.py parser.py logging_config.py movie_nowplaying.py episode_nowplaying.py music_nowplaying.py favicon.ico play-button.png pause-button.png /app/
COPY templates/ /app/templates/

RUN mkdir -p /app/tmp /app/preferences

EXPOSE 6001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6001/health', timeout=4)"

CMD ["python", "kodi-nowplaying.py"]
