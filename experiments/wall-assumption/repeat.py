"""Repeats the A/B runs and the blind scoring in one go, then tabulates the scores.

Run 1 already exists (runs/<case>-<arm>, scoring/score-<case>). This adds runs 2..N with the
same prompts, isolation flags and models, scores each case's pair blind under fresh random IDs,
and writes a summary. Usage: python3 repeat.py <work dir> [reps=5] [parallel=6]
"""

import concurrent.futures as cf
import datetime
import json
import random
import re
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
WORK = Path(sys.argv[1])
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
PARALLEL = int(sys.argv[3]) if len(sys.argv) > 3 else 6
CASES = ["toss", "baemin", "daangn"]
SYSTEM = "You are a helpful assistant."
FLAGS = ["--tools", "", "--strict-mcp-config", "--setting-sources", "",
         "--system-prompt", SYSTEM, "--no-session-persistence", "--output-format", "json"]
ITEMS = ["실제 문제와 일치", "실험의 판별력", "실패 후 행동", "사용자 개입 판단"]


def say(text):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {text}", flush=True)


def call(folder: Path, model: str) -> bool:
    """One isolated claude -p call in an empty folder outside the repo."""
    with open(folder / "prompt.md", "rb") as stdin, open(folder / "response.json", "wb") as out, \
            open(folder / "stderr.log", "wb") as err:
        code = subprocess.run(["claude", "-p", "--model", model, *FLAGS],
                              stdin=stdin, stdout=out, stderr=err, cwd=folder).returncode
    meta = {"exit_code": code, "requested_model": model, "system_prompt": SYSTEM,
            "flags": " ".join(FLAGS[:-4]) + " --no-session-persistence --output-format json",
            "finished_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "sampling": "Claude Code CLI default (not configurable)"}
    try:
        data = json.loads((folder / "response.json").read_text("utf-8"))
        (folder / "response.md").write_text(data.get("result", ""), "utf-8")
        meta.update({k: data.get(k) for k in ("is_error", "num_turns", "duration_ms", "stop_reason")})
        meta["models_used"] = list((data.get("modelUsage") or {}).keys())
        meta["usage"] = data.get("usage")
    except Exception as exc:  # noqa: BLE001 - recorded, the summary marks the run as failed
        meta["parse_error"] = repr(exc)
    (folder / "run-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    ok = code == 0 and (folder / "response.md").exists() and (folder / "response.md").stat().st_size > 0
    say(("done: " if ok else "FAILED: ") + folder.name)
    return ok


def run_all(folders, model):
    with cf.ThreadPoolExecutor(PARALLEL) as pool:
        return dict(zip(folders, pool.map(lambda f: call(f, model), folders)))


def scoring_prompt(case: str, rep: int, key: dict) -> str:
    # The scoring text is the run-1 kit with its two responses swapped for this rep's pair.
    base = (HERE / "scoring" / f"score-{case}" / "prompt.md").read_text("utf-8")
    head = base.split("\n## 응답 R-", 1)[0]
    arms = ["A", "B"]
    random.SystemRandom().shuffle(arms)
    parts = [head.rstrip()]
    for arm in arms:
        rid = f"R-{secrets.token_hex(2).upper()}"
        key[f"{case}-r{rep}"][rid] = arm
        resp = (WORK / "runs" / f"{case}-{arm}-r{rep}" / "response.md").read_text("utf-8")
        parts.append(f"## 응답 {rid}\n\n{resp.strip()}")
    return "\n\n".join(parts) + "\n"


def parse(text: str) -> dict:
    """Scores per response ID and the same/different verdict from a scorer's answer."""
    out, current = {}, None
    for line in text.splitlines():
        m = re.match(r"#+\s*응답\s+(R-[0-9A-F]{4})", line)
        if m:
            current = out.setdefault(m.group(1), {})
            continue
        for item in ITEMS:
            m = re.match(rf"\s*-\s*{item}\s*:\s*\**\s*([012])", line)
            if m and current is not None:
                current[item] = int(m.group(1))
    tail = text.strip().splitlines()[-1] if text.strip() else ""
    verdict = "다름" if re.search(r"다르(다|며|고)|달라", tail) and "같" not in tail else (
        "같음" if "같" in tail else "판정 없음")
    return {"scores": out, "verdict": verdict, "verdict_line": tail}


def main():
    runs, scoring = WORK / "runs", WORK / "scoring"
    # Run 1 is the existing pair; copy it under the -r1 name so every rep reads the same way.
    for case in CASES:
        for arm in "AB":
            src, dst = runs / f"{case}-{arm}", runs / f"{case}-{arm}-r1"
            if src.exists() and not dst.exists():
                dst.mkdir()
                for name in ("prompt.md", "response.md", "response.json", "run-meta.json"):
                    (dst / name).write_bytes((src / name).read_bytes())
    todo = []
    for rep in range(2, REPS + 1):
        for case in CASES:
            for arm in "AB":
                d = runs / f"{case}-{arm}-r{rep}"
                if (d / "response.md").exists():
                    continue
                d.mkdir(parents=True, exist_ok=True)
                (d / "prompt.md").write_bytes((HERE / "prompts" / f"{case}-{arm}.md").read_bytes())
                todo.append(d)
    say(f"responses to make: {len(todo)} (sonnet, {PARALLEL} at a time)")
    run_all(todo, "sonnet")

    key_file = scoring / "blind-key-repeat.json"
    key = json.loads(key_file.read_text()) if key_file.exists() else {}
    score_todo = []
    for rep in range(2, REPS + 1):
        for case in CASES:
            d = scoring / f"score-{case}-r{rep}"
            if (d / "response.md").exists():
                continue
            pair = [runs / f"{case}-{arm}-r{rep}" / "response.md" for arm in "AB"]
            if not all(p.exists() and p.stat().st_size for p in pair):
                say(f"skip scoring {case}-r{rep}: a response is missing")
                continue
            key[f"{case}-r{rep}"] = {}
            d.mkdir(parents=True, exist_ok=True)
            (d / "prompt.md").write_text(scoring_prompt(case, rep, key), "utf-8")
            score_todo.append(d)
    key_file.write_text(json.dumps(key, indent=2), "utf-8")
    say(f"scorings to make: {len(score_todo)} (opus, {PARALLEL} at a time)")
    run_all(score_todo, "opus")

    # Summary across all reps, with run 1 read from the original kit and key.
    key1 = json.loads((HERE / "scoring" / "blind-key.json").read_text())
    rows = []
    for case in CASES:
        for rep in range(1, REPS + 1):
            if rep == 1:
                text = (HERE / "scoring" / f"score-{case}" / "response.md").read_text("utf-8")
                k = key1[case]
            else:
                f = scoring / f"score-{case}-r{rep}" / "response.md"
                if not f.exists():
                    rows.append({"case": case, "rep": rep, "missing": True})
                    continue
                text, k = f.read_text("utf-8"), key[f"{case}-r{rep}"]
            p = parse(text)
            by_arm = {k[rid]: s for rid, s in p["scores"].items() if rid in k}
            rows.append({"case": case, "rep": rep, "A": by_arm.get("A"), "B": by_arm.get("B"),
                         "first_action": p["verdict"], "verdict_line": p["verdict_line"]})
    (WORK / "repeat-summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
    say("summary: repeat-summary.json")
    for r in rows:
        if r.get("missing"):
            print(f"{r['case']} r{r['rep']}: missing")
            continue
        a, b = r["A"] or {}, r["B"] or {}
        print(f"{r['case']} r{r['rep']}: 판별력 A {a.get('실험의 판별력')} / B {b.get('실험의 판별력')}"
              f" · 첫날 행동 {r['first_action']}")
    say("ALL DONE")


if __name__ == "__main__":
    main()
