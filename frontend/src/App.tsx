import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  answerStart,
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
import { AccountMenu, MissingJourney, useAccount } from "./account";
import { BlueprintPanel, SamplePreview } from "./blueprint";
import {
  ClarifyForm,
  CompletedView,
  DecisionView,
  ForkView,
  IssuesView,
  ProgressRail,
} from "./components";
import type { SideView } from "./components";
import { ModuleChat } from "./moduleChat";
import {
  forgetProject,
  ProjectsPage,
  ProjectSwitcher,
  RecentProjects,
  recordProject,
  useProjects,
} from "./projects";
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

// Another tab or request is preparing the card: look again at this pace, not faster.
export const PREPARE_POLL_MS = 3000;
const PREPARE_POLLS = 60;

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));
const keyOf = (journey: Journey) => `${journey.journey_id}:${journey.revision}`;
const isPreparing = (journey: Journey) =>
  journey.prompt?.type === "decision" && journey.prompt.card.preparing;
// The design takes minutes and its request can be cut at 5 minutes; reading again picks it up.
export const DESIGN_POLL_MS = 10_000;
const DESIGN_POLLS = 90; // About 15 minutes: three model calls of up to 280 seconds, and a margin.
const isDesigning = (journey: Journey) => journey.prompt?.type === "designing";

export default function App() {
  const [journey, setJourney] = useState<Journey | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(() => savedJourneyId() !== null);
  const [cardOpen, setCardOpen] = useState(true);
  const [confirmingRestart, setConfirmingRestart] = useState(false);
  const [side, setSide] = useState<SideView>("summary");
  const [listing, setListing] = useState(false);
  // A shared link that does not open: gone, mistyped, or made under another account.
  const [missingLink, setMissingLink] = useState<string | null>(null);
  const projects = useProjects();
  const account = useAccount();
  const stacked = useStacked();
  const inFlight = useRef(false);
  // The card whose `prepare` is running, and the one whose `prepare` failed.
  const preparing = useRef<string | null>(null);
  const [prepareFailed, setPrepareFailed] = useState<string | null>(null);
  // A choice sent while its card was still being prepared (작성자 결정 2026-11-25 (i)).
  const [choosingEarly, setChoosingEarly] = useState(false);
  const shown = useRef<Journey | null>(null);

  function show(next: Journey) {
    const current = shown.current;
    // A choice made during `prepare` can answer after it; the older view must not win.
    if (
      current?.journey_id === next.journey_id &&
      current.revision > next.revision
    )
      return;
    shown.current = next;
    setMissingLink(null);
    setJourney(next);
    rememberJourney(next.journey_id);
    recordProject(next);
  }

  async function prepare(current: Journey) {
    const key = keyOf(current);
    preparing.current = key;
    setPrepareFailed(null);
    try {
      show(await sendAction(current, { action: "prepare" }));
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "stale_revision")
        await waitForPrepared(current);
      else setPrepareFailed(key);
    } finally {
      if (preparing.current === key) preparing.current = null;
    }
  }

  /** Someone else is preparing this card: read it until that is done. */
  async function waitForPrepared(current: Journey) {
    for (let poll = 0; poll < PREPARE_POLLS; poll++) {
      await sleep(PREPARE_POLL_MS);
      if (shown.current?.journey_id !== current.journey_id) return;
      if (shown.current.revision !== current.revision) return;
      try {
        const next = await getJourney(current.journey_id);
        if (next.revision !== current.revision || !isPreparing(next)) {
          show(next);
          return;
        }
      } catch {
        break;
      }
    }
    setPrepareFailed(keyOf(current));
  }

  // The design whose request is running or being waited for, and one that never arrived.
  const designing = useRef<string | null>(null);
  const [designStuck, setDesignStuck] = useState<string | null>(null);

  async function requestDesign(current: Journey) {
    const key = keyOf(current);
    designing.current = key;
    setDesignStuck(null);
    try {
      show(await sendAction(current, { action: "design" }));
    } catch {
      // Cut at 5 minutes, or already being made elsewhere: the server keeps going, so read again.
      await waitForDesign(current);
    } finally {
      if (designing.current === key) designing.current = null;
    }
  }

  async function waitForDesign(current: Journey) {
    for (let poll = 0; poll < DESIGN_POLLS; poll++) {
      await sleep(DESIGN_POLL_MS);
      if (shown.current?.journey_id !== current.journey_id) return;
      try {
        const next = await getJourney(current.journey_id);
        if (!isDesigning(next)) {
          show(next);
          return;
        }
      } catch {
        // A dropped read says nothing about the design; the next one may get through.
      }
    }
    setDesignStuck(keyOf(current));
  }

  useEffect(() => {
    if (!journey || !isDesigning(journey)) return;
    const key = keyOf(journey);
    if (designing.current === key || designStuck === key) return;
    void requestDesign(journey);
  }, [journey, designStuck]);

  useEffect(() => {
    if (!journey || !isPreparing(journey)) return;
    const key = keyOf(journey);
    if (preparing.current === key || prepareFailed === key) return;
    void prepare(journey);
  }, [journey, prepareFailed]);

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
    const link = window.location.pathname + window.location.search;
    const fromLink = new URLSearchParams(window.location.search).has("journey");
    getJourney(id)
      .then(show)
      .catch((failure: unknown) => {
        if (
          failure instanceof ApiError &&
          ["journey_not_found", "invalid_input"].includes(failure.code)
        ) {
          // Keep a link someone opened in the address bar until they choose what to do.
          if (fromLink && failure.code === "journey_not_found")
            setMissingLink(link);
          else rememberJourney(null);
        } else setError(messageOf(failure));
      })
      .finally(() => setRestoring(false));
  }, []);

  function startFresh() {
    setMissingLink(null);
    rememberJourney(null);
    document.getElementById("idea")?.focus();
  }

  function start(idea: string) {
    setMissingLink(null);
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
    // The server holds this choice until the preparation ends, then applies it.
    setChoosingEarly(isPreparing(current) && action.action === "select");
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
    if (["focus", "reopen", "revise", "plan_deploy"].includes(action.action)) {
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
    setMissingLink(null);
    rememberJourney(null);
    setJourney(null);
    setError("");
    setCardOpen(true);
    setConfirmingRestart(false);
    setListing(false);
  }

  function openProject(id: string) {
    void run(async () => {
      try {
        show(await getJourney(id));
        setListing(false);
        setCardOpen(true);
        setConfirmingRestart(false);
      } catch (failure) {
        if (
          failure instanceof ApiError &&
          ["journey_not_found", "invalid_input"].includes(failure.code)
        ) {
          forgetProject(id);
          setError("이 프로젝트를 찾지 못해 목록에서 뺐어요.");
        } else setError(messageOf(failure));
      }
    });
  }

  const prompt = journey?.prompt ?? null;
  const startChat = (current: Journey | null) => (
    <StartChat
      journey={current}
      busy={busy}
      preview={<SamplePreview />}
      recent={
        projects && projects.length > 0 ? (
          <RecentProjects
            projects={projects}
            onOpen={openProject}
            onAll={() => setListing(true)}
          />
        ) : undefined
      }
      notice={
        missingLink !== null && (
          <MissingJourney
            email={account}
            link={missingLink}
            onNew={startFresh}
          />
        )
      }
      onIdea={start}
      onSend={(text, focus) =>
        changeInPlace((j) => sendStartMessage(j, text, focus))
      }
      onEdit={(change) => changeInPlace((j) => editStart(j, change))}
      onAnswer={(change) => changeInPlace((j) => answerStart(j, change))}
      onFill={() => changeInPlace(fillStart)}
      onBegin={() => {
        if (current?.start) act(current.start.submit as Action);
      }}
    />
  );
  const briefing = prompt?.type === "gcb" || prompt?.type === "clarify";
  const designingNow = prompt?.type === "designing";
  // The completion screen opens as soon as the decisions are in, before the design arrives.
  const finished = (!prompt && journey?.status === "completed") || designingNow;
  const inWorkspace = journey !== null && !briefing && !finished && !listing;
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
        <DecisionView
          prompt={prompt}
          busy={busy}
          act={act}
          prepareFailed={prepareFailed === keyOf(journey)}
          onRetryPrepare={() => void prepare(journey)}
        />
      )}
      {prompt?.type === "fork" && (
        <ForkView prompt={prompt} busy={busy} act={act} />
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
        {journey && !listing && (
          <ProjectSwitcher
            journey={journey}
            projects={projects ?? []}
            busy={busy}
            onOpen={openProject}
            onAll={() => setListing(true)}
          />
        )}
        <div className="topbar-actions">
          {journey?.notice && !listing && (
            <span className="topbar-notice">{journey.notice}</span>
          )}
          {listing ? (
            <button className="quiet" onClick={() => setListing(false)}>
              {journey ? "지금 프로젝트로 돌아가기" : "시작 화면으로"}
            </button>
          ) : (
            <button className="quiet" onClick={() => setListing(true)}>
              내 프로젝트
            </button>
          )}
          {journey &&
            !finished &&
            !listing &&
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
          {account && <AccountMenu email={account} />}
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
          ? choosingEarly
            ? "고른 답을 저장하고 있어요. 추천 준비가 끝나면 바로 다음 카드로 넘어가요."
            : "처리하는 중이에요. 모델을 쓸 때는 시간이 조금 걸려요."
          : ""}
      </p>
      {restoring ? (
        <p className="panel muted">저장된 여정을 불러오는 중이에요…</p>
      ) : listing ? (
        <main className="projects-main">
          <ProjectsPage
            projects={projects}
            currentId={journey?.journey_id ?? null}
            busy={busy}
            onOpen={openProject}
            onNew={restart}
          />
        </main>
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
              designing={
                designingNow
                  ? {
                      stuck: designStuck === keyOf(journey),
                      onRetry: () => void requestDesign(journey),
                    }
                  : undefined
              }
              onRestart={restart}
              busy={busy}
              onPlanDeploy={() => actAndShowCard({ action: "plan_deploy" })}
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
