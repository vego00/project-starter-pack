"""Scores saved designs against each case's review criteria with Codex, blind.

Usage: uv run --locked python benchmarks/judge.py <picks.json> <out dir> [--parallel 4]

picks.json maps a label to {"case": id, "report": report dir name, "run": n}. Each design gets a
random ID; the judge sees only the case input, the card choices, the criteria and the design
text, never the label, report or prompt version. Each call runs `codex exec` in an empty folder,
read-only, without saving the session, user config or rules, and its answer must match a schema.
Results go to <out dir>/judge-<ID>.json; <out dir>/judge-key.json maps IDs back to labels. Scores
are not printed, so they can stay sealed until a person has scored the same designs.
"""

import argparse
import concurrent.futures as cf
import json
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from benchmarks.design_view import render_design  # noqa: E402
from benchmarks.replay_to_app import saved_design  # noqa: E402
from benchmarks.run import load_cases  # noqa: E402

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scores", "overall"],
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion", "score", "quote", "reason"],
                "properties": {
                    "criterion": {"type": "integer"},
                    "score": {"type": "integer", "enum": [0, 1, 2]},
                    "quote": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "overall": {"type": "string"},
    },
}

INSTRUCTIONS = """당신은 서비스 설계를 채점하는 평가자다. 아래의 사용자 요구, 카드 선택, 채점 기준, 설계만 보고 채점한다.

규칙:
- 기준마다 0(없음), 1(일부 충족), 2(충족) 중 하나를 준다. criterion에는 기준 번호를 쓴다.
- quote에는 근거가 된 설계 문장을 그대로 옮긴다. 근거가 없으면 빈 문자열로 둔다.
- reason에는 왜 그 점수인지 한 문장으로 쓴다.
- 설계에 적히지 않은 것을 있다고 가정하지 않는다.
- overall에는 이 설계를 실제로 쓸 수 있을지와 가장 큰 문제를 한두 문장으로 쓴다.
- 이 설계를 만든 방법이나 버전은 알려 주지 않는다. 파일을 읽거나 명령을 실행하지 말고 바로 답한다.
"""


def build_prompt(case: dict, design: dict) -> str:
    spec = {k: v for k, v in case["spec"].items() if v not in (None, [], "")}
    criteria = "\n".join(f"{i}. {c}" for i, c in enumerate(case["human_review"], 1))
    return "\n\n".join(
        [
            INSTRUCTIONS,
            "## 사용자 요구\n\n" + json.dumps(spec, ensure_ascii=False, indent=1),
            "## 카드 선택\n\n" + json.dumps(case["selection"], ensure_ascii=False, indent=1),
            "## 채점 기준\n\n" + criteria,
            "## 설계\n\n" + render_design(design, "설계"),
        ]
    )


def judge_one(prompt: str, timeout_s: int = 900) -> dict:
    with tempfile.TemporaryDirectory(prefix="judge-") as folder:
        schema = Path(folder, "schema.json")
        schema.write_text(json.dumps(SCHEMA), "utf-8")
        answer = Path(folder, "answer.json")
        done = subprocess.run(
            [
                "codex",
                "exec",
                "-",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "-s",
                "read-only",
                "--output-schema",
                str(schema),
                "-o",
                str(answer),
            ],  # fmt: skip
            input=prompt,
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if done.returncode != 0 or not answer.exists():
            return {"error": f"exit {done.returncode}", "stderr_tail": done.stderr[-500:]}
        return {"result": json.loads(answer.read_text("utf-8"))}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("picks")
    parser.add_argument("out")
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args(argv)
    picks = json.loads(Path(args.picks).read_text("utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    key_file = out / "judge-key.json"
    key = json.loads(key_file.read_text("utf-8")) if key_file.exists() else {}
    jobs = []
    for label, pick in picks.items():
        if label in key.values():
            continue  # already judged
        jid = f"J-{secrets.token_hex(3).upper()}"
        key[jid] = label
        case = load_cases([pick["case"]])[0]
        design = saved_design(pick["report"], pick["case"], pick["run"])
        jobs.append((jid, case["id"], build_prompt(case, design)))
    key_file.write_text(json.dumps(key, ensure_ascii=False, indent=1), "utf-8")

    def run(job):
        jid, case_id, prompt = job
        print(f"start: {jid}", flush=True)
        result = {"id": jid, "case": case_id, "prompt": prompt, **judge_one(prompt)}
        (out / f"judge-{jid}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), "utf-8"
        )
        print(f"{'FAILED' if 'error' in result else 'done'}: {jid}", flush=True)

    with cf.ThreadPoolExecutor(args.parallel) as pool:
        list(pool.map(run, jobs))
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
