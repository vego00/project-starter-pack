from copy import deepcopy
from datetime import UTC, datetime

import pytest
from app.journey.design import ServiceDesign, Unknown
from app.journey.design_constraints import DesignConstraints, TargetServiceConstraints
from app.journey.design_validator import validate_design

NOW = datetime(2026, 11, 5, tzinfo=UTC)
DECISIONS = [
    {"card_id": "agent.topology", "card_version": 2, "option_id": "pipeline", "by": "user"},
    {"card_id": "model.provider", "card_version": 2, "option_id": "gemini", "by": "user"},
]


def node(node_id, kind="code", inputs=(), outputs=(), tools=()):
    fields = {
        "id": node_id,
        "kind": kind,
        "responsibility": f"{node_id} 역할",
        "inputs": [{"name": name, "type": "str"} for name in inputs],
        "outputs": [{"name": name, "type": "str"} for name in outputs],
        "tools": [{"name": name, "access": access, "reason": "필요"} for name, access in tools],
        "done_when": "끝남",
        "on_failure": "실패 경로로 보낸다",
    }
    if kind == "agent":
        fields["model"] = {"capability": "답변", "provider_scope": "gemini"}
    return fields


def valid_design():
    """A pipeline with one bounded retry loop. Every rule's fixture is one defect away from it."""
    return {
        "design_revision": 1,
        "provenance": {
            "journey_revision": 3,
            "project_spec_hash": "a" * 64,
            "decisions": deepcopy(DECISIONS),
            "generated_at": NOW,
            "source": "model",
            "model_id": "test-model",
            "prompt_version": "design-v1",
        },
        "requirements": [
            {
                "id": "R-1",
                "problem": "강의 내용을 찾지 못한다",
                "success_example": "질문하면 출처와 함께 답한다",
                "input": "질문",
                "expected_output": "출처가 붙은 답",
                "evidence": "강의 자료를 찾아 답하는",
                "core": True,
                "node_ids": ["answer"],
                "output": "draft",
                "eval_case_ids": ["E-1"],
                "task_ids": ["T-1"],
            }
        ],
        "nodes": [
            node("intake", inputs=["question"], outputs=["clean"]),
            node("answer", "agent", inputs=["clean", "feedback"], outputs=["draft"]),
            node("grade", inputs=["draft"], outputs=["feedback", "final"]),
            node("publish", inputs=["final"], outputs=["result"]),
            node("give_up", inputs=["draft"], outputs=["apology"]),
        ],
        "workflow": {
            "entry": "intake",
            "exits": ["publish", "give_up"],
            "edges": [
                {"source": "intake", "target": "answer"},
                {"source": "answer", "target": "grade"},
                {"source": "grade", "target": "answer", "condition": "출처 없음"},
                {"source": "grade", "target": "publish", "condition": "출처 있음"},
            ],
            "loop_limits": [
                {"node_ids": ["answer", "grade"], "max_iterations": 3, "on_exceeded": "give_up"}
            ],
            "max_model_calls": 6,
        },
        "state_fields": [
            {"name": "clean", "type": "str", "writers": ["intake"], "readers": ["answer"],
             "lifetime": "run"},
        ],
        "eval_cases": [{"id": "E-1", "given": "강의 질문", "expect": "출처가 있다"}],
        "tasks": [
            {"id": "T-1", "title": "답변 노드", "inputs": "예시 질문", "produces": "함수",
             "verify_by": "예시 질문에 출처가 붙는다"},
            {"id": "T-2", "title": "채점 노드", "inputs": "답변", "produces": "함수",
             "verify_by": "출처 없는 답을 되돌린다", "depends_on": ["T-1"]},
        ],
        "reasons": [
            {"text": "단계가 고정적이다", "requirement_ids": ["R-1"], "card_ids": ["agent.topology"]}
        ],
    }  # fmt: skip


def constraints(**target):
    limits = {
        "min_agent_nodes": 1,
        "max_agent_nodes": None,
        "routing": "fixed",
        "human_checks": [],
        "allowed_providers": ["gemini"],
        **target,
    }
    return DesignConstraints(
        decisions=DECISIONS,
        target=TargetServiceConstraints(**limits),
        unknowns=[],
        warnings=[],
        out_of_scope=[],
    )


def issues(fields, limits=None):
    return validate_design(ServiceDesign(**fields), limits or constraints())


def rules(fields, limits=None):
    return {issue.rule_id for issue in issues(fields, limits)}


def by_id(fields, node_id):
    return next(item for item in fields["nodes"] if item["id"] == node_id)


def changed(change):
    fields = valid_design()
    change(fields)
    return fields


def test_a_sound_design_has_no_issues():
    assert issues(valid_design()) == []


def test_validating_twice_gives_the_same_answer():
    assert issues(changed(lambda d: d["nodes"].append(node("intake")))) == issues(
        changed(lambda d: d["nodes"].append(node("intake")))
    )


# Each change adds one defect, and only that rule may fire.


def duplicate_node(d):
    d["nodes"].append(node("publish", inputs=["final"], outputs=["result"]))


def retarget_edge(d):
    d["workflow"]["edges"][0]["target"] = "ghost"


def drop_loop_limit(d):
    d["workflow"]["loop_limits"] = []


def trap_loop_limit(d):
    d["workflow"]["loop_limits"][0]["on_exceeded"] = "grade"


def add_unreachable_node(d):
    d["nodes"].append(node("orphan", inputs=["question"]))
    d["workflow"]["exits"].append("orphan")


def add_dead_end(d):
    d["nodes"].append(node("dead_end", inputs=["draft"]))
    d["workflow"]["edges"].append({"source": "grade", "target": "dead_end"})


def add_unconnected_input(d):
    by_id(d, "publish")["inputs"].append({"name": "missing", "type": "str"})


def change_input_type(d):
    by_id(d, "publish")["inputs"][0]["type"] = "int"


def change_field_type(d):
    d["state_fields"][0]["type"] = "int"


def writer_without_output(d):
    d["state_fields"][0]["writers"] = ["give_up"]
    by_id(d, "intake")["outputs"] = []


def reader_without_input(d):
    d["state_fields"][0]["readers"].append("publish")


def output_field_without_writing_it(d):
    by_id(d, "publish")["outputs"].append({"name": "clean", "type": "str"})


def produce_nothing_required(d):
    d["requirements"][0]["output"] = "something_else"


def reorder_tasks(d):
    d["tasks"].reverse()


def set_no_model_calls(d):
    d["workflow"]["max_model_calls"] = 0


def foreign_provider(d):
    by_id(d, "answer")["model"]["provider_scope"] = "openai"


def foreign_fallback(d):
    by_id(d, "answer")["model"]["fallback_scope"] = "openai"


def other_decision(d):
    d["provenance"]["decisions"][0]["option_id"] = "single"


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (duplicate_node, "ref.duplicate_id"),
        (retarget_edge, "ref.unknown"),
        (drop_loop_limit, "loop.no_limit"),
        (trap_loop_limit, "loop.no_way_out"),
        (add_unreachable_node, "graph.unreachable"),
        (add_dead_end, "graph.no_exit"),
        (add_unconnected_input, "io.unconnected"),
        (change_input_type, "io.type_mismatch"),
        (change_field_type, "io.type_mismatch"),
        (writer_without_output, "owner.writer_has_no_output"),
        (reader_without_input, "owner.reader_has_no_input"),
        (output_field_without_writing_it, "owner.unlisted_writer"),
        (produce_nothing_required, "trace.output_not_produced"),
        (reorder_tasks, "task.out_of_order"),
        (set_no_model_calls, "limit.no_model_calls"),
        (foreign_provider, "decision.provider_out_of_scope"),
        (foreign_fallback, "decision.provider_out_of_scope"),
        (other_decision, "provenance.decisions_changed"),
    ],
)
def test_a_defect_is_reported_as_an_error(change, rule):
    found = issues(changed(change))

    assert rule in {issue.rule_id for issue in found}
    assert any(issue.severity == "error" for issue in found if issue.rule_id == rule)


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (produce_nothing_required, "trace.output_not_produced"),
        (reorder_tasks, "task.out_of_order"),
        (set_no_model_calls, "limit.no_model_calls"),
        (foreign_provider, "decision.provider_out_of_scope"),
        (other_decision, "provenance.decisions_changed"),
        (reader_without_input, "owner.reader_has_no_input"),
        (output_field_without_writing_it, "owner.unlisted_writer"),
    ],
)
def test_a_single_defect_does_not_set_off_other_rules(change, rule):
    assert rules(changed(change)) == {rule}


@pytest.mark.parametrize(
    ("location", "edit"),
    [
        ("requirement node", lambda d: d["requirements"][0]["node_ids"].append("ghost")),
        ("requirement case", lambda d: d["requirements"][0]["eval_case_ids"].append("ghost")),
        ("requirement task", lambda d: d["requirements"][0]["task_ids"].append("ghost")),
        ("entry", lambda d: d["workflow"].update(entry="ghost")),
        ("exit", lambda d: d["workflow"]["exits"].append("ghost")),
        ("limit exit", lambda d: d["workflow"]["loop_limits"][0].update(on_exceeded="ghost")),
        ("field writer", lambda d: d["state_fields"][0].update(writers=["ghost"])),
        ("field reader", lambda d: d["state_fields"][0]["readers"].append("ghost")),
        ("task", lambda d: d["tasks"][1]["depends_on"].append("ghost")),
        ("reason requirement", lambda d: d["reasons"][0]["requirement_ids"].append("ghost")),
        ("reason card", lambda d: d["reasons"][0]["card_ids"].append("ghost")),
        ("node case", lambda d: by_id(d, "grade").update(eval_case_ids=["ghost"])),
    ],
)
def test_every_kind_of_reference_is_checked(location, edit):
    found = issues(changed(edit))

    assert any(issue.rule_id == "ref.unknown" and "ghost" in issue.message for issue in found)


def test_a_broken_design_never_crashes_the_validator():
    def wreck(d):
        d["workflow"].update(entry="ghost", exits=["ghost"])
        d["workflow"]["edges"] = [{"source": "ghost", "target": "ghost"}]
        d["requirements"][0]["node_ids"] = ["ghost"]

    assert any(issue.severity == "error" for issue in issues(changed(wreck)))


# Graph shape


def test_a_self_loop_counts_as_a_loop():
    fields = changed(
        lambda d: d["workflow"]["edges"].append({"source": "publish", "target": "publish"})
    )

    assert "loop.no_limit" in rules(fields)


def test_an_over_limit_exit_is_a_real_way_out():
    def only_leaves_through_the_limit(d):
        d["workflow"]["edges"] = [
            {"source": "intake", "target": "answer"},
            {"source": "answer", "target": "grade"},
            {"source": "grade", "target": "answer"},
        ]
        d["workflow"]["exits"] = ["give_up"]
        d["nodes"] = [item for item in d["nodes"] if item["id"] != "publish"]

    assert "graph.no_exit" not in rules(changed(only_leaves_through_the_limit))


def test_two_separate_loops_each_need_a_limit():
    def second_loop(d):
        d["nodes"].append(node("polish", inputs=["final"]))
        d["workflow"]["edges"] += [
            {"source": "publish", "target": "polish"},
            {"source": "polish", "target": "publish"},
        ]

    found = [i for i in issues(changed(second_loop)) if i.rule_id == "loop.no_limit"]

    assert len(found) == 1
    assert "polish" in found[0].message


def test_the_entry_may_take_inputs_from_outside():
    assert "io.unconnected" not in rules(valid_design())


def test_a_value_can_only_come_from_upstream():
    def read_from_a_later_node(d):
        by_id(d, "answer")["inputs"].append({"name": "result", "type": "str"})

    assert "io.unconnected" in rules(changed(read_from_a_later_node))


# Decisions limit the design


def agents_only(count):
    def change(d):
        d["nodes"] = [
            node("only", "agent", inputs=["question"], outputs=[f"out{i}" for i in range(count)]),
        ]
        d["workflow"] = {"entry": "only", "exits": ["only"], "edges": [], "max_model_calls": 1}
        d["state_fields"] = []
        d["requirements"][0].update(node_ids=["only"], output="out0")

    return change


def test_rules_only_allows_no_agent():
    assert "decision.too_many_agents" in rules(
        valid_design(), constraints(min_agent_nodes=0, max_agent_nodes=0, allowed_providers=[])
    )


def test_a_single_agent_design_cannot_grow_a_second_agent():
    fields = changed(lambda d: by_id(d, "grade").update(
        kind="agent", model={"capability": "채점", "provider_scope": "gemini"}
    ))  # fmt: skip

    assert "decision.too_many_agents" in rules(
        fields, constraints(min_agent_nodes=1, max_agent_nodes=1)
    )


def test_a_supervisor_needs_at_least_two_agents():
    assert "decision.too_few_agents" in rules(
        valid_design(), constraints(min_agent_nodes=2, routing="model")
    )


def test_the_pipeline_limit_has_no_upper_bound():
    assert "decision.too_many_agents" not in rules(valid_design())


def add_human(d):
    d["nodes"].append(node("approve", "human", inputs=["final"], outputs=["ok"]))
    d["workflow"]["edges"] = [
        edge for edge in d["workflow"]["edges"] if edge["target"] != "publish"
    ] + [
        {"source": "grade", "target": "approve", "condition": "출처 있음"},
        {"source": "approve", "target": "publish", "condition": "승인"},
        {"source": "approve", "target": "answer", "condition": "거절"},
    ]


def test_a_chosen_human_check_must_exist():
    assert "decision.missing_human_check" in rules(
        valid_design(), constraints(human_checks=["approval"])
    )


def test_no_human_check_means_none_in_the_target_service():
    assert "decision.unwanted_human_check" in rules(changed(add_human))


def test_a_chosen_human_check_is_satisfied():
    limits = constraints(human_checks=["approval"])

    assert issues(changed(add_human), limits) == []


def test_an_undecided_card_adds_no_limit():
    limits = constraints(
        min_agent_nodes=None, human_checks=None, allowed_providers=None, routing=None
    )

    assert issues(changed(lambda d: by_id(d, "answer")["model"].update(provider_scope="x")),
                  limits) == []  # fmt: skip


def give_write_tool(d):
    by_id(d, "publish")["tools"].append(
        {"name": "send", "access": "external_write", "reason": "전송"}
    )


def test_writing_before_a_chosen_approval_is_an_error():
    def write_before_approving(d):
        add_human(d)
        by_id(d, "grade")["tools"].append(
            {"name": "send", "access": "external_write", "reason": "전송"}
        )

    found = issues(changed(write_before_approving), constraints(human_checks=["approval"]))

    assert [(i.rule_id, i.severity) for i in found] == [
        ("permission.write_without_approval", "error")
    ]


def test_saving_inside_the_service_before_approval_passes():
    def save_before_approving(d):
        add_human(d)
        by_id(d, "grade")["tools"].append({"name": "save", "access": "write", "reason": "기록"})

    assert issues(changed(save_before_approving), constraints(human_checks=["approval"])) == []


def test_writing_after_approval_passes():
    def write_after_approving(d):
        add_human(d)
        give_write_tool(d)

    assert issues(changed(write_after_approving), constraints(human_checks=["approval"])) == []


def test_a_branch_without_a_condition_is_a_warning():
    def unlabel(d):
        d["workflow"]["edges"][2].pop("condition")

    found = issues(changed(unlabel))

    assert [(i.rule_id, i.severity) for i in found] == [("branch.unlabelled", "warning")]


def test_a_supervisor_without_a_branch_is_a_warning():
    def straight_line(d):
        d["workflow"]["edges"] = [
            {"source": "intake", "target": "answer"},
            {"source": "answer", "target": "grade"},
            {"source": "grade", "target": "publish"},
            {"source": "publish", "target": "give_up"},
        ]
        d["workflow"]["loop_limits"] = []
        d["workflow"]["exits"] = ["give_up"]
        by_id(d, "answer")["inputs"] = [{"name": "clean", "type": "str"}]

    routed = constraints(min_agent_nodes=1, routing="model")

    assert rules(changed(straight_line), routed) == {"branch.no_routing"}
    assert "branch.no_routing" not in rules(valid_design(), routed)


def test_an_approval_without_a_rejection_path_is_a_warning():
    def no_rejection(d):
        add_human(d)
        d["workflow"]["edges"] = [e for e in d["workflow"]["edges"] if e.get("condition") != "거절"]

    found = issues(changed(no_rejection), constraints(human_checks=["approval"]))

    assert [(i.rule_id, i.severity) for i in found] == [("branch.no_rejection", "warning")]


def test_writing_without_any_human_check_chosen_is_a_warning():
    found = issues(changed(give_write_tool))

    assert [(i.rule_id, i.severity) for i in found] == [
        ("permission.write_without_approval", "warning")
    ]


def test_reading_needs_no_approval():
    def give_read_tool(d):
        by_id(d, "publish")["tools"].append({"name": "search", "access": "read", "reason": "검색"})

    assert issues(changed(give_read_tool)) == []


def test_an_unset_call_limit_is_only_a_warning():
    found = issues(changed(lambda d: d["workflow"].update(max_model_calls=None)))

    assert [(i.rule_id, i.severity) for i in found] == [("limit.no_model_call_limit", "warning")]


def test_a_design_without_agents_needs_no_call_limit():
    def code_only(d):
        by_id(d, "answer").update(kind="code")
        by_id(d, "answer").pop("model")
        d["workflow"]["max_model_calls"] = None

    limits = constraints(min_agent_nodes=0, max_agent_nodes=0, allowed_providers=[])

    assert issues(changed(code_only), limits) == []


def test_an_agent_no_requirement_needs_is_flagged():
    def spare_agent(d):
        by_id(d, "grade").update(
            kind="agent", model={"capability": "채점", "provider_scope": "gemini"}
        )

    found = [i for i in issues(changed(spare_agent)) if i.rule_id == "trace.unjustified_agent"]

    assert [i.severity for i in found] == ["warning"]
    assert "grade" in found[0].message


# Unknowns from the decisions stay visible


BLOCKING = Unknown(text="아직 정하지 않은 결정: Agent 구조", blocks_confirmation=True)


def with_unknowns(*unknowns):
    limits = constraints().model_dump()
    limits["unknowns"] = list(unknowns)
    return DesignConstraints(**limits)


def test_a_design_cannot_drop_an_unknown():
    assert rules(valid_design(), with_unknowns(BLOCKING)) == {"unknown.dropped"}


def test_a_design_cannot_soften_a_blocking_unknown():
    softened = {"text": BLOCKING.text, "blocks_confirmation": False}
    fields = changed(lambda d: d.update(unknowns=[softened]))

    assert rules(fields, with_unknowns(BLOCKING)) == {"unknown.dropped"}


def test_a_carried_unknown_passes_and_still_blocks_confirmation():
    fields = changed(lambda d: d.update(unknowns=[BLOCKING.model_dump()], validation=[]))

    assert issues(fields, with_unknowns(BLOCKING)) == []
    assert "blocking_unknowns" in ServiceDesign(**fields).confirm_blockers


def test_validation_errors_block_confirmation_and_warnings_do_not():
    design = ServiceDesign(**changed(foreign_provider))
    design = design.model_copy(update={"validation": validate_design(design, constraints())})
    assert "validation_errors" in design.confirm_blockers

    design = ServiceDesign(**changed(give_write_tool))
    design = design.model_copy(update={"validation": validate_design(design, constraints())})
    assert design.confirm_blockers == []


def add_vector_tool(d):
    by_id(d, "answer")["tools"] = [
        {"name": "search_idea", "access": "read", "reason": "pgvector로 비슷한 메모를 찾는다"}
    ]


def add_embedding_task(d):
    d["tasks"][0]["produces"] = "메모 임베딩 테이블"


@pytest.mark.parametrize("change", [add_vector_tool, add_embedding_task])
def test_semantic_search_without_a_chosen_vector_store_is_an_error(change):
    found = issues(changed(change), constraints(vector_store="none"))

    assert [(i.rule_id, i.severity) for i in found] == [
        ("decision.vector_store_not_chosen", "error")
    ]


def test_semantic_search_is_fine_when_a_vector_store_was_chosen_or_not_asked():
    fields = changed(add_vector_tool)

    assert issues(fields, constraints(vector_store="pgvector")) == []
    assert issues(fields) == []


def test_a_responsibility_that_mentions_vectors_is_not_read():
    fields = valid_design()
    by_id(fields, "answer")["responsibility"] = "벡터 검색 없이 태그로 메모를 찾는다"

    assert issues(fields, constraints(vector_store="none")) == []
