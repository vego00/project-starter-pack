"""The graphs the workspace draws: rebuilt from decisions and the design, never stored.

Deterministic, so the picture cannot drift from what was decided. An undecided card is a blank node;
a skipped card or a card this registry does not hold leaves nothing to draw.
"""

from typing import Literal

from pydantic import BaseModel

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


class BlueprintNode(BaseModel):
    id: str
    label: str
    kind: NodeKind
    card_id: str | None = None
    icon: str | None = None
    group: Group | None = None


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

    def node(
        self,
        node_id: str,
        label: str,
        kind: NodeKind,
        card_id: str | None = None,
        icon: str | None = None,
        group: Group | None = None,
    ) -> str:
        self.graph.nodes.append(
            BlueprintNode(
                id=node_id, label=label, kind=kind, card_id=card_id, icon=icon, group=group
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


def _system(canvas: _Canvas) -> None:
    users = canvas.node("users", "사용자", "sys", icon="person", group="people")
    surface = canvas.option_node("product.surface", "surface", "사용 위치?", "client")
    surface = surface or canvas.node(
        "surface", "사용자 화면", "sys", icon="browser", group="client"
    )
    api = canvas.node("api", "백엔드 API", "sys", icon="server", group="app")
    runner = canvas.node(
        "runner", "에이전트 실행", "sys", "agent.topology", icon="agent", group="app"
    )
    canvas.edge(users, surface)
    canvas.edge(surface, api, "요청")

    execution = canvas.choice("backend.execution")
    if not canvas.in_play("backend.execution") or execution == "sync":
        canvas.edge(api, runner, "실행")
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

    if model := canvas.option_node("model.provider", "model", "모델?", "model"):
        canvas.edge(runner, model, "모델 호출")
        if canvas.choice("mlops.model_serving") != "external_api":
            serving = canvas.option_node("mlops.model_serving", "serving", "모델 서빙?", "model")
            if serving:
                canvas.edge(model, serving)

    database = None
    if canvas.choice("data.primary_db") != "none":
        database = canvas.option_node("data.primary_db", "database", "데이터 저장소?", "data")
        if database:
            canvas.edge(runner, database, "저장")

    if canvas.in_play("data.checkpointer") and canvas.choice("data.checkpointer") != "memory":
        postgres_again = (
            canvas.choice("data.checkpointer") == "postgres"
            and canvas.choice("data.primary_db") == "postgres"
        )
        if postgres_again:
            canvas.edge(runner, database, "체크포인트", dashed=True)
        else:
            state = canvas.option_node("data.checkpointer", "checkpoint", "상태 저장?", "data")
            canvas.edge(runner, state, "체크포인트", dashed=True)

    if canvas.choice("data.vector_store") != "none" and canvas.in_play("data.vector_store"):
        if canvas.choice("data.vector_store") == "pgvector" and database:
            canvas.edge(runner, database, "벡터 검색", dashed=True)
        else:
            search = canvas.option_node("data.vector_store", "search", "검색 저장소?", "data")
            canvas.edge(runner, search, "검색")

    orchestration = canvas.option_node("devops.orchestration", "orchestration", "실행 환경?", "ops")
    cloud = canvas.option_node("cloud.target", "cloud", "배포 위치?", "ops")
    if orchestration:
        canvas.edge(api, orchestration, "실행 환경", dashed=True)
    if orchestration and cloud:
        canvas.edge(orchestration, cloud, "배포", dashed=True)

    if canvas.choice("ops.tracing") != "none":
        tracing = canvas.option_node("ops.tracing", "tracing", "실행 추적?", "ops")
        if tracing:
            canvas.edge(runner, tracing, "실행 추적", dashed=True)


def _agent_draft(canvas: _Canvas) -> None:
    start = canvas.node("input", "입력 처리", "code")
    topology = canvas.choice("agent.topology")
    if not canvas.in_play("agent.topology"):
        core = canvas.node("core", "에이전트", "agent")
    elif topology is None:
        core = canvas.node("blank-agent.topology", "에이전트 구조?", "blank", "agent.topology")
    elif topology in ("supervisor", "hierarchical"):
        core = canvas.node("core", "Supervisor", "agent", "agent.topology")
        worker = canvas.node("worker", "담당 에이전트", "agent", "agent.topology")
        canvas.edge(core, worker, "라우팅")
    elif topology == "pipeline":
        core = canvas.node("core", "처리 단계", "agent", "agent.topology")
    else:
        core = canvas.node("core", "에이전트", "agent", "agent.topology")

    review = None
    if canvas.in_play("agent.hitl"):
        hitl = canvas.choice("agent.hitl")
        if hitl is None:
            review = canvas.node("blank-agent.hitl", "사람 확인?", "blank", "agent.hitl")
        elif hitl != "none":
            label = "사람 승인" if hitl == "approval" else "사용자 질문"
            review = canvas.node("review", label, "human", "agent.hitl")
    result = canvas.node("result", "결과 전달", "code")
    canvas.chain(start, core, review, result)


def _agent_from_design(canvas: _Canvas, design: ServiceDesign) -> None:
    for node in design.nodes:
        canvas.node(node.id, node.id, node.kind)
    for edge in design.workflow.edges:
        canvas.edge(edge.source, edge.target, edge.condition, edge.on_failure)


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
    return Blueprint(agent=agent.graph, system=system.graph, agent_is_draft=design is None)


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
