"""Ports for the model-backed parts, with mock and real implementations."""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from app.config import Settings
from app.journey.deciders.base import Decider
from app.journey.deciders.jev import JevDecider
from app.journey.deciders.mock import MockDecider
from app.journey.design_generator import Designer, LLMDesigner
from app.journey.llm import EXAONE_MODEL, ExaoneLLM, GeminiLLM, StructuredLLM
from app.journey.modules import ModuleChange, ModulePlan, ModuleTurn
from app.journey.prompts import (
    ADVISOR_SYSTEM,
    ADVISOR_VERSION,
    GCB_SYSTEM,
    GCB_VERSION,
    MODULE_SYSTEM,
    MODULE_VERSION,
    QA_SYSTEM,
    QA_VERSION,
    advisor_user,
    gcb_user,
    module_user,
    qa_user,
)
from app.journey.state import (
    MAX_GCB_CHARS,
    MAX_LLM_CALLS_PER_JOURNEY,
    Advice,
    Evidence,
    GcbDraft,
    JourneyState,
)
from app.registry.evidence import EvidenceCatalog, load_catalog
from app.registry.loader import Registry
from app.registry.schema import DecisionCard

logger = logging.getLogger(__name__)

MAX_NOTE_CHARS = 400
MAX_ANSWER_CHARS = 1500
# Provisional: a whole design is far larger than a card explanation. Recalibrate from real calls.
DESIGN_TIMEOUT_MS = 120_000
DESIGN_MAX_OUTPUT_TOKENS = 16_000
EXAONE_DESIGN_MAX_TOKENS = 32_000  # Reasoning tokens count toward this cap.
# K-EXAONE always reasons: a card explanation took 25-62 s (2026-11-11). The design timeout keeps
# a first attempt inside the screen's 300 s wait.
EXAONE_TIMEOUT_MS = 90_000
EXAONE_DESIGN_TIMEOUT_MS = 280_000
QA_UNAVAILABLE = (
    "지금은 답변을 만들지 못했어요. 선택지의 장단점을 참고하거나 잠시 후 다시 질문해 주세요."
)


class Answer(BaseModel):
    text: str
    answered_by: str
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class GcbDrafter(Protocol):
    def draft(self, state: JourneyState) -> GcbDraft: ...


class Advisor(Protocol):
    def advise(self, state: JourneyState, card: DecisionCard) -> Advice: ...


class Retriever(Protocol):
    def retrieve(self, state: JourneyState, card: DecisionCard) -> list[Evidence]: ...


class Responder(Protocol):
    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> Answer: ...


def llm_calls_used(state: JourneyState) -> int:
    nodes = ("gcb_drafter", "advisor", "qa", "designer")
    return sum(event.node in nodes and bool(event.model_id) for event in state.trace)


def _card_advice(card: DecisionCard, source: str) -> Advice:
    return Advice(source=source, notes={option.id: option.summary for option in card.options})


class MockGcbDrafter:
    """No model, no draft: the user fills in the form, which needs no invented content."""

    def draft(self, state: JourneyState) -> GcbDraft:
        return GcbDraft()


class GcbOutput(BaseModel):
    goal: str
    context: str = ""
    boundary: str = ""


class LLMGcbDrafter:
    """A failure leaves an empty form: drafting helps the user but must not block them."""

    def __init__(self, llm: StructuredLLM):
        self._llm = llm

    def draft(self, state: JourneyState) -> GcbDraft:
        try:
            result = self._llm.generate(
                system=GCB_SYSTEM, user=gcb_user(state.project_spec.idea), schema=GcbOutput
            )
            fields = {
                name: getattr(result.output, name).strip()
                for name in ("goal", "context", "boundary")
            }
            if not fields["goal"] or any(len(text) > MAX_GCB_CHARS for text in fields.values()):
                raise ValueError("draft has no goal or a field is too long")
        except Exception as exc:  # noqa: BLE001 - model boundary; the prompt holds user text
            logger.error("GCB draft failed type=%s", type(exc).__name__)
            return GcbDraft(source="unavailable")
        return GcbDraft(
            **fields,
            source="llm",
            model_id=result.model_id,
            prompt_version=GCB_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


class MockAdvisor:
    """Repeats the card's own text; it does not analyse the project."""

    def advise(self, state: JourneyState, card: DecisionCard) -> Advice:
        return _card_advice(card, "mock")


class OptionNote(BaseModel):
    option_id: str
    note: str


class AdvisorOutput(BaseModel):
    notes: list[OptionNote]


class LLMAdvisor:
    """Falls back to the card's own text: a model failure must not block the decision."""

    def __init__(self, llm: StructuredLLM, registry: Registry):
        self._llm = llm
        self._registry = registry

    def advise(self, state: JourneyState, card: DecisionCard) -> Advice:
        if llm_calls_used(state) >= MAX_LLM_CALLS_PER_JOURNEY:
            logger.warning("LLM budget reached journey_id=%s", state.journey_id)
            return _card_advice(card, "card_text")
        try:
            result = self._llm.generate(
                system=ADVISOR_SYSTEM,
                user=advisor_user(state, card, self._registry),
                schema=AdvisorOutput,
            )
            notes = _checked_notes(result.output, card)
        except Exception as exc:  # noqa: BLE001 - model boundary; the prompt holds user text
            logger.error("Advisor failed card_id=%s type=%s", card.card_id, type(exc).__name__)
            return _card_advice(card, "card_text")
        return Advice(
            source="llm",
            notes=notes,
            model_id=result.model_id,
            prompt_version=ADVISOR_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


def _checked_notes(output: AdvisorOutput, card: DecisionCard) -> dict[str, str]:
    """A valid shape is not enough: every option must be covered, once, within the limit."""
    notes = {item.option_id: item.note.strip() for item in output.notes}
    expected = {option.id for option in card.options}
    if len(output.notes) != len(expected) or set(notes) != expected:
        raise ValueError("advisor output does not cover the card's options")
    if not all(0 < len(note) <= MAX_NOTE_CHARS for note in notes.values()):
        raise ValueError("advisor note is empty or too long")
    return notes


class EmptyRetriever:
    """No lecture corpus yet. An empty result is shown as "no evidence", never invented."""

    def retrieve(self, state: JourneyState, card: DecisionCard) -> list[Evidence]:
        return []


class CuratedRetriever:
    """Reviewed links only. A search-based retriever can replace it behind the same port."""

    def __init__(self, catalog: EvidenceCatalog):
        self._catalog = catalog

    def retrieve(self, state: JourneyState, card: DecisionCard) -> list[Evidence]:
        wanted = set(card.learning_refs)
        found = []
        for link in self._catalog.links:
            if wanted.isdisjoint(link.topics):
                continue
            source = self._catalog.source(link.source_id)
            found.append(
                Evidence(
                    source_id=source.source_id,
                    title=source.title,
                    kind=source.kind,
                    location=link.location,
                    why=link.why,
                    url=source.url,
                )
            )
        return found


class MockResponder:
    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> Answer:
        return Answer(
            text="모델 미연결 상태의 고정 응답입니다. 선택지의 장단점을 참고해 주세요.",
            answered_by="mock",
        )


class QAOutput(BaseModel):
    answer: str


class LLMResponder:
    def __init__(self, llm: StructuredLLM, registry: Registry):
        self._llm = llm
        self._registry = registry

    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> Answer:
        unavailable = Answer(text=QA_UNAVAILABLE, answered_by="unavailable")
        if llm_calls_used(state) >= MAX_LLM_CALLS_PER_JOURNEY:
            return unavailable
        try:
            result = self._llm.generate(
                system=QA_SYSTEM,
                user=qa_user(state, card, self._registry, question),
                schema=QAOutput,
            )
            text = result.output.answer.strip()
            if not 0 < len(text) <= MAX_ANSWER_CHARS:
                raise ValueError("answer is empty or too long")
        except Exception as exc:  # noqa: BLE001 - model boundary; the prompt holds user text
            logger.error("Q&A failed card_id=%s type=%s", card.card_id, type(exc).__name__)
            return unavailable
        return Answer(
            text=text,
            answered_by="llm",
            model_id=result.model_id,
            prompt_version=QA_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


class ModuleOutput(BaseModel):
    reply: str
    changes: list[ModuleChange] = []


class ModuleReply(ModuleOutput):
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModuleWriter(Protocol):
    def write(
        self, plan: list[ModulePlan], chat: list[ModuleTurn], message: str
    ) -> ModuleReply | None: ...


class LLMModuleWriter:
    """None on failure: the caller keeps the state as it was, so the message can be sent again."""

    def __init__(self, llm: StructuredLLM):
        self._llm = llm

    def write(
        self, plan: list[ModulePlan], chat: list[ModuleTurn], message: str
    ) -> ModuleReply | None:
        try:
            result = self._llm.generate(
                system=MODULE_SYSTEM, user=module_user(plan, chat, message), schema=ModuleOutput
            )
            reply = result.output.reply.strip()
            if not reply or len(reply) > MAX_ANSWER_CHARS:
                raise ValueError("reply is empty or too long")
        except Exception as exc:  # noqa: BLE001 - model boundary; the prompt holds user text
            logger.error("module reply failed type=%s", type(exc).__name__)
            return None
        return ModuleReply(
            reply=reply,
            changes=result.output.changes,
            model_id=result.model_id,
            prompt_version=MODULE_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


@dataclass(frozen=True)
class JourneyDeps:
    decider: Decider = field(default_factory=MockDecider)
    advisor: Advisor = field(default_factory=MockAdvisor)
    retriever: Retriever = field(default_factory=EmptyRetriever)
    responder: Responder = field(default_factory=MockResponder)
    drafter: GcbDrafter = field(default_factory=MockGcbDrafter)
    # None means no model: the journey ends with a reference template.
    designer: Designer | None = None
    # None means no model: the build order is filled in with forms instead of a conversation.
    module_writer: ModuleWriter | None = None
    card_selection: bool = True

    @property
    def recommendations_are_mock(self) -> bool:
        return self.decider.name == "mock"

    @property
    def explanations_are_mock(self) -> bool:
        return isinstance(self.advisor, MockAdvisor)


def build_deps(settings: Settings, registry: Registry) -> JourneyDeps:
    decider: Decider = MockDecider()
    if settings.decider == "jev":
        key = settings.ai_gateway_api_key if settings.jev_route == "vercel" else None
        key = key or (settings.opencode_api_key if settings.jev_route == "opencode" else None)
        key = key or (settings.typesafe_api_key if settings.jev_route == "typesafe" else None)
        decider = JevDecider(
            settings.jev_route,
            registry,
            api_key=key.get_secret_value() if key else None,
            model=settings.jev_model,
        )
    retriever: Retriever = EmptyRetriever()
    if settings.evidence_scope == "owner":
        retriever = CuratedRetriever(load_catalog(registry))
    if settings.provider == "mock":
        return JourneyDeps(
            decider=decider, retriever=retriever, card_selection=settings.card_selection
        )
    llm: StructuredLLM
    design_llm: StructuredLLM
    if settings.provider == "exaone":
        exaone_key = settings.exaone_api_key.get_secret_value()
        exaone_model = settings.exaone_model or EXAONE_MODEL
        llm = ExaoneLLM(exaone_key, exaone_model, timeout_ms=EXAONE_TIMEOUT_MS)
        # Provisional: the design is the hardest call, so it reasons longer with room to spare.
        design_llm = ExaoneLLM(
            exaone_key,
            exaone_model,
            timeout_ms=EXAONE_DESIGN_TIMEOUT_MS,
            max_output_tokens=EXAONE_DESIGN_MAX_TOKENS,
            reasoning_effort="high",
        )
    else:
        api_key = settings.gemini_api_key.get_secret_value()
        llm = GeminiLLM(api_key, settings.gemini_model)
        design_llm = GeminiLLM(
            api_key,
            settings.gemini_design_model or settings.gemini_model,
            timeout_ms=DESIGN_TIMEOUT_MS,
            max_output_tokens=DESIGN_MAX_OUTPUT_TOKENS,
        )
    return JourneyDeps(
        decider=decider,
        retriever=retriever,
        drafter=LLMGcbDrafter(llm),
        advisor=LLMAdvisor(llm, registry),
        responder=LLMResponder(llm, registry),
        designer=LLMDesigner(design_llm, registry),
        module_writer=LLMModuleWriter(llm),
        card_selection=settings.card_selection,
    )
