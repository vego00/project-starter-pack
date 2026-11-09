"""Decision summary: a deterministic Markdown document built only from recorded decisions."""

from collections.abc import Mapping, Sequence

from app.journey.state import Evidence, JourneyState
from app.registry.loader import Registry

ARTIFACT_KEY = "decision_summary"

LAYER_NAMES = {
    "agent": "Agent 설계",
    "model": "모델",
    "data": "데이터·검색",
    "backend": "백엔드·실행",
    "devops": "DevOps",
    "mlops": "MLOps",
    "cloud": "Cloud",
    "product": "제품 형태",
    "ops": "검증·운영",
}
BY_LABELS = {"user": "직접 선택", "recommended": "추천 수락", "implied": "규칙으로 자동 확정"}
SPEC_LABELS = {
    "deployment_target": "배포 목표",
    "has_gpu": "GPU 장비",
    "expected_users": "사용자 수",
    "budget": "예산",
    "team_size": "팀 인원",
    "duration_weeks": "기간(주)",
    "weekly_hours": "주간 작업 시간",
    "data_traits": "데이터 특징",
}
DEPLOYMENT_LABELS = {
    "local_demo": "로컬 데모",
    "small_group": "소수 사용자",
    "public_service": "공개 서비스",
}
MOCK_NOTICE = (
    "> 이 문서의 추천은 모델 없이 카드 기본값으로 만들었으며, 이 프로젝트를 분석한 결과가 아닙니다."
)


def _quote(text: str) -> list[str]:
    """User text stays inside a blockquote, so it cannot add headings to the document."""
    return [f"> {line}" if line.strip() else ">" for line in text.splitlines()]


def _inline(text: str) -> str:
    return " ".join(text.split())


def _spec_value(name: str, value: object) -> str:
    if value is None:
        return "미확인"
    if name == "deployment_target":
        return DEPLOYMENT_LABELS.get(str(value), str(value))
    if isinstance(value, bool):
        return "있음" if value else "없음"
    if isinstance(value, list):
        return ", ".join(_inline(item) for item in value) or "미확인"
    return _inline(str(value))


def compose_summary(
    state: JourneyState,
    registry: Registry,
    *,
    is_mock: bool,
    evidence: Mapping[str, Sequence[Evidence]] | None = None,
) -> str:
    evidence = evidence or {}
    spec = state.project_spec
    decisions = state.all_decisions
    lines = ["# 프로젝트 결정 요약", ""]
    if is_mock:
        lines += [MOCK_NOTICE, ""]

    lines += ["## 프로젝트", "", *_quote(spec.idea), ""]
    for label, text in (
        ("Goal (달성할 상태)", spec.goal),
        ("Context (필요한 상황)", spec.context),
        ("Boundary (결과 기준)", spec.boundary),
    ):
        lines += [f"**{label}**", "", *_quote(text or "미확인"), ""]
    lines += [f"- {label}: {_spec_value(n, getattr(spec, n))}" for n, label in SPEC_LABELS.items()]
    lines += ["", "## 결정", ""]

    components: list[str] = []
    for card in registry.cards:
        decision = decisions.get(card.card_id)
        if decision is None:
            continue
        option = card.option(decision.option_id)
        name = option.name if option else decision.option_id
        lines += [f"### {LAYER_NAMES[card.layer]}: {card.question}", ""]
        lines += [f"- **선택:** {name} ({BY_LABELS[decision.by]})"]
        if decision.rationale:
            lines += [f"- **이유:** {_inline(decision.rationale)}"]
        if option:
            lines += [f"- **장점:** {' / '.join(option.pros)}"]
            lines += [f"- **감수할 점:** {' / '.join(option.cons)}"]
        others = [other.name for other in card.options if other.id != decision.option_id]
        lines += [f"- **고르지 않은 선택지:** {', '.join(others)}"]
        for item in evidence.get(card.card_id, ()):
            lines += [f"- **참고 필기:** {item.title} ({item.location}). {item.why}"]
        lines += [""]
        components += card.artifacts.get(decision.option_id, ())

    skipped = [card for card in registry.cards if card.card_id in state.skipped]
    if skipped:
        lines += ["## 해당 없음", ""]
        lines += [
            "이 프로젝트에는 필요 없다고 판단해 묻지 않은 결정이에요. 필요하면 다시 넣으세요.",
            "",
        ]
        lines += [f"- {card.title}: {card.question}" for card in skipped]
        lines += [""]

    lines += ["## 확인할 점", ""]
    warnings = [issue.message for issue in state.review_issues if issue.severity == "warning"]
    lines += [f"- {_inline(message)}" for message in warnings] or [
        "- 규칙 검사에서 경고가 없습니다."
    ]
    unknown = [label for n, label in SPEC_LABELS.items() if getattr(spec, n) is None]
    if unknown:
        lines += [
            f"- 답하지 않은 항목: {', '.join(unknown)}. 값이 정해지면 결정을 다시 확인하세요."
        ]
    lines += ["- 카드의 장단점은 초안이며 공식 문서로 다시 확인이 필요합니다."]
    if any(evidence.values()):
        lines += [
            "- 참고 필기는 개인 필기이며 강의 원문이 아닙니다. 일부 카드에만 연결되어 있습니다.",
            "",
        ]
    else:
        lines += ["- 강의 자료 근거는 아직 연결되어 있지 않습니다.", ""]

    if components:
        lines += ["## 추가될 구성 요소", ""]
        lines += [f"- `{item}`" for item in dict.fromkeys(components)]
        lines += [""]

    lines += ["## 다음 행동", ""]
    lines += [
        "1. 팀원과 이 문서를 읽고, 각 결정의 이유를 설명할 수 있는지 확인합니다.",
        "2. 위 '확인할 점'을 먼저 해결합니다.",
        "3. 비용이 드는 선택은 공식 가격을 확인한 뒤 상한을 정합니다.",
        "",
    ]
    return "\n".join(lines)
