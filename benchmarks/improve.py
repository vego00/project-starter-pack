"""Lets Codex change the design prompt once, in a checkout that holds nothing else.

Usage: uv run --locked python benchmarks/improve.py <base ref> <round> <problems.md> <work dir>

Makes branch loop/round-<round> from <base ref> in a sparse worktree that holds only the two
files the agent may edit: backend/app/journey/prompts.py and design_generator.py. Cases,
review criteria, the validator and reports are not checked out, so the agent cannot read them.
Codex gets the problem summary and runs with workspace-write inside that folder, without saved
sessions, user config or rules. Afterwards a guard compares the Python syntax trees: in prompts.py
only DESIGN_SYSTEM and DESIGN_VERSION may change, in design_generator.py only FIX_HINTS, and the
version must be the round's name. A change that passes is committed on the branch; one that
fails is left uncommitted and reported. Prints a JSON summary.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = "backend/app/journey/prompts.py"
GENERATOR = "backend/app/journey/design_generator.py"
NOTE = "CHANGE_NOTE.md"
ALLOWED = {PROMPTS: {"DESIGN_SYSTEM", "DESIGN_VERSION"}, GENERATOR: {"FIX_HINTS"}}

TASK = """설계 초안 프롬프트를 한 번 고친다.

이 폴더에는 두 파일만 있다.
- {prompts}: DESIGN_SYSTEM(설계를 쓰는 모델에게 주는 지시)과 DESIGN_VERSION
- {generator}: FIX_HINTS(규칙에 걸린 초안을 고쳐 쓸 때 덧붙이는 안내)

해야 할 일:
1. 아래 ‘문제 요약’에서 가장 자주, 가장 크게 설계를 망치는 문제 하나를 고른다.
2. 그 문제를 줄이도록 DESIGN_SYSTEM이나 FIX_HINTS의 문장을 고친다. 한 가지 주제만 바꾼다. 관련 없는 규칙은 건드리지 않는다.
3. DESIGN_VERSION을 "{version}"으로 바꾼다.
4. {note} 파일을 새로 만들어 세 줄로 쓴다: 고른 문제, 바꾼 문장, 기대하는 효과.

지킬 것:
- 이 두 파일의 다른 코드(함수, 다른 상수, import)는 바꾸지 않는다. 바꾸면 이번 변경은 버려진다.
- 특정 사례나 회사 이름, 문제 요약 속 노드 이름을 프롬프트에 넣지 않는다. 일반 규칙으로 쓴다.
- 지시는 쉬운 한국어 문장으로 쓰고, 이미 있는 문장과 모순되지 않게 한다.

## 문제 요약

{problems}
"""


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _top_level(source: str) -> dict[str, str]:
    """Each top-level statement, keyed by the name it assigns or defines, as a syntax dump."""
    found: dict[str, str] = {}
    for index, node in enumerate(ast.parse(source).body):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            name = target.id if isinstance(target, ast.Name) else f"#{index}"
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        elif isinstance(node, ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef):
            name = node.name
        else:
            name = f"#{index}:{type(node).__name__}"
        found[name] = ast.dump(node)
    return found


def guard(path: str, before: str, after: str) -> list[str]:
    """Names changed outside what this file allows. Empty means the change is in bounds."""
    old, new = _top_level(before), _top_level(after)
    allowed = ALLOWED[path]
    changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    return sorted(changed - allowed)


def version_of(source: str) -> str | None:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "DESIGN_VERSION":
            return ast.literal_eval(node.value)
    return None


def main(argv: list[str]) -> dict:
    base, round_no, problems_file, work = argv
    version = f"design-loop-r{round_no}"
    branch = f"loop/round-{round_no}"
    folder = Path(work) / f"improve-r{round_no}"
    git("worktree", "add", "--no-checkout", "-b", branch, str(folder), base)
    git("sparse-checkout", "set", "--no-cone", f"/{PROMPTS}", f"/{GENERATOR}", cwd=folder)
    git("checkout", branch, cwd=folder)
    before = {path: (folder / path).read_text("utf-8") for path in ALLOWED}
    task = TASK.format(
        prompts=PROMPTS,
        generator=GENERATOR,
        version=version,
        note=NOTE,
        problems=Path(problems_file).read_text("utf-8"),
    )
    done = subprocess.run(
        [
            "codex",
            "exec",
            "-",
            "-C",
            str(folder),
            "-s",
            "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
        ],  # fmt: skip
        input=task,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    summary: dict = {"branch": branch, "folder": str(folder), "codex_exit": done.returncode}
    changed = git("diff", "--name-only", cwd=folder).splitlines()
    added = git("ls-files", "--others", "--exclude-standard", cwd=folder).splitlines()
    touched = sorted(set(changed) | set(added))
    outside = [path for path in touched if path not in (*ALLOWED, NOTE)]
    problems: list[str] = [f"outside files: {', '.join(outside)}"] if outside else []
    for path, old in before.items():
        new = (folder / path).read_text("utf-8")
        try:
            broken = guard(path, old, new)
        except SyntaxError as exc:
            broken = [f"syntax error: {exc.msg}"]
        if broken:
            problems.append(f"{path} changed {', '.join(broken)}")
    new_version = version_of((folder / PROMPTS).read_text("utf-8"))
    if new_version != version:
        problems.append(f"version is {new_version!r}, expected {version!r}")
    if not (folder / NOTE).exists():
        problems.append(f"no {NOTE}")
    summary.update(touched=touched, problems=problems, version=new_version)
    if not problems and touched:
        # The note explains the change; it goes into the summary, not into the repository.
        summary["note"] = (folder / NOTE).read_text("utf-8").strip()
        (folder / NOTE).unlink()
        git("add", *ALLOWED, cwd=folder)
        git("commit", "-q", "-m", f"loop: round {round_no} prompt change by Codex", cwd=folder)
        summary["commit"] = git("rev-parse", "--short", "HEAD", cwd=folder)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


if __name__ == "__main__":
    main(sys.argv[1:])
