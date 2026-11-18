"""Re-checks saved design drafts with the current validator. No model is called.

Usage: uv run --locked python benchmarks/rescore.py <report dir or results.json> [--case C4] [--all]

Each draft the runner kept is rebuilt with the constraints it was made under and validated again.
The report says which rules reject it now, whether that differs from when it ran (a validator
change), and shows the nodes and edges the error messages name, so a rejection can be read
without rerunning the model. By default only rejected drafts are shown.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.journey.design import Provenance, ServiceDesign  # noqa: E402
from app.journey.design_constraints import DesignConstraints  # noqa: E402
from app.journey.design_generator import DesignDraft, assemble_design  # noqa: E402


def rebuild(attempt: dict[str, Any]) -> ServiceDesign:
    draft = DesignDraft.model_validate(attempt["draft"])
    fields = {name: getattr(draft, name) for name in DesignDraft.model_fields}
    return assemble_design(
        fields,
        DesignConstraints.model_validate(attempt["constraints"]),
        Provenance.model_validate(attempt["provenance"]),
    )


def named_nodes(design: ServiceDesign, messages: list[str]) -> list[str]:
    """Node ids the messages mention, in order, as they appear in the design."""
    ids = {node.id for node in design.nodes}
    found: list[str] = []
    for message in messages:
        for token in re.findall(r"[A-Za-z0-9_.\-]+", message):
            if token in ids and token not in found:
                found.append(token)
    return found


def describe(design: ServiceDesign, node_id: str) -> list[str]:
    node = next(n for n in design.nodes if n.id == node_id)
    tools = ", ".join(f"{t.name}({t.access})" for t in node.tools) or "없음"
    lines = [f"- `{node.id}` ({node.kind}) 도구: {tools}"]
    for edge in design.workflow.edges:
        if node_id in (edge.source, edge.target):
            flags = " [실패 길]" if edge.on_failure else ""
            when = f" 조건: {edge.condition}" if edge.condition else ""
            lines.append(f"  - {edge.source} → {edge.target}{flags}{when}")
    return lines


def rescore(results: list[dict], case: str | None = None, show_all: bool = False) -> list[str]:
    out: list[str] = []
    for result in results:
        if case and result.get("case") != case:
            continue
        for attempt in result.get("design_attempts", []):
            if attempt.get("outcome") not in ("accepted", "rejected"):
                if show_all:
                    out.append(
                        f"## {result['case']} run {result.get('run')} 시도 {attempt['call']}: "
                        f"{attempt.get('outcome')} (다시 볼 초안 없음)"
                    )
                continue
            design = rebuild(attempt)
            errors = [i for i in design.validation or [] if i.severity == "error"]
            now = sorted({i.rule_id for i in errors})
            if not errors and not show_all:
                continue
            before = attempt.get("rules", [])
            same = "같음" if now == before else f"달라짐 (실행 때: {', '.join(before) or '없음'})"
            out += [
                f"## {result['case']} {result.get('mode')} run {result.get('run')} · "
                f"시도 {attempt['call']}",
                "",
                f"- 판정: {'거절' if errors else '통과'} · 규칙: {', '.join(now) or '없음'} · "
                f"실행 때와 비교: {same}",
                f"- 모델: {attempt.get('model_id')} · 프롬프트: {attempt.get('prompt_version')} · "
                f"토큰 in/out: {attempt.get('input_tokens')}/{attempt.get('output_tokens')}",
                f"- 이 시도가 받은 고칠 점: {len(attempt.get('problems_in', []))}개",
            ]
            out += [f"  - {p}" for p in attempt.get("problems_in", [])]
            out += ["", "거절 이유:"]
            out += [f"- `{i.rule_id}` {i.message}" for i in errors] or ["- 없음"]
            nodes = named_nodes(design, [i.message for i in errors])
            if nodes:
                out += ["", "관련 노드와 연결선:"]
                for node_id in nodes:
                    out += describe(design, node_id)
            if any(i.rule_id.startswith("loop.") for i in errors):
                out += ["", "반복 한도:"]
                out += [
                    f"- {', '.join(limit.node_ids)}: 최대 {limit.max_iterations}회, "
                    f"넘으면 → {limit.on_exceeded}"
                    for limit in design.workflow.loop_limits
                ] or ["- 없음"]
            out.append("")
    return out or ["다시 볼 거절된 초안이 없습니다."]


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="report directory or its results.json")
    parser.add_argument("--case", help="only this case id")
    parser.add_argument("--all", action="store_true", help="also show accepted drafts")
    args = parser.parse_args(argv)
    path = Path(args.path)
    if path.is_dir():
        path = path / "results.json"
    results = json.loads(path.read_text("utf-8"))["results"]
    text = "\n".join(
        [
            f"# 저장된 초안 다시 검사 ({path.parent.name})",
            "",
            *rescore(results, args.case, args.all),
        ]
    )
    (path.parent / "rescore.md").write_text(text + "\n", "utf-8")
    print(text)
    return text


if __name__ == "__main__":
    main()
