"""Produces a validated service design, or a reference template when the model cannot.

The model writes only the design's content. Code adds where it came from, carries over what the
decisions left open, and decides whether the result can be used.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.journey.design import (
    MAX_ITEMS,
    DesignState,
    DevTask,
    EvalCase,
    Node,
    Provenance,
    Reason,
    Requirement,
    ServiceDesign,
    SimplerAlternative,
    StateField,
    Text,
    Unknown,
    Workflow,
)
from app.journey.design_constraints import DesignConstraints, derive_design_constraints
from app.journey.design_validator import validate_design
from app.journey.llm import StructuredLLM
from app.journey.prompts import DESIGN_SYSTEM, DESIGN_VERSION, design_user
from app.journey.state import JourneyState
from app.registry.loader import Registry

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # One draft and one automatic correction, from the approved plan's starting value.
MAX_OUTAGE_RETRIES = (
    1  # A provider failure says nothing about the draft, so it spares a correction.
)
MAX_REPORTED_PROBLEMS = 10
FAILED_MESSAGE = "맞춤 설계를 만들지 못해 참고 템플릿을 보여드려요. 확정할 수 없는 예시예요."


class DesignDraft(BaseModel):
    """The part of a design the model writes."""

    model_config = ConfigDict(extra="forbid")

    requirements: list[Requirement] = Field(min_length=1, max_length=MAX_ITEMS)
    unknowns: list[Unknown] = Field(default=[], max_length=MAX_ITEMS)
    nodes: list[Node] = Field(min_length=1, max_length=MAX_ITEMS)
    workflow: Workflow
    state_fields: list[StateField] = Field(default=[], max_length=MAX_ITEMS)
    eval_cases: list[EvalCase] = Field(min_length=1, max_length=MAX_ITEMS)
    tasks: list[DevTask] = Field(min_length=1, max_length=MAX_ITEMS)
    reasons: list[Reason] = Field(min_length=1, max_length=MAX_ITEMS)
    simpler_alternatives: list[SimplerAlternative] = Field(default=[], max_length=MAX_ITEMS)
    warnings: list[Text] = Field(default=[], max_length=MAX_ITEMS)


class DesignAttempt(BaseModel):
    draft: DesignDraft
    model_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class Designer(Protocol):
    def draft(
        self, state: JourneyState, constraints: DesignConstraints, problems: list[str]
    ) -> DesignAttempt:
        """Raises when the model fails or its output does not match the contract."""
        ...


class LLMDesigner:
    def __init__(self, llm: StructuredLLM, registry: Registry):
        self._llm = llm
        self._registry = registry

    def draft(
        self, state: JourneyState, constraints: DesignConstraints, problems: list[str]
    ) -> DesignAttempt:
        result = self._llm.generate(
            system=DESIGN_SYSTEM,
            user=design_user(state, constraints, self._registry, problems),
            schema=DesignDraft,
        )
        return DesignAttempt(
            draft=result.output,
            model_id=result.model_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


class DesignOutcome(BaseModel):
    design: DesignState
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def _spec_hash(state: JourneyState) -> str:
    spec = json.dumps(state.project_spec.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(spec.encode("utf-8")).hexdigest()


def _provenance(state: JourneyState, constraints: DesignConstraints, **source) -> Provenance:
    return Provenance(
        journey_revision=len(state.trace),
        project_spec_hash=_spec_hash(state),
        decisions=constraints.decisions,
        generated_at=datetime.now(UTC),
        **source,
    )


def _with_decisions(
    fields: dict, constraints: DesignConstraints, provenance: Provenance
) -> ServiceDesign:
    """Unknowns and warnings from the decisions come from code, so a model cannot lose them."""
    unknowns = list(constraints.unknowns)
    known = {unknown.text for unknown in unknowns}
    unknowns += [u for u in fields.pop("unknowns", []) if u.text not in known]
    warnings = list(dict.fromkeys([*constraints.warnings, *fields.pop("warnings", [])]))
    design = ServiceDesign(
        design_revision=1,
        provenance=provenance,
        unknowns=unknowns,
        warnings=warnings,
        **fields,
    )
    return design.model_copy(update={"validation": validate_design(design, constraints)})


def _port(name: str, kind: str = "str") -> dict:
    return {"name": name, "type": kind}


def _template_node(
    node_id: str, kind: str, role: str, inputs: list, outputs: list, **extra
) -> dict:
    return {
        "id": node_id,
        "kind": kind,
        "responsibility": role,
        "inputs": [_port(name) for name in inputs],
        "outputs": [_port(name) for name in outputs],
        "tools": [],
        "done_when": "출력을 다음 단계로 넘겼다",
        "on_failure": "오류 내용을 남기고 사용자에게 알린다",
        **extra,
    }


def template_design(state: JourneyState, constraints: DesignConstraints) -> ServiceDesign:
    """A generic two-agent shape that respects the decisions. It never replaces a real design."""
    allowed = constraints.target.allowed_providers
    model = {
        "capability": "한국어 입력을 이해하고 구조화된 결과를 쓴다",
        "provider_scope": allowed[0] if allowed else "미정",
    }
    wants_human = bool(constraints.target.human_checks)
    finish_input = "approved" if wants_human else "checked"
    nodes = [
        _template_node("intake", "code", "입력을 검사해 작업 요청으로 정리한다", ["request"], ["task"]),
        _template_node("worker", "agent", "요청을 처리해 초안을 만든다", ["task"], ["draft"], model=model),
        _template_node("reviewer", "agent", "초안을 기준에 맞춰 점검한다", ["draft"], ["checked"], model=model),
    ]  # fmt: skip
    path = ["intake", "worker", "reviewer"]
    if wants_human:
        nodes.append(
            _template_node("approval", "human", "사람이 결과를 확인한다", ["checked"], ["approved"])
        )
        path.append("approval")
    nodes.append(
        _template_node("finish", "code", "결과를 사용자에게 돌려준다", [finish_input], ["result"])
    )
    path.append("finish")
    return _with_decisions(
        {
            "requirements": [
                Requirement(
                    id="R-1",
                    problem=state.project_spec.idea[:2000],
                    success_example="직접 채워야 해요. 이 템플릿은 프로젝트를 분석한 결과가 아니에요.",
                    input="사용자 요청",
                    expected_output="점검을 거친 결과",
                    core=True,
                    node_ids=["worker", "reviewer"],
                    output="draft",
                    eval_case_ids=["E-1"],
                    task_ids=["T-1"],
                )
            ],
            "nodes": nodes,
            "workflow": {
                "entry": "intake",
                "exits": ["finish"],
                "edges": [
                    {"source": source, "target": target}
                    for source, target in zip(path, path[1:], strict=False)
                ],
                "max_model_calls": 2,
            },
            "eval_cases": [
                {"id": "E-1", "given": "대표 입력 한 건", "expect": "기대 결과를 직접 정해야 해요"}
            ],
            "tasks": [
                {
                    "id": "T-1",
                    "title": "입력부터 결과까지 가짜 응답으로 연결하기",
                    "inputs": "대표 입력 한 건",
                    "produces": "끝까지 실행되는 뼈대",
                    "verify_by": "대표 입력을 넣으면 결과가 돌아온다",
                }
            ],
            "reasons": [
                {
                    "text": "처리와 점검을 나눈 일반 예시예요. 프로젝트에 맞게 고쳐야 해요.",
                    "requirement_ids": ["R-1"],
                }
            ],
        },
        constraints,
        _provenance(state, constraints, source="template"),
    )


def _errors(design: ServiceDesign) -> list[str]:
    return [issue.message for issue in design.validation or [] if issue.severity == "error"]


def _contract_problems(exc: ValidationError) -> list[str]:
    """Names what broke the contract so a correction has a target. Excludes the input values."""
    return [
        f"{'.'.join(map(str, error['loc'])) or '전체'}: {error['msg']}"
        for error in exc.errors(include_input=False, include_url=False)[:MAX_REPORTED_PROBLEMS]
    ]


def _failed(state: JourneyState, constraints: DesignConstraints, **usage) -> DesignOutcome:
    return DesignOutcome(
        design=DesignState(
            status="failed", current=template_design(state, constraints), error=FAILED_MESSAGE
        ),
        **usage,
    )


def generate_design(
    state: JourneyState,
    registry: Registry,
    designer: Designer | None,
    *,
    attempts: int = MAX_ATTEMPTS,
    outage_retries: int = MAX_OUTAGE_RETRIES,
) -> DesignOutcome:
    """Each run after a changed decision is a new revision, so an old design never passes as new."""
    outcome = _generate(state, registry, designer, attempts, outage_retries)
    previous = state.design.current
    if previous is None:
        return outcome
    current = outcome.design.current.model_copy(
        update={"design_revision": previous.design_revision + 1}
    )
    return outcome.model_copy(
        update={"design": outcome.design.model_copy(update={"current": current})}
    )


def _generate(
    state: JourneyState,
    registry: Registry,
    designer: Designer | None,
    attempts: int,
    outage_retries: int,
) -> DesignOutcome:
    constraints = derive_design_constraints(state, registry)
    if designer is None or attempts < 1:
        return _failed(state, constraints)

    problems: list[str] = []
    usage: dict = {}
    while attempts > 0:
        try:
            attempt = designer.draft(state, constraints, problems)
            usage = {
                "model_id": attempt.model_id,
                "prompt_version": DESIGN_VERSION,
                "input_tokens": (usage.get("input_tokens") or 0) + (attempt.input_tokens or 0),
                "output_tokens": (usage.get("output_tokens") or 0) + (attempt.output_tokens or 0),
            }
            fields = {name: getattr(attempt.draft, name) for name in DesignDraft.model_fields}
            design = _with_decisions(
                fields,
                constraints,
                _provenance(
                    state,
                    constraints,
                    source="model",
                    model_id=attempt.model_id,
                    prompt_version=DESIGN_VERSION,
                ),
            )
        except ValidationError as exc:
            attempts -= 1
            problems = _contract_problems(exc)
            logger.warning(
                "Design draft broke the contract fields=%s",
                [
                    ".".join(map(str, error["loc"])) + ":" + error["type"]
                    for error in exc.errors(include_input=False, include_url=False)
                ],
            )
            continue
        except Exception as exc:  # noqa: BLE001 - model boundary; the prompt holds user text
            if outage_retries > 0:
                outage_retries -= 1
            else:
                attempts -= 1
            logger.error(
                "Design call failed type=%s status=%s",
                type(exc).__name__,
                getattr(exc, "code", None),
            )
            continue
        attempts -= 1
        problems = _errors(design)
        if not problems:
            return DesignOutcome(
                design=DesignState(status="review_required", current=design), **usage
            )
        rules = sorted({i.rule_id for i in design.validation or [] if i.severity == "error"})
        logger.warning("Design failed validation errors=%d rules=%s", len(problems), rules)
    return _failed(state, constraints, **usage)
