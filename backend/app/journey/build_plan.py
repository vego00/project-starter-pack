"""Plans a build from one design revision: every value the bundle needs and where it came from.

ADR-026 step 1. `plan_build` is the only place that reads the card choices and the design for a
bundle; `package.build_package` writes files from the `BuildSpec` alone, so two files cannot take
the same value from different places. Pure and deterministic. The spec is worked out each time a
bundle is made rather than kept in the journey state, because a design edited on the graph is
saved outside the journey's nodes and a stored copy could fall behind its revision.
"""

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.journey.build_checks import SEARCH_WORDS, BuildIssue, build_issues
from app.journey.design import ServiceDesign
from app.journey.modules import ModuleNote, ModulePlan, build_module_plan
from app.journey.n8n import N8N_IMAGE, WORKFLOW_PATH
from app.journey.state import BuildAnswer, ProjectSpec
from app.registry.build_decisions import BuildDecisions, BuildItem, default_build_decisions
from app.registry.loader import Registry
from app.registry.modules import default_module_rules
from app.registry.provider_models import ProviderModelTable, default_provider_models

EXTERNAL_KEY_PROVIDERS = {"gemini", "openai", "upstage", "exaone", "openrouter"}
SOURCE_NOTICE = {
    "template": (
        "> 참고 템플릿이에요. 이 프로젝트를 분석한 결과가 아니니 그대로 구현하지 말고 먼저 고치세요."
    ),
    "mock": "> 시험용 설계예요. 이 프로젝트를 분석한 결과가 아니에요.",
}


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CardRow(_Spec):
    title: str
    option: str | None = None
    summary: str = ""
    cons: tuple[str, ...] = ()
    state: Literal["chosen", "skipped", "open"]


class Decided(_Spec):
    id: str
    title: str
    source: Literal["card", "default", "design"]
    value: str = ""


class OpenDecision(_Spec):
    id: str
    title: str
    source: Literal["ask", "design"]
    question: str
    recommendation: str | None = None
    options: tuple[str, ...] = ()
    # held: the user left it for the builder. recheck: answered, but what the item shows changed.
    status: Literal["open", "held", "recheck"] = "open"
    previous: str | None = None
    reason: str | None = None
    # What the item shows now; stored with an answer to tell later whether it changed.
    inputs: dict[str, str | None] = {}


class Answered(_Spec):
    """A build preparation answer that still fits what the item shows."""

    id: str
    title: str
    question: str
    value: str
    by: Literal["user", "recommended"]
    at: datetime
    recommendation: str | None = None
    options: tuple[str, ...] = ()
    inputs: dict[str, str | None] = {}


class BuildSpec(_Spec):
    design: ServiceDesign
    idea: str
    notice: str | None
    implementation: str
    provider: str | None
    modules: tuple[ModulePlan, ...]
    cards: tuple[CardRow, ...]
    deploy_cards: tuple[CardRow, ...]
    stack: tuple[str, ...]
    containers: tuple[str, ...]
    human_tasks: tuple[str, ...]
    deploy_tasks: tuple[str, ...]
    rules: tuple[str, ...]
    verify_rules: tuple[str, ...]
    antislop: bool
    decided: tuple[Decided, ...]
    open: tuple[OpenDecision, ...]
    answered: tuple[Answered, ...] = ()
    issues: tuple[BuildIssue, ...] = ()


def _stack(chosen: Mapping[str, str | None]) -> list[str]:
    """The languages and frameworks, fixed by the bundle so the builder does not pick them. Two
    build trials (2026-11-05, 2026-11-23) found none named; the first builder chose these."""
    if chosen.get("backend.implementation") == "n8n":
        return [
            f"흐름: n8n {N8N_IMAGE.rsplit(':', 1)[1]}. `{WORKFLOW_PATH}`를 가져와 설계의 노드를 "
            "같은 이름의 n8n 노드로 채운다.",
            "노드 안의 코드: Code 노드의 JavaScript. 외부 API는 HTTP Request나 해당 서비스 노드로 부른다.",
            "실행 상태: n8n이 실행 기록을 자체 저장소에 남긴다. 실행 상태 저장 카드는 적용하지 않는다.",
        ]
    found = [
        "언어: Python 3.12. 의존성은 uv로 잠가 고정한다.",
        "API 서버: FastAPI.",
        "에이전트 흐름: LangGraph. `docs/multi-agent-design.md`의 노드, 흐름, 상태 필드를 "
        "그래프의 노드, 간선, 상태로 그대로 옮긴다.",
        "상태와 입출력 타입: Pydantic 모델.",
    ]
    if chosen.get("product.surface") == "web":
        found.append("웹 화면: React, Vite, TypeScript.")
    if chosen.get("product.surface") == "messenger":
        found.append("메신저 연결: 메신저가 제공하는 공식 봇 SDK나 웹훅으로 API 서버에 붙인다.")
    return found


def _containers(chosen: Mapping[str, str | None]) -> list[str]:
    """The containers the card choices call for, so a build needs only Docker on the computer."""
    found = ["앱: 서비스 코드와 언어 런타임. 이 컴퓨터에 설치하지 않고 이미지 안에서 실행한다."]
    if chosen.get("backend.implementation") == "n8n":
        found = [f"n8n: `{N8N_IMAGE}`. 포트는 127.0.0.1:5678에만 열고, workflow와 자격 증명은 "
                 "`/home/node/.n8n` 볼륨에 둔다."]  # fmt: skip
    if "postgres" in (chosen.get("data.primary_db"), chosen.get("data.checkpointer")) or (
        chosen.get("data.vector_store") == "pgvector"
    ):
        extension = " pgvector 확장이 든 이미지를 쓴다." if chosen.get(
            "data.vector_store") == "pgvector" else ""  # fmt: skip
        kept = [name for name, on in (
            ("데이터", chosen.get("data.primary_db") == "postgres"),
            ("검색 색인", chosen.get("data.vector_store") == "pgvector"),
            ("실행 상태", chosen.get("data.checkpointer") == "postgres")) if on]  # fmt: skip
        found.append(f"PostgreSQL: {', '.join(kept)}를 볼륨에 저장한다.{extension}")
    if chosen.get("data.primary_db") == "sqlite":
        found.append("SQLite: 별도 컨테이너 없이 앱 컨테이너의 볼륨에 파일로 둔다.")
    if chosen.get("data.vector_store") == "qdrant":
        found.append("Qdrant: 검색 색인을 볼륨에 저장한다.")
    if chosen.get("data.vector_store") == "chroma":
        found.append("Chroma: 검색 색인을 볼륨에 저장한다.")
    # n8n runs its own executions, so the execution card adds no queue (ADR-026, n8n.own_executions).
    if chosen.get("backend.execution") == "queue" and chosen.get("backend.implementation") != "n8n":
        found.append(
            "작업 큐와 워커: 큐 브로커 컨테이너와, 앱 이미지로 띄우는 워커 컨테이너를 둔다."
        )
    if "ollama" in (chosen.get("model.provider"), chosen.get("mlops.model_serving")):
        found.append("Ollama: 모델 파일은 볼륨에 두고, 받기 전에 용량을 사용자에게 확인한다.")
    if chosen.get("mlops.model_serving") == "vllm":
        found.append("vLLM: GPU가 필요하다. 장비를 먼저 확인한다.")
    return found


def _human_tasks(chosen: Mapping[str, str | None]) -> tuple[list[str], list[str]]:
    """What only a person can do: for the first, local build, and for deploying later."""
    now = [
        "Docker와 Docker Compose를 설치하고 실행 중인지 확인한다. 다른 도구는 컨테이너 안에 둔다."
    ]
    if chosen.get("model.provider") in EXTERNAL_KEY_PROVIDERS:
        now.append(
            "모델 제공자의 API 키를 발급받아 커밋하지 않는 `.env`에 넣는다. 키를 대화에 붙여넣지 않는다."
        )
    if chosen.get("model.provider") == "ollama" or chosen.get("mlops.model_serving") == "ollama":
        now.append("모델 파일을 직접 내려받는다. 용량과 장비 요구 사항을 먼저 확인한다.")
    later = []
    if chosen.get("cloud.target") not in {None, "local"}:
        later.append("클라우드 계정을 만들고 비용 상한과 알림을 먼저 설정한다.")
    return now, later


def _model_advice(
    item: BuildItem, chosen: Mapping[str, str | None], models: ProviderModelTable
) -> str | None:
    """A recommendation from the provider model table, or the item's own words without one."""
    provider = chosen.get("model.provider")
    if item.compute == "embedding" and chosen.get("mlops.model_serving") == "ollama":
        provider = "ollama"
    entry = models.providers.get(provider or "")
    if entry is None:
        return item.recommendation
    checked = f"(확인 {entry.checked_at.isoformat()}, {entry.source}). 사용자가 확정한다"
    note = f" {entry.note}" if entry.note else ""
    if item.compute == "embedding":
        note = f" {entry.embedding_note}" if entry.embedding_note else ""
    if item.compute == "model_ids" and entry.chat:
        light = f", 가벼운 일은 `{entry.light}`" if entry.light else ""
        return f"추천: 주 모델 `{entry.chat}`{light} {checked}.{note}"
    if item.compute == "embedding" and entry.embedding:
        size = f", {entry.embedding_dimensions}차원" if entry.embedding_dimensions else ""
        return f"추천: `{entry.embedding}`{size} {checked}.{note}"
    return item.recommendation


def _applies(item: BuildItem, chosen: Mapping[str, str | None], design: ServiceDesign) -> bool:
    if not all(condition.matches(chosen.get(condition.card)) for condition in item.when):
        return False
    if item.when_any and not any(c.matches(chosen.get(c.card)) for c in item.when_any):
        return False
    if item.design_has == "agent" and not any(node.kind == "agent" for node in design.nodes):
        return False
    if item.design_has == "search" and not (
        chosen.get("data.vector_store") not in (None, "none")
        or any(
            word in f"{tool.name} {tool.reason}".lower()
            for node in design.nodes
            for tool in node.tools
            for word in SEARCH_WORDS
        )
    ):
        return False
    return True


def _card_row(registry: Registry, card_id: str, option_id: str | None, skipped: bool) -> CardRow:
    card = registry.card(card_id)
    option = card.option(option_id) if option_id else None
    if option is None:
        return CardRow(title=card.title, state="skipped" if skipped else "open")
    return CardRow(
        title=card.title,
        option=option.name,
        summary=option.summary,
        cons=option.cons,
        state="chosen",
    )


def _digest(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _key(prefix: str, text: str) -> str:
    """Named by its words, so the same question in a new design keeps its answer."""
    return f"{prefix}-{_digest(text)[:8]}"


def _with_inputs(item: OpenDecision, cards: Mapping[str, str | None]) -> OpenDecision:
    inputs = {"question": _digest(item.question), "recommendation": _digest(item.recommendation)}
    return item.model_copy(update={"inputs": {**inputs, **cards}})


def _recheck_reason(registry: Registry, before: dict[str, str | None], now: dict[str, str | None]):
    changed = [
        k for k in now if k not in ("question", "recommendation") and before.get(k) != now[k]
    ]
    if changed:
        titles = ", ".join(registry.card(k).title for k in changed if k in registry.card_ids)
        return f"{titles} 결정이 바뀌었어요" if titles else "결정이 바뀌었어요"
    return "설계나 추천이 바뀌었어요"


def _sort_answers(
    items: list[OpenDecision],
    answers: Mapping[str, BuildAnswer],
    registry: Registry,
) -> tuple[list[OpenDecision], list[Answered]]:
    """An answer whose item shows the same thing stays decided; otherwise it is asked again.
    Answers to items that no longer apply are kept in the journey and just not shown."""
    still_open: list[OpenDecision] = []
    answered: list[Answered] = []
    for item in items:
        answer = answers.get(item.id)
        if answer is None:
            still_open.append(item)
        elif answer.inputs != item.inputs:
            still_open.append(item.model_copy(update={
                "status": "recheck", "previous": answer.value or None,
                "reason": _recheck_reason(registry, answer.inputs, item.inputs)}))  # fmt: skip
        elif answer.by == "held":
            still_open.append(item.model_copy(update={"status": "held"}))
        else:
            answered.append(Answered(
                id=item.id, title=item.title, question=item.question, value=answer.value,
                by=answer.by, at=answer.at, recommendation=item.recommendation,
                options=item.options, inputs=item.inputs))  # fmt: skip
    return still_open, answered


def plan_build(
    design: ServiceDesign,
    registry: Registry,
    idea: str,
    notes: Mapping[str, ModuleNote] | None = None,
    decisions: BuildDecisions | None = None,
    project: ProjectSpec | None = None,
    models: ProviderModelTable | None = None,
    answers: Mapping[str, BuildAnswer] | None = None,
) -> BuildSpec:
    items = (decisions or default_build_decisions()).items
    models = models or default_provider_models()
    chosen: dict[str, str | None] = {
        ref.card_id: ref.option_id for ref in design.provenance.decisions
    }
    skipped = {ref.card_id for ref in design.provenance.decisions if ref.by == "skipped"}
    decided: list[Decided] = []
    for item in items:
        if item.card and chosen.get(item.card) is None and item.fallback:
            chosen[item.card] = item.fallback
            decided.append(Decided(id=item.id, title=item.title, source="default",
                                   value=item.fallback))  # fmt: skip

    modules = build_module_plan(
        registry,
        default_module_rules(),
        {card: option for card, option in chosen.items() if option},
        notes,
    )
    human_now, human_later = _human_tasks(chosen)
    cards: list[CardRow] = []
    deploy_cards: list[CardRow] = []
    rules: list[str] = []
    verify: list[str] = []
    containers: list[str] = []
    stack: list[str] = []
    antislop = False
    open_items: list[OpenDecision] = []

    for item in items:
        if item.card is not None:
            if item.card not in registry.card_ids:
                continue
            row = _card_row(registry, item.card, chosen.get(item.card), item.card in skipped)
            if item.infrastructure:
                cards.append(row)
            if item.deploy and chosen.get(item.card) not in (None, "local", "none"):
                deploy_cards.append(row)
            if not any(d.id == item.id for d in decided) and chosen.get(item.card):
                decided.append(Decided(id=item.id, title=item.title, source="card",
                                       value=row.option or ""))  # fmt: skip
            continue
        if not _applies(item, chosen, design):
            continue
        rules += item.lines.get("rules", ())
        verify += item.lines.get("verify", ())
        containers += item.lines.get("containers", ())
        if item.compute == "stack":
            stack = _stack(chosen)
        elif item.compute == "containers":
            containers = _containers(chosen) + containers
        elif item.compute == "antislop":
            antislop = True
        elif item.compute == "unknowns":
            open_items += [
                _with_inputs(
                    OpenDecision(
                        id=_key("unknown", u.text),
                        title=item.title,
                        source="design",
                        question=u.text,
                        recommendation=u.recommendation,
                        options=tuple(u.options),
                    ),
                    {},
                )  # fmt: skip
                for u in design.unknowns
            ]
            continue
        elif item.compute == "open_targets":
            open_items += [
                _with_inputs(
                    OpenDecision(
                        id=f"target-{module.id}-{i}",
                        title=f"정할 목표치 ({module.name})",
                        source="ask",
                        question=f"{c.text}의 목표치를 얼마로 할까요?",
                    ),
                    {},
                )  # fmt: skip
                for module in modules
                for i, c in enumerate(module.criteria, 1)
                if c.needs_target and not c.target
            ]
            continue
        if item.source == "ask":
            advice = (
                _model_advice(item, chosen, models)
                if item.compute in ("model_ids", "embedding")
                else item.recommendation
            )
            cards_read = {c.card: chosen.get(c.card) for c in item.when}
            open_items.append(_with_inputs(OpenDecision(
                id=item.id, title=item.title, source="ask", question=item.question or item.title,
                recommendation=advice, options=item.options), cards_read))  # fmt: skip
        else:
            decided.append(Decided(id=item.id, title=item.title, source=item.source))

    issues = build_issues(design, chosen, project)
    provider = chosen.get("model.provider")
    if provider and (late := models.stale_days(provider, design.provenance.generated_at.date())):
        # Measured against the design's own date, so the same design gives the same bundle.
        issues.append(BuildIssue(
            rule_id="models.stale", severity="warning", route="note",
            message=f"{provider} 기본 모델은 확인한 지 {models.stale_after_days + late}일이 지났어요. "
            "공식 문서에서 지금 모델을 다시 확인한 뒤 정해요.",
        ))  # fmt: skip
    for issue in issues:
        if issue.severity == "error":
            # A design rule still broken here (a design saved before the rule) becomes a question.
            open_items.append(_with_inputs(OpenDecision(
                id=_key(issue.rule_id, issue.message), title="설계와 결정이 맞지 않는 곳",
                source="ask" if issue.route == "ask" else "design", question=issue.message,
                recommendation=issue.recommendation), {}))  # fmt: skip
    open_items, answered = _sort_answers(open_items, answers or {}, registry)
    return BuildSpec(
        design=design,
        idea=idea,
        notice=SOURCE_NOTICE.get(design.provenance.source),
        implementation=chosen.get("backend.implementation") or "code",
        provider=chosen.get("model.provider"),
        modules=tuple(sorted(modules, key=lambda module: module.column)),
        cards=tuple(cards),
        deploy_cards=tuple(deploy_cards),
        stack=tuple(stack),
        containers=tuple(containers),
        human_tasks=tuple(human_now),
        deploy_tasks=tuple(human_later),
        rules=tuple(rules),
        verify_rules=tuple(verify),
        antislop=antislop,
        decided=tuple(decided),
        open=tuple(open_items),
        answered=tuple(answered),
        issues=tuple(issue for issue in issues if issue.severity == "warning"),
    )
