"""Snapshot checks, separate from service input. Semantic judgements remain human reviews."""

import re
from typing import Any, Literal

from app.journey.start import FIELDS
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    checkpoint: str = "initial"
    field: str
    policy: Literal["unknown", "default", "value", "present", "not_said", "excludes"]
    value: Any = None
    source: Literal["said", "picked", "default", "recommended"] | None = None

    @model_validator(mode="after")
    def known_field(self):
        if self.field not in FIELDS:
            raise ValueError(f"Unknown start field: {self.field}")
        if self.policy in {"value", "excludes"} and self.value is None:
            raise ValueError("value/excludes requires a value")
        return self


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    message: str = Field(min_length=1, max_length=2000)
    focus: str | None = None


class IntakeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    status: Literal["초안", "확정"]
    notion: str
    copied_on: str
    source_status: str
    evaluation: Literal["intake"]
    family: str
    variant: str
    idea: str = Field(min_length=10, max_length=3000)
    turns: list[Turn] = []
    answers: dict[str, str] = {}
    continue_to: str | None = None
    selection: dict[str, str] = {}
    must_ask: list[str] = []
    may_skip: list[str] = []
    checks: list[Check]
    human_review: list[str]

    @model_validator(mode="after")
    def references(self):
        ids = [t.id for t in self.turns]
        if len(set(ids)) != len(ids) or "initial" in ids or "final" in ids:
            raise ValueError("Turn ids must be unique, not initial/final")
        checkpoints = {"initial", "final", *ids}
        if self.continue_to:
            checkpoints.add(f"card:{self.continue_to}")
        if any(c.checkpoint not in checkpoints for c in self.checks):
            raise ValueError("Unknown checkpoint")
        if len({c.id for c in self.checks}) != len(self.checks):
            raise ValueError("Duplicate check id")
        if set(self.answers) - set(FIELDS):
            raise ValueError("Unknown answer field")
        return self


def equivalent(field, actual, expected):
    if field in {"expected_users", "team_size", "duration_weeks", "weekly_hours"}:
        unit = {
            "expected_users": "명",
            "team_size": "명",
            "duration_weeks": "주",
            "weekly_hours": "시간",
        }[field]

        def exact_number(value):
            match = re.fullmatch(r"(\d+)\s*(?:" + unit + r")?", str(value))
            return int(match[1]) if match else value

        return exact_number(actual) == exact_number(expected)
    return actual == expected


def evaluate(checks: list[dict], snapshots: dict) -> list[dict]:
    results = []
    for raw in checks:
        check = Check.model_validate(raw)
        snapshot = snapshots.get(check.checkpoint)
        if snapshot is None:
            results.append({"id": check.id, "status": "not_run", "checkpoint": check.checkpoint})
            continue
        held = snapshot["fields"].get(check.field)
        value = held.get("value") if held else None
        source = held.get("source") if held else None
        if check.policy == "unknown":
            passed = value is None and source is None
        elif check.policy == "default":
            default = FIELDS[check.field].default
            if isinstance(default, tuple):
                default = list(default)
            passed = (
                default is not None
                and value == default
                and source == "default"
                and bool(held.get("why"))
            )
        elif check.policy == "not_said":
            passed = source not in {"said", "picked"}
        elif check.policy == "excludes":
            passed = check.value not in (value if isinstance(value, list) else [value])
        elif check.policy == "present":
            passed = value not in (None, "", [])
        else:
            passed = equivalent(check.field, value, check.value)
        if check.source is not None:
            passed = passed and source == check.source
        if source in {"said", "default", "recommended"}:
            passed = passed and bool(held.get("why"))
        results.append(
            {
                "id": check.id,
                "status": "pass" if passed else "fail",
                "checkpoint": check.checkpoint,
                "actual": held,
            }
        )
    return results
