import { useEffect, useRef, useState } from "react";
import { ApiError, getJourney, sendAction, startJourney } from "./api";
import type { Action, Journey } from "./api";
import {
  ClarifyForm,
  CompletedView,
  DecisionView,
  GcbForm,
  IssuesView,
  ProgressRail,
  StartForm,
} from "./components";

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

export default function App() {
  const [journey, setJourney] = useState<Journey | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(() => savedJourneyId() !== null);
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

  function restart() {
    rememberJourney(null);
    setJourney(null);
    setError("");
  }

  const prompt = journey?.prompt ?? null;
  return (
    <div className="app">
      <header className="topbar">
        <h1>프로젝트 스타터팩</h1>
        {journey && journey.status !== "completed" && (
          <button className="link" onClick={restart}>
            새 프로젝트
          </button>
        )}
      </header>
      {journey?.notice && <p className="notice">{journey.notice}</p>}
      {error && (
        <p className="alert page-alert" role="alert">
          {error}
        </p>
      )}
      <p className={busy ? "working" : "sr-only"} role="status">
        {busy ? "처리하는 중이에요. 모델을 쓸 때는 시간이 조금 걸려요." : ""}
      </p>
      {restoring ? (
        <p className="panel muted">저장된 여정을 불러오는 중이에요…</p>
      ) : !journey ? (
        <main className="single">
          <StartForm busy={busy} onStart={start} />
        </main>
      ) : (
        <main className="layout">
          <ProgressRail journey={journey} busy={busy} act={act} />
          <div>
            {prompt?.type === "gcb" && (
              <GcbForm prompt={prompt} busy={busy} act={act} />
            )}
            {prompt?.type === "clarify" && (
              <ClarifyForm prompt={prompt} busy={busy} act={act} />
            )}
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
            {!prompt && journey.status === "completed" && (
              <CompletedView journey={journey} onRestart={restart} />
            )}
            {!prompt && journey.status !== "completed" && (
              <p className="panel muted">
                다음 단계를 준비하지 못했어요. 페이지를 새로고침해 주세요.
              </p>
            )}
          </div>
        </main>
      )}
    </div>
  );
}
