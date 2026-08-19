#!/usr/bin/env bash
#
# 프로덕션 Postgres 일일 백업 → S3.
#
#   pg_dump(custom format, 압축) → s3://mulmit-backups-<계정>/pg/stock-<UTC시각>.dump
#
# 스케줄: 호스트 root crontab, 매일 19:00 UTC (04:00 KST).
# 보존: S3 수명주기 규칙이 30일 후 자동 삭제 (pg/ 프리픽스).
# 권한: 인스턴스 역할(stock-metrics-ec2)의 mulmit-backup-s3 인라인 정책.
#
# 복원 절차 (전체 복구):
#   aws s3 cp s3://mulmit-backups-941820582975/pg/<파일> /tmp/restore.dump
#   docker compose -f /opt/stock-metrics/docker-compose.yml stop web ingest
#   cat /tmp/restore.dump | docker compose -f /opt/stock-metrics/docker-compose.yml \
#     exec -T db pg_restore -U stock -d stock --clean --if-exists
#   docker compose -f /opt/stock-metrics/docker-compose.yml start web ingest
set -euo pipefail

BUCKET="mulmit-backups-941820582975"
APP_DIR="/opt/stock-metrics"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="/tmp/stock-${STAMP}.dump"

cd "$APP_DIR"
# custom format(-Fc)은 자체 압축 + pg_restore 선택 복원이 된다.
docker compose exec -T db pg_dump -U stock -d stock -Fc > "$OUT"

SIZE=$(stat -c%s "$OUT")
# 빈 덤프를 성공으로 올리면 백업이 있다는 착각만 남는다.
if [ "$SIZE" -lt 100000 ]; then
  echo "!! dump too small (${SIZE}B) — aborting upload" >&2
  rm -f "$OUT"
  exit 1
fi

aws s3 cp "$OUT" "s3://${BUCKET}/pg/stock-${STAMP}.dump" --only-show-errors
rm -f "$OUT"
echo "backup ok: pg/stock-${STAMP}.dump (${SIZE}B)"
