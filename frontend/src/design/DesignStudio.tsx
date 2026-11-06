import { useCallback, useEffect, useMemo, useState } from "react";
import { getDesign, getJourney } from "../api";
import {
  applyNodeChanges,
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useReactFlow,
} from "@xyflow/react";
import type { Connection, Edge, NodeChange, NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { checkDesign } from "./check";
import type { Issue } from "./check";
import {
  addEdge,
  addNode,
  formatPorts,
  idProblem,
  parsePorts,
  removeElements,
  renameNode,
  setEntry,
  summarizeChanges,
  toggleExit,
  updateEdge,
  updateNode,
} from "./edit";
import {
  canvasHeight,
  edgeId,
  NODE_HEIGHT,
  NODE_WIDTH,
  SIDE_IN,
  SIDE_OUT,
  toFlowEdges,
  toFlowNodes,
} from "./graph";
import type { FlowNode, Point } from "./graph";
import type { DesignCase } from "./mock";
import { loadDesignCases } from "./source";
import { KIND_LABEL } from "./types";
import type { Design, DesignEdge, DesignNode, NodeKind } from "./types";
import "./studio.css";

const ACCESS_LABEL = {
  read: "읽기",
  write: "서비스 안에 저장",
  external_write: "외부에 쓰기",
};

type Selection =
  | { type: "node"; id: string }
  | { type: "edge"; source: string; target: string }
  | null;

const FIT_OPTIONS = { padding: 0.08, maxZoom: 1 };

const ARIA_LABELS = {
  "controls.ariaLabel": "그래프 보기 조작",
  "controls.zoomIn.ariaLabel": "확대",
  "controls.zoomOut.ariaLabel": "축소",
  "controls.fitView.ariaLabel": "화면에 맞추기",
};

function DesignNodeCard({ data, selected }: NodeProps<FlowNode>) {
  const { node, isEntry, isExit, issues, highlighted, loopLimit } = data;
  const classes = [
    "flow-node",
    node.kind,
    selected && "selected",
    highlighted && "highlighted",
  ];
  return (
    <div
      className={classes.filter(Boolean).join(" ")}
      style={{ width: NODE_WIDTH, minHeight: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flow-node-tags">
        <span>{KIND_LABEL[node.kind]}</span>
        {isEntry && <span className="tag">시작</span>}
        {isExit && <span className="tag">끝</span>}
        {loopLimit !== null && (
          <span className="tag">최대 {loopLimit}회 반복</span>
        )}
      </div>
      <strong>{node.id}</strong>
      <p>{node.responsibility}</p>
      {issues > 0 && (
        <span className="flow-node-issue">확인할 점 {issues}건</span>
      )}
      <Handle type="source" position={Position.Bottom} />
      <Handle
        type="source"
        id={SIDE_OUT}
        className="side"
        isConnectable={false}
        position={Position.Right}
        style={{ top: "35%" }}
      />
      <Handle
        type="target"
        id={SIDE_IN}
        className="side"
        isConnectable={false}
        position={Position.Right}
        style={{ top: "65%" }}
      />
    </div>
  );
}

/** Brings a new node into view, which an initial fit does not do. */
function RefitOnChange({ signal }: { signal: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const timer = setTimeout(() => void fitView(FIT_OPTIONS), 50);
    return () => clearTimeout(timer);
  }, [signal, fitView]);
  return null;
}

const NODE_TYPES = { design: DesignNodeCard };

/** Commits on blur so one edit is one undo step. The key refreshes it after undo. */
function TextField({
  label,
  value,
  onCommit,
  rows,
  hint,
}: {
  label: string;
  value: string;
  onCommit: (next: string) => void;
  rows?: number;
  hint?: string;
}) {
  const commit = (next: string) => {
    if (next !== value) onCommit(next);
  };
  return (
    <label className="field" key={value}>
      <span>{label}</span>
      {rows ? (
        <textarea
          rows={rows}
          defaultValue={value}
          onBlur={(event) => commit(event.target.value)}
        />
      ) : (
        <input
          defaultValue={value}
          onBlur={(event) => commit(event.target.value)}
        />
      )}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

function RequiredText({
  label,
  value,
  onCommit,
  rows = 2,
}: {
  label: string;
  value: string;
  onCommit: (next: string) => void;
  rows?: number;
}) {
  return (
    <TextField
      label={label}
      value={value}
      rows={rows}
      onCommit={(next) => {
        if (next.trim()) onCommit(next.trim());
      }}
    />
  );
}

function NodePanel({
  design,
  node,
  issues,
  commit,
  select,
}: {
  design: Design;
  node: DesignNode;
  issues: Issue[];
  commit: (next: Design) => void;
  select: (next: Selection) => void;
}) {
  const [idError, setIdError] = useState("");
  const [target, setTarget] = useState("");
  const { entry, exits, edges } = design.workflow;
  const outgoing = edges.filter((edge) => edge.source === node.id);
  const incoming = edges.filter((edge) => edge.target === node.id);
  const options = design.nodes.filter(
    (other) =>
      other.id !== node.id &&
      !outgoing.some((edge) => edge.target === other.id),
  );
  const change = (patch: Parameters<typeof updateNode>[2]) =>
    commit(updateNode(design, node.id, patch));
  const mine = issues.filter((issue) => issue.nodeIds.includes(node.id));
  const served = design.requirements.filter((r) =>
    r.node_ids.includes(node.id),
  );

  return (
    <>
      <div className="panel-head">
        <h2>{node.id}</h2>
        <button className="link" onClick={() => select(null)}>
          전체 보기
        </button>
      </div>
      <p className="muted">
        {KIND_LABEL[node.kind]} 노드
        {served.length > 0 &&
          ` · 맡은 요구사항 ${served.map((r) => r.id).join(", ")}`}
      </p>
      {mine.map((issue) => (
        <p
          className={issue.severity === "error" ? "alert" : "note warn"}
          key={issue.message}
        >
          {issue.message}
        </p>
      ))}
      <RequiredText
        label="하는 일"
        value={node.responsibility}
        rows={3}
        onCommit={(responsibility) => change({ responsibility })}
      />
      <TextField
        label="받는 값"
        value={formatPorts(node.inputs)}
        rows={2}
        hint="한 줄에 하나씩, 이름: 형식"
        onCommit={(text) => change({ inputs: parsePorts(text) })}
      />
      <TextField
        label="내보내는 값"
        value={formatPorts(node.outputs)}
        rows={2}
        hint="한 줄에 하나씩, 이름: 형식"
        onCommit={(text) => change({ outputs: parsePorts(text) })}
      />
      <RequiredText
        label="끝났다고 보는 기준"
        value={node.done_when}
        onCommit={(done_when) => change({ done_when })}
      />
      <RequiredText
        label="실패하면"
        value={node.on_failure}
        onCommit={(on_failure) => change({ on_failure })}
      />
      {node.model && (
        <RequiredText
          label="필요한 모델 능력"
          value={node.model.capability}
          onCommit={(capability) =>
            change({ model: { ...node.model!, capability } })
          }
        />
      )}
      {node.model && (
        <p className="muted">허용 제공자: {node.model.provider_scope}</p>
      )}

      <h3>쓰는 도구</h3>
      {node.tools.length === 0 ? (
        <p className="muted">도구를 쓰지 않아요.</p>
      ) : (
        <ul className="plain-list">
          {node.tools.map((tool) => (
            <li key={tool.name}>
              <span>
                <strong>{tool.name}</strong> ({ACCESS_LABEL[tool.access]})
                <br />
                <span className="muted">{tool.reason}</span>
              </span>
              <button
                aria-label={`도구 ${tool.name} 빼기`}
                onClick={() =>
                  change({
                    tools: node.tools.filter((item) => item.name !== tool.name),
                  })
                }
              >
                빼기
              </button>
            </li>
          ))}
        </ul>
      )}

      <h3>연결</h3>
      <div className="row">
        <button
          disabled={entry === node.id}
          onClick={() => commit(setEntry(design, node.id))}
        >
          {entry === node.id ? "시작 노드예요" : "시작으로 지정"}
        </button>
        <button onClick={() => commit(toggleExit(design, node.id))}>
          {exits.includes(node.id) ? "끝 지정 해제" : "끝으로 지정"}
        </button>
      </div>
      {incoming.length > 0 && (
        <p className="muted">
          들어오는 곳: {incoming.map((edge) => edge.source).join(", ")}
        </p>
      )}
      <ul className="plain-list">
        {outgoing.map((edge) => (
          <li key={edge.target}>
            <button
              className="link"
              onClick={() =>
                select({
                  type: "edge",
                  source: edge.source,
                  target: edge.target,
                })
              }
            >
              다음: {edge.target}
              {edge.on_failure && " (실패 시)"}
              {edge.condition && ` (${edge.condition})`}
            </button>
            <button
              aria-label={`${edge.target}로 가는 연결 삭제`}
              onClick={() => commit(removeElements(design, [], [edge]))}
            >
              삭제
            </button>
          </li>
        ))}
      </ul>
      {options.length > 0 && (
        <div className="row">
          <label className="field grow">
            <span>다음 노드 연결</span>
            <select
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              <option value="">노드를 고르세요</option>
              {options.map((other) => (
                <option key={other.id} value={other.id}>
                  {other.id}
                </option>
              ))}
            </select>
          </label>
          <button
            disabled={!target}
            onClick={() => {
              commit(addEdge(design, node.id, target));
              setTarget("");
            }}
          >
            연결
          </button>
        </div>
      )}

      <h3>노드 관리</h3>
      <label className="field" key={node.id}>
        <span>노드 이름</span>
        <input
          defaultValue={node.id}
          aria-invalid={Boolean(idError)}
          onBlur={(event) => {
            const next = event.target.value.trim();
            if (next === node.id) {
              setIdError("");
              return;
            }
            const problem = idProblem(design, node.id, next);
            setIdError(problem ?? "");
            if (!problem) {
              commit(renameNode(design, node.id, next));
              select({ type: "node", id: next });
            }
          }}
        />
        {idError && (
          <small className="field-error" role="alert">
            {idError}
          </small>
        )}
      </label>
      <button
        className="danger"
        onClick={() => {
          commit(removeElements(design, [node.id]));
          select(null);
        }}
      >
        이 노드 삭제
      </button>
    </>
  );
}

function EdgePanel({
  design,
  edge,
  commit,
  select,
}: {
  design: Design;
  edge: DesignEdge;
  commit: (next: Design) => void;
  select: (next: Selection) => void;
}) {
  const { source, target } = edge;
  return (
    <>
      <div className="panel-head">
        <h2>연결</h2>
        <button className="link" onClick={() => select(null)}>
          전체 보기
        </button>
      </div>
      <p>
        {source} → {target}
      </p>
      <TextField
        label="이 길로 가는 조건"
        value={edge.condition ?? ""}
        hint="비워 두면 항상 이 길로 가요"
        onCommit={(text) =>
          commit(
            updateEdge(design, source, target, {
              condition: text.trim() || null,
            }),
          )
        }
      />
      <label className="check">
        <input
          type="checkbox"
          checked={edge.on_failure}
          onChange={(event) =>
            commit(
              updateEdge(design, source, target, {
                on_failure: event.target.checked,
              }),
            )
          }
        />
        실패했을 때 가는 길이에요
      </label>
      <button
        className="danger"
        onClick={() => {
          commit(removeElements(design, [], [edge]));
          select(null);
        }}
      >
        이 연결 삭제
      </button>
    </>
  );
}

function Overview({
  design,
  issues,
  changes,
  highlight,
  setHighlight,
  select,
}: {
  design: Design;
  issues: Issue[];
  changes: string[];
  highlight: string | null;
  setHighlight: (id: string | null) => void;
  select: (next: Selection) => void;
}) {
  const known = new Set(design.nodes.map((node) => node.id));
  const errors = issues.filter((issue) => issue.severity === "error").length;
  return (
    <>
      <h2>
        {errors > 0 ? `고쳐야 할 점 ${errors}건` : "구조에 막히는 곳이 없어요"}
      </h2>
      <p className="muted">
        구조만 검사한 결과예요. 내 문제를 푸는 설계인지는 아래 요구사항을 보고
        판단해 주세요.
      </p>

      {(issues.length > 0 ||
        design.unknowns.length > 0 ||
        design.warnings.length > 0) && (
        <>
          <h3>먼저 확인할 것</h3>
          <ul className="plain-list issues">
            {issues.map((issue) => (
              <li key={issue.message} className={issue.severity}>
                {issue.nodeIds.length > 0 ? (
                  <button
                    className="link"
                    onClick={() =>
                      select({ type: "node", id: issue.nodeIds[0] })
                    }
                  >
                    {issue.message}
                  </button>
                ) : (
                  <span>{issue.message}</span>
                )}
              </li>
            ))}
            {design.unknowns.map((unknown) => (
              <li key={unknown.text}>
                <span>
                  {unknown.blocks_confirmation
                    ? "정해야 진행해요: "
                    : "아직 몰라요: "}
                  {unknown.text}
                </span>
              </li>
            ))}
            {design.warnings.map((warning) => (
              <li key={warning}>
                <span>주의: {warning}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>요구사항</h3>
      <p className="muted">누르면 맡은 노드를 그래프에 표시해요.</p>
      <ul className="requirements">
        {design.requirements.map((requirement) => {
          const owners = requirement.node_ids.filter((id) => known.has(id));
          const active = highlight === requirement.id;
          return (
            <li key={requirement.id}>
              <button
                className={active ? "requirement active" : "requirement"}
                aria-pressed={active}
                onClick={() => setHighlight(active ? null : requirement.id)}
              >
                <strong>{requirement.problem}</strong>
                <span className="muted">
                  성공하면: {requirement.success_example}
                </span>
                <span className="muted">
                  {requirement.evidence
                    ? `사용자 글: "${requirement.evidence}"`
                    : "가정이에요. 사용자 글에 근거가 없어요."}
                </span>
                {owners.length > 0 ? (
                  <span>맡은 노드: {owners.join(", ")}</span>
                ) : (
                  <span className="field-error">맡은 노드가 없어요</span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      <h3>바꾼 내용</h3>
      {changes.length === 0 ? (
        <p className="muted">처음 설계 그대로예요.</p>
      ) : (
        <ul>
          {changes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function Studio({ item }: { item: DesignCase }) {
  const [history, setHistory] = useState({
    past: [] as Design[],
    present: item.design,
    future: [] as Design[],
  });
  const design = history.present;
  const [selection, setSelection] = useState<Selection>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [moved, setMoved] = useState<Map<string, Point>>(new Map());
  const [flowNodes, setFlowNodes] = useState<FlowNode[]>([]);

  const commit = useCallback((next: Design) => {
    setHistory((old) =>
      next === old.present
        ? old
        : { past: [...old.past, old.present], present: next, future: [] },
    );
  }, []);
  const undo = () =>
    setHistory((old) => ({
      past: old.past.slice(0, -1),
      present: old.past[old.past.length - 1],
      future: [old.present, ...old.future],
    }));
  const redo = () =>
    setHistory((old) => ({
      past: [...old.past, old.present],
      present: old.future[0],
      future: old.future.slice(1),
    }));

  const issues = useMemo(() => checkDesign(design), [design]);
  const changes = useMemo(
    () => summarizeChanges(item.design, design),
    [item.design, design],
  );
  const selectedNode =
    selection?.type === "node"
      ? design.nodes.find((node) => node.id === selection.id)
      : undefined;
  const selectedEdge =
    selection?.type === "edge"
      ? design.workflow.edges.find(
          (edge) =>
            edge.source === selection.source &&
            edge.target === selection.target,
        )
      : undefined;
  const highlightedIds =
    design.requirements.find((requirement) => requirement.id === highlight)
      ?.node_ids ?? [];
  const highlightKey = highlightedIds.join("\n");

  useEffect(() => {
    // Keeps the size React Flow measured, which it needs to draw edges.
    setFlowNodes((old) => {
      const measured = new Map(old.map((node) => [node.id, node.measured]));
      return toFlowNodes(
        design,
        moved,
        issues,
        selectedNode?.id ?? null,
        highlightKey ? highlightKey.split("\n") : [],
      ).map((node) => ({ ...node, measured: measured.get(node.id) }));
    });
  }, [design, moved, issues, selectedNode?.id, highlightKey]);

  const flowEdges = useMemo(
    () =>
      toFlowEdges(
        design,
        selectedEdge ? edgeId(selectedEdge.source, selectedEdge.target) : null,
      ),
    [design, selectedEdge],
  );

  const onNodesChange = useCallback((changes: NodeChange<FlowNode>[]) => {
    // Selection and removal go through the design, so this applies only moves and measurements.
    const local = changes.filter(
      (c) => c.type === "position" || c.type === "dimensions",
    );
    setFlowNodes((old) => applyNodeChanges(local, old));
  }, []);

  function add(kind: NodeKind) {
    const result = addNode(design, kind);
    commit(result.design);
    setSelection({ type: "node", id: result.id });
  }

  return (
    <div className="studio-body">
      <div className="studio-main">
        <div className="studio-tools" role="toolbar" aria-label="설계 수정">
          <button onClick={() => add("code")}>코드 노드 추가</button>
          <button onClick={() => add("agent")}>에이전트 노드 추가</button>
          <button onClick={() => add("human")}>사람 노드 추가</button>
          <span className="tool-gap" />
          <button disabled={!history.past.length} onClick={undo}>
            되돌리기
          </button>
          <button disabled={!history.future.length} onClick={redo}>
            다시 실행
          </button>
          <button
            disabled={moved.size === 0}
            onClick={() => setMoved(new Map())}
          >
            자동 배치
          </button>
        </div>
        <div className="studio-canvas" style={{ height: canvasHeight(design) }}>
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onNodeDragStop={(_, node) =>
              setMoved((old) => new Map(old).set(node.id, node.position))
            }
            onNodeClick={(_, node) =>
              setSelection({ type: "node", id: node.id })
            }
            onEdgeClick={(_, edge: Edge) =>
              setSelection({
                type: "edge",
                source: edge.source,
                target: edge.target,
              })
            }
            onPaneClick={() => setSelection(null)}
            onConnect={(connection: Connection) =>
              commit(addEdge(design, connection.source, connection.target))
            }
            onDelete={({ nodes, edges }) => {
              commit(
                removeElements(
                  design,
                  nodes.map((node) => node.id),
                  edges,
                ),
              );
              setSelection(null);
            }}
            nodesFocusable={false}
            edgesFocusable={false}
            ariaLabelConfig={ARIA_LABELS}
            deleteKeyCode={["Backspace", "Delete"]}
            zoomOnScroll={false}
            preventScrolling={false}
            fitView
            fitViewOptions={FIT_OPTIONS}
            minZoom={0.3}
          >
            <RefitOnChange signal={`${design.nodes.length}/${moved.size}`} />
            <Background gap={24} color="#e0e3ec" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <details className="studio-outline">
          <summary>글로 보기: 키보드와 화면 낭독기로 노드 고르기</summary>
          <ol>
            {design.nodes.map((node) => {
              const next = design.workflow.edges.filter(
                (edge) => edge.source === node.id,
              );
              return (
                <li key={node.id}>
                  <button
                    className="link"
                    onClick={() => setSelection({ type: "node", id: node.id })}
                  >
                    {node.id}
                  </button>{" "}
                  ({KIND_LABEL[node.kind]}) {node.responsibility}
                  {next.length > 0 && (
                    <span className="muted">
                      {" "}
                      다음: {next.map((edge) => edge.target).join(", ")}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </details>
      </div>
      <aside className="panel studio-panel" aria-label="선택한 항목">
        {selectedNode ? (
          <NodePanel
            key={selectedNode.id}
            design={design}
            node={selectedNode}
            issues={issues}
            commit={commit}
            select={setSelection}
          />
        ) : selectedEdge ? (
          <EdgePanel
            key={edgeId(selectedEdge.source, selectedEdge.target)}
            design={design}
            edge={selectedEdge}
            commit={commit}
            select={setSelection}
          />
        ) : (
          <Overview
            design={design}
            issues={issues}
            changes={changes}
            highlight={highlight}
            setHighlight={setHighlight}
            select={setSelection}
          />
        )}
      </aside>
    </div>
  );
}

/** The design a finished journey produced. Edits stay in this tab until saving exists. */
function JourneyDesign({ journeyId }: { journeyId: string }) {
  const [item, setItem] = useState<DesignCase | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([getDesign(journeyId), getJourney(journeyId)])
      .then(([design, journey]) =>
        setItem({
          id: journeyId,
          title: journey.idea,
          idea: journey.idea,
          design,
        }),
      )
      .catch((error: unknown) =>
        setFailure(
          error instanceof Error ? error.message : "설계를 불러오지 못했어요.",
        ),
      );
  }, [journeyId]);
  return (
    <div className="app studio">
      <header className="topbar">
        <h1>설계 구조 보기</h1>
        <a className="button" href={`/?journey=${journeyId}`}>
          결과로 돌아가기
        </a>
      </header>
      {failure && (
        <p className="note warn" role="alert">
          {failure}
        </p>
      )}
      {!item && !failure && (
        <p className="panel muted">설계를 불러오는 중이에요…</p>
      )}
      {item && (
        <>
          <p className="note">
            {item.idea} 고친 내용은 아직 저장되지 않아요. 빌드 묶음은 처음 만든
            설계 그대로예요.
          </p>
          <Studio key={item.id} item={item} />
        </>
      )}
    </div>
  );
}

export default function DesignStudio({
  journeyId = null,
}: {
  journeyId?: string | null;
}) {
  if (journeyId) return <JourneyDesign journeyId={journeyId} />;
  return <MockDesigns />;
}

function MockDesigns() {
  const cases = useMemo(loadDesignCases, []);
  const [caseId, setCaseId] = useState(cases[0].id);
  const item = cases.find((one) => one.id === caseId)!;
  return (
    <div className="app studio">
      <header className="topbar">
        <h1>설계 구조 보기</h1>
        <label className="case-picker">
          <span>예시</span>
          <select
            value={caseId}
            onChange={(event) => setCaseId(event.target.value)}
          >
            {cases.map((one) => (
              <option key={one.id} value={one.id}>
                {one.title}
              </option>
            ))}
          </select>
        </label>
      </header>
      <p className="note warn">
        <strong>예시 데이터</strong> {item.idea} 모델이 만든 설계가 아니고, 고친
        내용은 저장되지 않아요.
      </p>
      <Studio key={item.id} item={item} />
    </div>
  );
}
