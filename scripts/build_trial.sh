#!/usr/bin/env bash
# Builds a service from a downloaded build bundle with Antigravity (agy), kept apart from this
# project's context, so the author can judge the result.
#
#   bash scripts/build_trial.sh [bundle.zip] [name]   start a build (default: newest
#                                                     starter-pack*.zip in Windows Downloads)
#   bash scripts/build_trial.sh clean                 forget the builder's past conversations
#
# Isolation: agy runs with HOME set to a builder-only folder (BUILDER_HOME, default
# ~/builder-home), so none of the design-loop conversations kept under ~/.gemini are visible.
# Each build starts with the builder's conversations wiped (sign-in kept), in a new empty folder
# under BUILDS_DIR (default ~/builds), in a new agy project, with the same first message.
# Tools the build installs use the builder home for caches and settings (uv, npm, git identity).
set -euo pipefail

BUILDER_HOME="${BUILDER_HOME:-$HOME/builder-home}"
BUILDS_DIR="${BUILDS_DIR:-$HOME/builds}"
DOWNLOADS="${DOWNLOADS:-/mnt/c/Users/${WIN_USER:-141}/Downloads}"
STATE="$BUILDER_HOME/.gemini/antigravity-cli"
FIRST_MESSAGE="AGENTS.md와 BUILD.md를 읽고, BUILD.md의 진행 방법 순서대로 이 서비스를 만들어 주세요. \
.claude/skills의 skill을 쓸 수 없으면 그 파일을 읽고 같은 순서를 직접 따르세요. \
구현하면서 docs/build-notes.md를 채워 주세요."

clean() {
  # Everything agy remembers between sessions; the sign-in token and settings stay.
  rm -rf "$STATE"/conversations "$STATE"/brain "$STATE"/implicit "$STATE"/conversation_summaries.db \
    "$STATE"/*summaries*.pb "$STATE"/persistent_terminals "$BUILDER_HOME/.gemini/history"
  echo "빌더 기록을 지웠어요: $STATE"
}

if [[ "${1:-}" == "clean" ]]; then
  clean
  exit 0
fi

bundle="${1:-$(ls -t "$DOWNLOADS"/starter-pack*.zip 2>/dev/null | head -1 || true)}"
[[ -n "$bundle" && -f "$bundle" ]] || { echo "빌드 묶음 zip을 찾지 못했어요. 경로를 넘겨 주세요." >&2; exit 1; }

mkdir -p "$STATE"
if [[ ! -f "$STATE/antigravity-oauth-token" ]]; then
  echo "빌더 전용 agy에 아직 로그인하지 않았어요. 한 번만 로그인해 주세요:" >&2
  echo "  HOME=$BUILDER_HOME agy" >&2
  exit 1
fi

clean
folder="$BUILDS_DIR/${2:-build}-$(date +%m%d-%H%M)"
mkdir -p "$folder"
unpack="$(mktemp -d)"
python3 -m zipfile -e "$bundle" "$unpack"  # unzip is not installed everywhere
# The bundle's files sit under one top folder (starter-pack/); bring them up into the build folder.
top="$(find "$unpack" -mindepth 1 -maxdepth 1)"
if [[ "$(echo "$top" | wc -l)" -eq 1 && -d "$top" ]]; then
  cp -a "$top"/. "$folder"/
else
  cp -a "$unpack"/. "$folder"/
fi
rm -rf "$unpack"
[[ -f "$folder/BUILD.md" ]] || { echo "묶음에 BUILD.md가 없어요: $bundle" >&2; exit 1; }
printf '%s\n' "$FIRST_MESSAGE" >"$folder/.first-message.txt"
printf 'bundle=%s\nstarted=%s\ntool=agy\n' "$(basename "$bundle")" "$(date -Iseconds)" >"$folder/.build-trial.txt"

echo "빌드 폴더: $folder"
echo "끝나면 결과물의 흠과 $folder/docs/build-notes.md를 알려 주세요."
cd "$folder"
HOME="$BUILDER_HOME" agy --new-project --prompt-interactive "$FIRST_MESSAGE"
