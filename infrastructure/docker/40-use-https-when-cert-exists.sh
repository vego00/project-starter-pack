#!/bin/sh
# Nginx 시작 전에 실행된다. 인증서가 있으면 HTTPS 설정을 쓰고, 없으면 HTTP 전용 설정을 그대로 둔다.
set -eu
cert=/etc/letsencrypt/live/pjstarter.duckdns.org
if [ -r "$cert/fullchain.pem" ] && [ -r "$cert/privkey.pem" ]; then
  cp /etc/nginx/https.conf /etc/nginx/conf.d/default.conf
  echo "$0: using the HTTPS config"
fi
