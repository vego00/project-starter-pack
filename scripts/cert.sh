#!/usr/bin/env bash
# VM에서 Let's Encrypt 인증서를 받거나 만료 30일 전부터 갱신한다. 처음 실행하면 프런트를 HTTPS로 다시 띄운다.
# 사용법: scripts/cert.sh   (cron으로 하루 두 번 실행)
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

tag="$(cat .deploy/current)"
compose() { IMAGE_TAG="$tag" docker compose -f compose.yaml -f compose.prod.yaml "$@"; }

# certbot은 root로 파일을 쓰고, Nginx는 uid 101로 읽는다.
compose --profile certbot run --rm certbot certonly \
  --webroot -w /var/www/certbot -d pjstarter.duckdns.org \
  --keep-until-expiring --non-interactive --agree-tos --register-unsafely-without-email \
  --deploy-hook 'chown -R 101:101 /etc/letsencrypt/live /etc/letsencrypt/archive'

if compose exec -T frontend grep -q 'listen 8443 ssl' /etc/nginx/conf.d/default.conf; then
  compose exec -T frontend nginx -s reload
else
  compose up -d --no-build --pull never --force-recreate frontend
fi
