"""Runs against a live mock stack, then set E2E_BASE_URL:
`APP_PROVIDER=mock APP_DECIDER=mock APP_EVIDENCE_SCOPE=none docker compose up -d --wait`
(shell values override .env, which may point at real models).

Optional: E2E_SCREENSHOT_DIR saves screens; E2E_RESTART_CMD restarts the backend mid-journey;
E2E_CHROMIUM_PATH uses an already installed Chromium instead of the version Playwright expects.
"""

import os
import re
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL")
SCREENSHOTS = os.environ.get("E2E_SCREENSHOT_DIR")
RESTART_CMD = os.environ.get("E2E_RESTART_CMD")
CHROMIUM_PATH = os.environ.get("E2E_CHROMIUM_PATH")
GOAL = "수강생이 강의 내용을 출처와 함께 바로 찾을 수 있는 상태"
IDEA = "부트캠프 강의 자료를 찾아 질문에 답하고 출처를 알려주는 서비스를 만들고 싶어요."
SURFACE = "사용자가 이 서비스를 어디서 쓰나요?"

pytestmark = pytest.mark.skipif(not BASE_URL, reason="E2E_BASE_URL is not set")


@pytest.fixture(scope="module", autouse=True)
def require_mock_stack() -> None:
    """These tests assert mock text; a real model would also spend free quota for nothing."""
    health = httpx.get(f"{BASE_URL}/health", timeout=5).json()
    if (health["provider"], health["decider"]) != ("mock", "mock"):
        pytest.fail(f"E2E needs a mock stack, got {health['provider']}/{health['decider']}")


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROMIUM_PATH)
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ko-KR")
    page = context.new_page()
    page.goto(BASE_URL)
    yield page
    context.close()


def shot(page: Page, name: str) -> None:
    if SCREENSHOTS:
        page.screenshot(path=str(Path(SCREENSHOTS) / f"{name}.png"), full_page=True)


def start(page: Page) -> None:
    page.get_by_label("프로젝트 아이디어").fill(IDEA)
    page.get_by_role("button", name="보내기", exact=True).click()
    expect(page.get_by_role("log", name="시작 대화")).to_be_visible()


def begin(page: Page) -> None:
    """The mock stack has no model: goal blanks are filled, then the journey starts."""
    page.get_by_role("button", name="목표 빈칸은 알아서 채워 주세요").click()
    page.get_by_role("button", name="결정 시작하기").click()


def confirm_brief(page: Page) -> None:
    begin(page)


def fill_field(page: Page, label: str, text: str) -> None:
    page.get_by_role("button", name=f"{label} 고치기").click()
    page.get_by_label(f"{label} 직접 적기").fill(text)
    page.get_by_role("button", name="저장").click()
    expect(page.get_by_role("button", name=f"{label} 고치기 닫기")).to_be_visible()
    page.get_by_role("button", name=f"{label} 고치기 닫기").click()


def skip_clarify(page: Page) -> None:
    confirm_brief(page)
    page.wait_for_function("document.querySelector('[role=status]').textContent === ''")
    expect(page.locator(".option").first).to_be_visible()


def option_button(page: Page, option: str):
    """The name is the option plus the words on the button, which differ for the recommended one."""
    return page.get_by_role(
        "button", name=re.compile(rf"^{re.escape(option)} (선택|이걸로 정하기|바꾸기)$")
    )


def choose(page: Page, heading: str, option: str) -> None:
    expect(page.get_by_role("heading", name=heading)).to_be_visible()
    option_button(page, option).click()
    expect(page.get_by_role("heading", name=heading)).to_be_hidden()


def open_stage(page: Page, stage: str) -> None:
    page.get_by_role("button", name=re.compile(rf"^{stage} \d")).click()


def choose_surface(page: Page, option: str = "웹 화면") -> None:
    choose(page, SURFACE, option)


def plan_deploy(page: Page) -> None:
    """The fork after the agent design (ADR-024): go on to the deployment cards."""
    expect(page.get_by_role("heading", name="에이전트 설계를 마쳤어요")).to_be_visible()
    page.get_by_role("button", name=re.compile("^배포 계획 세우기")).click()


def test_all_cards_to_completion_with_reload_and_restart(page: Page):
    shot(page, "1-start")
    start(page)
    shot(page, "1b-gcb")
    expect(page.get_by_role("button", name="결정 시작하기")).to_be_disabled()
    fill_field(page, "끝났을 때 어떤 상태면 되나요?", GOAL)
    page.get_by_role("button", name="배포 범위 고치기").click()
    page.get_by_role("button", name="소수 사용자").click()
    expect(page.get_by_text("직접 고름").first).to_be_visible()
    page.get_by_role("button", name="배포 범위 고치기 닫기").click()
    fill_field(page, "사용자 수", "20")
    fill_field(page, "개발 인원", "4")
    page.get_by_role("button", name="목표 빈칸은 알아서 채워 주세요").click()
    # GPU and budget stay blank: only the goal is needed to start (ADR-024).
    expect(page.get_by_role("button", name="결정 시작하기")).to_be_enabled()
    shot(page, "2-brief")
    page.get_by_role("button", name="결정 시작하기").click()

    expect(page.get_by_text("내 프로젝트를 분석한 결과가 아닙니다")).to_be_visible()
    shot(page, "3-card")
    choose_surface(page)
    choose(page, "에이전트를 어떤 구조로 구성할까요?", "고정 파이프라인")
    choose(page, "에이전트가 실행 중간에 사람의 확인을 받아야 하나요?", "승인 후 실행")

    # The blank budget is asked on the card that reads it, with its default.
    expect(page.get_by_role("heading", name="어떤 경로로 LLM을 사용할까요?")).to_be_visible()
    strip = page.get_by_role("group", name="이 카드가 쓰는 정보")
    strip.get_by_role("button", name="예산 무료로만 기본값").click()
    strip.get_by_role("button", name="월 5만원 이하").click()
    expect(strip.get_by_role("button", name="예산 월 5만원 이하 직접 고름")).to_be_visible()
    shot(page, "3b-card-info")
    choose(page, "어떤 경로로 LLM을 사용할까요?", "Gemini")
    plan_deploy(page)
    choose(page, "서비스가 다루는 데이터를 어디에 저장할까요?", "PostgreSQL")
    choose(page, "문서를 의미로 검색하는 벡터 저장소를 무엇으로 할까요?", "불필요")

    page.reload()
    expect(page.get_by_role("heading", name="에이전트 실행 상태를 어디에")).to_be_visible()
    expect(page.get_by_text("6 / 12")).to_be_visible()

    if RESTART_CMD:
        subprocess.run(RESTART_CMD, shell=True, check=True, timeout=120)
        page.reload()
        expect(page.get_by_role("heading", name="에이전트 실행 상태를 어디에")).to_be_visible()

    choose(page, "에이전트 실행 상태를 어디에 저장할까요?", "메모리")
    choose(page, "에이전트 작업을 어떻게 실행할까요?", "요청 내 동기 실행")
    choose(page, "컨테이너 오케스트레이션이 필요한가요?", "불필요 (Compose 유지)")
    choose(page, "모델을 어떻게 서빙할까요?", "외부 API만")

    # Approval + memory rules out the cloud: the rule from an earlier card reaches this one.
    expect(option_button(page, "GCP")).to_be_disabled()
    expect(page.get_by_text("재시작해도 남는 체크포인터가 필요합니다").first).to_be_visible()
    shot(page, "4-blocked")
    choose(page, "어디에 배포할까요?", "로컬만")
    choose(page, "완성된 서비스의 실행 기록을 어떻게 볼까요?", "자체 실행 기록")

    expect(page.get_by_role("heading", name="설계가 준비됐어요")).to_be_visible()
    expect(page.get_by_text("12 / 12")).to_be_visible()
    assert page.locator(".blueprint-canvas").bounding_box()["height"] > 300
    shot(page, "5-completed")

    with page.expect_download() as download:
        page.get_by_role("link", name="결정 요약 다운로드").click()
    assert download.value.suggested_filename == "decision-summary.md"
    document = Path(download.value.path()).read_text(encoding="utf-8")
    assert document.startswith("# 프로젝트 결정 요약")
    assert IDEA in document
    assert GOAL in document
    assert "승인 후 실행 (직접 선택)" in document

    expect(page.get_by_text("참고용")).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role("link", name="빌드 묶음 다운로드").click()
    assert download.value.suggested_filename == "starter-pack.zip"
    with zipfile.ZipFile(download.value.path()) as archive:
        names = archive.namelist()
        build = archive.read("starter-pack/BUILD.md").decode("utf-8")
    assert "starter-pack/docs/infrastructure.md" in names
    assert "참고 템플릿" in build


def test_ending_at_the_agent_design_and_planning_the_rest_later(page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    choose(page, "에이전트를 어떤 구조로 구성할까요?", "고정 파이프라인")
    choose(page, "에이전트가 실행 중간에 사람의 확인을 받아야 하나요?", "승인 후 실행")
    choose(page, "어떤 경로로 LLM을 사용할까요?", "Gemini")

    expect(page.get_by_role("heading", name="에이전트 설계를 마쳤어요")).to_be_visible()
    expect(page.get_by_text("여기서 끝낼까요?")).to_be_visible()
    shot(page, "fork")
    page.get_by_role("button", name=re.compile("^여기서 끝내기")).click()

    expect(page.get_by_role("heading", name="설계가 준비됐어요")).to_be_visible()
    expect(page.get_by_text("에이전트 설계까지 결정 4개를 마쳤어요")).to_be_visible()
    shot(page, "fork-ended")
    with page.expect_download() as download:
        page.get_by_role("link", name="빌드 묶음 다운로드").click()
    with zipfile.ZipFile(download.value.path()) as archive:
        infra = archive.read("starter-pack/docs/infrastructure.md").decode("utf-8")
    assert "아직 정하지 않았어요" in infra

    page.reload()
    page.get_by_role("button", name=re.compile("^배포 계획 이어서 세우기")).click()
    choose(page, "서비스가 다루는 데이터를 어디에 저장할까요?", "PostgreSQL")
    expect(page.get_by_role("heading", name="여기서 끝낼까요?")).to_be_hidden()


def test_questions_defer_and_reopen(page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    choose(page, "에이전트를 어떤 구조로 구성할까요?", "고정 파이프라인")
    page.get_by_label("이 카드에 대해 질문하기").fill("interrupt가 뭐예요?")
    page.get_by_role("button", name="질문", exact=True).click()
    expect(page.get_by_text("모델 미연결 상태의 고정 응답")).to_be_visible()

    page.get_by_role("button", name="나중에 결정").click()
    expect(page.get_by_role("heading", name="어떤 경로로 LLM을")).to_be_visible()

    choose(page, "어떤 경로로 LLM을 사용할까요?", "Ollama 로컬")

    # A card deferred in the agent design comes back before the fork (ADR-024).
    expect(page.get_by_role("heading", name="에이전트가 실행 중간에 사람의 확인을")).to_be_visible()
    open_stage(page, "시스템 구성")
    expect(page.get_by_text("Ollama 컨테이너 · 자동 확정")).to_be_visible()

    # The provider card closes the agent stage (ADR-024).
    open_stage(page, "에이전트 설계")
    page.get_by_role("button", name="모델 제공자 다시 고르기").click()
    expect(page.get_by_role("heading", name="어떤 경로로 LLM을")).to_be_visible()
    open_stage(page, "시스템 구성")
    expect(page.get_by_text("Ollama 컨테이너 · 자동 확정")).to_be_visible()
    page.keyboard.press("Escape")

    option_button(page, "Gemini").click()
    expect(page.get_by_text("자동 확정")).to_be_hidden()


def test_changing_an_earlier_decision_asks_to_review_later_ones(page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    choose(page, "에이전트를 어떤 구조로 구성할까요?", "고정 파이프라인")
    shot(page, "7-graph")

    open_stage(page, "제품 형태")
    page.get_by_role("button", name="사용 위치 다시 고르기").click()
    choose_surface(page, "정기 리포트")

    expect(page.get_by_role("button", name=re.compile("다시 확인 1"))).to_be_visible()
    open_stage(page, "에이전트 설계")
    notice = page.get_by_text("앞 단계가 바뀌었어요. 다시 확인해 주세요.")
    expect(notice).to_be_visible()
    shot(page, "8-review")

    page.get_by_role("button", name="현재 결정 유지").click()
    expect(notice).to_be_hidden()


def test_pressing_a_decided_icon_keeps_the_decision_until_changed(page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    page.get_by_role("button", name="시스템 구성", exact=True).click()

    page.get_by_role("button", name="시스템 웹 화면 다시 고르기").click()

    expect(page.get_by_role("heading", name=SURFACE)).to_be_visible()
    expect(page.get_by_role("button", name="시스템 웹 화면")).to_be_visible()
    expect(page.get_by_text("1 / 12")).to_be_visible()

    page.get_by_role("button", name="웹 화면 그대로 두기").click()
    expect(page.get_by_role("heading", name=SURFACE)).to_be_hidden()
    page.get_by_role("button", name="시스템 구성", exact=True).click()
    expect(page.get_by_role("button", name="시스템 웹 화면 다시 고르기")).to_be_visible()


def reach_data_cards(page: Page) -> None:
    start(page)
    skip_clarify(page)
    choose_surface(page)
    choose(page, "에이전트를 어떤 구조로 구성할까요?", "고정 파이프라인")
    choose(page, "에이전트가 실행 중간에 사람의 확인을 받아야 하나요?", "승인 후 실행")
    choose(page, "어떤 경로로 LLM을 사용할까요?", "Gemini")
    plan_deploy(page)
    choose(page, "서비스가 다루는 데이터를 어디에 저장할까요?", "PostgreSQL")


def test_each_decision_on_one_postgres_opens_from_its_own_line(page: Page):
    reach_data_cards(page)
    choose(
        page, "문서를 의미로 검색하는 벡터 저장소를 무엇으로 할까요?", "pgvector (PostgreSQL 확장)"
    )
    choose(page, "에이전트 실행 상태를 어디에 저장할까요?", "PostgreSQL 체크포인터")
    page.get_by_role("button", name="시스템 구성", exact=True).click()
    shot(page, "stacked-service")

    page.get_by_role("button", name=re.compile("^시스템 벡터 검색: .* 다시 고르기$")).click()

    expect(page.get_by_role("heading", name="문서를 의미로 검색하는")).to_be_visible()
    page.get_by_role("button", name=re.compile("그대로 두기$")).click()
    expect(page.get_by_role("heading", name="문서를 의미로 검색하는")).to_be_hidden()


def test_an_answer_without_a_service_opens_from_the_line_below_the_graph(page: Page):
    reach_data_cards(page)
    choose(page, "문서를 의미로 검색하는 벡터 저장소를 무엇으로 할까요?", "불필요")
    page.get_by_role("button", name="시스템 구성", exact=True).click()

    page.get_by_role("button", name="검색 저장소: 불필요 다시 고르기").click()

    expect(page.get_by_role("heading", name="문서를 의미로 검색하는")).to_be_visible()


def test_a_flow_step_explains_itself_and_opens_its_decision(page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    choose(page, "에이전트를 어떤 구조로 구성할까요?", "고정 파이프라인")
    page.get_by_role("button", name="에이전트 흐름", exact=True).click()

    page.get_by_role("button", name="에이전트 처리 단계 설명 보기").click()

    expect(page.get_by_text("아직 모름")).to_be_visible()
    shot(page, "step-detail")
    page.get_by_role("button", name=re.compile("^Agent 구조: .* 다시 고르기$")).click()
    expect(page.get_by_role("heading", name="에이전트를 어떤 구조로 구성할까요?")).to_be_visible()


def test_the_build_order_shows_start_conditions_from_the_decisions(page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    page.get_by_role("button", name="만드는 순서", exact=True).click()

    page.get_by_role("button", name=re.compile("^웹 화면 시작 조건")).click()

    expect(page.get_by_text("승인 전에는 화면 코드를 쓰지 않는다")).to_be_visible()
    expect(page.get_by_text(re.compile("^빼면 안 되는 이유:")).first).to_be_visible()
    shot(page, "build-order")


def test_the_graph_stays_put_while_the_card_scrolls(browser: Browser):
    context = browser.new_context(viewport={"width": 1280, "height": 700}, locale="ko-KR")
    page = context.new_page()
    page.goto(BASE_URL)
    start(page)
    skip_clarify(page)
    graph = page.get_by_role("region", name="설계 그래프")
    card = page.locator(".workspace-card")
    before = graph.bounding_box()["y"]

    card.hover()
    page.mouse.wheel(0, 600)
    page.wait_for_function("document.querySelector('.workspace-card').scrollTop > 0")

    assert page.evaluate("window.scrollY") == 0
    assert graph.bounding_box()["y"] == before
    context.close()


def test_a_system_card_shows_the_system_graph_and_what_changed(page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    agent_tab = page.get_by_role("button", name="에이전트 흐름", exact=True)
    expect(agent_tab).to_have_attribute("aria-pressed", "true")
    choose(page, "에이전트를 어떤 구조로 구성할까요?", "고정 파이프라인")
    choose(page, "에이전트가 실행 중간에 사람의 확인을 받아야 하나요?", "승인 후 실행")

    system_tab = page.get_by_role("button", name="시스템 구성", exact=True)
    expect(system_tab).to_have_attribute("aria-pressed", "true")
    option_button(page, "Gemini").click()

    expect(page.get_by_text("방금 반영:")).to_be_visible()
    expect(page.locator(".bp-service.changed")).not_to_have_count(0)


def test_stale_tab_cannot_answer_the_wrong_card(browser: Browser, page: Page):
    start(page)
    skip_clarify(page)
    choose_surface(page)
    other = page.context.new_page()
    other.goto(page.url)
    expect(option_button(other, "Supervisor 라우팅")).to_be_visible()

    option_button(page, "Supervisor 라우팅").click()
    expect(page.get_by_role("heading", name="에이전트가 실행 중간에")).to_be_visible()

    option_button(other, "Supervisor 라우팅").click()
    expect(other.get_by_role("alert").first).to_contain_text("최신 상태가 아니에요")
    expect(other.get_by_role("heading", name="에이전트가 실행 중간에")).to_be_visible()
    expect(other.get_by_text("2 / 12")).to_be_visible()


def test_the_system_diagram_fits_a_wide_panel(browser: Browser):
    context = browser.new_context(viewport={"width": 1600, "height": 900}, locale="ko-KR")
    page = context.new_page()
    page.goto(BASE_URL)
    start(page)
    skip_clarify(page)
    page.get_by_role("button", name="시스템 구성", exact=True).click()
    expect(page.get_by_role("group", name="시스템 구성")).to_be_visible()

    canvas = page.locator(".blueprint-canvas")
    assert canvas.evaluate("c => c.scrollWidth <= c.clientWidth")

    for _ in range(3):
        page.get_by_role("button", name="확대").click()
    assert canvas.evaluate("c => c.scrollWidth > c.clientWidth")

    box = canvas.bounding_box()
    page.mouse.move(box["x"] + 400, box["y"] + 4)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 4, steps=4)
    page.mouse.up()
    assert canvas.evaluate("c => c.scrollLeft") > 0

    page.get_by_role("button", name="화면 맞춤").click()
    assert canvas.evaluate("c => c.scrollWidth <= c.clientWidth")

    page.mouse.move(box["x"] + 300, box["y"] + 200)
    page.keyboard.down("Control")
    page.mouse.wheel(0, -200)
    page.keyboard.up("Control")
    expect(page.locator(".zoom-value")).not_to_have_text("맞춤")
    assert page.evaluate("window.visualViewport.scale") == 1
    context.close()


def test_closing_the_card_tab_gives_the_graph_the_page(browser: Browser):
    context = browser.new_context(viewport={"width": 1600, "height": 900}, locale="ko-KR")
    page = context.new_page()
    page.goto(BASE_URL)
    start(page)
    skip_clarify(page)
    canvas = page.locator(".blueprint-canvas")
    question = page.get_by_role("heading", name=SURFACE)
    before = canvas.bounding_box()["width"]

    page.get_by_role("button", name="카드 닫기").click()
    expect(question).to_be_hidden()
    assert canvas.bounding_box()["width"] > before + 300
    shot(page, "9-graph-only")

    page.get_by_role("button", name="에이전트 흐름", exact=True).click()
    page.get_by_role("button", name="미정 에이전트 구조?").click()
    expect(page.get_by_role("heading", name="에이전트를 어떤 구조로")).to_be_visible()
    context.close()


def test_phone_width_has_no_horizontal_scroll(browser: Browser):
    context = browser.new_context(viewport={"width": 375, "height": 800}, locale="ko-KR")
    page = context.new_page()
    page.goto(BASE_URL)
    start(page)
    skip_clarify(page)
    shot(page, "6-phone")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    card_top = page.locator(".option").first.bounding_box()["y"]
    graph_top = page.get_by_role("region", name="설계 그래프").bounding_box()["y"]
    rail_top = page.get_by_role("complementary").bounding_box()["y"]
    assert rail_top < card_top < graph_top
    context.close()


def test_the_theme_can_be_switched_and_is_remembered(page: Page):
    html = page.locator("html")
    before = html.get_attribute("data-theme")
    other = "dark" if before == "light" else "light"

    page.get_by_role("button", name="다크 모드" if before == "light" else "라이트 모드").click()
    expect(html).to_have_attribute("data-theme", other)

    page.reload()
    expect(html).to_have_attribute("data-theme", other)
