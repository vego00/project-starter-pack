"""Turns a finished journey's decisions into the limits a service design must respect.

Pure and deterministic: no model decides what a card means. `target` limits the service the user
will build. The starter's own design review never depends on those choices (see `starter`).
"""

from pydantic import BaseModel, ConfigDict

from app.journey.design import DecisionRef, Unknown
from app.journey.state import Decision, JourneyState
from app.registry.loader import Registry
from app.registry.schema import DecisionCard

# option_id -> (fewest agent nodes, most agent nodes or None, routing)
# Code and human nodes are not counted. Past the minimum, each added role needs a reason.
TOPOLOGY = {
    "pipeline": (2, None, "fixed"),
    "supervisor": (2, None, "model"),
    "hierarchical": (2, None, "model_with_subgraphs"),
}
HUMAN_CHECKS = {"none": [], "question": ["question"], "approval": ["approval"]}
# True / False say whether a run can resume after a restart. None means the user must check.
RESUMABLE = {"memory": False, "postgres": True, "other": None}
EXTERNAL_PROVIDERS = {"gemini", "openai", "upstage", "openrouter"}

CONSTRAINING_CARDS = {
    "agent.topology",
    "agent.hitl",
    "model.provider",
    "data.primary_db",
    "data.vector_store",
    "data.checkpointer",
    "backend.execution",
}
# Left undecided, these change core function, permissions or feasibility.
BLOCKING_CARDS = {"agent.topology", "agent.hitl", "model.provider"}
OUT_OF_SCOPE_CARDS = {
    "devops.orchestration": "컨테이너 운영 방식은 배포 설계에서 다룬다",
    "mlops.model_serving": "모델을 실행할 장소는 배포 설계에서 다룬다",
    "cloud.target": "배포 위치는 배포 설계에서 다룬다",
}


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetServiceConstraints(_Record):
    """Limits on the generated design. None means the deciding card has no usable answer."""

    min_agent_nodes: int | None = None
    max_agent_nodes: int | None = None
    routing: str | None = None
    human_checks: list[str] | None = None
    allowed_providers: list[str] | None = None
    resumable: bool | None = None
    execution: str | None = None
    # "none" means the design must not add that store or the tools that read and write it.
    primary_db: str | None = None
    vector_store: str | None = None


class StarterGuarantees(_Record):
    """Holds for every design, including one whose target service has no human check."""

    user_review_required: bool = True
    review_survives_restart: bool = True


class OutOfScopeCard(_Record):
    card_id: str
    reason: str


class DesignConstraints(_Record):
    decisions: list[DecisionRef]
    target: TargetServiceConstraints
    starter: StarterGuarantees = StarterGuarantees()
    unknowns: list[Unknown]
    warnings: list[str]
    out_of_scope: list[OutOfScopeCard]


def _snapshot(card: DecisionCard, decision: Decision | None, skipped: bool) -> DecisionRef:
    if decision is None:
        by = "skipped" if skipped else "deferred"
        return DecisionRef(card_id=card.card_id, card_version=card.version, by=by)
    return DecisionRef(
        card_id=decision.card_id,
        card_version=decision.card_version,
        option_id=decision.option_id,
        by=decision.by,
    )


def _spec_conflicts(state: JourneyState, chosen: dict[str, str]) -> tuple[list[Unknown], list[str]]:
    """Only combinations the user's own answers make plainly contradictory."""
    spec = state.project_spec
    unknowns: list[Unknown] = []
    warnings: list[str] = []
    cloud = chosen.get("cloud.target")
    if spec.deployment_target == "public_service" and cloud == "local":
        unknowns.append(
            Unknown(
                text="공개 서비스가 목표인데 배포 위치가 로컬이에요. 둘 중 하나를 바꿔야 해요.",
                blocks_confirmation=True,
            )
        )
    elif spec.deployment_target == "small_group" and cloud == "local":
        warnings.append("소수 사용자가 쓸 계획인데 배포 위치가 로컬이에요. 접속 방법을 확인하세요.")
    if spec.has_gpu is False and (
        chosen.get("model.provider") == "ollama"
        or chosen.get("mlops.model_serving") in {"ollama", "vllm"}
    ):
        warnings.append("GPU가 없다고 답했는데 모델을 직접 실행하는 선택이에요. 장비를 확인하세요.")
    if chosen.get("data.checkpointer") == "memory" and spec.deployment_target in {
        "small_group",
        "public_service",
    }:
        warnings.append("여러 사람이 쓸 계획인데 실행 상태가 메모리에만 남아요.")
    if chosen.get("model.provider") in EXTERNAL_PROVIDERS and any(
        "개인정보" in trait for trait in spec.data_traits or []
    ):
        warnings.append("개인정보를 다루는데 입력이 외부 모델로 전송돼요. 허용 범위를 확인하세요.")
    return unknowns, warnings


def derive_design_constraints(state: JourneyState, registry: Registry) -> DesignConstraints:
    decisions = state.all_decisions
    refs: list[DecisionRef] = []
    usable: dict[str, str] = {}
    unknowns: list[Unknown] = []
    warnings = [issue.message for issue in state.review_issues if issue.severity == "warning"]

    skipped = state.skipped
    for card in registry.cards:
        decision = decisions.get(card.card_id)
        refs.append(_snapshot(card, decision, card.card_id in skipped))
        blocks = card.card_id in BLOCKING_CARDS
        constrains = card.card_id in CONSTRAINING_CARDS
        if decision is None:
            # A skipped card was judged not needed: it is recorded, not left as an open question.
            if constrains and card.card_id not in skipped:
                text = f"아직 정하지 않은 결정: {card.title}"
                unknowns.append(Unknown(text=text, blocks_confirmation=blocks))
            continue
        if card.option(decision.option_id) is None:
            # The card changed after this decision, so its meaning can no longer be read.
            if constrains:
                text = f"다시 골라야 하는 결정: {card.title} (선택지가 바뀌었어요)"
                unknowns.append(Unknown(text=text, blocks_confirmation=blocks))
            continue
        usable[card.card_id] = decision.option_id
        if decision.card_version != card.version:
            warnings.append(f"{card.title} 카드가 결정 이후 바뀌었어요. 내용을 다시 확인하세요.")

    for card_id in decisions.keys() - set(registry.card_ids):
        warnings.append(f"지금은 없는 카드의 결정이에요: {card_id}")

    agents = TOPOLOGY.get(usable.get("agent.topology", ""), (None, None, None))
    provider = usable.get("model.provider")
    target = TargetServiceConstraints(
        min_agent_nodes=agents[0],
        max_agent_nodes=agents[1],
        routing=agents[2],
        human_checks=HUMAN_CHECKS.get(usable.get("agent.hitl", "")),
        allowed_providers=None if provider is None else [provider],
        resumable=RESUMABLE.get(usable.get("data.checkpointer", "")),
        execution=usable.get("backend.execution"),
        primary_db=usable.get("data.primary_db"),
        vector_store=usable.get("data.vector_store"),
    )
    if usable.get("data.checkpointer") == "other":
        warnings.append("직접 지정한 저장소가 중단 후 재개를 지원하는지 확인하세요.")

    spec_unknowns, spec_warnings = _spec_conflicts(state, usable)
    return DesignConstraints(
        decisions=refs,
        target=target,
        unknowns=[*unknowns, *spec_unknowns],
        warnings=[*warnings, *spec_warnings],
        out_of_scope=[
            OutOfScopeCard(card_id=card_id, reason=reason)
            for card_id, reason in OUT_OF_SCOPE_CARDS.items()
        ],
    )
