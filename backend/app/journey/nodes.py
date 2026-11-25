"""Graph nodes. Each returns only the state fields it owns (enforced in `graph.py`).

Any node calling `interrupt` re-runs from its start on resume, so a model call must never share a
node with one: that is why the Decider runs in `clarify_gate`, not in `clarify_question`.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command, interrupt
from pydantic import ValidationError

from app.journey.blueprint import OPTION_ICONS
from app.journey.composers.summary import ARTIFACT_KEY, compose_summary
from app.journey.constraints import displaced, evaluate, preview, revived
from app.journey.controller import next_card, split_at_fork
from app.journey.deciders.base import DeciderQuestion, judge, judge_many
from app.journey.design_constraints import BLOCKING_CARDS, derive_design_constraints
from app.journey.design_edit import keep_human_edits
from app.journey.design_generator import MAX_ATTEMPTS, MAX_OUTAGE_RETRIES, generate_design
from app.journey.services import JourneyDeps, StartFailure, llm_calls_used
from app.journey.start import (
    FIELDS,
    GCB_NAMES,
    StartChange,
    StartTurn,
    apply_start_changes,
    as_start_value,
    asked_field,
    card_defaults,
    display,
    reply_text,
    signal_answers,
    start_from_draft,
)
from app.journey.state import (
    CLARIFY_QUESTIONS,
    DONE_ACTION,
    FORK_ACTION,
    GATE_ACTION,
    GCB_ACTION,
    ISSUE_ACTION,
    MAX_CLARIFY_ROUNDS,
    MAX_LLM_CALLS_PER_JOURNEY,
    MAX_QUESTIONS_PER_CARD,
    MAX_QUESTIONS_PER_ROUND,
    QA,
    AcceptRecommendationAction,
    AskAction,
    CardBrief,
    CardPresentation,
    CardQA,
    CardSignal,
    Decision,
    DeferAction,
    EndHereAction,
    FocusAction,
    GcbDraft,
    JourneyState,
    KeepAction,
    OptionView,
    PlanDeployAction,
    PrepareAction,
    ProjectSpec,
    Recommendation,
    ReopenAction,
    ReviseAction,
    SelectAction,
    SignalAction,
    SignalChoice,
    SkippedCard,
)
from app.registry.loader import Registry
from app.registry.schema import DecisionCard

Node = Callable[[JourneyState], dict[str, Any]]

RESUME_KEY = "value"
# ADR-018 starting value, above the 0.7 recommendation gate. Not measured: tune on fixed cases.
SKIP_CONFIDENCE = 0.85


def resume_command(payload: Any) -> Command:
    """The only way to answer an interrupt.

    LangGraph treats a bare `{}` as an empty resume map and rejects `None`, so raw user input
    could otherwise stall a journey. Wrapping leaves judging the payload to the nodes.
    """
    return Command(resume={RESUME_KEY: payload})


def _wait_for_user(prompt: dict[str, Any]) -> Any:
    return interrupt(prompt)[RESUME_KEY]


def _reject(message: str) -> dict[str, Any]:
    return {"gate_outcome": "invalid", "gate_error": message}


def _reopen(state: JourneyState, card_id: str) -> dict[str, Any]:
    if card_id in state.skipped:
        # Putting a skipped card back: it becomes pending and is asked like any other.
        remaining = {k: v for k, v in state.skipped_cards.items() if k != card_id}
        return {"skipped_cards": remaining, "gate_outcome": "advance", "gate_error": None}
    if card_id in state.implied:
        return _reject("자동으로 정해진 결정입니다. 이 결정을 만든 앞선 선택을 바꿔 주세요.")
    if card_id not in state.decisions:
        return _reject("아직 결정하지 않은 카드는 다시 열 수 없습니다.")
    remaining = {k: v for k, v in state.decisions.items() if k != card_id}
    return {
        "decisions": remaining,
        "previous_choices": {
            **state.previous_choices,
            card_id: state.decisions[card_id].option_id,
        },
        "needs_review": [c for c in state.needs_review if c != card_id],
        "gate_outcome": "advance",
        "gate_error": None,
    }


def _revise(state: JourneyState, card_id: str) -> dict[str, Any]:
    if card_id in state.implied:
        return _reject("자동으로 정해진 결정입니다. 이 결정을 만든 앞선 선택을 바꿔 주세요.")
    if card_id not in state.decisions:
        return _reject("아직 결정하지 않은 카드는 고칠 수 없습니다.")
    return {"editing_card": card_id, "gate_outcome": "advance", "gate_error": None}


def _later_decisions(registry: Registry, decisions: dict[str, Decision], card_id: str) -> list[str]:
    stage = registry.card(card_id).stage
    return [c for c in decisions if registry.card(c).stage > stage]


def _answer_label(registry: Registry, card_id: str, option_id: str) -> str:
    card = registry.card(card_id)
    return f"{card.title}: {next(o.name for o in card.options if o.id == option_id)}"


def _keep(state: JourneyState, card_id: str) -> dict[str, Any]:
    if card_id not in state.needs_review:
        return _reject("다시 확인할 결정이 아닙니다.")
    return {
        "needs_review": [c for c in state.needs_review if c != card_id],
        "gate_outcome": "keep",
        "gate_error": None,
    }


def _accepted_answers(spec: ProjectSpec, fields: list[str], answers: dict[str, Any]) -> list[QA]:
    accepted: list[QA] = []
    for name in fields:
        if answers.get(name) is None:
            continue  # Skipping a question is allowed; the signal just stays unknown.
        try:
            ProjectSpec.model_validate({**spec.model_dump(), name: answers[name]})
        except ValidationError:
            continue
        accepted.append(QA(field=name, question=CLARIFY_QUESTIONS[name], answer=answers[name]))
    return accepted


def _progress(state: JourneyState, registry: Registry) -> dict[str, int]:
    return {
        "total": len(registry.cards),
        "decided": len(state.decisions),
        "implied": len(state.implied),
        "deferred": sum(card_id in state.pending_cards for card_id in state.deferred_cards),
    }


def _selection_question(card: DecisionCard) -> DeciderQuestion:
    options = ", ".join(option.name for option in card.options)
    return DeciderQuestion(
        id=f"select.{card.card_id}",
        text=(
            f"이 프로젝트를 설계할 때 '{card.title}' 결정이 필요한가요? "
            f"카드 질문: {card.question} 선택지: {options}"
        ),
        choices=("needed", "unneeded", "unknown"),
        criteria={
            "needed": "프로젝트에 이 결정이 다루는 기능이나 구성이 있거나 생길 수 있음",
            "unneeded": "프로젝트 정보로 보아 이 결정이 다루는 기능이나 구성이 분명히 필요 없음",
            "unknown": "주어진 정보로는 필요한지 판단할 수 없음",
        },
        # Asking is the safe side: a card is left out only on a confident "unneeded".
        default="needed",
    )


def _with_signals(state: JourneyState, fields: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """Start fields and the spec moved together, for the signals in `names` only."""
    answers = signal_answers({name: fields[name] for name in names})
    spec = ProjectSpec.model_validate({**state.project_spec.model_dump(), **answers})
    return {"start_fields": fields, "project_spec": spec}


def _leave_unchanged(state: JourneyState) -> dict[str, Any]:
    """Leaving a card in revise mode as it was. Project info changed on it meanwhile still
    counts as a change, so a finished result is built again from the new info."""
    outcome = "advance" if state.info_changed else "unchanged"
    return {
        "editing_card": None,
        "info_changed": False,
        "gate_outcome": outcome,
        "gate_error": None,
    }


def _card_signals(state: JourneyState, card: DecisionCard) -> list[CardSignal]:
    signals = []
    for name in card.uses:
        field, held = FIELDS[name], state.start_fields.get(name)
        value = held.value if held else as_start_value(getattr(state.project_spec, name))
        if value is None:
            continue
        signals.append(
            CardSignal(
                name=name,
                label=field.name_in_text,
                kind=field.kind,
                choices=[SignalChoice(value=c.value, label=c.label) for c in field.choices],
                free_text=field.free_text,
                value=value,
                display=display(field, value),
                source=held.source if held else None,
                why=held.why if held else None,
            )
        )
    return signals


def _recommendation_reason(card: DecisionCard, option_id: str, decider: str) -> str:
    default = card.default_recommendation
    if decider == "mock":
        # A mock did not read the project: only the card's stated default reason is honest.
        return default.reason if option_id == default.option else ""
    signals = card.signals.get(option_id, ())
    return f"이런 경우에 잘 맞아요: {', '.join(signals)}" if signals else ""


def build_nodes(registry: Registry, deps: JourneyDeps) -> dict[str, Node]:
    def _stage(card_id: str) -> int:
        return registry.card(card_id).stage

    def _plan_deploy(state: JourneyState, action: PlanDeployAction) -> dict[str, Any]:
        _, late = split_at_fork(state.pending_cards, _stage)
        if not late:
            return _reject("더 정할 배포 카드가 없어요.")
        if action.card_id is not None and action.card_id not in late:
            return _reject("지금 고를 수 있는 카드가 아닙니다.")
        return {
            "plan_scope": "full",
            "focus_card": action.card_id,
            "gate_outcome": "advance",
            "gate_error": None,
        }

    def gcb_drafter(state: JourneyState) -> dict[str, Any]:
        idea = state.project_spec.idea
        if deps.start_writer is None:
            draft = deps.drafter.draft(state)
            return {
                "gcb_draft": draft,
                "start_fields": start_from_draft(draft),
                "start_chat": [StartTurn(role="user", text=idea)],
                "_trace": draft.model_dump(
                    include={"model_id", "prompt_version", "input_tokens", "output_tokens"}
                ),
            }
        # The idea is the first message: one call fills the goal and the signals together.
        reply = deps.start_writer.write({}, [], idea, None)
        if isinstance(reply, StartFailure):
            answer = StartTurn(
                role="assistant",
                text=f"{reply.reason} 칸을 눌러 직접 채워도 돼요.",
            )
            return {
                "gcb_draft": GcbDraft(source="unavailable"),
                "start_chat": [StartTurn(role="user", text=idea), answer],
            }
        fields, applied, rejected = apply_start_changes({}, reply.changes, "said", message=idea)
        answer = StartTurn(
            role="assistant",
            text=reply_text(applied, fields, None),
            changes=applied,
            rejected=rejected,
            asks=asked_field(fields),
        )
        texts = {name: str(fields[name].value) for name in GCB_NAMES if name in fields}
        return {
            "gcb_draft": GcbDraft(**texts, source="llm", model_id=reply.model_id),
            "start_fields": fields,
            "start_chat": [StartTurn(role="user", text=idea), answer],
            "_trace": reply.model_dump(
                include={"model_id", "prompt_version", "input_tokens", "output_tokens"}
            ),
        }

    def gcb_gate(state: JourneyState) -> dict[str, Any]:
        draft = state.gcb_draft
        spec = state.project_spec
        # The start screen fills every signal (ADR-023), so all of them are accepted here.
        asked = spec.missing_signals()
        raw = _wait_for_user(
            {
                "type": "gcb",
                "questions": [
                    {"field": name, "question": CLARIFY_QUESTIONS[name]} for name in asked
                ],
                "draft": draft.model_dump(include={"goal", "context", "boundary"}),
                "source": draft.source,
                "error": state.gate_error,
            }
        )
        try:
            action = GCB_ACTION.validate_python(raw)
        except ValidationError:
            return _reject("입력 내용을 확인해 주세요. 칸마다 1,000자까지 쓸 수 있어요.")
        fields = action.model_dump(include={"goal", "context", "boundary"})
        answered = (
            {}
            if action.answers is None
            else {
                "clarifications": _accepted_answers(spec, asked, action.answers),
                "clarify_rounds": MAX_CLARIFY_ROUNDS,
            }
        )
        return {
            **answered,
            "gcb_answer": {name: text for name, text in fields.items() if text},
            "gate_outcome": "advance",
            "gate_error": None,
        }

    def intake(state: JourneyState) -> dict[str, Any]:
        answers = {qa.field: qa.answer for qa in state.clarifications}
        spec = ProjectSpec.model_validate(
            {**state.project_spec.model_dump(), **state.gcb_answer, **answers}
        )
        return {"project_spec": spec}

    def clarify_gate(state: JourneyState) -> dict[str, Any]:
        missing = state.project_spec.missing_signals()
        if not missing or state.clarify_rounds >= MAX_CLARIFY_ROUNDS:
            return {"clarify_passed": True}
        verdict = judge(
            deps.decider,
            state,
            DeciderQuestion(
                id="clarify.sufficient",
                text="이 프로젝트 정보로 기술 선택지를 추천하기에 충분한가요?",
                choices=("yes", "no"),
                criteria={
                    "yes": "규모, 기간, 배포 목표를 알 수 있어 선택지를 구분할 수 있음",
                    "no": "결정을 바꿀 정보가 빠져 있어 사용자에게 물어봐야 함",
                },
                default="no",
            ),
        )
        return {"clarify_passed": verdict.answer == "yes", "_trace": verdict.trace()}

    def card_selector(state: JourneyState) -> dict[str, Any]:
        """Leaves out cards this project does not need (ADR-018). Any doubt asks the card."""
        if not deps.card_selection:
            return {"skipped_cards": {}}
        # Cards that block confirming a design are always asked.
        cards = [card for card in registry.cards if card.card_id not in BLOCKING_CARDS]
        questions = {card.card_id: _selection_question(card) for card in cards}
        verdicts, meta = judge_many(deps.decider, state, list(questions.values()))
        skipped = {}
        for card_id, question in questions.items():
            verdict = verdicts[question.id]
            if verdict.answer == "unneeded" and verdict.confidence >= SKIP_CONFIDENCE:
                skipped[card_id] = SkippedCard(
                    confidence=verdict.confidence, decider=verdict.decider
                )
        return {"skipped_cards": skipped, "_trace": meta}

    def clarify_question(state: JourneyState) -> dict[str, Any]:
        spec = state.project_spec
        fields = spec.missing_signals()[:MAX_QUESTIONS_PER_ROUND]
        questions = [{"field": name, "question": CLARIFY_QUESTIONS[name]} for name in fields]
        answers = _wait_for_user(
            {"type": "clarify", "round": state.clarify_rounds + 1, "questions": questions}
        )
        answers = answers if isinstance(answers, dict) else {}
        accepted = _accepted_answers(spec, fields, answers)
        return {
            "clarifications": [*state.clarifications, *accepted],
            "clarify_rounds": state.clarify_rounds + 1,
        }

    def constraint_engine(state: JourneyState) -> dict[str, Any]:
        chosen = {card_id: d.option_id for card_id, d in state.decisions.items()}
        result = evaluate(registry, chosen)
        implied: dict[str, Decision] = {}
        for card_id, choice in result.implied.items():
            previous = state.implied.get(card_id)
            if previous is not None and previous.option_id == choice.option_id:
                implied[card_id] = previous
                continue
            implied[card_id] = Decision(
                card_id=card_id,
                card_version=registry.card(card_id).version,
                option_id=choice.option_id,
                by="implied",
                rationale=choice.message,
                at=datetime.now(UTC),
            )
        effective = {**chosen, **{card_id: d.option_id for card_id, d in implied.items()}}
        # Recomputed on every change, so a card comes back once a decision points at it.
        out = set(state.skipped_cards) - revived(registry, effective, state.skipped_cards)
        blocked = result.blocked
        if editing := state.editing_card:
            # Options are judged as if this card were still open; its own choice blocks nothing.
            others = {card_id: option for card_id, option in chosen.items() if card_id != editing}
            blocked = {**blocked, editing: evaluate(registry, others).blocked.get(editing, {})}
        return {
            "implied": implied,
            "pending_cards": [card_id for card_id in result.pending if card_id not in out],
            "conflicts": result.conflicts,
            "blocked_options": blocked,
        }

    def controller(state: JourneyState) -> dict[str, Any]:
        # Stage first: a decision made here can invalidate the ones in later stages.
        pending = sorted(state.pending_cards, key=_stage)
        # Cards deferred in the agent design come back before the fork, not after every card.
        early, _ = split_at_fork(pending, _stage)
        if state.focus_card in pending:
            following = state.focus_card
        else:
            following = next_card(early or pending, state.deferred_cards)
        current = state.editing_card or following
        update: dict[str, Any] = {"current_card_id": current}
        if current is None:
            return update
        # Info this card reads and nobody gave takes its small-start default now (ADR-024).
        blank = [
            name
            for name in registry.card(current).uses
            if name not in state.start_fields and getattr(state.project_spec, name) is None
        ]
        fields = card_defaults(state.start_fields, blank)
        if added := [name for name in blank if name in fields]:
            update.update(_with_signals(state, fields, added))
        return update

    def advisor(state: JourneyState) -> dict[str, Any]:
        advice = deps.advisor.advise(state, registry.card(state.current_card_id))
        return {
            "advice": advice,
            "_trace": advice.model_dump(
                include={"model_id", "prompt_version", "input_tokens", "output_tokens"}
            ),
        }

    def recommender(state: JourneyState) -> dict[str, Any]:
        card = registry.card(state.current_card_id)
        blocked = state.blocked_options.get(card.card_id, {})
        choices = tuple(option.id for option in card.options if option.id not in blocked)
        if not choices:
            return {
                "recommendation": Recommendation(
                    status="needs_comparison", decider=deps.decider.name
                )
            }
        default = card.default_recommendation
        verdict = judge(
            deps.decider,
            state,
            DeciderQuestion(
                id=f"recommend.{card.card_id}",
                text=f"이 프로젝트에 가장 잘 맞는 선택지는? {card.question}",
                choices=choices,
                criteria={
                    option.id: " / ".join((option.summary, *card.signals.get(option.id, ())))
                    for option in card.options
                    if option.id in choices
                },
                default=default.option if default.option in choices else None,
            ),
        )
        if verdict.answer is None:
            recommendation = Recommendation(
                status="needs_comparison", confidence=verdict.confidence, decider=verdict.decider
            )
        else:
            recommendation = Recommendation(
                status="recommended",
                option_id=verdict.answer,
                confidence=verdict.confidence,
                reason=_recommendation_reason(card, verdict.answer, verdict.decider),
                decider=verdict.decider,
            )
        return {"recommendation": recommendation, "_trace": verdict.trace()}

    def retriever(state: JourneyState) -> dict[str, Any]:
        return {"evidence": deps.retriever.retrieve(state, registry.card(state.current_card_id))}

    def present(state: JourneyState) -> dict[str, Any]:
        card = registry.card(state.current_card_id)
        brief = state.saved_brief
        if brief is None and state.gate_outcome == "prepare":
            brief = CardBrief(
                advice=state.advice,
                recommendation=state.recommendation,
                evidence=state.evidence,
                inputs=state.brief_inputs(card.card_id),
            )
        # Without a brief the options go out now; advice and recommendation come on `prepare`.
        preparing = brief is None
        chosen = {
            card_id: d.option_id
            for card_id, d in state.decisions.items()
            if card_id != card.card_id
        }
        blocked = state.blocked_options.get(card.card_id, {})
        held = (
            state.decisions[card.card_id].option_id if card.card_id == state.editing_card else None
        )
        views = []
        for option in card.options:
            impact = preview(registry, chosen, card.card_id, option.id)
            stops_fitting = (
                displaced(registry, chosen, card.card_id, held, option.id)
                if held not in (None, option.id) and option.id not in blocked
                else {}
            )
            views.append(
                OptionView(
                    option=option,
                    note="" if preparing else brief.advice.notes.get(option.id, ""),
                    blocked_reason=blocked.get(option.id),
                    icon=OPTION_ICONS.get((card.card_id, option.id)),
                    implies={k: v.option_id for k, v in impact.implied.items()},
                    implied_messages=[v.message for v in impact.implied.values()],
                    warnings=[conflict.message for conflict in impact.conflicts],
                    must_change=[_answer_label(registry, *item) for item in stops_fitting.items()],
                    artifacts=list(card.artifacts.get(option.id, ())),
                )
            )
        briefs = state.card_briefs if preparing else {**state.card_briefs, card.card_id: brief}
        return {
            "card_briefs": briefs,
            "current_card": CardPresentation(
                card_id=card.card_id,
                version=card.version,
                layer=card.layer,
                question=card.question,
                options=views,
                recommendation=None if preparing else brief.recommendation,
                evidence=[] if preparing else brief.evidence,
                advice_source="card_text" if preparing else brief.advice.source,
                preparing=preparing,
                to_review=(
                    [
                        _answer_label(registry, later, state.decisions[later].option_id)
                        for later in _later_decisions(registry, state.decisions, card.card_id)
                    ]
                    if held
                    else []
                ),
                learning_refs=list(card.learning_refs),
                div_refs=list(card.div_refs),
                signals=_card_signals(state, card),
            ),
        }

    def decision_gate(state: JourneyState) -> dict[str, Any]:
        current = state.current_card
        raw = _wait_for_user(
            {
                "type": "decision",
                "card": current.model_dump(mode="json"),
                "qa": [
                    qa.model_dump(mode="json")
                    for qa in state.qa_history
                    if qa.card_id == current.card_id
                ],
                "conflicts": [c.model_dump(mode="json") for c in state.conflicts],
                "progress": _progress(state, registry),
                "error": state.gate_error,
                "current_option_id": (
                    state.decisions[current.card_id].option_id
                    if state.editing_card == current.card_id
                    else None
                ),
            }
        )
        # Every outcome overwrites pending_question, so a stale question is never answered again.
        return {"pending_question": None, **_apply_gate_action(state, raw)}

    def _apply_gate_action(state: JourneyState, raw: Any) -> dict[str, Any]:
        current = state.current_card
        try:
            action = GATE_ACTION.validate_python(raw)
        except ValidationError:
            return _reject("요청 형식을 확인하지 못했습니다. 선택지를 다시 골라 주세요.")

        if isinstance(action, PrepareAction):
            if not current.preparing:
                return _reject("이미 추천까지 준비된 카드예요.")
            return {"gate_outcome": "prepare", "gate_error": None}
        if isinstance(action, AskAction):
            asked = sum(qa.card_id == current.card_id for qa in state.qa_history)
            if asked >= MAX_QUESTIONS_PER_CARD:
                return _reject("이 카드의 질문 한도에 도달했습니다. 선택지를 골라 주세요.")
            return {
                "pending_question": action.question,
                "gate_outcome": "ask",
                "gate_error": None,
            }
        editing = state.editing_card == current.card_id
        if isinstance(action, DeferAction):
            if editing:
                return _leave_unchanged(state)
            others = [card_id for card_id in state.deferred_cards if card_id != current.card_id]
            return {
                "deferred_cards": [*others, current.card_id],
                "focus_card": None,
                "gate_outcome": "advance",
                "gate_error": None,
            }
        if isinstance(action, ReopenAction):
            return _reopen(state, action.card_id)
        if isinstance(action, ReviseAction):
            return _revise(state, action.card_id)
        if isinstance(action, KeepAction):
            return _keep(state, action.card_id)
        if isinstance(action, FocusAction):
            if action.card_id not in state.pending_cards:
                return _reject("지금 고를 수 있는 카드가 아닙니다.")
            return {
                "focus_card": action.card_id,
                "editing_card": None,
                "gate_outcome": "advance",
                "gate_error": None,
            }

        if isinstance(action, SignalAction):
            return _change_signal(state, action)
        if isinstance(action, AcceptRecommendationAction):
            if current.recommendation is None:
                return _reject("추천을 준비하는 중이에요. 선택지를 직접 골라도 돼요.")
            option_id = current.recommendation.option_id
            by, rationale = "recommended", current.recommendation.reason
            if option_id is None:
                return _reject("이 카드에는 추천이 없습니다. 선택지를 비교해 직접 골라 주세요.")
        else:
            assert isinstance(action, SelectAction)
            option_id, by, rationale = action.option_id, "user", action.rationale

        view = next((v for v in current.options if v.option.id == option_id), None)
        if view is None:
            return _reject("없는 선택지입니다. 목록에서 다시 골라 주세요.")
        if view.blocked_reason is not None:
            return _reject(f"지금은 고를 수 없는 선택지입니다. {view.blocked_reason}")
        held = state.decisions[current.card_id].option_id if editing else None
        if held == option_id:
            return _leave_unchanged(state)
        decision = Decision(
            card_id=current.card_id,
            card_version=current.version,
            option_id=option_id,
            by=by,
            rationale=rationale,
            at=datetime.now(UTC),
        )
        previous = held or state.previous_choices.get(current.card_id)
        later = (
            _later_decisions(registry, state.decisions, current.card_id)
            if previous not in (None, option_id)
            else []
        )
        return {
            "decisions": {**state.decisions, current.card_id: decision},
            "editing_card": None,
            "deferred_cards": [c for c in state.deferred_cards if c != current.card_id],
            "previous_choices": {
                k: v for k, v in state.previous_choices.items() if k != current.card_id
            },
            "needs_review": list(
                dict.fromkeys([*(c for c in state.needs_review if c != current.card_id), *later])
            ),
            "info_changed": False,
            "gate_outcome": "advance",
            "gate_error": None,
        }

    def _change_signal(state: JourneyState, action: SignalAction) -> dict[str, Any]:
        """Only what this card reads can change here; the card is then prepared again."""
        card_id = state.current_card.card_id
        if action.field not in registry.card(card_id).uses:
            return _reject("이 카드에서 바꿀 수 있는 정보가 아니에요.")
        change = StartChange(field=action.field, value=action.value, values=action.values)
        fields, applied, rejected = apply_start_changes(state.start_fields, [change], "picked")
        if not applied:
            return _reject(" / ".join(rejected))
        try:
            moved = _with_signals(state, fields, [action.field])
        except ValidationError:
            # Free text such as "0" people fits the field but not the spec.
            name = FIELDS[action.field].name_in_text
            return _reject(f"{name}: 고를 수 있는 값이 아니라 그대로 뒀어요.")
        if moved["project_spec"] == state.project_spec:
            # The value it already had: nothing to explain again or rebuild.
            return {**moved, "gate_outcome": "advance", "gate_error": None}
        return {
            **moved,
            # Every card that read this info explains and recommends it again.
            "card_briefs": {
                k: v
                for k, v in state.card_briefs.items()
                if action.field not in registry.card(k).uses
            },
            "info_changed": True,
            "gate_outcome": "advance",
            "gate_error": None,
        }

    def qa(state: JourneyState) -> dict[str, Any]:
        card = registry.card(state.current_card_id)
        answer = deps.responder.answer(state, card, state.pending_question)
        entry = CardQA(
            card_id=card.card_id,
            question=state.pending_question,
            answer=answer.text,
            answered_by=answer.answered_by,
        )
        return {
            "qa_history": [*state.qa_history, entry],
            "_trace": answer.model_dump(
                include={"model_id", "prompt_version", "input_tokens", "output_tokens"}
            ),
        }

    def reviewer(state: JourneyState) -> dict[str, Any]:
        # Rule conflicts only: no LLM review of context mismatches yet.
        has_errors = any(conflict.severity == "error" for conflict in state.conflicts)
        return {
            "review_issues": state.conflicts,
            "status": "needs_fix" if has_errors else "completed",
        }

    def composer(state: JourneyState) -> dict[str, Any]:
        evidence = {card.card_id: deps.retriever.retrieve(state, card) for card in registry.cards}
        document = compose_summary(
            state, registry, is_mock=deps.recommendations_are_mock, evidence=evidence
        )
        return {"artifacts": {ARTIFACT_KEY: document}}

    def designer(state: JourneyState) -> dict[str, Any]:
        remaining = MAX_LLM_CALLS_PER_JOURNEY - llm_calls_used(state)
        attempts = min(MAX_ATTEMPTS, remaining)
        outcome = generate_design(
            state,
            registry,
            deps.designer,
            attempts=attempts,
            outage_retries=min(MAX_OUTAGE_RETRIES, remaining - attempts),
        )
        constraints = derive_design_constraints(state, registry)
        return {
            "design": keep_human_edits(state.design, outcome.design, constraints),
            "_trace": outcome.model_dump(
                include={"model_id", "prompt_version", "input_tokens", "output_tokens"}
            ),
        }

    def issue_gate(state: JourneyState) -> dict[str, Any]:
        raw = _wait_for_user(
            {
                "type": "issues",
                "issues": [c.model_dump(mode="json") for c in state.review_issues],
                "error": state.gate_error,
            }
        )
        try:
            action = ISSUE_ACTION.validate_python(raw)
        except ValidationError:
            return _reject("다시 고를 카드를 지정해 주세요.")
        return _reopen(state, action.card_id)

    def fork_gate(state: JourneyState) -> dict[str, Any]:
        """After the agent design: end with the system left undecided, or plan the deployment."""
        _, late = split_at_fork(sorted(state.pending_cards, key=_stage), _stage)
        asks = [
            name
            for card_id in late
            for name in registry.card(card_id).uses
            if name not in state.start_fields and getattr(state.project_spec, name) is None
        ]
        raw = _wait_for_user(
            {
                "type": "fork",
                "remaining": [
                    {"card_id": card_id, "title": registry.card(card_id).title} for card_id in late
                ],
                "asks": [FIELDS[name].name_in_text for name in dict.fromkeys(asks)],
                "error": state.gate_error,
            }
        )
        try:
            action = FORK_ACTION.validate_python(raw)
        except ValidationError:
            return _reject("여기서 끝낼지, 배포 계획을 세울지 골라 주세요.")
        if isinstance(action, EndHereAction):
            return {"plan_scope": "agent", "gate_outcome": "advance", "gate_error": None}
        if isinstance(action, PlanDeployAction):
            return _plan_deploy(state, action)
        return _revise(state, action.card_id)

    def done_gate(state: JourneyState) -> dict[str, Any]:
        raw = _wait_for_user({"type": "done", "error": state.gate_error})
        try:
            action = DONE_ACTION.validate_python(raw)
        except ValidationError:
            return _reject("다시 고를 카드를 지정해 주세요.")
        if isinstance(action, PlanDeployAction):
            return _plan_deploy(state, action)
        if isinstance(action, KeepAction):
            return _keep(state, action.card_id)
        if isinstance(action, ReviseAction):
            return _revise(state, action.card_id)
        return _reopen(state, action.card_id)

    return {
        "gcb_drafter": gcb_drafter,
        "gcb_gate": gcb_gate,
        "intake": intake,
        "clarify_gate": clarify_gate,
        "clarify_question": clarify_question,
        "card_selector": card_selector,
        "constraint_engine": constraint_engine,
        "controller": controller,
        "advisor": advisor,
        "recommender": recommender,
        "retriever": retriever,
        "present": present,
        "decision_gate": decision_gate,
        "qa": qa,
        "reviewer": reviewer,
        "composer": composer,
        "designer": designer,
        "issue_gate": issue_gate,
        "fork_gate": fork_gate,
        "done_gate": done_gate,
    }
