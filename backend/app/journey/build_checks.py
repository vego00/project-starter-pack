"""Consistency rules between the card choices, the design and the project (ADR-026 step 2).

Pure and deterministic. The no-result evaluation rule is a warning, not an error: 212 of 299
saved model designs (2026-11-25) broke it, so as an error it would turn most first drafts into
retries before the design prompt asks for such a case; the bundle's search defaults tell the
builder to add one. Each rule says where its finding goes: `design` is an error the design
can fix, so the validator sends it back to the model; `ask` is a question for the user, listed
under the bundle's remaining decisions; `note` is a warning shown in the bundle. A design that
still breaks a `design` rule (one saved before the rule existed) gets it as a question too.
Word lists are plain substrings, checked on lower-cased text.
"""

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.journey.design import ServiceDesign
from app.journey.state import ProjectSpec

EXTERNAL_PROVIDERS = {"gemini", "openai", "upstage", "exaone", "openrouter"}
VECTOR_WORDS = ("pgvector", "qdrant", "chroma", "embedding", "vector", "임베딩", "벡터")
SEARCH_WORDS = ("search", "retriev", "검색")
EMPTY_WORDS = ("찾지 못", "못 찾", "결과가 없", "결과 없", "없다고", "없음을", "해당 없", "관련 없",
               "no result", "not found", "0건", "빈 결과", "빈 목록")  # fmt: skip
# A case whose input has nothing to find, whatever it then expects (an answer or a handover).
NOTHING_GIVEN = ("없는", "없음", "모르는", "관련 없", "답하기 어려운", "존재하지 않")
SERVING_WORDS = ("ollama", "vllm", "로컬 모델", "직접 띄", "임베딩", "embedding")
AUTH_WORDS = ("인증", "로그인", "auth", "토큰", "token", "권한", "login", "계정")
DEPLOY_WORDS = ("배포", "deploy", "gcp", "aws", "cloud run", "클라우드")


class BuildIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    severity: Literal["error", "warning"]
    route: Literal["design", "ask", "note"]
    message: str
    recommendation: str | None = None


def _has(text: str, words: Iterable[str]) -> str | None:
    lowered = text.lower()
    return next((word for word in words if word in lowered), None)


def _built(design: ServiceDesign) -> list[tuple[str, str]]:
    """Tools and tasks: what gets built. A responsibility may say what a node does without."""
    return [
        (f"노드 {node.id}의 도구 {tool.name}", f"{tool.name} {tool.reason}")
        for node in design.nodes
        for tool in node.tools
    ] + [
        (f"개발 작업 {task.id}", f"{task.title} {task.inputs} {task.produces} {task.verify_by}")
        for task in design.tasks
    ]


def _everything(design: ServiceDesign) -> str:
    parts = [
        f"{r.problem} {r.expected_output or ''} {r.success_example}" for r in design.requirements
    ]
    parts += [f"{n.id} {n.responsibility} {n.done_when}" for n in design.nodes]
    parts += [text for _, text in _built(design)]
    return " ".join(parts)


def design_issues(design: ServiceDesign, chosen: Mapping[str, str | None]) -> list[BuildIssue]:
    """The rules a new draft can fix. The validator reports these as errors."""
    found: list[BuildIssue] = []
    if chosen.get("data.vector_store") == "none":
        for where, text in _built(design):
            if word := _has(text, VECTOR_WORDS):
                found.append(BuildIssue(
                    rule_id="decision.vector_store_not_chosen", severity="error", route="design",
                    message=f"검색 저장소를 '없음'으로 골랐는데 {where}가 벡터 검색을 써요: {word}",
                ))  # fmt: skip
        for unknown in design.unknowns:
            if word := _has(unknown.text, VECTOR_WORDS):
                found.append(BuildIssue(
                    rule_id="decision.vector_store_reopened", severity="error", route="design",
                    message="검색 저장소를 '없음'으로 정했는데 미확인 사항에서 벡터 저장소를 다시 "
                    f"물어요: {word}",
                ))  # fmt: skip
    searches = chosen.get("data.vector_store") not in (None, "none") or any(
        _has(text, SEARCH_WORDS) for _, text in _built(design)
    )
    covered = any(
        _has(case.expect, EMPTY_WORDS) or _has(case.given, NOTHING_GIVEN)
        for case in design.eval_cases
    )
    if searches and not covered:
        found.append(BuildIssue(
            rule_id="eval.no_empty_result_case", severity="warning", route="note",
            message="검색하는 설계인데 찾을 것이 없을 때 없다고 답하는 평가 사례가 없어요",
        ))  # fmt: skip
    return found


def _many_users(project: ProjectSpec | None) -> bool:
    if project is None:
        return False
    users = project.expected_users
    return project.deployment_target in ("small_group", "public_service") or (
        isinstance(users, int) and users > 1
    )


def build_issues(
    design: ServiceDesign, chosen: Mapping[str, str | None], project: ProjectSpec | None = None
) -> list[BuildIssue]:
    """Every rule: the design ones plus those about the bundle and the project."""
    found = design_issues(design, chosen)
    text = _everything(design)
    store = chosen.get("data.vector_store")
    if store not in (None, "none") and not _has(
        " ".join(t for _, t in _built(design)), (*VECTOR_WORDS, *SEARCH_WORDS)
    ):
        found.append(BuildIssue(
            rule_id="decision.vector_store_unused", severity="warning", route="note",
            message="검색 저장소를 골랐는데 설계의 도구와 작업에 검색이 없어요. 검색을 만들지 않으면 "
            "검색 저장소 컨테이너를 띄우지 않아요.",
        ))  # fmt: skip
    serving = chosen.get("mlops.model_serving")
    if chosen.get("model.provider") in EXTERNAL_PROVIDERS and serving in ("ollama", "vllm"):
        if not _has(text, SERVING_WORDS):
            found.append(BuildIssue(
                rule_id="decision.serving_unused", severity="warning", route="note",
                message=f"외부 모델 제공자와 {serving} 서빙을 함께 골랐는데 설계에서 {serving}을 "
                "쓰는 곳이 없어요. 남은 결정의 '모델 제공자와 모델 서빙의 역할'에서 정해요.",
            ))  # fmt: skip
    web = chosen.get("product.surface") == "web"
    if web and _many_users(project) and not _has(text, AUTH_WORDS):
        found.append(BuildIssue(
            rule_id="access.many_users_no_login", severity="error", route="ask",
            message="여러 사람이 쓰는 웹 서비스인데 누가 어떻게 들어오는지(로그인, 권한)가 "
            "설계에 없어요. 사용자는 어떻게 구분할까요?",
            recommendation="사용자마다 로그인이나 개인 토큰으로 구분하고, 자기 데이터만 보게 합니다.",
        ))  # fmt: skip
    if chosen.get("cloud.target") not in (None, "local"):
        for where, task_text in _built(design):
            # "로컬 또는 클라우드" still allows a local first build.
            local = "로컬" in task_text or "local" in task_text.lower()
            if (
                where.startswith("개발 작업")
                and not local
                and (word := _has(task_text, DEPLOY_WORDS))
            ):
                found.append(BuildIssue(
                    rule_id="deploy.in_first_build", severity="warning", route="note",
                    message=f"{where}에 배포 작업({word})이 있어요. 첫 빌드는 이 컴퓨터에서 "
                    "끝내고, 배포는 '배포 (나중)'에서 해요.",
                ))  # fmt: skip
    if chosen.get("backend.implementation") == "n8n" and chosen.get("backend.execution") in (
        "background", "queue"
    ):  # fmt: skip
        found.append(BuildIssue(
            rule_id="n8n.own_executions", severity="warning", route="note",
            message="n8n은 workflow 실행을 스스로 관리해요. 작업 실행 카드의 큐와 워커는 만들지 "
            "않아요. 실행이 많아지면 배포 때 n8n의 queue 모드를 정해요.",
        ))  # fmt: skip
    return found
