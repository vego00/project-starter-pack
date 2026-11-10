import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import type { Journey } from "./api";

/** Returns an error message, or "" when the server took it. */
export type ModuleSend = (text: string) => Promise<string>;

export function ModuleChat({
  journey,
  busy,
  onSend,
  onUndo,
}: {
  journey: Journey;
  busy: boolean;
  onSend: ModuleSend;
  onUndo: () => Promise<string>;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  const thread = useRef<HTMLDivElement>(null);
  const chat = journey.module_chat;
  const isForm = journey.module_mode === "form";

  useEffect(() => {
    const box = thread.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [chat.length, pending]);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setPending(message);
    setError("");
    const failure = await onSend(message);
    setPending("");
    // The server kept nothing, so the sentence goes back where it was written.
    if (failure) {
      setText(message);
      setError(failure);
    }
  }

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void send();
    }
  }

  async function undo() {
    setError(await onUndo());
  }

  const undoButton = journey.module_undo_count > 0 && (
    <button className="quiet" disabled={busy} onClick={() => void undo()}>
      마지막 변경 되돌리기 ({journey.module_undo_count}번 더 할 수 있어요)
    </button>
  );

  if (isForm)
    return (
      <div className="module-chat">
        <p>
          모델이 연결되지 않아 대화 대신 직접 채워요. 만드는 순서 탭에서 모듈을
          누르고 칸마다 <strong>고치기</strong>를 눌러 주세요.
        </p>
        <p className="muted">
          시작 조건과 규칙 기준은 뺄 수 없어요. 목표치는 숫자로 잴 수 있게
          적어야 저장돼요.
        </p>
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        {undoButton}
      </div>
    );

  return (
    <div className="module-chat">
      <div
        className="chat-thread"
        ref={thread}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="모듈 대화"
      >
        <div className="chat-msg bot">
          <p>
            모듈마다 목표, 이번에 만들 것과 안 만들 것, 정할 목표치를 말로 적어
            주세요. 말한 것만 채우고, 시작 조건은 빼지 않아요.
          </p>
          <p className="muted">
            예: 에이전트는 강의 자료로만 답해요. 음성 입력은 이번에 빼요.
          </p>
        </div>
        {chat.map((turn, index) => (
          <div
            key={index}
            className={`chat-msg ${turn.role === "user" ? "user" : "bot"}`}
          >
            <p>{turn.text}</p>
            {turn.changes.length > 0 && (
              <div className="chat-changes">
                <strong>반영한 곳</strong>
                {turn.changes.map((change) => (
                  <span key={change}>{change}</span>
                ))}
              </div>
            )}
            {turn.rejected.map((reason) => (
              <p key={reason} className="chat-refused">
                {reason}
              </p>
            ))}
          </div>
        ))}
        {pending && (
          <>
            <div className="chat-msg user">
              <p>{pending}</p>
            </div>
            <div className="chat-msg bot">
              <p className="muted">보낸 문장을 정리하는 중이에요…</p>
            </div>
          </>
        )}
      </div>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {undoButton}
      <form className="chat-composer" onSubmit={(event) => void send(event)}>
        <label htmlFor="module-message" className="sr-only">
          모듈에 대해 말하기
        </label>
        <textarea
          id="module-message"
          rows={2}
          maxLength={2000}
          value={text}
          placeholder="말로 적어 주세요"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKey}
        />
        <button className="primary" disabled={busy || !text.trim()}>
          보내기
        </button>
      </form>
    </div>
  );
}
