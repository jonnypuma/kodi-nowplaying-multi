FROM python:3.12-slim

ENV TZ=UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Must match the owner of the mounted ./tmp and ./preferences directories.
# Override at build time when your host user is not 1000:
#   docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g)
ARG APP_UID=1000
ARG APP_GID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY kodi-nowplaying.py parser.py logging_config.py movie_nowplaying.py episode_nowplaying.py music_nowplaying.py favicon.ico play-button.png pause-button.png /app/
COPY nowplaying-common.css /app/
COPY nowplaying-common.js /app/
COPY kodi_np/ /app/kodi_np/
COPY templates/ /app/templates/

RUN if ! getent group "${APP_GID}" >/dev/null; then groupadd --gid "${APP_GID}" app; fi \
    && if ! getent passwd "${APP_UID}" >/dev/null; then \
         useradd --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home --shell /usr/sbin/nologin app; \
       fi \
    && mkdir -p /app/tmp /app/preferences \
    && chown -R "${APP_UID}:${APP_GID}" /app

USER ${APP_UID}:${APP_GID}

EXPOSE 6001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6001/health', timeout=4)"

CMD ["gunicorn", "--bind", "0.0.0.0:6001", "--workers", "1", "--threads", "8", "--timeout", "180", "kodi_np.app:app"]
