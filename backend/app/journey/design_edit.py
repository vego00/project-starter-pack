"""Applies a person's graph edits to a design, and carries them onto a regenerated one.

The backend validator decides what can be saved. Edits are found by comparing the design as it was
generated with the design as people left it, so several saves add up without separate bookkeeping.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.journey.design import (
    MAX_ITEMS,
    ChangeRequest,
    DesignState,
    Edge,
    ServiceDesign,
    Workflow,
)
from app.journey.design_constraints import DesignConstraints
from app.journey.design_validator import validate_design

MAX_REPORTED = 5
EDIT_SUMMARY = "그래프에서 직접 수정"
KEPT_AFTER_FAILURE = (
    "새 설계를 만들지 못해 직접 고친 이전 설계를 그대로 뒀어요. 바꾼 결정은 아직 반영되지 않았어요."
)


class DesignEdit(BaseModel):
    """What the graph screen can change. Everything else in the design stays as it was."""

    model_config = ConfigDict(extra="forbid")

    design_revision: int = Field(ge=1)
    nodes: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_ITEMS)
    workflow: Workflow
    requirement_nodes: dict[str, list[str]] = {}
    # Old id -> new id, so references the screen does not hold can follow a rename.
    renames: dict[str, str] = {}


class DesignEditError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("design edit rejected")
        self.problems = problems


def compose_renames(earlier: dict[str, str], later: dict[str, str]) -> dict[str, str]:
    """A rename of a renamed node still points from the original id."""
    merged = dict(earlier)
    for old, new in later.items():
        original = next((key for key, value in merged.items() if value == old), old)
        merged[original] = new
    return merged


def _merged_nodes(current: ServiceDesign, edit: DesignEdit) -> list[dict[str, Any]]:
    """Fields the screen does not show, such as a node's eval cases, stay with the node."""
    old = {node.id: node.model_dump(mode="json") for node in current.nodes}
    earlier = {new: former for former, new in edit.renames.items()}
    merged = []
    for raw in edit.nodes:
        node_id = raw.get("id")
        base = old.get(node_id) or old.get(earlier.get(node_id)) or {}
        node = {**base, **raw}
        if "model" in raw and "model" in base:
            node["model"] = {**base["model"], **raw["model"]}
        merged.append(node)
    return merged


def _merged_state_fields(
    current: ServiceDesign, renames: dict[str, str], ids: set[str]
) -> list[dict[str, Any]]:
    fields = []
    for field in current.state_fields:
        data = field.model_dump(mode="json")
        for side in ("writers", "readers"):
            # A rename that was undone leaves the old id in place, so it no longer applies.
            renamed = (
                node_id if node_id in ids else renames.get(node_id, node_id)
                for node_id in data[side]
            )
            data[side] = [node_id for node_id in renamed if node_id in ids]
        if data["writers"]:
            if len(data["writers"]) < 2:
                data["merge"] = None
            fields.append(data)
    return fields


def _contract_problem(error: dict[str, Any]) -> str:
    message = error["msg"]
    if "a core requirement needs a node" in message:
        return "핵심 요구사항을 맡을 노드가 없어요. 요구사항을 맡을 노드를 남겨 주세요."
    location = ".".join(str(part) for part in error["loc"])
    return f"{location} 항목의 형식을 확인해 주세요."


def _assemble(
    current: ServiceDesign,
    nodes: list[dict[str, Any]],
    workflow: dict[str, Any],
    requirement_nodes: dict[str, list[str]],
    renames: dict[str, str],
    **replaced: Any,
) -> ServiceDesign:
    ids = {node.get("id") for node in nodes}
    data = current.model_dump(mode="json")
    requirements = [
        {**item, "node_ids": requirement_nodes.get(item["id"], item["node_ids"])}
        for item in data["requirements"]
    ]
    payload = {
        **data,
        "nodes": nodes,
        "workflow": workflow,
        "requirements": requirements,
        "state_fields": _merged_state_fields(current, renames, ids),
        "validation": None,
        "confirmation": None,
        **replaced,
    }
    try:
        return ServiceDesign.model_validate(payload)
    except ValidationError as exc:
        problems = list(dict.fromkeys(_contract_problem(e) for e in exc.errors()))
        raise DesignEditError(problems[:MAX_REPORTED]) from None


def apply_design_edit(
    current: ServiceDesign, edit: DesignEdit, constraints: DesignConstraints
) -> ServiceDesign:
    """Returns the next revision, or raises with what must be fixed before it can be saved."""
    next_revision = current.design_revision + 1
    change = ChangeRequest(
        from_revision=current.design_revision,
        to_revision=next_revision,
        request=EDIT_SUMMARY,
        summary=EDIT_SUMMARY,
    )
    design = _assemble(
        current,
        _merged_nodes(current, edit),
        edit.workflow.model_dump(mode="json"),
        edit.requirement_nodes,
        edit.renames,
        design_revision=next_revision,
        change_requests=[
            *(item.model_dump(mode="json") for item in current.change_requests),
            change.model_dump(mode="json"),
        ],
    )
    issues = validate_design(design, constraints)
    errors = [issue.message for issue in issues if issue.severity == "error"]
    if errors:
        raise DesignEditError(errors[:MAX_REPORTED])
    return design.model_copy(update={"validation": issues})


def _error_count(design: ServiceDesign, constraints: DesignConstraints) -> int:
    return sum(issue.severity == "error" for issue in validate_design(design, constraints))


def _if_no_worse(
    design: ServiceDesign,
    constraints: DesignConstraints,
    nodes: list[dict[str, Any]],
    workflow: dict[str, Any],
    requirement_nodes: dict[str, list[str]],
    renames: dict[str, str],
) -> ServiceDesign | None:
    """The design with this change, or None if it breaks the contract or adds a rule error."""
    limit = _error_count(design, constraints)
    try:
        candidate = _assemble(design, nodes, workflow, requirement_nodes, renames)
    except DesignEditError:
        return None
    issues = validate_design(candidate, constraints)
    if sum(issue.severity == "error" for issue in issues) > limit:
        return None
    return candidate.model_copy(update={"validation": issues})


def _dumped(design: ServiceDesign) -> list[dict[str, Any]]:
    return [node.model_dump(mode="json") for node in design.nodes]


def _edge_key(edge: Edge) -> tuple[str, str]:
    return edge.source, edge.target


def _with_node_edits(
    design: ServiceDesign,
    base: ServiceDesign,
    edited: ServiceDesign,
    constraints: DesignConstraints,
) -> tuple[ServiceDesign, list[str]]:
    """One node at a time, so a node that no longer fits does not cost the others."""
    before = {node.id: node for node in base.nodes}
    skipped = []
    for node in edited.nodes:
        if node.id not in before or node == before[node.id]:
            continue
        ids = {item.id for item in design.nodes}
        nodes = [
            node.model_dump(mode="json") if item["id"] == node.id else item
            for item in _dumped(design)
        ]
        candidate = (
            _if_no_worse(
                design, constraints, nodes, design.workflow.model_dump(mode="json"), {}, {}
            )
            if node.id in ids
            else None
        )
        if candidate is None:
            skipped.append(node.id)
        else:
            design = candidate
    return design, skipped


def _with_structure_edits(
    design: ServiceDesign,
    base: ServiceDesign,
    edited: ServiceDesign,
    renames: dict[str, str],
    constraints: DesignConstraints,
) -> tuple[ServiceDesign, bool]:
    """Added and removed parts go together: a new node is useless without its connections."""
    base_ids = {node.id for node in base.nodes}
    edited_ids = {node.id for node in edited.nodes}
    added, removed = edited_ids - base_ids, base_ids - edited_ids
    base_edges = {_edge_key(edge): edge for edge in base.workflow.edges}
    edited_edges = {_edge_key(edge): edge for edge in edited.workflow.edges}
    flow = design.workflow
    same_ends = base.workflow.entry == edited.workflow.entry and set(base.workflow.exits) == set(
        edited.workflow.exits
    )
    if not added and not removed and base_edges == edited_edges and same_ends:
        return design, True

    nodes = [item for item in _dumped(design) if item["id"] not in removed]
    nodes += [node.model_dump(mode="json") for node in edited.nodes if node.id in added]
    known = {item["id"] for item in nodes}
    gone = set(base_edges) - set(edited_edges)
    edges = {
        _edge_key(edge): edge
        for edge in flow.edges
        if edge.source in known and edge.target in known and _edge_key(edge) not in gone
    }
    for edge_key, edge in edited_edges.items():
        if base_edges.get(edge_key) != edge and edge.source in known and edge.target in known:
            edges[edge_key] = edge
    entry = (
        edited.workflow.entry
        if edited.workflow.entry != base.workflow.entry or flow.entry in removed
        else flow.entry
    )
    exits = (
        list(edited.workflow.exits)
        if set(edited.workflow.exits) != set(base.workflow.exits)
        else [item for item in flow.exits if item not in removed]
    )
    limits = [
        {**limit.model_dump(mode="json"), "node_ids": kept}
        for limit in flow.loop_limits
        if (kept := [item for item in limit.node_ids if item not in removed])
        and limit.on_exceeded not in removed
    ]
    owners = {item.id: item.node_ids for item in edited.requirements}
    requirement_nodes = {
        item.id: [
            *(node_id for node_id in item.node_ids if node_id not in removed),
            *(node_id for node_id in owners.get(item.id, []) if node_id in added),
        ]
        for item in design.requirements
    }
    workflow = {
        **flow.model_dump(mode="json"),
        "entry": entry,
        "exits": exits,
        "edges": [edge.model_dump(mode="json") for edge in edges.values()],
        "loop_limits": limits,
    }
    candidate = _if_no_worse(design, constraints, nodes, workflow, requirement_nodes, renames)
    return (design, False) if candidate is None else (candidate, True)


def keep_human_edits(
    previous: DesignState, fresh: DesignState, constraints: DesignConstraints
) -> DesignState:
    """Puts what people changed onto a regenerated design, and says what could not be kept."""
    if previous.generated is None or previous.current is None or fresh.current is None:
        return fresh
    if fresh.status == "failed":
        return previous.model_copy(update={"status": "failed", "error": KEPT_AFTER_FAILURE})

    base, edited = previous.generated, previous.current
    design, skipped = _with_node_edits(fresh.current, base, edited, constraints)
    design, structure_kept = _with_structure_edits(
        design, base, edited, previous.human_renames, constraints
    )
    warnings = [
        f"직접 고친 노드 {node_id}는 새 설계와 맞지 않아 적용하지 못했어요." for node_id in skipped
    ]
    if not structure_kept:
        warnings.append("직접 바꾼 노드 추가·삭제나 연결은 새 설계와 맞지 않아 적용하지 못했어요.")
    design = design.model_copy(update={"warnings": [*design.warnings, *warnings][:MAX_ITEMS]})
    return fresh.model_copy(
        update={
            "current": design,
            "generated": fresh.current,
            "human_renames": previous.human_renames if structure_kept else {},
        }
    )
