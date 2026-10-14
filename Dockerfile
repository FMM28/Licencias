FROM python:3.12-slim
WORKDIR /srv
RUN useradd --system --uid 10001 --home /srv app && mkdir /data && chown app /data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY migrations migrations
COPY app app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ENV LICENSE_PRIVATE_KEY_FILE=/data/private.key \
    LICENSE_AUTO_MIGRATE=false
USER app
VOLUME /data
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]