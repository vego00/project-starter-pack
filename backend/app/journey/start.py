"""The start screen (ADR-023): GCB and project signals filled by chat, picks and defaults.

Field definitions live here only; the screen draws what this module sends. Values are stored as
the user saw them and turned into `ProjectSpec` fields only when the journey starts.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

StartSource = Literal["said", "picked", "default", "recommended"]
NOTHING = "따로 없음"  # A GCB field filled without content; it reaches the spec as unset.
MAX_TEXT = 1000
MAX_FREE = 40


class StartValue(BaseModel):
    value: str | list[str]
    source: StartSource
    why: str | None = None


class StartTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    changes: list[str] = []
    rejected: list[str] = []


class StartChange(BaseModel):
    """One field a model wants to set. A multi-choice field sends its whole list in `values`."""

    field: str
    value: str = ""
    values: list[str] = []


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class StartField:
    name: str
    label: str
    kind: Literal["text", "choice", "multi"]
    choices: tuple[Choice, ...] = ()
    # Ranges stay text: no rule reads these, so no representative number is invented.
    free_text: bool = False
    default: str | tuple[str, ...] | None = None
    why: str = ""
    rule_read: bool = False
    # A shorter name for replies and change lists, when `label` is a question.
    short: str = ""

    @property
    def is_gcb(self) -> bool:
        return self.kind == "text"

    @property
    def name_in_text(self) -> str:
        return self.short or self.label


def _choices(*labels: str) -> tuple[Choice, ...]:
    return tuple(Choice(label, label) for label in labels)


SMALL_START = "작게 시작하는 기준이에요."
START_FIELDS: tuple[StartField, ...] = (
    StartField("goal", "끝났을 때 어떤 상태면 되나요?", "text", short="목표"),
    StartField("context", "판단에 필요한 상황", "text", short="상황"),
    StartField("boundary", "꼭 지킬 기준", "text", short="기준"),
    StartField(
        "deployment_target",
        "배포 범위",
        "choice",
        (
            Choice("local_demo", "로컬 데모"),
            Choice("small_group", "소수 사용자"),
            Choice("public_service", "공개 서비스"),
        ),
        default="small_group",
        why="작은 범위로 먼저 써 보는 것을 기준으로 해요.",
        rule_read=True,
    ),
    StartField(
        "has_gpu",
        "GPU 장비",
        "choice",
        (Choice("yes", "있어요"), Choice("no", "없어요")),
        default="no",
        why="GPU 없이 API로 시작하는 것을 기준으로 해요.",
        rule_read=True,
    ),
    StartField(
        "data_traits",
        "다루는 데이터",
        "multi",
        _choices("문서 검색 필요", "개인정보 포함", "표·수치 데이터", "특별한 것 없음"),
        default=("특별한 것 없음",),
        why="개인정보가 있으면 꼭 바꿔 주세요.",
        rule_read=True,
    ),
    StartField(
        "expected_users",
        "사용자 수",
        "choice",
        _choices("10명 이하", "10~100명", "100명 넘게"),
        free_text=True,
        default="10명 이하",
        why=SMALL_START,
    ),
    StartField(
        "team_size",
        "개발 인원",
        "choice",
        _choices("혼자", "2~3명", "4명 이상"),
        free_text=True,
        default="혼자",
        why=SMALL_START,
    ),
    StartField(
        "duration_weeks",
        "개발 기간",
        "choice",
        _choices("4주 이하", "5~8주", "9주 이상"),
        free_text=True,
        default="4주 이하",
        why=SMALL_START,
    ),
    StartField(
        "budget",
        "예산",
        "choice",
        _choices("무료로만", "월 5만원 이하", "월 5만원 넘게"),
        free_text=True,
        default="무료로만",
        why="비용이 없는 선택지부터 보는 기준이에요.",
    ),
    StartField(
        "weekly_hours",
        "주당 시간",
        "choice",
        _choices("10시간 이하", "10~20시간", "20시간 넘게"),
        free_text=True,
        default="10시간 이하",
        why=SMALL_START,
    ),
)
FIELDS = {field.name: field for field in START_FIELDS}
GCB_NAMES = tuple(field.name for field in START_FIELDS if field.is_gcb)
# The follow-up question goes to the blank that changes the most decisions.
ASK_ORDER = ("goal", "deployment_target", "has_gpu", "data_traits")
QUESTIONS = {
    "goal": "프로젝트가 끝났을 때 누가 무엇을 할 수 있게 되면 좋을까요?",
    "deployment_target": "어디까지 배포할 계획인가요? 로컬 데모, 소수 사용자, 공개 서비스 중에서요.",
    "has_gpu": "모델을 직접 실행할 GPU 장비가 있나요?",
    "data_traits": "다루는 데이터에 개인정보가 들어 있나요? 문서를 찾아 답하는 서비스인가요?",
}


def _tidy(text: str) -> str:
    return " ".join(text.split())


def _object_particle(word: str) -> str:
    last = word[-1] if word else ""
    if "가" <= last <= "힣":
        return "을" if (ord(last) - ord("가")) % 28 else "를"
    return "을"


def _check(field: StartField, change: StartChange) -> str | list[str] | None:
    """The value to store, or None when it does not fit the field."""
    if field.kind == "text":
        text = _tidy(change.value)
        return text if 0 < len(text) <= MAX_TEXT else None
    allowed = {choice.value for choice in field.choices}
    if field.kind == "multi":
        values = list(dict.fromkeys(_tidy(v) for v in change.values if v.strip()))
        return values if values and set(values) <= allowed else None
    value = _tidy(change.value)
    if value in allowed:
        return value
    if field.free_text and 0 < len(value) <= MAX_FREE:
        return value
    return None


def apply_start_changes(
    current: Mapping[str, StartValue],
    changes: list[StartChange],
    source: StartSource,
    focus: str | None = None,
) -> tuple[dict[str, StartValue], list[str], list[str]]:
    """The validator for what a model or a person sets. While a field is in focus, only it moves."""
    updated = dict(current)
    applied: list[str] = []
    rejected: list[str] = []
    for change in changes:
        field = FIELDS.get(change.field)
        if field is None:
            rejected.append(f"'{change.field}'은 채울 수 있는 칸이 아니에요.")
            continue
        if focus is not None and field.name != focus:
            continue
        value = _check(field, change)
        if value is None:
            rejected.append(f"{field.name_in_text}: 고를 수 있는 값이 아니라 그대로 뒀어요.")
            continue
        updated[field.name] = StartValue(value=value, source=source)
        applied.append(field.name_in_text)
    return updated, list(dict.fromkeys(applied)), rejected


def fill_defaults(current: Mapping[str, StartValue]) -> tuple[dict[str, StartValue], list[str]]:
    """Blank signal fields take the fixed small-start defaults; GCB fields are filled elsewhere."""
    updated = dict(current)
    labels = []
    for field in START_FIELDS:
        if field.is_gcb or field.name in updated or field.default is None:
            continue
        value = list(field.default) if isinstance(field.default, tuple) else field.default
        updated[field.name] = StartValue(value=value, source="default", why=field.why)
        labels.append(field.name_in_text)
    return updated, labels


def missing(current: Mapping[str, StartValue]) -> list[str]:
    return [field.name for field in START_FIELDS if field.name not in current]


def next_question(current: Mapping[str, StartValue]) -> str | None:
    blank = [name for name in ASK_ORDER if name not in current]
    return QUESTIONS[blank[0]] if blank else None


def reply_text(applied: list[str], current: Mapping[str, StartValue], focus: str | None) -> str:
    """Written by code, not the model: it only says what was filled and asks one question."""
    if applied and focus:
        name = FIELDS[focus].name_in_text
        head = f"{name}{_object_particle(name)} 고쳤어요."
    elif applied:
        head = f"{len(applied)}칸을 채웠어요."
    else:
        head = "이 문장에서는 채울 칸을 찾지 못했어요. 칸을 눌러 고르거나 다르게 말해 주세요."
    if not missing(current):
        return f"{head} 모두 채웠어요. 결정을 시작할 수 있어요."
    question = next_question(current)
    tail = question or "남은 칸은 '빈칸은 알아서 채워 주세요'로 채울 수 있어요."
    return f"{head} {tail}"


def start_from_draft(draft: Any) -> dict[str, StartValue]:
    """A GCB draft written from the idea alone counts as what the user said."""
    return {
        name: StartValue(value=_tidy(text), source="said")
        for name in GCB_NAMES
        if (text := getattr(draft, name, "")) and _tidy(text)
    }


def _label(field: StartField, value: str) -> str:
    return next((c.label for c in field.choices if c.value == value), value)


def display(field: StartField, value: str | list[str]) -> str:
    if isinstance(value, list):
        return ", ".join(_label(field, v) for v in value)
    return _label(field, value)


def _number_or_text(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def to_spec(current: Mapping[str, StartValue]) -> dict[str, Any]:
    """The GCB action that starts the journey. "따로 없음" and blanks stay unset."""
    texts = {}
    for name in GCB_NAMES:
        held = current.get(name)
        text = held.value if held and isinstance(held.value, str) else ""
        texts[name] = "" if text == NOTHING else text
    answers: dict[str, Any] = {}
    for field in START_FIELDS:
        held = current.get(field.name)
        if field.is_gcb or held is None:
            continue
        if field.name == "has_gpu":
            answers[field.name] = held.value == "yes"
        elif field.name in ("deployment_target", "budget", "data_traits"):
            answers[field.name] = held.value
        else:
            answers[field.name] = _number_or_text(str(held.value))
    return {"action": "gcb", **texts, "answers": answers}
