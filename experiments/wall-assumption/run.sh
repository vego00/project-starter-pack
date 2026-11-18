#!/usr/bin/env bash
# One isolated run per case arm: an empty folder outside the repo, no tools, no MCP, no settings files,
# the same system prompt and model for every run. Usage: bash run.sh toss-A   (or: bash run.sh all)
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
MODEL=sonnet
SYSTEM="You are a helpful assistant."
one() {
  local id="$1" dir="$ROOT/$1"
  [ -f "$dir/prompt.md" ] || { echo "no prompt: $id"; return 1; }
  cd "$dir" || return 1
  echo "start: $id ($(date '+%H:%M:%S'))"
  claude -p --model "$MODEL" --tools "" --strict-mcp-config --setting-sources "" \
    --system-prompt "$SYSTEM" --no-session-persistence --output-format json \
    < prompt.md > response.json 2> stderr.log
  local code=$?
  python3 -I - "$dir" "$code" "$MODEL" "$SYSTEM" <<'PY'
import json, sys, subprocess, datetime, pathlib
d, code, model, system = pathlib.Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
raw = (d / "response.json").read_text("utf-8", "replace")
meta = {"exit_code": code, "requested_model": model, "system_prompt": system,
        "flags": "-p --tools '' --strict-mcp-config --setting-sources '' --no-session-persistence --output-format json",
        "finished_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "claude_version": subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip(),
        "sampling": "Claude Code CLI default (not configurable)"}
try:
    data = json.loads(raw)
    (d / "response.md").write_text(data.get("result", ""), "utf-8")
    meta.update({k: data.get(k) for k in ("is_error", "num_turns", "duration_ms", "session_id", "stop_reason")})
    meta["models_used"] = list((data.get("modelUsage") or {}).keys())
    meta["usage"] = data.get("usage")
except Exception as exc:
    meta["parse_error"] = repr(exc)
(d / "run-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
PY
  if [ "$code" -eq 0 ] && [ -s "$dir/response.md" ]; then echo "done: $id ($(date '+%H:%M:%S'))"; else echo "FAILED: $id (exit $code, see $dir/stderr.log)"; fi
}
if [ "${1:-}" = "all" ]; then
  for id in toss-A toss-B baemin-A baemin-B daangn-A daangn-B; do one "$id" & done; wait
else
  one "${1:?usage: bash run.sh <case-arm>|all}"
fi
