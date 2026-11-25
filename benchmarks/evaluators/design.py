"""Structural checks do not assert semantic requirement satisfaction."""

import hashlib
import io
import json
import zipfile

from app.journey.build_plan import plan_build
from app.journey.package import build_package
from app.journey.state import ProjectSpec


def design_checks(
    design,
    package=None,
    registry=None,
    idea=None,
    *,
    case=None,
    fixed_choices=True,
    final_spec=None,
):
    ids = {node.id for node in design.nodes}
    refs = all(e.source in ids and e.target in ids for e in design.workflow.edges)
    checks = [
        {"id": "node_references", "status": "pass" if refs else "fail"},
        {
            "id": "validation",
            "status": "not_run"
            if design.validation is None
            else "fail"
            if any(i.severity == "error" for i in design.validation or [])
            else "pass",
        },
    ]
    # Compare every downloaded file against this exact saved revision, not a keyword.
    status = "not_run"
    if package is not None:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            actual = {
                name.removeprefix("starter-pack/"): archive.read(name).decode()
                for name in archive.namelist()
            }
        expected = build_package(plan_build(design, registry, idea, project=final_spec))
        status = "pass" if actual == expected else "fail"
    checks.append(
        {
            "id": "package_matches_revision",
            "status": status,
            "design_revision": design.design_revision,
        }
    )
    if case is not None:
        given = ProjectSpec.model_validate(case["spec"])
        # The journey may fill blank info with card defaults, but never change what the case gave.
        spec = final_spec or given
        kept = all(getattr(spec, name) == getattr(given, name) for name in given.model_fields_set)
        digest = hashlib.sha256(
            json.dumps(spec.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        checks.append(
            {
                "id": "spec_snapshot",
                "status": "pass"
                if kept and digest == design.provenance.project_spec_hash
                else "fail",
            }
        )
        refs = {d.card_id: d for d in design.provenance.decisions}
        may_skip = set(case.get("may_skip", []))

        def chosen(card_id, option_id):
            ref = refs.get(card_id)
            if ref is not None and ref.by == "skipped":
                return card_id in may_skip
            return ref is not None and ref.option_id == option_id

        checks.append(
            {
                "id": "fixed_choices",
                "status": "not_run"
                if not fixed_choices
                else "pass"
                if all(chosen(k, v) for k, v in case["selection"].items())
                else "fail",
            }
        )
        if case.get("design_checks"):
            checks = [c for c in checks if c["id"] in case["design_checks"]]
    return checks
