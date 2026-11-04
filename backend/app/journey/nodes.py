"""Graph nodes. Each returns only the state fields it owns (enforced in `graph.py`).

Any node calling `interrupt` re-runs from its start on resume, so a model call must never share a
node with one: that is why the Decider runs in `clarify_gate`, not in `clarify_question`.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command, interrupt
from pydantic import ValidationError

from app.journey.constraints import evaluate, preview
from app.journey.controller import next_card
from app.journey.deciders.base import DeciderQuestion, judge
from app.journey.services import JourneyDeps
from app.journey.state import (
    CLARIFY_QUESTIONS,
    GATE_ACTION,
    ISSUE_ACTION,
    MAX_CLARIFY_ROUNDS,
    MAX_QUESTIONS_PER_CARD,
    MAX_QUESTIONS_PER_ROUND,
    QA,
    AcceptRecommendationAction,
    AskAction,
    CardPresentation,
    CardQA,
    Decision,
    DeferAction,
    JourneyState,
    OptionView,
    ProjectSpec,
    Recommendation,
    ReopenAction,
    SelectAction,
)
from app.registry.loader import Registry

Node = Callable[[JourneyState], dict[str, Any]]

RESUME_KEY = "value"


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
    if card_id in state.implied:
        return _reject("자동으로 정해진 결정입니다. 이 결정을 만든 앞선 선택을 바꿔 주세요.")
    if card_id not in state.decisions:
        return _reject("아직 결정하지 않은 카드는 다시 열 수 없습니다.")
    remaining = {k: v for k, v in state.decisions.items() if k != card_id}
    return {"decisions": remaining, "gate_outcome": "advance", "gate_error": None}


def _progress(state: JourneyState, registry: Registry) -> dict[str, int]:
    return {
        "total": len(registry.cards),
        "decided": len(state.decisions),
        "implied": len(state.implied),
        "deferred": sum(card_id in state.pending_cards for card_id in state.deferred_cards),
    }


def build_nodes(registry: Registry, deps: JourneyDeps) -> dict[str, Node]:
    def intake(state: JourneyState) -> dict[str, Any]:
        # S2 keeps the structured input as is; idea extraction by LLM arrives in S3.
        answers = {qa.field: qa.answer for qa in state.clarifications}
        spec = ProjectSpec.model_validate({**state.project_spec.model_dump(), **answers})
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
                text="이 프로젝트 정보로 결정 카드를 추천하기에 충분한가요?",
                choices=("yes", "no"),
                default="no",
            ),
        )
        return {
            "clarify_passed": verdict.answer == "yes",
            "_trace": {
                "decider": verdict.decider,
                "confidence": verdict.confidence,
                "model_id": verdict.model_id,
            },
        }

    def clarify_question(state: JourneyState) -> dict[str, Any]:
        spec = state.project_spec
        fields = spec.missing_signals()[:MAX_QUESTIONS_PER_ROUND]
        questions = [{"field": name, "question": CLARIFY_QUESTIONS[name]} for name in fields]
        answers = _wait_for_user(
            {"type": "clarify", "round": state.clarify_rounds + 1, "questions": questions}
        )
        answers = answers if isinstance(answers, dict) else {}
        accepted: list[QA] = []
        for name in fields:
            if answers.get(name) is None:
                continue  # Skipping a question is allowed; the signal just stays unknown.
            try:
                ProjectSpec.model_validate({**spec.model_dump(), name: answers[name]})
            except ValidationError:
                continue
            accepted.append(QA(field=name, question=CLARIFY_QUESTIONS[name], answer=answers[name]))
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
        return {
            "implied": implied,
            "pending_cards": result.pending,
            "conflicts": result.conflicts,
            "blocked_options": result.blocked,
        }

    def controller(state: JourneyState) -> dict[str, Any]:
        return {"current_card_id": next_card(state.pending_cards, state.deferred_cards)}

    def advisor(state: JourneyState) -> dict[str, Any]:
        return {"advice": deps.advisor.advise(state, registry.card(state.current_card_id))}

    def recommender(state: JourneyState) -> dict[str, Any]:
        card = registry.card(state.current_card_id)
        blocked = state.blocked_options.get(card.card_id, {})
        choices = tuple(option.id for option in card.options if option.id not in blocked)
        if not choices:
            return {
                "recommendation": Recommendation(
                    status="needs_comparison", decider=getattr(deps.decider, "name", "unknown")
                )
            }
        default = card.default_recommendation
        verdict = judge(
            deps.decider,
            state,
            DeciderQuestion(
                id=f"recommend.{card.card_id}",
                text=card.question,
                choices=choices,
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
                reason=default.reason if verdict.answer == default.option else "",
                decider=verdict.decider,
            )
        return {
            "recommendation": recommendation,
            "_trace": {
                "decider": verdict.decider,
                "confidence": verdict.confidence,
                "model_id": verdict.model_id,
            },
        }

    def retriever(state: JourneyState) -> dict[str, Any]:
        return {"evidence": deps.retriever.retrieve(state, registry.card(state.current_card_id))}

    def present(state: JourneyState) -> dict[str, Any]:
        card = registry.card(state.current_card_id)
        chosen = {card_id: d.option_id for card_id, d in state.decisions.items()}
        blocked = state.blocked_options.get(card.card_id, {})
        views = []
        for option in card.options:
            impact = preview(registry, chosen, card.card_id, option.id)
            views.append(
                OptionView(
                    option=option,
                    note=state.advice.notes.get(option.id, ""),
                    blocked_reason=blocked.get(option.id),
                    implies={k: v.option_id for k, v in impact.implied.items()},
                    implied_messages=[v.message for v in impact.implied.values()],
                    warnings=[conflict.message for conflict in impact.conflicts],
                    artifacts=list(card.artifacts.get(option.id, ())),
                )
            )
        return {
            "current_card": CardPresentation(
                card_id=card.card_id,
                version=card.version,
                layer=card.layer,
                question=card.question,
                options=views,
                recommendation=state.recommendation,
                evidence=state.evidence,
                advice_source=state.advice.source,
                learning_refs=list(card.learning_refs),
                div_refs=list(card.div_refs),
            )
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

        if isinstance(action, AskAction):
            asked = sum(qa.card_id == current.card_id for qa in state.qa_history)
            if asked >= MAX_QUESTIONS_PER_CARD:
                return _reject("이 카드의 질문 한도에 도달했습니다. 선택지를 골라 주세요.")
            return {
                "pending_question": action.question,
                "gate_outcome": "ask",
                "gate_error": None,
            }
        if isinstance(action, DeferAction):
            others = [card_id for card_id in state.deferred_cards if card_id != current.card_id]
            return {
                "deferred_cards": [*others, current.card_id],
                "gate_outcome": "advance",
                "gate_error": None,
            }
        if isinstance(action, ReopenAction):
            return _reopen(state, action.card_id)

        if isinstance(action, AcceptRecommendationAction):
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
        decision = Decision(
            card_id=current.card_id,
            card_version=current.version,
            option_id=option_id,
            by=by,
            rationale=rationale,
            at=datetime.now(UTC),
        )
        return {
            "decisions": {**state.decisions, current.card_id: decision},
            "deferred_cards": [c for c in state.deferred_cards if c != current.card_id],
            "gate_outcome": "advance",
            "gate_error": None,
        }

    def qa(state: JourneyState) -> dict[str, Any]:
        card = registry.card(state.current_card_id)
        answer = deps.responder.answer(state, card, state.pending_question)
        entry = CardQA(
            card_id=card.card_id,
            question=state.pending_question,
            answer=answer,
            answered_by=deps.responder.name,
        )
        return {"qa_history": [*state.qa_history, entry]}

    def reviewer(state: JourneyState) -> dict[str, Any]:
        # S2 covers rule conflicts only; LLM review of context mismatches arrives in S3.
        has_errors = any(conflict.severity == "error" for conflict in state.conflicts)
        return {
            "review_issues": state.conflicts,
            "status": "needs_fix" if has_errors else "completed",
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

    return {
        "intake": intake,
        "clarify_gate": clarify_gate,
        "clarify_question": clarify_question,
        "constraint_engine": constraint_engine,
        "controller": controller,
        "advisor": advisor,
        "recommender": recommender,
        "retriever": retriever,
        "present": present,
        "decision_gate": decision_gate,
        "qa": qa,
        "reviewer": reviewer,
        "issue_gate": issue_gate,
    }
