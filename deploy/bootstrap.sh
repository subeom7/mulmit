#!/usr/bin/env bash
#
# EC2 최초 1회 세팅. 인스턴스 생성 시 User data에 붙여 넣거나,
# SSM Session Manager로 들어와 직접 실행한다.
#
# 대상: Amazon Linux 2023 (arm64). SSM 에이전트가 기본 탑재돼 있어
# SSH 없이 관리할 수 있다.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/subeom7/stock-metrics-calculator.git}"
# 머지 전에 브랜치를 올려 검증할 때 쓴다. 평소에는 main.
BRANCH="${BRANCH:-main}"
APP_DIR="/opt/stock-metrics"

echo ">> 패키지 설치"
dnf update -y
dnf install -y docker git

echo ">> docker compose 플러그인"
install -d /usr/libexec/docker/cli-plugins
ARCH="$(uname -m)"  # aarch64
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
  -o /usr/libexec/docker/cli-plugins/docker-compose
chmod +x /usr/libexec/docker/cli-plugins/docker-compose

systemctl enable --now docker
usermod -aG docker ssm-user 2>/dev/null || true
usermod -aG docker ec2-user 2>/dev/null || true

# 2GB RAM에서 Postgres + gunicorn 워커 2개 + 빌드가 겹치면 아슬아슬하다.
# 스왑이 있으면 OOM killer 대신 조금 느려지는 쪽으로 끝난다.
if [[ ! -f /swapfile ]]; then
  echo ">> 스왑 2GB"
  dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo ">> 도커 로그 크기 제한"
# 기본값은 무제한이라 몇 주 뒤 디스크가 로그로 가득 찬다
cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
systemctl restart docker

echo ">> 저장소 클론 (${BRANCH})"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" checkout --force "origin/${BRANCH}"
fi
cd "$APP_DIR"
chmod +x deploy/*.sh

if [[ ! -f .env ]]; then
  cp deploy/env.example .env
  # POSTGRES_PASSWORD를 무작위로 채운다. 사람이 정하면 약해진다.
  PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PASSWORD}|" .env
  echo
  echo "  !! .env를 만들었습니다. DOMAIN과 IMAGE를 채워 주세요:"
  echo "     sudo vi ${APP_DIR}/.env"
  echo
fi

echo ">> 완료. 첫 기동:"
echo "     cd ${APP_DIR} && sudo docker compose up -d"
echo "   그 다음부터는 GitHub Actions가 배포합니다."
