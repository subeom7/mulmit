#!/usr/bin/env bash
#
# EC2에서 실행되는 배포 스크립트. GitHub Actions가 SSM으로 호출한다.
#
#   ./deploy/release.sh ghcr.io/owner/repo:<sha>
#
# 헬스체크가 실패하면 직전 이미지로 되돌린다. 되돌리기까지 실패하면
# 0이 아닌 값으로 끝나서 Actions가 빨갛게 뜬다.
set -euo pipefail

IMAGE="${1:?배포할 이미지 태그가 필요합니다}"
APP_DIR="/opt/stock-metrics"
PREV_FILE="${APP_DIR}/.previous-image"
HEALTH_URL="http://127.0.0.1:8000/api/health"

cd "$APP_DIR"

# .env에는 POSTGRES_PASSWORD, DOMAIN 같은 비밀값이 들어 있다. 저장소에 없다.
if [[ ! -f .env ]]; then
  echo "!! .env가 없습니다. deploy/env.example을 참고해 만드세요." >&2
  exit 1
fi

current_image() {
  grep -E '^IMAGE=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true
}

set_image() {
  local value="$1"
  # .env의 IMAGE 줄을 교체(없으면 추가)
  if grep -qE '^IMAGE=' .env; then
    sed -i "s|^IMAGE=.*|IMAGE=${value}|" .env
  else
    echo "IMAGE=${value}" >> .env
  fi
}

wait_healthy() {
  # web 컨테이너가 뜨고 DB 마이그레이션(create_all)까지 끝나는 시간을 준다
  for _ in $(seq 1 30); do
    if docker compose exec -T web curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

PREVIOUS="$(current_image)"
echo ">> 이전 이미지: ${PREVIOUS:-없음}"
echo ">> 새 이미지  : ${IMAGE}"

set_image "$IMAGE"
docker compose pull web ingest
docker compose up -d --remove-orphans

if wait_healthy; then
  echo ">> 헬스체크 통과"
  [[ -n "$PREVIOUS" ]] && echo "$PREVIOUS" > "$PREV_FILE"
  # 오래된 이미지 정리. 안 하면 30GB 디스크가 조용히 찬다.
  docker image prune -af --filter "until=168h" >/dev/null 2>&1 || true
  docker compose ps
  exit 0
fi

echo "!! 헬스체크 실패 — 롤백합니다" >&2
docker compose logs --tail 50 web >&2 || true

if [[ -z "$PREVIOUS" ]]; then
  echo "!! 되돌릴 이전 이미지가 없습니다" >&2
  exit 1
fi

set_image "$PREVIOUS"
docker compose up -d
if wait_healthy; then
  echo "!! 롤백 완료 (${PREVIOUS}) — 배포는 실패로 처리합니다" >&2
  exit 1
fi

echo "!! 롤백도 실패했습니다. 수동 확인이 필요합니다." >&2
exit 2
