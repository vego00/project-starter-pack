"""Runs the prompt improvement loop: measure, judge, improve, measure again, keep or revert.

Usage:
  uv run --locked python benchmarks/loop.py --base <ref> --work <dir> [--rounds 3] [--runs 3]
      [--cases C1,C4-design,C6,C8] [--no-judge]

Round 0 measures <ref>. Each later round hands a problem summary to the improvement agent
(improve.py, Codex), measures the prompt it wrote, and keeps it only by the rules in decide().
Every measurement drafts through agy (subscription) on a fresh checkout of the prompt being
tested, with this repository's benchmarks/ copied over it, so all rounds use the same cases
and tools. Card advice is mock and Jev follows .env. Judge scores (Codex) are recorded but do
not decide anything until they are calibrated against a person's scores.

Progress lines go to stdout and <work>/loop.log; per-case runner output goes to
<work>/logs/<round>-<case>.log; the round summaries go to <work>/loop-report.md and .json.
"""

import argparse
import concurrent.futures as cf
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from benchmarks.rescore import rescore  # noqa: E402

# Development set: improved against. C2 replaced C6 on 2026-11-20 because C6 never produced a
# rejection to learn from. Held-out set: only checked, never shown to the improvement agent.
DEV_CASES = ["C1", "C2", "C4-design", "C8"]
HELD_OUT_CASES = ["C5", "C6"]
AGY_MODEL = "gemini-3.8-flash-low"
CORE_RULE = "permission.write_without_approval"
# Rule counts reached their ceiling (11/12 first drafts, 1 rejection on 2026-11-20), so since
# 2026-11-23 the judge's score decides. A change must raise the mean by this much on both the
# measurement and its confirmation. Judge noise is not measured yet; the confirmation guards it.
JUDGE_GAIN = 0.05
# Same prompt measured twice moved first-draft passes by about 3 (2026-11-19).
SINGLE_SLACK = 2


def log(work: Path, text: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {text}"
    print(line, flush=True)
    with open(work / "loop.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def checkout_for_measuring(ref: str, folder: Path) -> Path:
    """A full checkout of the prompt under test, with this repo's benchmarks/ and .env."""
    if folder.exists():
        git("worktree", "remove", "--force", str(folder))
    git("worktree", "add", "-q", "--detach", str(folder), ref)
    shutil.rmtree(folder / "benchmarks")
    shutil.copytree(ROOT / "benchmarks", folder / "benchmarks",
                    ignore=shutil.ignore_patterns("__pycache__"))  # fmt: skip
    (folder / ".env").symlink_to(ROOT / ".env")
    return folder


def measure_case(folder: Path, case: str, runs: int, label: str, logfile: Path) -> Path | None:
    command = ["uv", "run", "--locked", "python", "benchmarks/run.py", "--designer", "agy",
               "--agy-model", AGY_MODEL, "--agy-effort", "low", "--allow-real",
               "--cases", case, "--modes", "flow", "--runs", str(runs), "--gap", "0",
               "--label", label, "--timeout", "3600"]  # fmt: skip
    with open(logfile, "w", encoding="utf-8") as out:
        done = subprocess.run(command, cwd=folder, stdout=out, stderr=subprocess.STDOUT)
    lines = logfile.read_text("utf-8").strip().splitlines()
    if done.returncode != 0 or not lines or not lines[-1].endswith("summary.md"):
        return None
    report = Path(lines[-1]).parent
    target = ROOT / "reports" / report.name  # judge.py and rescore read reports from here
    shutil.copytree(report, target, dirs_exist_ok=True)
    return target


def measure(work: Path, ref: str, round_no: int, cases: list[str], runs: int) -> dict:
    folder = checkout_for_measuring(ref, work / f"measure-r{round_no}")
    (work / "logs").mkdir(exist_ok=True)
    log(work, f"round {round_no}: measuring {ref} on {', '.join(cases)} x{runs}")
    with cf.ThreadPoolExecutor(len(cases)) as pool:
        futures = {
            case: pool.submit(
                measure_case,
                folder,
                case,
                runs,
                f"loop-r{round_no}-{case}",
                work / "logs" / f"r{round_no}-{case}.log",
            )  # fmt: skip
            for case in cases
        }
        reports = {case: future.result() for case, future in futures.items()}
    git("worktree", "remove", "--force", str(folder))
    return {"ref": ref, "reports": {c: (r.name if r else None) for c, r in reports.items()}}


def metrics(measurement: dict) -> dict:
    """Per case: designs that met the rules, single-draft passes, rules and contract breaks."""
    out: dict = {}
    for case, report in measurement["reports"].items():
        if report is None:
            out[case] = {"failed": True}
            continue
        results = json.loads((ROOT / "reports" / report / "results.json").read_text("utf-8"))
        rules: Counter = Counter()
        for result in results["results"]:
            for attempt in result.get("design_attempts", []):
                rules.update(attempt.get("rules", []))
                rules.update(f"형식:{f.split(':')[0]}" for f in attempt.get("contract_fields", []))
        rows = results["results"]
        out[case] = {
            "runs": len(rows),
            "model": sum((r.get("design") or {}).get("source") == "model" for r in rows),
            "single": sum(bool(r.get("single_draft_pass")) for r in rows),
            "rules": dict(rules),
        }
    return out


def decide(best: dict, candidate: dict) -> tuple[bool, str]:
    """Keep a change if the judge scores it clearly higher and nothing else slips.

    With judge scores on both sides (the default since 2026-11-23): sending before approval may
    never increase, designs that met the rules may not drop, first-draft passes may drop by at
    most SINGLE_SLACK, and the mean judge score must rise by JUDGE_GAIN. Without them (--no-judge)
    the older rejection rule below applies.

    Older rule: keep a change only if drafts are rejected clearly less often and nothing else slips.

    Designs that met the rules already sit at the ceiling (12/12 in round 0, 2026-11-19), so
    they and single-draft passes are floors that must not drop. The gain is counted in
    rejections (rule breaks plus contract breaks), and with 3 runs per case it must be at least
    2 so noise alone does not keep a change. Sending before approval may never increase.
    """
    if any(m.get("failed") for m in candidate.values()):
        return False, "측정 실패가 있어 판정하지 않음"

    def total(numbers: dict, key: str) -> int:
        return sum(m[key] for m in numbers.values())

    def rejections(numbers: dict) -> int:
        return sum(sum(m["rules"].values()) for m in numbers.values())

    core_before = sum(m["rules"].get(CORE_RULE, 0) for m in best.values())
    core_after = sum(m["rules"].get(CORE_RULE, 0) for m in candidate.values())
    if core_after > core_before:
        return False, f"승인 전 외부 쓰기가 늘었음 ({core_before} → {core_after})"
    if total(candidate, "model") < total(best, "model"):
        return False, f"맞춤 설계가 줄었음 ({total(best, 'model')} → {total(candidate, 'model')})"
    if judge_mean(best) is not None and judge_mean(candidate) is not None:
        if total(candidate, "single") < total(best, "single") - SINGLE_SLACK:
            return False, (f"첫 초안 통과가 {SINGLE_SLACK}개 넘게 줄었음 "
                           f"({total(best, 'single')} → {total(candidate, 'single')})")  # fmt: skip
        before_score, after_score = judge_mean(best), judge_mean(candidate)
        if after_score - before_score >= JUDGE_GAIN - 1e-9:
            return True, f"채점 {before_score:.2f} → {after_score:.2f}"
        return False, f"채점 {before_score:.2f} → {after_score:.2f} (유지 기준 +{JUDGE_GAIN})"
    if any("judge" in m for m in candidate.values()):
        return False, "채점이 빠진 사례가 있어 판정하지 않음"
    if total(candidate, "single") < total(best, "single"):
        return (
            False,
            f"첫 초안 통과가 줄었음 ({total(best, 'single')} → {total(candidate, 'single')})",
        )
    before, after = rejections(best), rejections(candidate)
    if before - after >= 2:
        return True, f"거절 {before} → {after}"
    return False, f"거절 {before} → {after} (유지 기준 −2)"


def average(first: dict, second: dict) -> dict:
    """Per case, the mean of two measurements of the same prompt: the baseline a kept change
    leaves for the next round, so one lucky measurement does not set the bar."""
    out: dict = {}
    for case in first:
        a, b = first[case], second[case]
        rules = {r: (a["rules"].get(r, 0) + b["rules"].get(r, 0)) / 2
                 for r in a["rules"].keys() | b["rules"].keys()}  # fmt: skip
        out[case] = {"runs": a["runs"], "model": (a["model"] + b["model"]) / 2,
                     "single": (a["single"] + b["single"]) / 2, "rules": rules}  # fmt: skip
        if a.get("judge") is not None and b.get("judge") is not None:
            out[case]["judge"] = (a["judge"] + b["judge"]) / 2
    return out


def judge_mean(numbers: dict) -> float | None:
    """Mean of the per-case judge scores, each case weighted alike; None if any case lacks one."""
    scores = [m.get("judge") for m in numbers.values()]
    if not scores or any(s is None for s in scores):
        return None
    return sum(scores) / len(scores)


def judge_scores(out: Path) -> dict:
    """Per case from a judge run: mean score (0..1, criteria scored 0-2) and the judge's notes on
    criteria below full marks. Designs the judge failed on are left out of the mean."""
    key = json.loads((out / "judge-key.json").read_text("utf-8"))
    per: dict[str, dict] = {}
    for jid, label in key.items():
        path = out / f"judge-{jid}.json"
        if not path.exists():
            continue
        found = json.loads(path.read_text("utf-8"))
        if "result" not in found:
            continue
        case = label.split("-", 1)[1].rsplit("-", 1)[0]
        scores = found["result"]["scores"]
        entry = per.setdefault(case, {"scores": [], "notes": []})
        entry["scores"].append(sum(s["score"] for s in scores) / (2 * len(scores)))
        entry["notes"] += [f"기준 {s['criterion']} ({s['score']}/2): {s['reason']}"
                           for s in scores if s["score"] < 2]  # fmt: skip
        entry["notes"] += [f"빌더가 물을 질문: {q['question']}"
                           for q in found["result"].get("builder_questions", [])
                           if q["kind"] == "decide_before_build"]  # fmt: skip
    return {case: {"score": sum(e["scores"]) / len(e["scores"]), "notes": e["notes"]}
            for case, e in per.items() if e["scores"]}  # fmt: skip


def problem_summary(measurement: dict, numbers: dict, notes: list[str] | None = None) -> str:
    """What the improvement agent sees: rule counts, a few rejections and the judge's notes on
    criteria below full marks, without case names."""
    rules: Counter = Counter()
    for case_metrics in numbers.values():
        rules.update(case_metrics.get("rules", {}))
    total = sum(m.get("runs", 0) for m in numbers.values())
    passed = sum(m.get("model", 0) for m in numbers.values())
    lines = [f"최근 측정: 맞춤 설계 {passed}/{total}.", "", "| 거절 이유 | 횟수 |", "| --- | --- |"]
    lines += [f"| {rule} | {count} |" for rule, count in rules.most_common()]
    examples: list[str] = []
    for report in measurement["reports"].values():
        if report is None:
            continue
        results = json.loads((ROOT / "reports" / report / "results.json").read_text("utf-8"))
        body = [ln for ln in rescore(results["results"]) if not ln.startswith("## ")]
        examples += [ln for ln in body if ln.startswith(("- `", "  - ")) and "고칠 점" not in ln]
    lines += ["", "거절 예시(노드 이름은 예시일 뿐 프롬프트에 넣지 않는다):", *examples[:20]]
    if notes:
        mean = judge_mean(numbers)
        lines += ["", f"채점 평균 {mean:.2f} (0~1). 채점자가 만점을 주지 않은 이유(사례 내용은 예시일 뿐 "
                  "프롬프트에 넣지 않는다):", *[f"- {n}" for n in notes[:30]]]  # fmt: skip
    return "\n".join(lines)


def judge(work: Path, measurement: dict, round_no: int) -> str | None:
    picks = {}
    for case, report in measurement["reports"].items():
        if report is None:
            continue
        results = json.loads((ROOT / "reports" / report / "results.json").read_text("utf-8"))
        for row in results["results"]:
            if (row.get("artifact") or {}).get("provenance", {}).get("source") == "model":
                picks[f"r{round_no}-{case}-{row['run']}"] = {
                    "case": case, "report": report, "run": row["run"]}  # fmt: skip
    if not picks:
        return None
    picks_file = work / f"judge-r{round_no}-picks.json"
    picks_file.write_text(json.dumps(picks, ensure_ascii=False, indent=1), "utf-8")
    out = work / f"judge-r{round_no}"
    log(work, f"round {round_no}: judging {len(picks)} designs")
    with open(work / "logs" / f"r{round_no}-judge.log", "w", encoding="utf-8") as handle:
        subprocess.run(["uv", "run", "--locked", "python", "benchmarks/judge.py",
                        str(picks_file), str(out)], cwd=ROOT, stdout=handle,
                       stderr=subprocess.STDOUT)  # fmt: skip
    return str(out)


def add_judge(work: Path, measurement: dict, numbers: dict, round_no) -> tuple[str | None, list]:
    """Judge the measurement's designs and put each case's mean score into numbers."""
    out = judge(work, measurement, round_no)
    if out is None:
        return None, []
    scored = judge_scores(Path(out))
    notes: list[str] = []
    for case, m in numbers.items():
        if not m.get("failed"):
            m["judge"] = scored.get(case, {}).get("score")
            notes += scored.get(case, {}).get("notes", [])
    return out, notes


def improve(work: Path, base: str, round_no: int, summary: str) -> dict:
    problems = work / f"problems-r{round_no}.md"
    problems.write_text(summary, "utf-8")
    log(work, f"round {round_no}: improvement agent (Codex) on {base}")
    with open(work / "logs" / f"r{round_no}-improve.log", "w", encoding="utf-8") as handle:
        done = subprocess.run(["uv", "run", "--locked", "python", "benchmarks/improve.py", base,
                               str(round_no), str(problems), str(work)],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=handle, text=True)  # fmt: skip
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        return {"problems": ["improve.py gave no summary"], "stdout": done.stdout[-500:]}


def write_report(work: Path, rounds: list[dict]) -> None:
    (work / "loop-report.json").write_text(json.dumps(rounds, ensure_ascii=False, indent=1))
    lines = ["# 개선 루프 기록", ""]
    for entry in rounds:
        numbers = entry["metrics"]
        model = sum(m.get("model", 0) for m in numbers.values())
        runs = sum(m.get("runs", 0) for m in numbers.values())
        lines += [f"## 바퀴 {entry['round']} · {entry['ref']}", "",
                  f"- 맞춤 설계 {model}/{runs} · 판정: {entry.get('verdict', '기준선')}"]  # fmt: skip
        if entry.get("note"):
            lines.append(f"- 바꾼 것: {entry['note']}")
        for case, m in numbers.items():
            if m.get("failed"):
                lines.append(f"- {case}: 측정 실패")
                continue
            top = ", ".join(f"{k} {v}" for k, v in Counter(m["rules"]).most_common(4)) or "-"
            score = f", 채점 {m['judge']:.2f}" if m.get("judge") is not None else ""
            lines.append(
                f"- {case}: {m['model']}/{m['runs']}, 첫 초안 {m['single']}{score} · {top}"
            )
        if entry.get("confirm_metrics"):
            again = entry["confirm_metrics"]
            ok = [m for m in again.values() if not m.get("failed")]
            lines.append(
                f"- 확인 측정(2차): 맞춤 설계 {sum(m['model'] for m in ok)}"
                f"/{sum(m['runs'] for m in ok)}, 첫 초안 {sum(m['single'] for m in ok)}, "
                f"거절 {sum(sum(m['rules'].values()) for m in ok)}"
            )
        if judge_mean(numbers) is not None:
            lines.append(f"- 채점 평균 {judge_mean(numbers):.2f} · {entry.get('judge')}")
        if entry.get("confirm_metrics") and judge_mean(entry["confirm_metrics"]) is not None:
            lines.append(f"- 확인 측정 채점 평균 {judge_mean(entry['confirm_metrics']):.2f}")
        lines.append("")
    (work / "loop-report.md").write_text("\n".join(lines), "utf-8")


def main(argv: list[str] | None = None) -> list[dict]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", default=",".join(DEV_CASES))
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument(
        "--baseline",
        help="loop-report.json of an earlier round 0 for the same ref, cases and runs; reused",
    )
    args = parser.parse_args(argv)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    cases = args.cases.split(",")
    started = time.time()

    best_ref = git("rev-parse", "--short", args.base)
    if args.baseline:
        earlier = json.loads(Path(args.baseline).read_text("utf-8"))[0]
        same = earlier["ref"] == best_ref and set(earlier["metrics"]) == set(cases)
        same = same and all(m.get("runs") == args.runs for m in earlier["metrics"].values())
        if not same:
            parser.error("--baseline was measured for another ref, cases or run count")
        rounds = [earlier]
        first, best = earlier["measurement"], earlier["metrics"]
        log(work, f"round 0: reusing the measurement of {best_ref} from {args.baseline}")
    else:
        first = measure(work, best_ref, 0, cases, args.runs)
        best = metrics(first)
        rounds = [{"round": 0, "ref": best_ref, "metrics": best, "measurement": first}]
        notes: list[str] = []
        if not args.no_judge:
            rounds[0]["judge"], notes = add_judge(work, first, best, 0)
    write_report(work, rounds)
    last, misses = first, 0
    if args.baseline:
        notes = rounds[0].get("judge_notes", [])
    rounds[0]["judge_notes"] = notes
    for round_no in range(1, args.rounds + 1):
        change = improve(work, best_ref, round_no, problem_summary(last, best, notes))
        if change.get("problems") or not change.get("commit"):
            entry = {"round": round_no, "ref": "-", "metrics": {}, "verdict": "변경 무효",
                     "note": "; ".join(change.get("problems", [])), "change": change}  # fmt: skip
            rounds.append(entry)
            misses += 1
        else:
            measured = measure(work, change["commit"], round_no, cases, args.runs)
            numbers = metrics(measured)
            judged, new_notes = (None, []) if args.no_judge else add_judge(
                work, measured, numbers, round_no)  # fmt: skip
            keep, why = decide(best, numbers)
            entry = {"round": round_no, "ref": change["commit"], "metrics": numbers,
                     "measurement": measured, "note": change.get("note")}  # fmt: skip
            if keep:
                # The same prompt measured twice moved by about ±3 first drafts and ±6
                # rejections (rounds 1 and 3, 2026-11-19), so a pass is measured again and
                # kept only if the second measurement passes too.
                log(work, f"round {round_no}: passed ({why}), measuring again to confirm")
                again = measure(work, change["commit"], f"{round_no}b", cases, args.runs)
                again_numbers = metrics(again)
                if not args.no_judge:
                    entry["confirm_judge"], _ = add_judge(
                        work, again, again_numbers, f"{round_no}b"
                    )
                keep, why_again = decide(best, again_numbers)
                why = f"1차 {why} · 2차 {why_again}"
                entry.update(confirm_metrics=again_numbers, confirm_measurement=again)
                if keep:
                    numbers = average(numbers, again_numbers)
            entry["verdict"] = ("유지 · " if keep else "되돌림 · ") + why
            entry.update(judge=judged, judge_notes=new_notes)
            rounds.append(entry)
            if keep:
                best_ref, best, last, misses = change["commit"], numbers, measured, 0
                notes = new_notes
            else:
                misses += 1
        log(work, f"round {round_no}: {entry['verdict']}")
        write_report(work, rounds)
        if misses >= 2:
            log(work, "두 바퀴 연속 개선이 없어 멈춤")
            break
    log(work, f"끝 · 최선 {best_ref} · {int(time.time() - started)}초")
    return rounds


if __name__ == "__main__":
    main()
