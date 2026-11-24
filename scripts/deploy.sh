#!/usr/bin/env bash
# VM에서 한 커밋의 GHCR 이미지로 교체한다. /health가 실패하면 직전 배포로 되돌린다.
# 사용법: scripts/deploy.sh <커밋 SHA> <GHCR 사용자>   (GHCR 토큰은 표준 입력)
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

tag="$1"
registry_user="$2"
mkdir -p .deploy
previous="$(cat .deploy/current 2>/dev/null || true)"

compose() { IMAGE_TAG="$1" docker compose -f compose.yaml -f compose.prod.yaml "${@:2}"; }

healthy() {
  local port
  port="$(compose "$1" port frontend 5173)"
  port="${port##*:}"
  for _ in $(seq 30); do
    curl -fsS "http://127.0.0.1:$port/health" > /dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

# 토큰을 VM에 남기지 않도록 이번 실행에서만 쓰는 docker 설정 폴더에 로그인한다.
DOCKER_CONFIG="$(mktemp -d)"
export DOCKER_CONFIG
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
docker login ghcr.io -u "$registry_user" --password-stdin > /dev/null
# 켜진 프로필(oauth2-proxy 등)의 이미지까지 받는다.
compose "$tag" pull --quiet
compose "$tag" up -d --no-build --pull never

if healthy "$tag"; then
  echo "$tag" > .deploy/current
  [ -n "$previous" ] && [ "$previous" != "$tag" ] && echo "$previous" > .deploy/previous
  # 디스크를 아끼려고 현재와 직전 배포의 이미지만 남긴다.
  keep="$(cat .deploy/current .deploy/previous 2>/dev/null || true)"
  docker images --filter 'reference=ghcr.io/vego00/project-starter-pack/*' --format '{{.Repository}}:{{.Tag}}' |
    while read -r image; do
      [ "${image##*:}" = "<none>" ] && continue
      grep -qxF "${image##*:}" <<< "$keep" || docker rmi "$image" > /dev/null || echo "kept $image" >&2
    done
  echo "deployed $tag"
  exit 0
fi

echo "health check failed for $tag" >&2
if [ -n "$previous" ]; then
  compose "$previous" up -d --no-build --pull never
  healthy "$previous" && echo "rolled back to $previous" >&2 || echo "rollback to $previous is also unhealthy" >&2
else
  echo "no previous deploy to roll back to; rebuild with: docker compose -f compose.yaml -f compose.prod.yaml up -d --build" >&2
fi
exit 1
