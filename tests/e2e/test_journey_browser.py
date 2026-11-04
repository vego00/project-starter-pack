"""Runs against a live stack: `docker compose up -d --wait`, then set E2E_BASE_URL.

Optional: E2E_SCREENSHOT_DIR saves screens; E2E_RESTART_CMD restarts the backend mid-journey;
E2E_CHROMIUM_PATH uses an already installed Chromium instead of the version Playwright expects.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL")
SCREENSHOTS = os.environ.get("E2E_SCREENSHOT_DIR")
RESTART_CMD = os.environ.get("E2E_RESTART_CMD")
CHROMIUM_PATH = os.environ.get("E2E_CHROMIUM_PATH")
IDEA = "부트캠프 강의 자료를 찾아 질문에 답하고 출처를 알려주는 서비스를 만들고 싶어요."

pytestmark = pytest.mark.skipif(not BASE_URL, reason="E2E_BASE_URL is not set")


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
    page.get_by_role("button", name="결정 시작하기").click()


def skip_clarify(page: Page) -> None:
    for _ in range(2):
        expect(page.get_by_role("heading", name="프로젝트를 조금 더 알려 주세요")).to_be_visible()
        page.get_by_role("button", name="다음").click()
        page.wait_for_function("document.querySelector('[role=status]').textContent === ''")
    expect(page.get_by_text("추천:")).to_be_visible()


def choose(page: Page, heading: str, option: str) -> None:
    expect(page.get_by_role("heading", name=heading)).to_be_visible()
    page.get_by_role("button", name=f"{option} 선택").click()
    expect(page.get_by_role("heading", name=heading)).to_be_hidden()


def test_seven_cards_to_completion_with_reload_and_restart(page: Page):
    shot(page, "1-start")
    start(page)

    expect(page.get_by_role("heading", name="프로젝트를 조금 더 알려 주세요")).to_be_visible()
    page.get_by_label("어디까지 배포할 계획인가요?").select_option("small_group")
    page.get_by_label("실제로 사용할 사람은 몇 명 정도인가요?").fill("20")
    shot(page, "2-clarify")
    page.get_by_role("button", name="다음").click()
    expect(page.get_by_label("함께 개발하는 인원은 몇 명인가요?")).to_have_value("")
    page.get_by_label("함께 개발하는 인원은 몇 명인가요?").fill("4")
    page.get_by_role("button", name="다음").click()

    expect(page.get_by_text("내 프로젝트를 분석한 결과는 아니에요")).to_be_visible()
    shot(page, "3-card")
    choose(page, "에이전트가 실행 중간에 사람의 확인을 받아야 하나요?", "승인 interrupt")
    choose(page, "어떤 경로로 LLM을 사용할까요?", "Gemini")

    page.reload()
    expect(page.get_by_role("heading", name="에이전트 실행 상태를 어디에")).to_be_visible()
    expect(page.get_by_text("2 / 7")).to_be_visible()

    if RESTART_CMD:
        subprocess.run(RESTART_CMD, shell=True, check=True, timeout=120)
        page.reload()
        expect(page.get_by_role("heading", name="에이전트 실행 상태를 어디에")).to_be_visible()

    choose(page, "에이전트 실행 상태를 어디에 저장할까요?", "메모리")
    choose(page, "에이전트 작업을 어떻게 실행할까요?", "요청 내 동기 실행")
    choose(page, "컨테이너 오케스트레이션이 필요한가요?", "불필요 (Compose 유지)")
    choose(page, "모델을 어떻게 서빙할까요?", "외부 API만")

    # Approval + memory rules out the cloud: the rule from an earlier card reaches this one.
    expect(page.get_by_role("button", name="GCP 선택")).to_be_disabled()
    expect(page.get_by_text("재시작해도 남는 체크포인터가 필요합니다").first).to_be_visible()
    shot(page, "4-blocked")
    choose(page, "어디에 배포할까요?", "로컬만")

    expect(page.get_by_role("heading", name="모든 결정을 마쳤어요")).to_be_visible()
    expect(page.get_by_text("7 / 7")).to_be_visible()
    shot(page, "5-completed")


def test_questions_defer_and_reopen(page: Page):
    start(page)
    skip_clarify(page)
    page.get_by_label("이 카드에 대해 질문하기").fill("interrupt가 뭐예요?")
    page.get_by_role("button", name="질문", exact=True).click()
    expect(page.get_by_text("모델 미연결 상태의 고정 응답")).to_be_visible()

    page.get_by_role("button", name="나중에 결정").click()
    expect(page.get_by_role("heading", name="어떤 경로로 LLM을")).to_be_visible()

    choose(page, "어떤 경로로 LLM을 사용할까요?", "Ollama 로컬")
    expect(page.get_by_text("Ollama 컨테이너 · 자동 확정")).to_be_visible()

    page.get_by_role("button", name="모델 다시 고르기").click()
    expect(page.get_by_role("heading", name="어떤 경로로 LLM을")).to_be_visible()
    expect(page.get_by_text("자동 확정")).to_be_hidden()


def test_stale_tab_cannot_answer_the_wrong_card(browser: Browser, page: Page):
    start(page)
    skip_clarify(page)
    other = page.context.new_page()
    other.goto(page.url)
    expect(other.get_by_role("button", name="없음 선택")).to_be_visible()

    page.get_by_role("button", name="없음 선택").click()
    expect(page.get_by_role("heading", name="어떤 경로로 LLM을")).to_be_visible()

    other.get_by_role("button", name="없음 선택").click()
    expect(other.get_by_role("alert").first).to_contain_text("최신 상태가 아니에요")
    expect(other.get_by_role("heading", name="어떤 경로로 LLM을")).to_be_visible()
    expect(other.get_by_text("1 / 7")).to_be_visible()


def test_phone_width_has_no_horizontal_scroll(browser: Browser):
    context = browser.new_context(viewport={"width": 375, "height": 800}, locale="ko-KR")
    page = context.new_page()
    page.goto(BASE_URL)
    start(page)
    skip_clarify(page)
    shot(page, "6-phone")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    card_top = page.get_by_text("추천:").bounding_box()["y"]
    rail_top = page.get_by_role("complementary").bounding_box()["y"]
    assert card_top < rail_top
    context.close()
