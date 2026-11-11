"""The graphs the workspace draws: rebuilt from decisions and the design, never stored.

Deterministic, so the picture cannot drift from what was decided. An undecided card is a blank node;
a skipped card or a card this registry does not hold leaves nothing to draw.
"""

from typing import Literal

from pydantic import BaseModel

from app.journey.design import Edge as DesignEdge
from app.journey.design import Node as DesignNode
from app.journey.design import ServiceDesign
from app.journey.state import JourneyState
from app.registry.loader import Registry

NodeKind = Literal["code", "agent", "human", "blank", "sys"]
# Which box of the system diagram a node sits in.
Group = Literal["people", "client", "app", "model", "data", "ops"]
# Marks for options. The graph draws one only for a service the user actually chose; a card shows
# them all so options can be told apart. Lowercase generic names are shapes.
OPTION_ICONS = {
    ("data.checkpointer", "memory"): "memory",
    ("data.primary_db", "none"): "none",
    ("data.vector_store", "none"): "none",
    ("ops.tracing", "none"): "none",
    ("product.surface", "web"): "browser",
    ("product.surface", "messenger"): "chat",
    ("product.surface", "report"): "document",
    ("backend.execution", "background"): "worker",
    ("model.provider", "gemini"): "googlegemini",
    ("model.provider", "openai"): "openai",
    ("model.provider", "upstage"): "agent",
    ("model.provider", "exaone"): "agent",
    ("model.provider", "openrouter"): "agent",
    ("model.provider", "ollama"): "ollama",
    ("mlops.model_serving", "ollama"): "ollama",
    ("mlops.model_serving", "vllm"): "server",
    ("data.primary_db", "postgres"): "postgresql",
    ("data.primary_db", "sqlite"): "sqlite",
    ("data.checkpointer", "postgres"): "postgresql",
    ("data.checkpointer", "other"): "database",
    ("data.vector_store", "pgvector"): "postgresql",
    ("data.vector_store", "qdrant"): "search",
    ("data.vector_store", "chroma"): "search",
    ("devops.orchestration", "none"): "docker",
    ("devops.orchestration", "local_k8s"): "kubernetes",
    ("devops.orchestration", "single_vm_k3s"): "k3s",
    ("devops.orchestration", "managed_k8s"): "kubernetes",
    ("cloud.target", "local"): "laptop",
    ("cloud.target", "gcp"): "googlecloud",
    ("cloud.target", "aws"): "amazonwebservices",
    ("ops.tracing", "langsmith"): "langchain",
    ("ops.tracing", "logs"): "log",
}
# Decisions one PostgreSQL can answer together: drawn as one service with a line for each.
POSTGRES_ROLES = (
    ("data.primary_db", "데이터 저장", "postgres"),
    ("data.checkpointer", "상태 저장", "postgres"),
    ("data.vector_store", "벡터 검색", "pgvector"),
)
CODE_STEP = "모델을 호출하지 않는 코드 단계예요."
UNKNOWN_AGENT_STEP = [
    "단계가 몇 개이고 각각 무슨 일을 하는지",
    "단계별 입력과 출력",
    "쓰는 도구와 권한",
    "완료 기준",
]
DECISIONS_BY_KIND = {
    "agent": ("agent.topology", "model.provider"),
    "human": ("agent.hitl", "data.checkpointer"),
}


class BlueprintRow(BaseModel):
    """One decision answered by a service that answers several."""

    role: str
    label: str
    card_id: str


class BlueprintNote(BaseModel):
    """A decided card whose answer draws no service, kept within reach of the graph."""

    group: Group
    label: str
    card_id: str


class StepTool(BaseModel):
    name: str
    access: Literal["read", "write", "external_write"]
    reason: str


class StepDecision(BaseModel):
    card_id: str
    label: str


class BlueprintStep(BaseModel):
    """What building a step takes. Before a design exists, only what the decisions settle."""

    line: str
    fixed: list[str] = []
    unknown: list[str] = []
    inputs: list[str] = []
    outputs: list[str] = []
    how: str | None = None
    tools: list[StepTool] = []
    done_when: str | None = None
    on_failure: str | None = None
    checks: list[str] = []
    first_task: str | None = None
    decisions: list[StepDecision] = []


class BlueprintNode(BaseModel):
    id: str
    label: str
    kind: NodeKind
    card_id: str | None = None
    icon: str | None = None
    group: Group | None = None
    rows: list[BlueprintRow] = []
    step: BlueprintStep | None = None


class BlueprintEdge(BaseModel):
    source: str
    target: str
    label: str | None = None
    dashed: bool = False


class BlueprintGraph(BaseModel):
    nodes: list[BlueprintNode] = []
    edges: list[BlueprintEdge] = []


class Blueprint(BaseModel):
    agent: BlueprintGraph
    system: BlueprintGraph
    notes: list[BlueprintNote] = []
    # True until a design exists: the agent flow is then only what the cards imply.
    agent_is_draft: bool


class BlueprintExample(BaseModel):
    id: str
    name: str
    note: str
    blueprint: Blueprint


class _Canvas:
    def __init__(self, registry: Registry, choices: dict[str, str], skipped: set[str]):
        self.registry, self.choices, self.skipped = registry, choices, skipped
        self.graph = BlueprintGraph()
        self.notes: list[BlueprintNote] = []

    def node(
        self,
        node_id: str,
        label: str,
        kind: NodeKind,
        card_id: str | None = None,
        icon: str | None = None,
        group: Group | None = None,
        rows: list[BlueprintRow] | None = None,
        step: BlueprintStep | None = None,
    ) -> str:
        self.graph.nodes.append(
            BlueprintNode(
                id=node_id,
                label=label,
                kind=kind,
                card_id=card_id,
                icon=icon,
                group=group,
                rows=rows or [],
                step=step,
            )
        )
        return node_id

    def edge(self, source: str, target: str, label: str | None = None, dashed: bool = False):
        self.graph.edges.append(
            BlueprintEdge(source=source, target=target, label=label, dashed=dashed)
        )

    def chain(self, *node_ids: str | None) -> str:
        present = [node_id for node_id in node_ids if node_id]
        for source, target in zip(present, present[1:]):
            self.edge(source, target)
        return present[-1]

    def in_play(self, card_id: str) -> bool:
        return card_id in self.registry.card_ids and card_id not in self.skipped

    def choice(self, card_id: str) -> str | None:
        return self.choices.get(card_id)

    def option_name(self, card_id: str) -> str:
        return self.registry.card(card_id).option(self.choices[card_id]).name

    def decided(self, *card_ids: str) -> list[StepDecision]:
        return [
            StepDecision(
                card_id=card_id,
                label=f"{self.registry.card(card_id).title}: {self.option_name(card_id)}",
            )
            for card_id in dict.fromkeys(card_ids)
            if card_id in self.choices and card_id in self.registry.card_ids
        ]

    def setting(self, card_id: str, label: str) -> list[str]:
        """One line stating a decision other than the step's own, once it is made."""
        return [f"{label}: {self.option_name(card_id)}"] if card_id in self.choices else []

    def settled(self, card_id: str) -> list[str]:
        """What the chosen option commits the step to, in the card's own words."""
        option = self.registry.card(card_id).option(self.choices[card_id])
        return [f"{option.name}: {option.summary}", *option.pros[:1], *option.cons[:1]]

    def note(self, card_id: str, group: Group) -> None:
        label = f"{self.registry.card(card_id).title}: {self.option_name(card_id)}"
        self.notes.append(BlueprintNote(group=group, label=label, card_id=card_id))

    def option_node(self, card_id: str, node_id: str, blank: str, group: Group) -> str | None:
        """Draws the chosen option under its own name, or a blank to fill in."""
        if not self.in_play(card_id):
            return None
        option_id = self.choice(card_id)
        if option_id is None:
            return self.node(f"blank-{card_id}", blank, "blank", card_id, group=group)
        label = self.registry.card(card_id).option(option_id).name
        icon = OPTION_ICONS.get((card_id, option_id), "server")
        return self.node(node_id, label, "sys", card_id, icon=icon, group=group)


def _data(canvas: _Canvas, runner: str) -> None:
    rows = [
        BlueprintRow(role=role, label=canvas.option_name(card_id), card_id=card_id)
        for card_id, role, option_id in POSTGRES_ROLES
        if canvas.choice("data.primary_db") == "postgres" and canvas.choice(card_id) == option_id
    ]
    shared = {row.card_id for row in rows} if len(rows) > 1 else set()
    if shared:
        canvas.node("database", "PostgreSQL", "sys", icon="postgresql", group="data", rows=rows)
        canvas.edge(runner, "database")

    if "data.primary_db" not in shared:
        if canvas.choice("data.primary_db") == "none":
            canvas.note("data.primary_db", "data")
        elif database := canvas.option_node(
            "data.primary_db", "database", "데이터 저장소?", "data"
        ):
            canvas.edge(runner, database, "저장")

    if "data.checkpointer" not in shared:
        if canvas.choice("data.checkpointer") == "memory":
            canvas.note("data.checkpointer", "data")
        elif state := canvas.option_node("data.checkpointer", "checkpoint", "상태 저장?", "data"):
            canvas.edge(runner, state, "체크포인트", dashed=True)

    if "data.vector_store" not in shared:
        if canvas.choice("data.vector_store") == "none":
            canvas.note("data.vector_store", "data")
        elif search := canvas.option_node("data.vector_store", "search", "검색 저장소?", "data"):
            canvas.edge(runner, search, "검색")


def _system(canvas: _Canvas) -> None:
    users = canvas.node("users", "사용자", "sys", icon="person", group="people")
    surface = canvas.option_node("product.surface", "surface", "사용 위치?", "client")
    surface = surface or canvas.node(
        "surface", "사용자 화면", "sys", icon="browser", group="client"
    )
    api = canvas.node("api", "백엔드 API", "sys", icon="server", group="app")
    # Drawn after the execution parts below, so the service box reads top to bottom in run order.
    runner = "runner"
    canvas.edge(users, surface)
    canvas.edge(surface, api, "요청")

    execution = canvas.choice("backend.execution")
    if not canvas.in_play("backend.execution") or execution == "sync":
        canvas.edge(api, runner, "실행")
        if execution == "sync":
            canvas.note("backend.execution", "app")
    elif execution is None:
        blank = canvas.option_node("backend.execution", "execution", "작업 실행?", "app")
        canvas.chain(api, blank, runner)
    elif execution == "queue":
        queue = canvas.node("queue", "Redis 큐", "sys", "backend.execution", "redis", "app")
        worker = canvas.node("worker", "Worker", "sys", "backend.execution", "worker", "app")
        canvas.chain(api, queue, worker, runner)
    else:
        middle = canvas.option_node("backend.execution", "execution", "작업 실행?", "app")
        canvas.chain(api, middle, runner)
    canvas.node(runner, "에이전트 실행", "sys", "agent.topology", icon="agent", group="app")

    if model := canvas.option_node("model.provider", "model", "모델?", "model"):
        canvas.edge(runner, model, "모델 호출")
        if canvas.choice("mlops.model_serving") != "external_api":
            serving = canvas.option_node("mlops.model_serving", "serving", "모델 서빙?", "model")
            if serving:
                canvas.edge(model, serving)
    if canvas.choice("mlops.model_serving") == "external_api":
        canvas.note("mlops.model_serving", "model")

    _data(canvas, runner)

    orchestration = canvas.option_node("devops.orchestration", "orchestration", "실행 환경?", "ops")
    cloud = canvas.option_node("cloud.target", "cloud", "배포 위치?", "ops")
    if orchestration:
        canvas.edge(api, orchestration, "실행 환경", dashed=True)
    if orchestration and cloud:
        canvas.edge(orchestration, cloud, "배포", dashed=True)

    if canvas.choice("ops.tracing") == "none":
        canvas.note("ops.tracing", "ops")
    elif tracing := canvas.option_node("ops.tracing", "tracing", "실행 추적?", "ops"):
        canvas.edge(runner, tracing, "실행 추적", dashed=True)


def _agent_step(canvas: _Canvas, line: str) -> BlueprintStep:
    topology = ("agent.topology",) if canvas.choice("agent.topology") else ()
    return BlueprintStep(
        line=line,
        fixed=[
            *(canvas.settled("agent.topology") if topology else []),
            *canvas.setting("model.provider", "모델"),
        ],
        unknown=UNKNOWN_AGENT_STEP,
        decisions=canvas.decided(*topology, "model.provider"),
    )


def _review_step(canvas: _Canvas, hitl: str) -> BlueprintStep:
    option = canvas.registry.card("agent.hitl").option(hitl)
    return BlueprintStep(
        line=option.summary,
        fixed=[
            *canvas.settled("agent.hitl"),
            *canvas.setting("data.checkpointer", "기다리는 동안 상태 저장"),
        ],
        unknown=(
            ["무엇을 승인하는지", "거절하면 어디로 돌아가는지"]
            if hitl == "approval"
            else ["언제 묻는지", "답이 없으면 어떻게 하는지"]
        ),
        decisions=canvas.decided("agent.hitl", "data.checkpointer"),
    )


def _agent_draft(canvas: _Canvas) -> None:
    start = canvas.node(
        "input",
        "입력 처리",
        "code",
        step=BlueprintStep(
            line="요청을 받아 다음 단계로 넘겨요",
            fixed=[CODE_STEP],
            unknown=["어떤 입력을 받는지", "입력을 어떻게 검사하는지"],
        ),
    )
    topology = canvas.choice("agent.topology")
    if not canvas.in_play("agent.topology"):
        step = _agent_step(canvas, "에이전트가 작업을 처리해요")
        core = canvas.node("core", "에이전트", "agent", step=step)
    elif topology is None:
        core = canvas.node("blank-agent.topology", "에이전트 구조?", "blank", "agent.topology")
    else:
        step = _agent_step(canvas, canvas.registry.card("agent.topology").option(topology).summary)
        if topology in ("supervisor", "hierarchical"):
            core = canvas.node("core", "Supervisor", "agent", "agent.topology", step=step)
            worker_step = _agent_step(canvas, "관리자가 맡긴 작업을 처리해요")
            worker = canvas.node(
                "worker", "담당 에이전트", "agent", "agent.topology", step=worker_step
            )
            canvas.edge(core, worker, "라우팅")
        else:
            label = "처리 단계" if topology == "pipeline" else "에이전트"
            core = canvas.node("core", label, "agent", "agent.topology", step=step)

    review = None
    if canvas.in_play("agent.hitl"):
        hitl = canvas.choice("agent.hitl")
        if hitl is None:
            review = canvas.node("blank-agent.hitl", "사람 확인?", "blank", "agent.hitl")
        elif hitl != "none":
            label = "사람 승인" if hitl == "approval" else "사용자 질문"
            review = canvas.node(
                "review", label, "human", "agent.hitl", step=_review_step(canvas, hitl)
            )
    result = canvas.node(
        "result",
        "결과 전달",
        "code",
        step=BlueprintStep(
            line="결과를 사용자에게 보내요",
            fixed=[CODE_STEP, *canvas.setting("product.surface", "결과를 보여 줄 곳")],
            unknown=["결과 형식"],
            decisions=canvas.decided("product.surface"),
        ),
    )
    canvas.chain(start, core, review, result)


def _how(canvas: _Canvas, node: DesignNode) -> str:
    if node.kind == "agent":
        fallback = f" 대체 모델: {node.model.fallback_scope}." if node.model.fallback_scope else ""
        model = node.model
        return f"모델 호출 단계예요. 모델: {model.provider_scope}. 필요한 능력: {model.capability}.{fallback}"
    if node.kind == "human":
        stored = canvas.setting("data.checkpointer", "기다리는 동안 상태 저장")
        return " ".join(["실행을 멈추고 사람의 입력을 기다려요.", *stored])
    return CODE_STEP


def _design_step(canvas: _Canvas, design: ServiceDesign, node: DesignNode) -> BlueprintStep:
    requirements = [r for r in design.requirements if node.id in r.node_ids]
    requirement_ids = {r.id for r in requirements}
    task_ids = {task for r in requirements for task in r.task_ids}
    reasoned = [
        card_id
        for reason in design.reasons
        if requirement_ids & set(reason.requirement_ids)
        for card_id in reason.card_ids
    ]
    return BlueprintStep(
        line=node.responsibility,
        inputs=[f"{port.name}: {port.type}" for port in node.inputs],
        outputs=[f"{port.name}: {port.type}" for port in node.outputs],
        how=_how(canvas, node),
        tools=[
            StepTool(name=tool.name, access=tool.access, reason=tool.reason) for tool in node.tools
        ],
        done_when=node.done_when,
        on_failure=node.on_failure,
        checks=[
            f"{case.given}: {case.expect}"
            for case in design.eval_cases
            if case.id in node.eval_case_ids
        ],
        first_task=next((task.title for task in design.tasks if task.id in task_ids), None),
        decisions=canvas.decided(*DECISIONS_BY_KIND.get(node.kind, ()), *reasoned),
    )


def _edge_label(design: ServiceDesign, edge: DesignEdge, order: dict[str, int]) -> str | None:
    limit = next(
        (
            loop
            for loop in design.workflow.loop_limits
            if edge.source in loop.node_ids and edge.target in loop.node_ids
        ),
        None,
    )
    if limit is None or order[edge.target] > order[edge.source]:
        return edge.condition
    return " ".join(filter(None, [edge.condition, f"(최대 {limit.max_iterations}회)"]))


def _agent_from_design(canvas: _Canvas, design: ServiceDesign) -> None:
    order = {node.id: index for index, node in enumerate(design.nodes)}
    for node in design.nodes:
        canvas.node(node.id, node.id, node.kind, step=_design_step(canvas, design, node))
    for edge in design.workflow.edges:
        canvas.edge(edge.source, edge.target, _edge_label(design, edge, order), edge.on_failure)


def _build(
    registry: Registry,
    choices: dict[str, str],
    skipped: set[str],
    design: ServiceDesign | None,
) -> Blueprint:
    agent = _Canvas(registry, choices, skipped)
    if design is None:
        _agent_draft(agent)
    else:
        _agent_from_design(agent, design)
    system = _Canvas(registry, choices, skipped)
    _system(system)
    return Blueprint(
        agent=agent.graph, system=system.graph, notes=system.notes, agent_is_draft=design is None
    )


def build_blueprint(state: JourneyState, registry: Registry) -> Blueprint:
    choices = {card_id: d.option_id for card_id, d in state.all_decisions.items()}
    return _build(registry, choices, state.skipped, state.design.current)


EXAMPLES = (
    (
        "basic",
        "웹 + 파이프라인",
        "작은 팀의 기본형이에요. 사람 확인을 거치고 PostgreSQL에 저장해요.",
        {
            "product.surface": "web",
            "agent.topology": "pipeline",
            "agent.hitl": "approval",
            "model.provider": "gemini",
            "mlops.model_serving": "external_api",
            "data.primary_db": "postgres",
            "data.checkpointer": "postgres",
            "data.vector_store": "none",
            "backend.execution": "sync",
            "devops.orchestration": "none",
            "cloud.target": "local",
            "ops.tracing": "langsmith",
        },
    ),
    (
        "private",
        "데이터를 밖으로 못 보낼 때",
        "모델을 내부에서 돌리고 실행 기록도 직접 남겨요.",
        {
            "product.surface": "report",
            "agent.topology": "single",
            "agent.hitl": "none",
            "model.provider": "ollama",
            "mlops.model_serving": "ollama",
            "data.primary_db": "sqlite",
            "data.checkpointer": "memory",
            "data.vector_store": "chroma",
            "backend.execution": "background",
            "devops.orchestration": "none",
            "cloud.target": "local",
            "ops.tracing": "logs",
        },
    ),
    (
        "team",
        "봇 + Supervisor + Queue",
        "소수 사용자에게 공개하는 구성이에요. 만들 것이 가장 많아요.",
        {
            "product.surface": "messenger",
            "agent.topology": "supervisor",
            "agent.hitl": "approval",
            "model.provider": "gemini",
            "mlops.model_serving": "external_api",
            "data.primary_db": "postgres",
            "data.checkpointer": "postgres",
            "data.vector_store": "pgvector",
            "backend.execution": "queue",
            "devops.orchestration": "single_vm_k3s",
            "cloud.target": "gcp",
            "ops.tracing": "langsmith",
        },
    ),
)


def blueprint_examples(registry: Registry) -> list[BlueprintExample]:
    return [
        BlueprintExample(
            id=example_id, name=name, note=note, blueprint=_build(registry, choices, set(), None)
        )
        for example_id, name, note, choices in EXAMPLES
    ]
