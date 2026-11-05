"""Checks a service design against itself and against the user's decisions.

Pure and deterministic. The contract checks one record at a time; this module checks what only the
whole design can show: references, graph shape, data flow, owners, permissions and limits.
Passing means no registered rule was broken. It does not prove the design is useful or that a
program built from it terminates.
"""

from app.journey.design import ServiceDesign, ValidationIssue
from app.journey.design_constraints import DesignConstraints


class _Issues(list[ValidationIssue]):
    def error(self, rule_id: str, message: str) -> None:
        self.append(ValidationIssue(rule_id=rule_id, severity="error", message=message))

    def warning(self, rule_id: str, message: str) -> None:
        self.append(ValidationIssue(rule_id=rule_id, severity="warning", message=message))


def _reach(start: str, graph: dict[str, set[str]]) -> set[str]:
    """Nodes reachable in one or more steps, so `start` is included only if it is on a cycle."""
    seen: set[str] = set()
    stack = list(graph.get(start, ()))
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(graph.get(node, ()))
    return seen


def _flow_graph(design: ServiceDesign, known: set[str]) -> dict[str, set[str]]:
    """Over-limit exits count as edges: a loop may leave only through its limit."""
    graph: dict[str, set[str]] = {node_id: set() for node_id in known}
    for edge in design.workflow.edges:
        if edge.source in known and edge.target in known:
            graph[edge.source].add(edge.target)
    for limit in design.workflow.loop_limits:
        for node_id in limit.node_ids:
            if node_id in known and limit.on_exceeded in known:
                graph[node_id].add(limit.on_exceeded)
    return graph


def _check_ids(design: ServiceDesign, issues: _Issues) -> None:
    groups = {
        "노드": [node.id for node in design.nodes],
        "요구사항": [req.id for req in design.requirements],
        "평가 사례": [case.id for case in design.eval_cases],
        "개발 작업": [task.id for task in design.tasks],
        "상태 필드": [field.name for field in design.state_fields],
    }
    for label, ids in groups.items():
        for duplicate in sorted({item for item in ids if ids.count(item) > 1}):
            issues.error("ref.duplicate_id", f"{label} ID가 중복됐어요: {duplicate}")


def _check_references(design: ServiceDesign, issues: _Issues) -> None:
    nodes = {node.id for node in design.nodes}
    cases = {case.id for case in design.eval_cases}
    tasks = {task.id for task in design.tasks}
    requirements = {req.id for req in design.requirements}
    cards = {ref.card_id for ref in design.provenance.decisions}
    workflow = design.workflow

    def check(owner: str, referenced: list[str], allowed: set[str], label: str) -> None:
        for item in referenced:
            if item not in allowed:
                issues.error("ref.unknown", f"{owner}: 없는 {label}를 가리켜요: {item}")

    for req in design.requirements:
        check(f"요구사항 {req.id}", req.node_ids, nodes, "노드")
        check(f"요구사항 {req.id}", req.eval_case_ids, cases, "평가 사례")
        check(f"요구사항 {req.id}", req.task_ids, tasks, "개발 작업")
    for node in design.nodes:
        check(f"노드 {node.id}", node.eval_case_ids, cases, "평가 사례")
    check("흐름 시작점", [workflow.entry], nodes, "노드")
    check("흐름 종료점", workflow.exits, nodes, "노드")
    for edge in workflow.edges:
        check("흐름 연결", [edge.source, edge.target], nodes, "노드")
    for limit in workflow.loop_limits:
        check("반복 한도", [*limit.node_ids, limit.on_exceeded], nodes, "노드")
    for field in design.state_fields:
        check(f"상태 필드 {field.name}", [*field.writers, *field.readers], nodes, "노드")
    for task in design.tasks:
        check(f"개발 작업 {task.id}", task.depends_on, tasks, "개발 작업")
    for reason in design.reasons:
        check("구성 이유", reason.requirement_ids, requirements, "요구사항")
        check("구성 이유", reason.card_ids, cards, "결정 카드")


def _check_graph(design: ServiceDesign, graph: dict[str, set[str]], issues: _Issues) -> None:
    workflow = design.workflow
    if workflow.entry not in graph:
        return
    from_entry = _reach(workflow.entry, graph) | {workflow.entry}
    exits = set(workflow.exits) & set(graph)
    for node_id in graph:
        if node_id not in from_entry:
            issues.error("graph.unreachable", f"시작점에서 닿지 않는 노드예요: {node_id}")
        elif node_id not in exits and not _reach(node_id, graph) & exits:
            issues.error("graph.no_exit", f"종료점으로 갈 수 없는 노드예요: {node_id}")


def _check_loops(design: ServiceDesign, graph: dict[str, set[str]], issues: _Issues) -> None:
    reach = {node_id: _reach(node_id, graph) for node_id in graph}
    checked: set[str] = set()
    for node_id in graph:
        if node_id in checked or node_id not in reach[node_id]:
            continue
        cycle = {other for other in reach[node_id] if node_id in reach[other]}
        checked |= cycle
        names = ", ".join(sorted(cycle))
        limits = [limit for limit in design.workflow.loop_limits if cycle & set(limit.node_ids)]
        if not limits:
            issues.error("loop.no_limit", f"반복 횟수 한도가 없는 순환이에요: {names}")
        elif not any(limit.on_exceeded not in cycle for limit in limits):
            issues.error("loop.no_way_out", f"한도를 넘어도 순환을 벗어나지 못해요: {names}")


def _check_data_flow(design: ServiceDesign, graph: dict[str, set[str]], issues: _Issues) -> None:
    upstream: dict[str, set[str]] = {node_id: set() for node_id in graph}
    for node_id in graph:
        for later in _reach(node_id, graph):
            upstream[later].add(node_id)
    outputs = {node.id: {port.name: port.type for port in node.outputs} for node in design.nodes}
    fields = {field.name: field for field in design.state_fields}

    for node in design.nodes:
        if node.id == design.workflow.entry:
            continue
        for port in node.inputs:
            sources = [
                outputs[source][port.name]
                for source in upstream.get(node.id, ())
                if port.name in outputs.get(source, {})
            ]
            field = fields.get(port.name)
            if field is not None and node.id in field.readers:
                sources.append(field.type)
            if not sources:
                issues.error(
                    "io.unconnected", f"노드 {node.id}의 입력 {port.name}을 만드는 곳이 없어요"
                )
            elif port.type not in sources:
                issues.error(
                    "io.type_mismatch",
                    f"노드 {node.id}의 입력 {port.name}은 {port.type}인데 "
                    f"들어오는 값은 {', '.join(sorted(set(sources)))}이에요",
                )


def _check_owners(design: ServiceDesign, issues: _Issues) -> None:
    nodes = {node.id: node for node in design.nodes}
    fields = {field.name: field for field in design.state_fields}
    for field in design.state_fields:
        for writer in field.writers:
            if writer in nodes:
                ports = {port.name: port.type for port in nodes[writer].outputs}
                if field.name not in ports:
                    issues.error(
                        "owner.writer_has_no_output",
                        f"노드 {writer}는 {field.name}을 쓴다고 했지만 그런 출력이 없어요",
                    )
                elif ports[field.name] != field.type:
                    issues.error(
                        "io.type_mismatch",
                        f"상태 필드 {field.name}은 {field.type}인데 "
                        f"노드 {writer}의 출력은 {ports[field.name]}이에요",
                    )
        for reader in field.readers:
            if reader in nodes and all(port.name != field.name for port in nodes[reader].inputs):
                issues.error(
                    "owner.reader_has_no_input",
                    f"노드 {reader}는 {field.name}을 읽는다고 했지만 그런 입력이 없어요",
                )
    for node in design.nodes:
        for port in node.outputs:
            field = fields.get(port.name)
            if field is not None and node.id not in field.writers:
                issues.error(
                    "owner.unlisted_writer",
                    f"노드 {node.id}가 쓰기 권한이 없는 상태 필드 {port.name}을 내보내요",
                )


def _check_decisions(
    design: ServiceDesign,
    constraints: DesignConstraints,
    graph: dict[str, set[str]],
    issues: _Issues,
) -> None:
    target = constraints.target
    agents = [node for node in design.nodes if node.kind == "agent"]
    humans = [node for node in design.nodes if node.kind == "human"]

    if target.min_agent_nodes is not None and len(agents) < target.min_agent_nodes:
        issues.error(
            "decision.too_few_agents",
            f"선택한 구조에는 에이전트가 {target.min_agent_nodes}개 이상 필요한데 "
            f"{len(agents)}개예요",
        )
    if target.max_agent_nodes is not None and len(agents) > target.max_agent_nodes:
        issues.error(
            "decision.too_many_agents",
            f"선택한 구조의 에이전트는 최대 {target.max_agent_nodes}개인데 {len(agents)}개예요",
        )
    if target.human_checks is not None:
        if target.human_checks and not humans:
            issues.error("decision.missing_human_check", "선택한 사람 확인 지점이 설계에 없어요")
        if not target.human_checks and humans:
            issues.error("decision.unwanted_human_check", "사람 확인 없음을 골랐는데 있어요")

    if target.allowed_providers is not None:
        allowed = set(target.allowed_providers)
        for node in agents:
            scopes = [node.model.provider_scope, node.model.fallback_scope]
            for scope in filter(None, scopes):
                if scope not in allowed:
                    issues.error(
                        "decision.provider_out_of_scope",
                        f"노드 {node.id}가 고르지 않은 모델 제공자를 써요: {scope}",
                    )

    needs_approval = "approval" in (target.human_checks or [])
    human_ids = {node.id for node in humans}
    for node in design.nodes:
        if not any(tool.access == "write" for tool in node.tools):
            continue
        if any(node.id in _reach(human, graph) for human in human_ids & set(graph)):
            continue
        message = f"노드 {node.id}가 사람 확인 없이 외부에 쓰기를 해요"
        if needs_approval:
            issues.error("permission.write_without_approval", message)
        else:
            issues.warning("permission.write_without_approval", message)

    if agents and design.workflow.max_model_calls == 0:
        issues.error("limit.no_model_calls", "에이전트가 있는데 모델 호출 한도가 0이에요")
    if agents and design.workflow.max_model_calls is None:
        issues.warning("limit.no_model_call_limit", "모델 호출 한도가 정해지지 않았어요")

    if set(design.provenance.decisions) != set(constraints.decisions):
        issues.error(
            "provenance.decisions_changed", "설계가 현재 결정과 다른 결정으로 만들어졌어요"
        )
    carried = {unknown.text: unknown for unknown in design.unknowns}
    for unknown in constraints.unknowns:
        kept = carried.get(unknown.text)
        if kept is None or (unknown.blocks_confirmation and not kept.blocks_confirmation):
            issues.error("unknown.dropped", f"미확인 사항이 설계에서 빠졌어요: {unknown.text}")


def _check_tracing(design: ServiceDesign, issues: _Issues) -> None:
    outputs = {node.id: {port.name for port in node.outputs} for node in design.nodes}
    for req in design.requirements:
        if req.output is not None and req.node_ids:
            if not any(req.output in outputs.get(node_id, ()) for node_id in req.node_ids):
                issues.error(
                    "trace.output_not_produced",
                    f"요구사항 {req.id}의 산출물 {req.output}을 담당 노드가 만들지 않아요",
                )
    claimed = {node_id for req in design.requirements for node_id in req.node_ids}
    for node in design.nodes:
        if node.kind == "agent" and node.id not in claimed:
            issues.warning(
                "trace.unjustified_agent", f"요구사항과 연결되지 않은 에이전트: {node.id}"
            )

    earlier: set[str] = set()
    all_tasks = {task.id for task in design.tasks}
    for task in design.tasks:
        for dependency in task.depends_on:
            if dependency in all_tasks and dependency not in earlier:
                issues.error(
                    "task.out_of_order",
                    f"개발 작업 {task.id}가 뒤에 나오는 작업 {dependency}에 의존해요",
                )
        earlier.add(task.id)


def validate_design(design: ServiceDesign, constraints: DesignConstraints) -> list[ValidationIssue]:
    issues = _Issues()
    graph = _flow_graph(design, {node.id for node in design.nodes})
    _check_ids(design, issues)
    _check_references(design, issues)
    _check_graph(design, graph, issues)
    _check_loops(design, graph, issues)
    _check_data_flow(design, graph, issues)
    _check_owners(design, issues)
    _check_decisions(design, constraints, graph, issues)
    _check_tracing(design, issues)
    return list(issues)
