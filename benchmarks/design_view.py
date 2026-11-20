"""Renders a saved design as Markdown a person or a judge can read.

The same text goes to human review pages and to the judge, so both look at the same thing.
Version labels and model names are left out so a reader cannot tell which prompt made it.
"""


def render_design(design: dict, title: str) -> str:
    workflow = design["workflow"]
    lines = [f"### {title}", "", "요구사항:"]
    for req in design["requirements"]:
        core = " (핵심)" if req.get("core") else ""
        lines.append(f"- {req['id']}{core}: {req['problem']} → {req.get('expected_output') or ''}")
    lines += [
        "",
        "노드:",
        "",
        "| 노드 | 종류 | 맡은 일 | 도구 | 실패하면 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for node in design["nodes"]:
        tools = ", ".join(f"{t['name']}({t['access']})" for t in node["tools"]) or "-"
        lines.append(
            f"| {node['id']} | {node['kind']} | {node['responsibility']} | {tools} "
            f"| {node['on_failure']} |"
        )
    lines += [
        "",
        f"흐름: 시작 {workflow['entry']} · 끝 {', '.join(workflow['exits'])} · "
        f"모델 호출 한도 {workflow.get('max_model_calls')}",
    ]
    for edge in workflow["edges"]:
        flag = " [실패 길]" if edge.get("on_failure") else ""
        when = f" ({edge['condition']})" if edge.get("condition") else ""
        lines.append(f"- {edge['source']} → {edge['target']}{flag}{when}")
    for limit in workflow.get("loop_limits", []):
        lines.append(
            f"- 반복 한도: {', '.join(limit['node_ids'])} 최대 {limit['max_iterations']}회, "
            f"넘으면 → {limit['on_exceeded']}"
        )
    fields = design.get("state_fields", [])
    if fields:
        lines += ["", "상태 필드:"]
        lines += [
            f"- {f['name']}: 쓰는 노드 {', '.join(f.get('writers', []))} · "
            f"읽는 노드 {', '.join(f.get('readers', []))} · 수명 {f.get('lifetime', '-')}"
            for f in fields
        ]
    lines += ["", "미확인:"] + (
        [f"- {u['text']}" for u in design.get("unknowns", [])] or ["- 없음"]
    )
    lines += ["", "경고:"] + ([f"- {w}" for w in design.get("warnings", [])] or ["- 없음"])
    lines += ["", "평가 사례:"] + [
        f"- {e['id']}: {e['given']} → {e['expect']}" for e in design.get("eval_cases", [])
    ]
    lines += ["", "작업 순서:"] + [
        f"- {t['title']}: 입력 {t.get('inputs', '')} / 산출물 {t.get('produces', '')} / "
        f"확인 {t.get('verify_by', '')}"
        for t in design.get("tasks", [])
    ]
    return "\n".join(lines)
