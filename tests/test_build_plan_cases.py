"""Every fixed case's bundle, built from a mock run, carries the build defaults and no
contradiction between the search store card and the files (ADR-026 step 1)."""

import importlib.util
from pathlib import Path

import pytest
from app.journey.build_plan import plan_build
from app.journey.design import ServiceDesign
from app.journey.package import build_package
from app.journey.services import JourneyDeps
from app.registry.loader import load_registry

RUNNER = Path(__file__).resolve().parents[1] / "benchmarks" / "run.py"
spec = importlib.util.spec_from_file_location("eval_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
REGISTRY = load_registry()
DESIGN_CASES = [c["id"] for c in runner.load_cases() if c.get("evaluation") == "design"]
VECTOR_WORDS = ("pgvector", "embedding", "임베딩", "벡터")


def bundle(case_id):
    case = runner.load_cases([case_id])[0]
    result = runner.run_case(case, "flow", JourneyDeps(), REGISTRY)
    design = ServiceDesign.model_validate(result["artifact"])
    return case, build_package(plan_build(design, REGISTRY, case["spec"]["idea"]))


@pytest.mark.parametrize("case_id", DESIGN_CASES)
def test_every_case_bundle_carries_the_defaults(case_id):
    case, files = bundle(case_id)
    build, infra = files["BUILD.md"], files["docs/infrastructure.md"]
    chosen = case["selection"]

    assert "127.0.0.1에만 연다" in infra
    assert "## 남은 결정" in build
    if chosen.get("data.primary_db") not in (None, "none"):
        assert "테스트용 데이터베이스를 따로" in build
    if chosen.get("cloud.target") not in (None, "local"):
        assert "클라우드 계정" not in infra.split("## 배포 (나중)")[0]
    web_code = chosen.get("product.surface") == "web" and chosen.get(
        "backend.implementation", "code") == "code"  # fmt: skip
    assert (".claude/skills/antislop/SKILL.md" in files) == web_code


@pytest.mark.parametrize("case_id", DESIGN_CASES)
def test_no_file_uses_a_vector_store_the_card_left_out(case_id):
    case, files = bundle(case_id)
    if case["selection"].get("data.vector_store", "none") != "none":
        return
    for name, text in files.items():
        if name.startswith(".claude/skills/antislop"):
            continue
        assert not any(word in text for word in VECTOR_WORDS), (case_id, name)


def test_c1_has_no_search_store_contradiction():
    _, files = bundle("C1")
    infra = files["docs/infrastructure.md"]
    store = infra.split("### 검색 저장소")[1].split("\n### ")[0]
    others = [text for name, text in files.items()
              if name != "docs/infrastructure.md" and not name.startswith(".claude/skills/antislop")]  # fmt: skip

    if "불필요" in store:
        assert not any(word in text for text in others for word in VECTOR_WORDS)
    else:
        assert "pgvector 확장이 든 이미지" in infra.split("## 컨테이너 목록")[1]
