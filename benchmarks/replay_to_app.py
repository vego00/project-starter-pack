"""Puts saved benchmark designs into a database the web app can open, without a model call.

Usage: uv run --locked python benchmarks/replay_to_app.py <picks.json> <database url>

picks.json maps a label to {"case": id, "report": report dir name, "run": n}. Each pick runs
the case's journey again with the card decisions the saved design was made under (its
provenance), skipping the cards that run skipped, and the designer hands back that design, so
the app checks it against the same decisions as the benchmark did. Card advice stays mock.
Each journey is owned by the local user, as the web app records it in local sign-in mode. The
output lists, per label, the journey id to open as /?journey=<id>. Use a scratch database, not
the one you work in.
"""

import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.journey.deciders.base import DeciderResult  # noqa: E402
from app.journey.deciders.mock import MockDecider  # noqa: E402
from app.journey.design_generator import DesignAttempt, DesignDraft  # noqa: E402
from app.journey.persistence import open_checkpointer  # noqa: E402
from app.journey.services import JourneyDeps  # noqa: E402
from app.main import LOCAL_USER  # noqa: E402
from app.owners import OwnerStore, PostgresOwners  # noqa: E402
from app.registry.loader import Registry, load_registry  # noqa: E402

from benchmarks.run import REPORTS_DIR, load_cases, run_flow  # noqa: E402


class ReplayDesigner:
    """Returns one saved design as if a model had just written it."""

    def __init__(self, design: dict):
        fields = {name: design[name] for name in DesignDraft.model_fields if name in design}
        self._attempt = DesignAttempt(
            draft=DesignDraft.model_validate(fields),
            model_id=design["provenance"].get("model_id") or "replay",
        )

    def draft(self, state, constraints, problems):
        return self._attempt


def saved_design(report: str, case: str, run: int) -> dict:
    results = json.loads((REPORTS_DIR / report / "results.json").read_text("utf-8"))["results"]
    for result in results:
        if result["case"] == case and result["run"] == run:
            artifact = result.get("artifact") or {}
            if artifact.get("provenance", {}).get("source") != "model":
                raise ValueError(f"{report} {case} run {run} has no model design")
            return artifact
    raise ValueError(f"{report} has no {case} run {run}")


def replay(
    case: dict, design: dict, registry: Registry, checkpointer: Any, owners: OwnerStore
) -> dict[str, Any]:
    """Runs the case again under the decisions the design was made with. A fresh run would pick
    the mock defaults instead (the benchmark took Jev's), and the validator would then judge the
    design against cards it was never written for."""
    decisions = design["provenance"]["decisions"]
    chosen = {d["card_id"]: d["option_id"] for d in decisions if d["option_id"] is not None}
    skipped = {d["card_id"] for d in decisions if d["by"] == "skipped"}
    sure = DeciderResult(answer="unneeded", confidence=1.0)
    deps = JourneyDeps(
        designer=ReplayDesigner(design),
        decider=MockDecider({f"select.{card_id}": sure for card_id in skipped}),
    )
    as_made = {**case, "selection": chosen, "evaluation": "design"}
    result = run_flow(as_made, deps, registry, checkpointer=checkpointer)
    owners.add(UUID(result["journey_id"]), LOCAL_USER)
    return result


def main(argv: list[str]) -> dict[str, dict]:
    picks = json.loads(Path(argv[0]).read_text("utf-8"))
    registry = load_registry()
    out: dict[str, dict] = {}
    with open_checkpointer(argv[1]) as saver:
        owners = PostgresOwners(saver.conn)
        owners.setup()
        for label, pick in picks.items():
            case = load_cases([pick["case"]])[0]
            design = saved_design(pick["report"], pick["case"], pick["run"])
            result = replay(case, design, registry, saver, owners)
            source = (result.get("design") or {}).get("source")
            out[label] = {"case": pick["case"], "journey_id": result["journey_id"]}
            out[label]["source"] = source
            print(f"{label}: {pick['case']} journey={result['journey_id']} design={source}")
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
