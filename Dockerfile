FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY lizenztool/ lizenztool/
COPY lizenztool.toml .

RUN pip install --no-cache-dir .

# Commit hash baked at build time (shown in footer); overridable at runtime via env.
ARG GIT_COMMIT=dev
ENV BUILD_COMMIT=${GIT_COMMIT}

RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "lizenztool.api:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
