FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY lizenztool/ lizenztool/
COPY lizenztool.toml .

RUN pip install --no-cache-dir .

RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# --forwarded-allow-ips controls which peers uvicorn trusts to set
# request.client.host from X-Forwarded-For (see lizenztool/api.py::_client_ip).
# Trusting "*" would let any client set that value directly. Default to
# loopback only; override via FORWARDED_ALLOW_IPS when the app sits behind a
# real reverse proxy (e.g. the bundled Caddy container reaches it over the
# Docker network, not localhost — see docker-compose.yml/README for the value
# to set there). On Railway and similar PaaS the platform's own edge proxy
# must be configured to pass a trustworthy X-Forwarded-For in the first place;
# this setting only decides whether uvicorn believes it.
ENV FORWARDED_ALLOW_IPS="127.0.0.1"

CMD ["sh", "-c", "exec uvicorn lizenztool.api:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
