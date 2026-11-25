import importlib.util
import inspect
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from app.journey import package
from app.journey.build_plan import BuildSpec, plan_build
from app.journey.design import ServiceDesign
from app.journey.package import build_package, package_zip
from app.registry.build_decisions import BuildDecisions, load_build_decisions
from app.registry.loader import RegistryError, load_registry

REGISTRY = load_registry()
_spec = importlib.util.spec_from_file_location(
    "validator_fixture", Path(__file__).parent / "test_design_validator.py"
)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def design(**choices):
    fields = _fixture.valid_design()
    decisions = {d["card_id"]: d for d in fields["provenance"]["decisions"]}
    for card_id, option_id in choices.items():
        version = REGISTRY.card(card_id).version
        decisions[card_id] = {"card_id": card_id, "card_version": version,
                              "option_id": option_id, "by": "user"}  # fmt: skip
    fields["provenance"]["decisions"] = list(decisions.values())
    return ServiceDesign(**fields)


def files_for(**choices):
    return build_package(plan_build(design(**choices), REGISTRY, "아이디어"))


def test_the_list_loads_and_every_source_is_used():
    items = load_build_decisions(REGISTRY).items

    assert {item.source for item in items} == {"card", "default", "design", "ask"}
    assert len({item.id for item in items}) == len(items)


def test_a_dangling_card_in_the_list_fails_at_load(tmp_path):
    path = tmp_path / "build.yaml"
    path.write_text("version: 1\nitems:\n  - {id: x, title: x, source: card, card: no.such}\n")

    with pytest.raises(RegistryError):
        load_build_decisions(REGISTRY, path)


def test_the_package_reads_only_the_spec():
    source = inspect.getsource(package)
    parameters = inspect.signature(build_package).parameters

    assert list(parameters) == ["spec"] and parameters["spec"].annotation is BuildSpec
    assert "provenance" not in source and "Registry" not in source and "registry" not in source


def test_the_same_decisions_give_the_same_bundle():
    first = files_for(**{"product.surface": "web"})
    second = files_for(**{"product.surface": "web"})

    assert first == second
    assert package_zip(first) == package_zip(second)


def test_defaults_follow_the_choices():
    web = files_for(**{"product.surface": "web", "data.primary_db": "postgres",
                       "cloud.target": "gcp"})  # fmt: skip
    plain = files_for(**{"product.surface": "report", "data.primary_db": "none",
                         "data.vector_store": "none", "cloud.target": "local"})  # fmt: skip

    build, infra = web["BUILD.md"], web["docs/infrastructure.md"]
    assert "127.0.0.1에만 연다" in infra and "127.0.0.1에만 연다" in plain["docs/infrastructure.md"]
    assert (
        "테스트용 데이터베이스를 따로" in build and "테스트용 데이터베이스" not in plain["BUILD.md"]
    )
    assert (
        "가짜 모델 모드" in build
        and "가짜 모델 모드" in web[".claude/skills/verify-design/SKILL.md"]
    )
    assert "렌더링해서 보여 준다" in build and "렌더링해서" not in plain["BUILD.md"]
    assert (
        ".claude/skills/antislop/SKILL.md" in web
        and ".claude/skills/antislop/SKILL.md" not in plain
    )
    # The first build stays local; the cloud is listed for later.
    assert "## 배포 (나중)" in infra and "클라우드 계정" in infra.split("## 배포 (나중)")[1]
    assert "클라우드 계정" not in infra.split("## 배포 (나중)")[0]
    assert "## 배포 (나중)" not in plain["docs/infrastructure.md"]


def test_antislop_ships_pinned_with_its_licenses():
    files = files_for(**{"product.surface": "web"})

    assert files[".claude/skills/antislop/VERSION"].strip() == "3.2.32"
    assert "Copyright (c) 2026 Miqdad Badjuber" in files[".claude/skills/antislop/LICENSE"]
    assert "Addy Osmani" in files[".claude/skills/antislop-ui/LICENSE-web-quality-skills"]
    assert "during 모드" in files["BUILD.md"]
    with zipfile.ZipFile(BytesIO(package_zip(files))) as archive:
        assert "starter-pack/.claude/skills/antislop-human/references/WCAG.md" in archive.namelist()


def test_questions_left_open_are_listed_with_their_recommendation():
    spec = plan_build(design(**{"product.surface": "web", "data.vector_store": "pgvector",
                                "data.primary_db": "postgres"}), REGISTRY, "아이디어")  # fmt: skip
    build = build_package(spec)["BUILD.md"]

    assert {"model_ids", "embedding_model", "data_scope", "screen_layout"} <= {
        item.id for item in spec.open
    }
    section = build.split("## 남은 결정")[1].split("\n## ")[0]
    assert "임베딩 모델과 차원" in section and "(추천:" in section


def test_a_journey_saved_before_the_implementation_card_is_built_as_code():
    fields = _fixture.valid_design()
    spec = plan_build(ServiceDesign(**fields), REGISTRY, "아이디어")

    assert spec.implementation == "code"
    assert any(d.id == "implementation" and d.source == "default" for d in spec.decided)


def test_an_unknown_compute_name_is_rejected():
    with pytest.raises(ValueError):
        BuildDecisions.model_validate(
            {
                "version": 1,
                "items": [{"id": "x", "title": "x", "source": "default", "compute": "z"}],
            }
        )


def test_model_ids_are_recommended_with_their_source_and_date():
    from app.registry.provider_models import default_provider_models

    spec = plan_build(design(**{"model.provider": "openai", "data.vector_store": "pgvector",
                                "data.primary_db": "postgres"}), REGISTRY, "아이디어")  # fmt: skip
    advice = {item.id: item.recommendation for item in spec.open}
    entry = default_provider_models().providers["openai"]

    assert f"`{entry.chat}`" in advice["model_ids"] and "사용자가 확정한다" in advice["model_ids"]
    assert (
        entry.checked_at.isoformat() in advice["model_ids"] and entry.source in advice["model_ids"]
    )
    assert f"`{entry.embedding}`" in advice["embedding_model"]


def test_an_old_model_entry_is_warned_and_a_missing_one_stays_generic():
    from datetime import date

    from app.registry.provider_models import ProviderModels, ProviderModelTable

    old = ProviderModelTable(version=1, stale_after_days=60, providers={"gemini": ProviderModels(
        chat="m", source="https://example.invalid", checked_at=date(2026, 8, 1))})  # fmt: skip
    spec = plan_build(design(), REGISTRY, "아이디어", models=old)
    missing = plan_build(design(**{"model.provider": "upstage"}), REGISTRY, "아이디어", models=old)

    assert "models.stale" in {issue.rule_id for issue in spec.issues}
    advice = next(i.recommendation for i in missing.open if i.id == "model_ids")
    assert "공식 문서에서" in advice


def test_the_model_table_only_names_real_providers(tmp_path):
    from app.registry.provider_models import load_provider_models

    path = tmp_path / "models.yaml"
    path.write_text("version: 1\nstale_after_days: 60\nproviders:\n  nobody:\n"
                    "    source: x\n    checked_at: 2026-11-25\n")  # fmt: skip
    with pytest.raises(RegistryError):
        load_provider_models(REGISTRY, path)
