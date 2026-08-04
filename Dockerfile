# syntax=docker/dockerfile:1
#
# 웹과 수집 배치가 같은 이미지를 쓴다. 커맨드만 다르다(compose 참고).
# 빌드 스테이지를 나눈 건 컴파일러/헤더를 최종 이미지에서 빼기 위해서다.
# t4g(Graviton) 대상이라 linux/arm64로 빌드하지만 Dockerfile 자체는
# 아키텍처 중립이다 — numpy/pandas/statsmodels 모두 aarch64 휠이 있다.

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATA_DIR=/data \
    PORT=8000

# curl은 헬스체크용
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app \
 && mkdir -p /data && chown app:app /data

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app app ./app
COPY --chown=app:app scripts ./scripts

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# 워커 2개 = t4g.small의 vCPU 수. 몬테카를로가 CPU 바운드라 더 늘려도
# 스루풋이 안 오르고 메모리만 먹는다(워커당 pandas/statsmodels가 통째로 올라간다).
CMD ["sh", "-c", "gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WEB_CONCURRENCY:-2} \
    --bind 0.0.0.0:${PORT} \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -"]
