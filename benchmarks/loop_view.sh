#!/usr/bin/env bash
# Starts the improvement loop in tmux session "loop" with a live view. Usage:
#   bash benchmarks/loop_view.sh <base ref> <work dir> [extra loop.py args]
set -euo pipefail
base="$1"; work="$2"; shift 2
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$work/logs"; touch "$work/loop.log"
tmux kill-session -t loop 2>/dev/null || true
tmux new-session -d -s loop -n loop -x 240 -y 60 -c "$root"
tmux set -t loop pane-border-status top
tmux set -t loop pane-border-format " #{pane_title} "
tmux select-pane -t loop:loop.0 -T "오케스트레이터"
tmux send-keys -t loop:loop.0 "uv run --locked python benchmarks/loop.py --base $base --work $work $*" Enter
tmux split-window -t loop:loop.0 -h -c "$root"
tmux select-pane -t loop:loop.1 -T "측정 진행 (사례별 마지막 줄)"
tmux send-keys -t loop:loop.1 "watch -n 3 'for f in \$(ls -t $work/logs/*.log 2>/dev/null | head -8); do printf \"%-24s %s\n\" \$(basename \$f .log) \"\$(tail -1 \$f | cut -c1-80)\"; done'" Enter
tmux split-window -t loop:loop.1 -v -c "$root"
tmux select-pane -t loop:loop.2 -T "바퀴 기록"
tmux send-keys -t loop:loop.2 "watch -n 5 cat $work/loop-report.md" Enter
echo "tmux attach -t loop"
