import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  ApiError,
  editModule,
  editStart,
  fillStart,
  getJourney,
  sendAction,
  sendModuleMessage,
  sendStartMessage,
  startJourney,
  undoModule,
} from "./api";
import type { Action, Journey } from "./api";
import { BlueprintPanel, SamplePreview } from "./blueprint";
import {
  ClarifyForm,
  CompletedView,
  DecisionView,
  IssuesView,
  ProgressRail,
} from "./components";
import type { SideView } from "./components";
import { ModuleChat } from "./moduleChat";
import { StartChat } from "./startChat";
import { ThemeToggle } from "./theme";

const LAST_JOURNEY_KEY = "starter-pack:last-journey:v1";

function savedJourneyId(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get("journey");
  if (fromUrl) return fromUrl;
  try {
    return localStorage.getItem(LAST_JOURNEY_KEY);
  } catch {
    return null;
  }
}

function rememberJourney(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("journey", id);
  else url.searchParams.delete("journey");
  window.history.replaceState(null, "", url);
  try {
    if (id) localStorage.setItem(LAST_JOURNEY_KEY, id);
    else localStorage.removeItem(LAST_JOURNEY_KEY);
  } catch {
    // Without storage the address bar still holds the journey.
  }
}

function messageOf(failure: unknown): string {
  return failure instanceof Error
    ? failure.message
    : "요청에 실패했어요. 다시 시도해 주세요.";
}

const STACKED = "(max-width: 1100px)";

/** Tab follows the DOM, so the DOM has to follow the stacked order the screen shows. */
function useStacked(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const query = window.matchMedia?.(STACKED);
      query?.addEventListener("change", changed);
      return () => query?.removeEventListener("change", changed);
    },
    () => window.matchMedia?.(STACKED).matches ?? false,
  );
}

export default function App() {
  const [journey, setJourney] = useState<Journey | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(() => savedJourneyId() !== null);
  const [cardOpen, setCardOpen] = useState(true);
  const [confirmingRestart, setConfirmingRestart] = useState(false);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [side, setSide] = useState<SideView>("summary");
  const stacked = useStacked();
  const inFlight = useRef(false);

  function show(next: Journey) {
    setJourney(next);
    rememberJourney(next.journey_id);
  }

  async function run(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await work();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  useEffect(() => {
    const id = savedJourneyId();
    if (!id) return;
    getJourney(id)
      .then(show)
      .catch((failure: unknown) => {
        if (
          failure instanceof ApiError &&
          ["journey_not_found", "invalid_input"].includes(failure.code)
        )
          rememberJourney(null);
        else setError(messageOf(failure));
      })
      .finally(() => setRestoring(false));
  }, []);

  function start(idea: string) {
    void run(async () => {
      try {
        show(await startJourney(idea));
      } catch (failure) {
        setError(messageOf(failure));
      }
    });
  }

  function act(action: Action) {
    if (!journey) return;
    setLastAction(action.action);
    const current = journey;
    void run(async () => {
      try {
        show(await sendAction(current, action));
      } catch (failure) {
        setError(messageOf(failure));
        // The server may have moved on: show what is true now instead of a stale card.
        const code = failure instanceof ApiError ? failure.code : "";
        if (["stale_revision", "journey_failed"].includes(code)) {
          try {
            show(await getJourney(current.journey_id));
          } catch {
            // Keep the current screen; the error above already tells the user to retry.
          }
        }
      }
    });
  }

  /** Moving to a card from the rail or the graph has to show that card. */
  function actAndShowCard(action: Action) {
    if (["focus", "reopen", "revise"].includes(action.action)) {
      setCardOpen(true);
    }
    act(action);
  }

  /** Errors go back to the chat or the field that sent them, not to the page. */
  async function changeInPlace(
    work: (current: Journey) => Promise<Journey>,
  ): Promise<string> {
    if (!journey) return "";
    if (inFlight.current)
      return "앞의 요청을 처리하는 중이에요. 끝나면 다시 보내 주세요.";
    const current = journey;
    let failed = "";
    await run(async () => {
      try {
        show(await work(current));
      } catch (failure) {
        failed = messageOf(failure);
        if (failure instanceof ApiError && failure.code === "stale_revision") {
          try {
            show(await getJourney(current.journey_id));
          } catch {
            // Keep the screen; the message already asks to try again.
          }
        }
      }
    });
    return failed;
  }

  function restart() {
    rememberJourney(null);
    setJourney(null);
    setError("");
    setCardOpen(true);
    setConfirmingRestart(false);
  }

  const prompt = journey?.prompt ?? null;
  const startChat = (current: Journey | null) => (
    <StartChat
      journey={current}
      busy={busy}
      preview={<SamplePreview />}
      onIdea={start}
      onSend={(text, focus) =>
        changeInPlace((j) => sendStartMessage(j, text, focus))
      }
      onEdit={(change) => changeInPlace((j) => editStart(j, change))}
      onFill={() => changeInPlace(fillStart)}
      onBegin={() => {
        if (current?.start) act(current.start.submit as Action);
      }}
    />
  );
  const briefing = prompt?.type === "gcb" || prompt?.type === "clarify";
  const finished = !prompt && journey?.status === "completed";
  const inWorkspace = journey !== null && !briefing && !finished;
  // The last decision also generates the design, the one wait that runs long.
  const makingDesign =
    prompt?.type === "decision" &&
    !prompt.current_option_id &&
    ["select", "accept_recommendation"].includes(lastAction ?? "") &&
    journey!.cards.filter((c) => !c.option_name && c.state !== "skipped")
      .length <= 1;
  const panels = journey && [
    <BlueprintPanel
      key="graph"
      journey={journey}
      busy={busy}
      act={actAndShowCard}
      cardOpen={cardOpen}
      onToggleCard={() => setCardOpen(!cardOpen)}
    />,
    <div
      key="card"
      className={`workspace-card${busy ? " is-busy" : ""}`}
      aria-busy={busy}
    >
      {prompt?.type === "decision" && (
        <DecisionView prompt={prompt} busy={busy} act={act} />
      )}
      {prompt?.type === "issues" && (
        <IssuesView
          prompt={prompt}
          cards={journey.cards}
          busy={busy}
          act={act}
        />
      )}
      {!prompt && journey.status !== "completed" && (
        <p className="panel muted">
          다음 단계를 준비하지 못했어요. 페이지를 새로고침해 주세요.
        </p>
      )}
    </div>,
  ];
  return (
    <div
      className={`app${journey ? " wide" : " landing"}${inWorkspace ? " shell" : ""}`}
    >
      <header className="topbar">
        <h1>프로젝트 스타터팩</h1>
        {journey && <span className="topbar-idea">{journey.idea}</span>}
        <div className="topbar-actions">
          {journey?.notice && (
            <span className="topbar-notice">{journey.notice}</span>
          )}
          {journey &&
            !finished &&
            (confirmingRestart ? (
              <span className="confirm">
                지금 여정에서 나갈까요?
                <button className="quiet danger" onClick={restart}>
                  나가기
                </button>
                <button
                  className="quiet"
                  onClick={() => setConfirmingRestart(false)}
                >
                  계속하기
                </button>
              </span>
            ) : (
              <button
                className="quiet"
                onClick={() => setConfirmingRestart(true)}
              >
                새 프로젝트
              </button>
            ))}
          <ThemeToggle />
        </div>
      </header>
      {error && (
        <p className="alert page-alert" role="alert">
          {error}
        </p>
      )}
      <p className={busy ? "working" : "sr-only"} role="status">
        {busy
          ? makingDesign
            ? "결정을 반영해 설계를 만들고 있어요. 시간이 조금 걸려요."
            : "처리하는 중이에요. 모델을 쓸 때는 시간이 조금 걸려요."
          : ""}
      </p>
      {restoring ? (
        <p className="panel muted">저장된 여정을 불러오는 중이에요…</p>
      ) : !journey ? (
        <main className="start-page">{startChat(null)}</main>
      ) : briefing ? (
        <main className={prompt.type === "gcb" ? "start-page" : "brief-page"}>
          {prompt.type === "gcb" ? (
            startChat(journey)
          ) : (
            <ClarifyForm prompt={prompt} busy={busy} act={act} />
          )}
        </main>
      ) : finished ? (
        <>
          <ProgressRail journey={journey} busy={busy} act={actAndShowCard} />
          <main className="done-page">
            <CompletedView
              journey={journey}
              onRestart={restart}
              side={side}
              onSide={setSide}
              moduleChat={
                <ModuleChat
                  journey={journey}
                  busy={busy}
                  onSend={(text) =>
                    changeInPlace((current) => sendModuleMessage(current, text))
                  }
                  onUndo={() => changeInPlace(undoModule)}
                />
              }
              graph={
                <BlueprintPanel
                  journey={journey}
                  busy={busy}
                  act={actAndShowCard}
                  onLayerChange={(layer) => {
                    if (layer === "order") setSide("chat");
                  }}
                  editModule={
                    journey.module_mode === "closed"
                      ? undefined
                      : (change) =>
                          changeInPlace((current) =>
                            editModule(current, change),
                          )
                  }
                />
              }
            />
          </main>
        </>
      ) : (
        <>
          <ProgressRail journey={journey} busy={busy} act={actAndShowCard} />
          <main className={`workspace${cardOpen ? "" : " no-card"}`}>
            {stacked ? [...panels!].reverse() : panels}
          </main>
        </>
      )}
    </div>
  );
}
