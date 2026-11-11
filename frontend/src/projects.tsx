import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import type { Journey } from "./api";
import { STAGE_NAMES } from "./components";

/* The project list (WS-001, 2026-11-11). There is no sign-in and no list API, so the list
   lives in this browser only: a server-wide list would show other people's projects.
   Removing a project from the list leaves its journey on the server. */

const KEY = "starter-pack:projects:v1";
const CHANGED = "starter-pack:projects-changed";
const LIMIT = 50;

type ProjectState = "start" | "deciding" | "done";
export type Project = {
  id: string;
  idea: string;
  name: string | null;
  state: ProjectState;
  where: string;
  usedAt: number;
};

const STATE_LABEL: Record<ProjectState, string> = {
  start: "시작 정보 채우는 중",
  deciding: "결정 중",
  done: "설계 완료",
};

function describe(journey: Journey): Pick<Project, "state" | "where"> {
  const prompt = journey.prompt;
  if (prompt?.type === "gcb") {
    const blanks = journey.start?.missing.length ?? 0;
    return {
      state: "start",
      where: blanks > 0 ? `빈칸 ${blanks}개` : "모두 채움",
    };
  }
  if (prompt?.type === "clarify") return { state: "start", where: "추가 질문" };
  if (prompt?.type === "decision") {
    const card = journey.cards.find((c) => c.card_id === prompt.card.card_id);
    return {
      state: "deciding",
      where: card ? `${STAGE_NAMES[card.stage] ?? ""} 단계` : "",
    };
  }
  if (prompt?.type === "issues")
    return { state: "deciding", where: "확인할 문제" };
  if (journey.status === "completed") return { state: "done", where: "" };
  return { state: "deciding", where: "" };
}

function isProject(item: unknown): item is Project {
  const p = item as Project;
  return (
    typeof p === "object" &&
    p !== null &&
    typeof p.id === "string" &&
    typeof p.idea === "string" &&
    (p.name === null || typeof p.name === "string") &&
    p.state in STATE_LABEL &&
    typeof p.where === "string" &&
    typeof p.usedAt === "number"
  );
}

let cachedRaw: string | null | undefined;
let cached: Project[] = [];

/** null when the browser blocks storage; the snapshot stays the same object until it changes. */
function read(): Project[] | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      cached = Array.isArray(parsed)
        ? parsed.filter(isProject).sort((a, b) => b.usedAt - a.usedAt)
        : [];
    } catch {
      cached = [];
    }
  }
  return cached;
}

function write(list: Project[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, LIMIT)));
  } catch {
    return;
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function recordProject(journey: Journey) {
  const list = read();
  if (!list) return;
  const kept = list.find((p) => p.id === journey.journey_id);
  const next: Project = {
    id: journey.journey_id,
    idea: journey.idea,
    name: kept?.name ?? null,
    ...describe(journey),
    usedAt: Date.now(),
  };
  write([next, ...list.filter((p) => p.id !== next.id)]);
}

export function forgetProject(id: string) {
  const list = read();
  if (list) write(list.filter((p) => p.id !== id));
}

function renameProject(id: string, name: string) {
  const list = read();
  if (!list) return;
  const trimmed = name.trim();
  write(
    list.map((p) =>
      p.id === id
        ? { ...p, name: trimmed && trimmed !== p.idea ? trimmed : null }
        : p,
    ),
  );
}

function subscribe(changed: () => void) {
  window.addEventListener("storage", changed);
  window.addEventListener(CHANGED, changed);
  return () => {
    window.removeEventListener("storage", changed);
    window.removeEventListener(CHANGED, changed);
  };
}

export function useProjects(): Project[] | null {
  return useSyncExternalStore(subscribe, read);
}

const titleOf = (p: Project) => p.name ?? p.idea;
const statusOf = (p: Project) =>
  p.where ? `${STATE_LABEL[p.state]} · ${p.where}` : STATE_LABEL[p.state];
const two = (n: number) => String(n).padStart(2, "0");

export function formatUsed(at: number, now = new Date()): string {
  const used = new Date(at);
  const day = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(used)) / 86_400_000);
  if (days === 0)
    return `오늘 ${two(used.getHours())}:${two(used.getMinutes())}`;
  if (days === 1) return "어제";
  const date = `${used.getMonth() + 1}월 ${used.getDate()}일`;
  return used.getFullYear() === now.getFullYear()
    ? date
    : `${used.getFullYear()}년 ${date}`;
}

/** A real link, so a project can also open in a new tab; a plain click stays in this one. */
function ProjectLink({
  project,
  className,
  onOpen,
  children,
  current,
}: {
  project: Project;
  className: string;
  onOpen: (id: string) => void;
  children: ReactNode;
  current?: boolean;
}) {
  function click(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0)
      return;
    event.preventDefault();
    onOpen(project.id);
  }
  return (
    <a
      className={className}
      href={`?journey=${project.id}`}
      aria-current={current ? "true" : undefined}
      onClick={click}
    >
      {children}
    </a>
  );
}

/** A: the three latest projects under the start box. */
export function RecentProjects({
  projects,
  onOpen,
  onAll,
}: {
  projects: Project[];
  onOpen: (id: string) => void;
  onAll: () => void;
}) {
  return (
    <section className="recent" aria-labelledby="recent-title">
      <div className="recent-head">
        <h2 id="recent-title">이어서 하기</h2>
        <button type="button" className="quiet" onClick={onAll}>
          모두 보기 · {projects.length}개
        </button>
      </div>
      {projects.slice(0, 3).map((project) => (
        <ProjectLink
          key={project.id}
          project={project}
          className="recent-row"
          onOpen={onOpen}
        >
          <span className="recent-title">{titleOf(project)}</span>
          <span className="recent-when">{formatUsed(project.usedAt)}</span>
          <span className="recent-status">{statusOf(project)}</span>
        </ProjectLink>
      ))}
    </section>
  );
}

type Filter = "all" | "active" | "done";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "active", label: "진행 중" },
  { value: "done", label: "완료" },
];
const matches = (p: Project, filter: Filter) =>
  filter === "all" || (filter === "done") === (p.state === "done");

function ProjectRow({
  project,
  current,
  busy,
  onOpen,
}: {
  project: Project;
  current: boolean;
  busy: boolean;
  onOpen: (id: string) => void;
}) {
  const [mode, setMode] = useState<"idle" | "menu" | "rename" | "forget">(
    "idle",
  );
  const [draft, setDraft] = useState("");
  const menuButton = useRef<HTMLButtonElement>(null);
  const area = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (mode !== "menu") return;
    const away = (event: Event) => {
      if (!area.current?.contains(event.target as Node)) setMode("idle");
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [mode]);

  function close() {
    setMode("idle");
    menuButton.current?.focus();
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === "Escape" && mode !== "idle") {
      event.stopPropagation();
      close();
    }
  }

  const title = titleOf(project);
  return (
    <div className="project-row" ref={area} onKeyDown={onKey}>
      {mode === "rename" ? (
        <form
          className="project-rename"
          onSubmit={(event) => {
            event.preventDefault();
            renameProject(project.id, draft);
            close();
          }}
        >
          <label htmlFor={`rename-${project.id}`}>새 이름</label>
          <input
            id={`rename-${project.id}`}
            autoFocus
            maxLength={80}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" disabled={!draft.trim()}>
            저장
          </button>
          <button type="button" className="quiet" onClick={close}>
            취소
          </button>
        </form>
      ) : (
        <ProjectLink
          project={project}
          className="project-title"
          onOpen={onOpen}
          current={current}
        >
          <span className="project-name">{title}</span>
          {current && (
            <>
              {" "}
              <span className="project-current">지금 여는 중</span>
            </>
          )}
        </ProjectLink>
      )}
      <span className="project-status">{statusOf(project)}</span>
      <span className="project-when">{formatUsed(project.usedAt)}</span>
      <div className="project-more">
        <button
          type="button"
          ref={menuButton}
          className="quiet"
          aria-label={`${title} 더 보기`}
          aria-expanded={mode === "menu"}
          disabled={busy}
          onClick={() => setMode(mode === "menu" ? "idle" : "menu")}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="5" cy="12" r="1.8" />
            <circle cx="12" cy="12" r="1.8" />
            <circle cx="19" cy="12" r="1.8" />
          </svg>
        </button>
        {mode === "menu" && (
          <div className="project-menu">
            <button
              type="button"
              autoFocus
              onClick={() => {
                setDraft(title);
                setMode("rename");
              }}
            >
              이름 바꾸기
            </button>
            <button
              type="button"
              className="danger"
              onClick={() => setMode("forget")}
            >
              목록에서 지우기
            </button>
          </div>
        )}
      </div>
      {mode === "forget" && (
        <div className="project-confirm" role="alert">
          <span>
            목록에서 지울까요? 이 브라우저의 목록에서만 빠지고, 주소가 있으면
            다시 열 수 있어요.
          </span>
          <button
            type="button"
            className="danger"
            autoFocus
            onClick={() => forgetProject(project.id)}
          >
            지우기
          </button>
          <button type="button" className="quiet" onClick={close}>
            취소
          </button>
        </div>
      )}
    </div>
  );
}

/** B: every project this browser has opened. */
export function ProjectsPage({
  projects,
  currentId,
  busy,
  onOpen,
  onNew,
}: {
  projects: Project[] | null;
  currentId: string | null;
  busy: boolean;
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => heading.current?.focus(), []);

  const list = projects ?? [];
  const words = query.trim().toLowerCase();
  const shown = list.filter(
    (p) =>
      matches(p, filter) &&
      (!words || `${p.name ?? ""} ${p.idea}`.toLowerCase().includes(words)),
  );

  return (
    <div className="projects-page">
      <div className="projects-head">
        <div>
          <h2 ref={heading} tabIndex={-1}>
            내 프로젝트
          </h2>
          <p className="muted">
            이 브라우저에서 연 프로젝트예요. 다른 브라우저나 기기에서는 보이지
            않아요.
          </p>
        </div>
        <button type="button" className="primary" onClick={onNew}>
          새 프로젝트
        </button>
      </div>

      {projects === null ? (
        <p className="alert" role="alert">
          이 브라우저가 저장을 막아 두어 목록을 만들 수 없어요. 프로젝트 주소를
          북마크해 두면 다시 열 수 있어요.
        </p>
      ) : list.length === 0 ? (
        <div className="projects-empty">
          <p>아직 연 프로젝트가 없어요.</p>
          <p className="muted">
            만들고 싶은 서비스를 한 문장으로 적으면 여기에 쌓여요.
          </p>
        </div>
      ) : (
        <>
          <div className="projects-tools">
            <label htmlFor="project-search" className="sr-only">
              프로젝트 찾기
            </label>
            <input
              id="project-search"
              type="search"
              placeholder="아이디어나 이름으로 찾기"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <div
              className="projects-filter"
              role="group"
              aria-label="상태로 거르기"
            >
              {FILTERS.map((option) => (
                <button
                  type="button"
                  key={option.value}
                  className={filter === option.value ? "on" : ""}
                  aria-pressed={filter === option.value}
                  onClick={() => setFilter(option.value)}
                >
                  {option.label}{" "}
                  {list.filter((p) => matches(p, option.value)).length}
                </button>
              ))}
            </div>
          </div>
          {shown.length === 0 ? (
            <p className="projects-empty muted" role="status">
              조건에 맞는 프로젝트가 없어요.
            </p>
          ) : (
            <div className="project-list">
              <div className="project-row project-row-head" aria-hidden="true">
                <span>프로젝트</span>
                <span>지금 단계</span>
                <span>최근 사용</span>
                <span />
              </div>
              {shown.map((project) => (
                <ProjectRow
                  key={project.id}
                  project={project}
                  current={project.id === currentId}
                  busy={busy}
                  onOpen={onOpen}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** C: the idea in the top bar opens the latest projects without leaving the screen. */
export function ProjectSwitcher({
  journey,
  projects,
  busy,
  onOpen,
  onAll,
}: {
  journey: Journey;
  projects: Project[];
  busy: boolean;
  onOpen: (id: string) => void;
  onAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  const area = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (event: Event) => {
      if (!area.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  function close() {
    setOpen(false);
    toggle.current?.focus();
  }

  function pick(id: string) {
    setOpen(false);
    if (id !== journey.journey_id) onOpen(id);
  }

  return (
    <div
      className="switcher"
      ref={area}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) close();
      }}
    >
      <button
        type="button"
        ref={toggle}
        className="switcher-toggle"
        aria-expanded={open}
        aria-controls="switcher-panel"
        aria-label={`프로젝트 바꾸기, 지금: ${journey.idea}`}
        disabled={busy}
        onClick={() => setOpen(!open)}
      >
        <span>{journey.idea}</span>
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div className="switcher-panel" id="switcher-panel">
          <p className="muted">최근 프로젝트</p>
          {projects.slice(0, 5).map((project) => {
            const current = project.id === journey.journey_id;
            return (
              <ProjectLink
                key={project.id}
                project={project}
                className="switcher-row"
                current={current}
                onOpen={pick}
              >
                <span className="switcher-check" aria-hidden="true">
                  {current && (
                    <svg width="16" height="16" viewBox="0 0 24 24">
                      <path d="M5 12l5 5 9-10" />
                    </svg>
                  )}
                </span>
                <span className="switcher-text">
                  <span className="switcher-title">{titleOf(project)}</span>
                  <span className="muted">{statusOf(project)}</span>
                </span>
                <span className="muted">
                  {current ? "지금" : formatUsed(project.usedAt)}
                </span>
              </ProjectLink>
            );
          })}
          <button
            type="button"
            className="switcher-all"
            onClick={() => {
              setOpen(false);
              onAll();
            }}
          >
            모든 프로젝트 보기 · {projects.length}개
          </button>
        </div>
      )}
    </div>
  );
}
