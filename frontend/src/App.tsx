import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { generatePack } from "./api";
import type { GenerateResponse } from "./api";
import { DRAFT_KEY, MAX_DRAFT, downloadMarkdown, toMarkdown } from "./document";

const examples = [
  {
    label: "회의 후속 작업",
    text: "팀 회의가 끝나면 회의록에서 담당자별 할 일을 정리하는 데 시간이 오래 걸려요.",
  },
  {
    label: "학습 자료 정리",
    text: "부트캠프 강의 노트가 흩어져 있어 프로젝트에 필요한 내용을 다시 찾기 어려워요.",
  },
  {
    label: "반복 업무 줄이기",
    text: "매주 여러 파일에서 진행 상황을 복사해 팀 주간 보고서를 작성하는 일이 번거로워요.",
  },
];

type Phase = "idle" | "loading" | "success" | "error";
type View = "result" | "draft";

function restoreDraft(): { content: string; status: string } {
  try {
    const saved = localStorage.getItem(DRAFT_KEY);
    return {
      content: saved?.slice(0, MAX_DRAFT) || "",
      status: saved ? "이 브라우저의 저장된 초안" : "아직 저장하지 않은 초안",
    };
  } catch {
    return {
      content: "",
      status: "브라우저 저장을 사용할 수 없습니다. 다운로드를 이용해 주세요.",
    };
  }
}

export default function App() {
  const [initial] = useState(restoreDraft);
  const [draft, setDraft] = useState(initial.content);
  const [saveStatus, setSaveStatus] = useState(initial.status);
  const [painPoint, setPainPoint] = useState("");
  const [context, setContext] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [view, setView] = useState<View>(initial.content ? "draft" : "result");
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [error, setError] = useState("");
  const [health, setHealth] = useState("확인 중");
  const [checking, setChecking] = useState(false);
  const busy = useRef(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLHeadingElement>(null);
  const length = Array.from(painPoint.trim()).length;
  const contextLength = Array.from(context.trim()).length;
  const valid = length >= 10 && length <= 3000 && contextLength <= 2000;
  const loading = phase === "loading";

  async function checkHealth() {
    setChecking(true);
    try {
      const response = await fetch("/health", {
        signal: AbortSignal.timeout(5000),
      });
      const body = await response.json();
      setHealth(
        response.ok && body.status === "ok"
          ? "API 연결됨"
          : "API 연결 확인 필요",
      );
    } catch {
      setHealth("API 연결 확인 필요");
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    void checkHealth();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    if (!valid) {
      setError("문제는 10~3,000자, 참고 맥락은 2,000자 이내로 입력해 주세요.");
      setPhase("error");
      return;
    }
    busy.current = true;
    setPhase("loading");
    setError("");
    try {
      const next = await generatePack(painPoint, context);
      setResult(next);
      setPhase("success");
      setView("result");
      requestAnimationFrame(() => resultRef.current?.focus());
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "요청에 실패했어요. 다시 시도해 주세요.",
      );
      setPhase("error");
    } finally {
      busy.current = false;
    }
  }

  function saveDraft() {
    try {
      localStorage.setItem(DRAFT_KEY, draft);
      setSaveStatus("이 브라우저에 저장됨 · 서버 저장 아님");
    } catch {
      setSaveStatus("저장하지 못했습니다. 초안을 다운로드해 주세요.");
    }
  }

  function newProject() {
    if (
      (draft || result || painPoint || context) &&
      !window.confirm(
        "현재 작업을 비울까요? 저장된 초안은 새 초안을 저장하기 전까지 유지됩니다. 필요한 내용은 먼저 저장하거나 다운로드하세요.",
      )
    )
      return;
    setPainPoint("");
    setContext("");
    setResult(null);
    setDraft("");
    setError("");
    setPhase("idle");
    setView("result");
    setSaveStatus("새 초안 · 기존 저장본은 유지됩니다");
    promptRef.current?.focus();
  }

  function appendResult() {
    if (!result) return;
    const next = [draft, toMarkdown(result)].filter(Boolean).join("\n\n");
    if (next.length > MAX_DRAFT) {
      setError(
        "초안은 50,000자까지 작성할 수 있어요. 결과를 별도로 다운로드해 주세요.",
      );
      return;
    }
    setDraft(next);
    setView("draft");
    setSaveStatus("변경 사항을 저장해 주세요");
  }

  const headings =
    view === "result" && result
      ? [
          "입력한 문제",
          "목표",
          "가정과 확인할 점",
          "에이전트 구성",
          "작업 흐름",
          "다음 행동",
        ]
      : draft
          .split("\n")
          .filter((line) => /^#{1,3} /.test(line))
          .map((line) => line.replace(/^#+ /, ""));
  const pack = result?.starter_pack;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        작업공간으로 건너뛰기
      </a>
      <aside className="sidebar" aria-label="작업공간 탐색">
        <a className="brand" href="/" aria-label="프로젝트 스타터팩 홈">
          <span className="brand-mark">
            P<span>↗</span>
          </span>
          <span>
            Starter Pack<small>FROM PROBLEM TO PROJECT</small>
          </span>
        </a>
        <button
          className="primary new-button"
          onClick={newProject}
          disabled={loading}
        >
          <span>＋</span> 새 프로젝트
        </button>
        <div className="nav-label">WORKSPACE</div>
        <div className="nav-active">
          <span>▧</span> 프로젝트 스튜디오 <span className="nav-count">01</span>
        </div>
        <section className="outline" aria-label="문서 목차">
          <div className="nav-label">문서 목차</div>
          {headings.length ? (
            <ol>
              {headings.map((heading, i) => (
                <li key={`${i}-${heading}`}>{heading}</li>
              ))}
            </ol>
          ) : (
            <p>
              결과나 초안을 작성하면
              <br />
              목차가 여기에 표시됩니다.
            </p>
          )}
        </section>
        <div className="connection-card">
          <span className="nav-label">CONNECTION</span>
          <strong>
            <span className="status-dot" /> 모델 미연결
          </strong>
          <p>
            지금은 예시 결과로
            <br />
            작업 흐름을 확인할 수 있어요.
          </p>
          <div className="api-health" role="status">
            {checking ? "API 확인 중…" : health}
          </div>
          <button
            className="text-button"
            onClick={() => void checkHealth()}
            disabled={checking}
          >
            연결 다시 확인 ↻
          </button>
        </div>
        <div className="sidebar-footer">작은 문제에서, 첫 프로젝트까지.</div>
      </aside>

      <main id="workspace">
        <header className="page-header">
          <div>
            <div className="eyebrow">YOUR NEXT PROJECT STARTS HERE</div>
            <h1>
              프로젝트 스튜디오<span>.</span>
            </h1>
            <p>불편했던 순간을, 시작할 수 있는 프로젝트로.</p>
          </div>
          <span className="mode-badge">
            LOCAL PREVIEW <span>·</span> 예시 모드
          </span>
        </header>
        <div className="steps" aria-label="작업 순서">
          <div>
            <span>01</span>
            <strong>문제 적기</strong>
            <small>해결하고 싶은 불편</small>
          </div>
          <i>→</i>
          <div>
            <span>02</span>
            <strong>구조 확인</strong>
            <small>목표와 작업 흐름</small>
          </div>
          <i>→</i>
          <div>
            <span>03</span>
            <strong>다음 행동</strong>
            <small>초안으로 구체화</small>
          </div>
        </div>

        <div className="workspace-grid">
          <article className="canvas panel">
            <div className="panel-heading">
              <h2 tabIndex={-1} ref={resultRef}>
                프로젝트 캔버스
              </h2>
              <span className="caption">나만의 시작점</span>
            </div>
            <div className="canvas-toolbar">
              <div className="view-buttons" aria-label="문서 보기">
                <button
                  aria-pressed={view === "result"}
                  className={view === "result" ? "selected" : ""}
                  onClick={() => setView("result")}
                >
                  설계 결과
                </button>
                <button
                  aria-pressed={view === "draft"}
                  className={view === "draft" ? "selected" : ""}
                  onClick={() => setView("draft")}
                >
                  내 초안
                </button>
              </div>
              {view === "draft" ? (
                <button onClick={saveDraft}>저장</button>
              ) : (
                result && (
                  <button
                    onClick={() =>
                      downloadMarkdown(
                        toMarkdown(result),
                        "starter-pack-example.md",
                      )
                    }
                  >
                    ↓ 결과 다운로드
                  </button>
                )
              )}
            </div>
            {view === "draft" ? (
              <div className="draft-content">
                <label htmlFor="draft">
                  Markdown 초안 <span>자유롭게 적고 다듬어 보세요.</span>
                </label>
                <textarea
                  id="draft"
                  value={draft}
                  maxLength={MAX_DRAFT}
                  onChange={(event) => {
                    setDraft(event.target.value);
                    setSaveStatus("변경 사항을 저장해 주세요");
                  }}
                  placeholder={
                    "# 프로젝트 이름\n\n## 해결할 문제\n어떤 불편을 해결하고 싶나요?\n\n## 다음 행동\n- 가장 작은 첫 단계를 적어보세요."
                  }
                />
                <div className="draft-footer">
                  <span role="status">{saveStatus}</span>
                  <span>{draft.length.toLocaleString()} / 50,000</span>
                  <button
                    disabled={!draft.trim()}
                    onClick={() =>
                      downloadMarkdown(draft, "starter-pack-draft.md")
                    }
                  >
                    ↓ 초안 다운로드
                  </button>
                </div>
              </div>
            ) : pack && result ? (
              <div className="result-content">
                <p className="mock-notice">{result.notice}</p>
                {loading && (
                  <p role="status">
                    새 예시 결과를 요청하고 있어요. 아래는 이전 결과입니다.
                  </p>
                )}
                <section>
                  <span className="section-number">01 / PROBLEM</span>
                  <h3>입력한 문제</h3>
                  <p className="problem-quote">{pack.pain_point}</p>
                </section>
                <section>
                  <h3>목표</h3>
                  <p>{pack.goal}</p>
                </section>
                <section>
                  <h3>가정과 확인할 점</h3>
                  <ul>
                    {pack.assumptions.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </section>
                <section>
                  <h3>
                    에이전트 구성{" "}
                    <span className="mini-badge">필요성 미정</span>
                  </h3>
                  <p className="muted">
                    실제 모델 연결 후 일반 코드·단일 에이전트·다중 에이전트를
                    비교합니다.
                  </p>
                  <div className="role-list">
                    {pack.agent_blueprint.roles.map((role, i) => (
                      <span key={i}>{role}</span>
                    ))}
                  </div>
                </section>
                <section>
                  <h3>작업 흐름</h3>
                  <ol className="workflow">
                    {pack.agent_blueprint.workflow.map((step, i) => (
                      <li key={i}>
                        <span>{i + 1}</span>
                        {step}
                      </li>
                    ))}
                  </ol>
                </section>
                <section className="next-steps">
                  <h3>다음 행동</h3>
                  <ol>
                    {pack.next_steps.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ol>
                </section>
                <button className="secondary" onClick={appendResult}>
                  ＋ 결과를 내 초안에 추가
                </button>
              </div>
            ) : (
              <div className="empty-state">
                <div className="paper-illustration" aria-hidden="true">
                  <span>↗</span>
                  <i />
                  <i />
                  <i />
                  <b>＋</b>
                </div>
                <span className="eyebrow">A SMALL START, A REAL PROJECT</span>
                <h3>
                  좋은 시작은
                  <br />
                  작은 불편에서 나와요.
                </h3>
                <p>
                  오른쪽에 해결하고 싶은 문제를 적어주세요.
                  <br />
                  목표, 작업 흐름, 다음 행동을 이곳에서 확인해요.
                </p>
                <button
                  className="secondary"
                  onClick={() => promptRef.current?.focus()}
                >
                  첫 문제 적어보기 ↗
                </button>
                <div className="empty-footnote">
                  또는{" "}
                  <button
                    className="text-button"
                    onClick={() => setView("draft")}
                  >
                    내 초안부터 작성하기
                  </button>
                </div>
              </div>
            )}
          </article>

          <section
            className="assistant-panel panel"
            aria-labelledby="assistant-title"
          >
            <div className="panel-heading">
              <h2 id="assistant-title">
                <span className="sparkle">✦</span> 설계 어시스턴트
              </h2>
              <span className="mini-badge">예시</span>
            </div>
            <div className="assistant-intro">
              <span className="assistant-avatar" aria-hidden="true">
                ✦
              </span>
              <div>
                <strong>어떤 문제를 해결하고 싶나요?</strong>
                <p>
                  누가, 언제, 무엇 때문에 불편한지
                  <br />
                  편하게 이야기해 주세요.
                </p>
              </div>
            </div>
            <form onSubmit={submit} noValidate>
              <label htmlFor="pain-point">
                해결하고 싶은 문제 <span>필수</span>
              </label>
              <textarea
                ref={promptRef}
                id="pain-point"
                value={painPoint}
                disabled={loading}
                onChange={(event) => setPainPoint(event.target.value)}
                aria-describedby="input-hint"
                aria-invalid={phase === "error" && !valid}
                placeholder="예: 팀 회의가 끝나면 담당자별 할 일을 정리하는 데 시간이 오래 걸려요."
                rows={6}
              />
              <div className="field-meta" id="input-hint">
                <span>10~3,000자</span>
                <span className={length > 3000 ? "invalid" : ""}>
                  {length.toLocaleString()}자
                </span>
              </div>
              <div className="example-chips">
                {examples.map((example) => (
                  <button
                    key={example.label}
                    type="button"
                    disabled={loading}
                    onClick={() => {
                      setPainPoint(example.text);
                      promptRef.current?.focus();
                    }}
                  >
                    {example.label} ↗
                  </button>
                ))}
              </div>
              <label htmlFor="context">
                참고 맥락 <span>선택</span>
              </label>
              <textarea
                id="context"
                value={context}
                disabled={loading}
                onChange={(event) => setContext(event.target.value)}
                aria-describedby="context-hint"
                rows={3}
                placeholder="누가 사용할지, 현재 쓰는 도구나 제약을 알려주세요."
              />
              <div className="field-meta" id="context-hint">
                <span>최대 2,000자</span>
                <span className={contextLength > 2000 ? "invalid" : ""}>
                  {contextLength.toLocaleString()}자
                </span>
              </div>
              <button
                className="primary generate-button"
                type="submit"
                disabled={loading || !valid}
              >
                {loading ? "예시 결과를 불러오는 중…" : "예시 스타터팩 만들기"}{" "}
                <span aria-hidden="true">{loading ? "◌" : "↑"}</span>
              </button>
              <p className="form-notice">
                모델 호출 없이 고정 템플릿을 반환합니다.
                <br />
                입력은 서버에 저장하지 않습니다.
              </p>
            </form>
            <div className="request-status" role="status" aria-live="polite">
              {phase === "loading"
                ? "API에 요청하고 있어요."
                : phase === "success"
                  ? "예시 결과가 준비됐어요. 캔버스에서 확인해 주세요."
                  : ""}
            </div>
            {error && (
              <div className="error-box" role="alert">
                {error}
                <p>입력과 초안은 유지됩니다.</p>
              </div>
            )}
            <div className="assistant-footer">
              <span>↳</span> 구체적일수록, 다음 단계가 선명해져요.
            </div>
          </section>
        </div>
        <footer className="page-footer">
          <span>
            PROJECT STARTER PACK <b> / </b> WORKSPACE 01
          </span>
          <span>예시 결과를 확인하고, 내 생각으로 발전시켜 보세요.</span>
        </footer>
      </main>
    </div>
  );
}
