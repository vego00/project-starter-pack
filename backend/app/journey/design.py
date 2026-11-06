"""Service design contract: the structured result a user reviews after the Decision Journey.

Screen, diagram and Markdown are all rendered from this one record. Rules that compare records
across the design (references, graph shape, owners) belong to the validator, not this contract.
Lists rather than maps, so the shape stays usable as a model's structured output schema.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = 1

# Provisional bounds that keep one design a readable size; recalibrate from real designs.
MAX_SHORT = 200
MAX_TEXT = 2000
MAX_ITEMS = 50

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SHORT)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

GenerationSource = Literal["model", "mock", "template"]
DesignStatus = Literal["not_started", "generating", "review_required", "confirmed", "failed"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionRef(_Record):
    """A decision as it stood when the design was generated.

    `deferred` has no option yet. `skipped` has none because the card was judged not needed.
    """

    card_id: Short
    card_version: int = Field(ge=1)
    option_id: Short | None = None
    by: Literal["user", "recommended", "implied", "deferred", "skipped"]

    @model_validator(mode="after")
    def _deferred_has_no_option(self):
        if (self.by in ("deferred", "skipped")) != (self.option_id is None):
            raise ValueError("only a deferred or skipped decision has no option")
        return self


class Provenance(_Record):
    """What the design was made from. The spec is hashed so user text is not stored twice."""

    journey_revision: int = Field(ge=0)
    project_spec_hash: Sha256
    decisions: list[DecisionRef] = Field(max_length=MAX_ITEMS)
    generated_at: datetime
    source: GenerationSource
    model_id: Short | None = None
    prompt_version: Short | None = None

    @model_validator(mode="after")
    def _model_details_match_the_source(self):
        has_model = self.model_id is not None and self.prompt_version is not None
        if self.source == "model" and not has_model:
            raise ValueError("a model-generated design names its model and prompt version")
        if self.source != "model" and (self.model_id or self.prompt_version):
            raise ValueError("only a model-generated design names a model")
        return self


class Requirement(_Record):
    """One line of `요구사항 → 담당 노드 → 산출물 → 평가 사례 → 첫 개발 작업`.

    `evidence` quotes the user's text; without it the requirement is an assumption to confirm.
    """

    id: Id
    problem: Text
    success_example: Text
    input: Text
    expected_output: Text
    evidence: Text | None = None
    core: bool
    node_ids: list[Id] = Field(default=[], max_length=MAX_ITEMS)
    output: Short | None = None
    eval_case_ids: list[Id] = Field(default=[], max_length=MAX_ITEMS)
    task_ids: list[Id] = Field(default=[], max_length=MAX_ITEMS)

    @property
    def is_assumption(self) -> bool:
        return self.evidence is None

    @model_validator(mode="after")
    def _core_requirement_is_traced_end_to_end(self):
        if self.core and not (self.node_ids and self.output and self.eval_case_ids):
            raise ValueError(f"{self.id}: a core requirement needs a node, output and eval case")
        if self.core and not self.task_ids:
            raise ValueError(f"{self.id}: a core requirement needs a development task")
        return self


class Unknown(_Record):
    """`blocks_confirmation` is for what changes core function, permissions or feasibility."""

    text: Text
    blocks_confirmation: bool


class Port(_Record):
    name: Id
    type: Short


class ToolPermission(_Record):
    name: Id
    access: Literal["read", "write"]
    reason: Text


class ModelNeed(_Record):
    capability: Text
    provider_scope: Short
    fallback_scope: Short | None = None


class _Node(_Record):
    id: Id
    responsibility: Text
    inputs: list[Port] = Field(max_length=MAX_ITEMS)
    outputs: list[Port] = Field(max_length=MAX_ITEMS)
    # Required with no default: an empty list states "no tools" rather than leaving it unsaid.
    tools: list[ToolPermission] = Field(max_length=MAX_ITEMS)
    done_when: Text
    on_failure: Text
    eval_case_ids: list[Id] = Field(default=[], max_length=MAX_ITEMS)


class CodeNode(_Node):
    kind: Literal["code"]


class HumanNode(_Node):
    kind: Literal["human"]


class AgentNode(_Node):
    kind: Literal["agent"]
    model: ModelNeed


Node = Annotated[CodeNode | HumanNode | AgentNode, Field(discriminator="kind")]


class Edge(_Record):
    source: Id
    target: Id
    condition: Short | None = None
    on_failure: bool = False


class LoopLimit(_Record):
    node_ids: list[Id] = Field(min_length=1, max_length=MAX_ITEMS)
    max_iterations: int = Field(ge=1)
    on_exceeded: Id


class Workflow(_Record):
    entry: Id
    exits: list[Id] = Field(min_length=1, max_length=MAX_ITEMS)
    edges: list[Edge] = Field(max_length=MAX_ITEMS * 2)
    loop_limits: list[LoopLimit] = Field(default=[], max_length=MAX_ITEMS)
    max_model_calls: int | None = Field(default=None, ge=0)


class StateField(_Record):
    name: Id
    type: Short
    writers: list[Id] = Field(min_length=1, max_length=MAX_ITEMS)
    readers: list[Id] = Field(max_length=MAX_ITEMS)
    lifetime: Literal["run", "session", "persistent"]
    merge: Short | None = None

    @model_validator(mode="after")
    def _shared_writes_state_how_they_merge(self):
        if len(self.writers) > 1 and self.merge is None:
            raise ValueError(f"{self.name}: several writers need a stated merge")
        return self


class EvalCase(_Record):
    id: Id
    given: Text
    expect: Text


class DevTask(_Record):
    """Listed in build order, so the first entry is the user's first task."""

    id: Id
    title: Short
    inputs: Text
    produces: Text
    verify_by: Text
    depends_on: list[Id] = Field(default=[], max_length=MAX_ITEMS)


class Reason(_Record):
    text: Text
    requirement_ids: list[Id] = Field(default=[], max_length=MAX_ITEMS)
    card_ids: list[Short] = Field(default=[], max_length=MAX_ITEMS)


class SimplerAlternative(_Record):
    description: Text
    why_not: Text


class ValidationIssue(_Record):
    rule_id: Short
    severity: Literal["error", "warning"]
    message: Text


class ChangeRequest(_Record):
    """Revision `to_revision` was made from this request; `summary` is what the user sees."""

    from_revision: int = Field(ge=1)
    to_revision: int = Field(ge=2)
    request: Text
    summary: Text

    @model_validator(mode="after")
    def _moves_forward(self):
        if self.to_revision <= self.from_revision:
            raise ValueError("a change request must produce a later revision")
        return self


class Confirmation(_Record):
    design_revision: int = Field(ge=1)
    at: datetime


class ServiceDesign(_Record):
    schema_version: Literal[1] = SCHEMA_VERSION
    design_revision: int = Field(ge=1)
    provenance: Provenance
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
    # None means not validated yet, which is different from validated with no issues.
    validation: list[ValidationIssue] | None = None
    change_requests: list[ChangeRequest] = Field(default=[], max_length=MAX_ITEMS)
    confirmation: Confirmation | None = None

    @property
    def confirm_blockers(self) -> list[str]:
        blockers = []
        if self.provenance.source != "model":
            blockers.append("source_not_model")
        if self.validation is None:
            blockers.append("not_validated")
        elif any(issue.severity == "error" for issue in self.validation):
            blockers.append("validation_errors")
        if any(unknown.blocks_confirmation for unknown in self.unknowns):
            blockers.append("blocking_unknowns")
        return blockers

    @model_validator(mode="after")
    def _confirmation_is_earned_for_this_revision(self):
        if self.confirmation is None:
            return self
        if self.confirmation.design_revision != self.design_revision:
            raise ValueError("a confirmation only holds for the revision it confirmed")
        if self.confirm_blockers:
            raise ValueError(f"cannot confirm: {', '.join(self.confirm_blockers)}")
        return self


class DesignState(BaseModel):
    """Separate from the journey's own status: a finished journey may have no design yet.

    `current` survives a new run or a failed one, so a model failure never loses a good design;
    a confirmed design stays confirmed until a new revision replaces it.
    """

    model_config = ConfigDict(extra="forbid")

    status: DesignStatus = "not_started"
    current: ServiceDesign | None = None
    # Earlier confirmed designs, kept as history and never shown as the current one.
    confirmed_history: list[ServiceDesign] = Field(default=[], max_length=MAX_ITEMS)
    error: Short | None = None

    @model_validator(mode="after")
    def _status_matches_the_design(self):
        confirmed = self.current is not None and self.current.confirmation is not None
        if self.status == "not_started" and self.current is not None:
            raise ValueError("not_started has no design")
        if self.status == "review_required" and (self.current is None or confirmed):
            raise ValueError("review_required needs an unconfirmed design")
        if self.status == "confirmed" and not confirmed:
            raise ValueError("confirmed status needs a confirmed current design")
        if any(design.confirmation is None for design in self.confirmed_history):
            raise ValueError("history only holds confirmed designs")
        return self
