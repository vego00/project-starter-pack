import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, PointerEvent, SVGProps } from "react";
import { designViewUrl, getBlueprintExamples } from "./api";
import { SERVICE_ICONS } from "./serviceIcons";
import type {
  Action,
  BlueprintExample,
  BlueprintGraph,
  BlueprintNode,
  BlueprintNote,
  BlueprintRow,
  BlueprintStep,
  Journey,
  ModuleChange,
  ModulePlan,
} from "./api";

export type Point = { x: number; y: number };
export type Layer = "agent" | "system" | "order";
/** Returns an error message, or "" when the server saved it. */
export type ModuleEdit = (change: ModuleChange) => Promise<string>;

const WIDTH = 176;
const HEIGHT = 96;
const GAP_X = 66;
const GAP_Y = 34;
const PAD = 26;
// Room above and below the row of steps for lines that loop back or skip ahead.
const STEP_LANE_ROOM = 34;
const STEP_LANE_FIRST = 20;
const STEP_LANE_NEXT = 14;
const DRAG_START = 4;
const MAX_LABEL = 11;
// Below this the labels are too small to read, so a narrow panel scrolls instead.
const MIN_SCALE = 0.65;
const MAX_SCALE = 1.5;
const ZOOM_STEP = 1.25;
const ZOOM_MIN = 0.4;
const ZOOM_MAX = 2.5;
const LABEL_LINE = 14;
const KEY_STEP = 16;
const KEY_MOVES: Record<string, Point> = {
  ArrowUp: { x: 0, y: -KEY_STEP },
  ArrowDown: { x: 0, y: KEY_STEP },
  ArrowLeft: { x: -KEY_STEP, y: 0 },
  ArrowRight: { x: KEY_STEP, y: 0 },
};
// Keeps a node a 44px target when the graph is drawn at MIN_SCALE.
const HIT_PAD = 5;

const KIND_LABEL: Record<BlueprintNode["kind"], string> = {
  code: "코드",
  agent: "에이전트",
  human: "사람",
  blank: "미정",
  sys: "시스템",
};

/** Columns by longest path, ignoring the edge that closes a loop. */
export function layoutBlueprint(graph: BlueprintGraph): Record<string, Point> {
  const next = new Map<string, string[]>(
    graph.nodes.map((node) => [node.id, []]),
  );
  const incoming = new Set<string>();
  for (const edge of graph.edges) {
    if (next.has(edge.source) && next.has(edge.target)) {
      next.get(edge.source)!.push(edge.target);
      incoming.add(edge.target);
    }
  }
  const column = new Map<string, number>();
  const visit = (id: string, depth: number, path: Set<string>) => {
    if (path.has(id) || (column.get(id) ?? -1) >= depth) return;
    column.set(id, depth);
    path.add(id);
    next.get(id)!.forEach((target) => visit(target, depth + 1, path));
    path.delete(id);
  };
  for (const node of graph.nodes) {
    if (!incoming.has(node.id)) visit(node.id, 0, new Set());
  }
  for (const node of graph.nodes) {
    if (!column.has(node.id)) visit(node.id, 0, new Set());
  }
  const rows = new Map<number, string[]>();
  for (const node of graph.nodes) {
    const at = column.get(node.id)!;
    rows.set(at, [...(rows.get(at) ?? []), node.id]);
  }
  const tallest = Math.max(1, ...[...rows.values()].map((row) => row.length));
  const points: Record<string, Point> = {};
  for (const [at, row] of rows) {
    const offset = (tallest - row.length) / 2;
    row.forEach((id, index) => {
      points[id] = {
        x: PAD + at * (WIDTH + GAP_X),
        y: PAD + STEP_LANE_ROOM + (index + offset) * (HEIGHT + GAP_Y),
      };
    });
  }
  return points;
}

/** Screen pixels per diagram unit, whichever way the graph is sized right now. */
function drawnScale(svg: SVGSVGElement | null | undefined, width: number) {
  const fromMatrix = svg?.getScreenCTM?.()?.a;
  if (fromMatrix) return fromMatrix;
  const shown = svg?.getBoundingClientRect().width;
  return shown ? shown / width : 1;
}

type DrawnEdge = {
  source: string;
  target: string;
  labels: string[];
  dashed: boolean;
};

/** Parallel edges would share one curve and one label spot, so they are drawn as one. */
export function mergeEdges(edges: BlueprintGraph["edges"]): DrawnEdge[] {
  const merged = new Map<string, DrawnEdge>();
  for (const edge of edges) {
    const key = `${edge.source}>${edge.target}`;
    const drawn = merged.get(key) ?? {
      source: edge.source,
      target: edge.target,
      labels: [],
      dashed: true,
    };
    if (edge.label && !drawn.labels.includes(edge.label)) {
      drawn.labels.push(edge.label);
    }
    drawn.dashed &&= edge.dashed;
    merged.set(key, drawn);
  }
  return [...merged.values()];
}

function EdgeLabel({
  x,
  y,
  labels,
}: {
  x: number;
  y: number;
  labels: string[];
}) {
  if (labels.length === 0) return null;
  return (
    <text
      className="bp-edge-label"
      x={x}
      y={y - ((labels.length - 1) * LABEL_LINE) / 2}
    >
      {labels.map((label, index) => (
        <tspan key={label} x={x} dy={index === 0 ? 0 : LABEL_LINE}>
          {label}
        </tspan>
      ))}
    </text>
  );
}

function shortLabel(label: string, max = MAX_LABEL): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

const SERVICE_W = 112;
const SERVICE_H = 94;
const STACK_W = 172;
const STACK_HEAD = 40;
// Keeps a line a 44px target when the graph is drawn at MIN_SCALE.
const ROW_H = 68;
const MAX_ROW_LABEL = 24;
const TILE = 52;
const GLYPH = 30;
const BOX_PAD = 16;
const BOX_HEAD = 24;
const CELL_GAP = 18;
const COLUMN_GAP = 62;
const BOX_GAP = 26;
const LANE_GAP = 8;
const LANE_CLEARANCE = 12;
const LANE_CORNER = 8;

const SERVICE_GROUPS: { id: string; title: string | null; column: number }[] = [
  { id: "people", title: null, column: 0 },
  { id: "client", title: "사용자 접점", column: 1 },
  { id: "app", title: "서비스", column: 2 },
  { id: "model", title: "모델", column: 3 },
  { id: "data", title: "데이터", column: 3 },
  { id: "ops", title: "운영·배포", column: 4 },
];

// Drawn here for parts no card names a product for, so they never look like a chosen service.
const GENERIC_GLYPHS: Record<string, string> = {
  person:
    "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.5-6.5 8-6.5s8 2.5 8 6.5",
  browser: "M3 5h18v14H3zM3 9h18M6 7h.01M9 7h.01",
  chat: "M4 5h16v11H9l-5 4z",
  document: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7",
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  agent: "M4 4h6v6H4zM14 14h6v6h-6zM10 7h4a3 3 0 0 1 3 3v4",
  database:
    "M4 6c0-3 16-3 16 0v12c0 3-16 3-16 0zM4 6c0 3 16 3 16 0M4 12c0 3 16 3 16 0",
  worker:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3",
  laptop: "M5 5h14v10H5zM2 19h20",
  log: "M4 5h16M4 10h16M4 15h10M4 20h7",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
  memory:
    "M6 6h12v12H6zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4",
  none: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM6 6l12 12",
};

const groupOf = (node: BlueprintNode) => node.group ?? "app";

const sizeOf = (node: BlueprintNode) =>
  node.rows.length > 0
    ? { width: STACK_W, height: STACK_HEAD + node.rows.length * ROW_H }
    : { width: SERVICE_W, height: SERVICE_H };

/** A line of a shared service, handled like a node of its own when pressed. */
const rowNode = (node: BlueprintNode, row: BlueprintRow): BlueprintNode => ({
  ...node,
  id: `${node.id}/${row.card_id}`,
  label: `${row.role}: ${row.label}`,
  card_id: row.card_id,
  rows: [],
});

const noteNode = (note: BlueprintNote): BlueprintNode => ({
  id: `note/${note.card_id}`,
  label: note.label,
  kind: "sys",
  card_id: note.card_id,
  icon: null,
  group: note.group,
  rows: [],
  step: null,
});

const decisionNode = (
  decision: BlueprintStep["decisions"][number],
): BlueprintNode => ({
  id: `decision/${decision.card_id}`,
  label: decision.label,
  kind: "sys",
  card_id: decision.card_id,
  icon: null,
  group: null,
  rows: [],
  step: null,
});

/** Every part of the graph that answers one decision. */
const decisionNodes = (graph: BlueprintGraph) =>
  graph.nodes.flatMap((node) =>
    node.rows.length > 0 ? node.rows.map((row) => rowNode(node, row)) : [node],
  );

/** Boxes in columns, each column centred against the tallest. */
export function layoutSystem(graph: BlueprintGraph): Record<string, Point> {
  const columns = [...new Set(SERVICE_GROUPS.map((group) => group.column))];
  const inGroup = (id: string) =>
    graph.nodes.filter((node) => groupOf(node) === id);
  const boxHeight = (nodes: BlueprintNode[]) =>
    BOX_HEAD +
    BOX_PAD * 2 +
    nodes.reduce((sum, node) => sum + sizeOf(node).height, 0) +
    (nodes.length - 1) * CELL_GAP;
  const stacks = columns.map((column) =>
    SERVICE_GROUPS.filter(
      (group) => group.column === column && inGroup(group.id).length > 0,
    ),
  );
  const heightOf = (stack: typeof SERVICE_GROUPS) =>
    stack.reduce(
      (sum, group, index) =>
        sum + boxHeight(inGroup(group.id)) + (index ? BOX_GAP : 0),
      0,
    );
  const tallest = Math.max(0, ...stacks.map(heightOf));
  const points: Record<string, Point> = {};
  let x = PAD + BOX_PAD;
  for (const stack of stacks.filter((item) => item.length > 0)) {
    const columnWidth = Math.max(
      ...stack.flatMap((group) =>
        inGroup(group.id).map((node) => sizeOf(node).width),
      ),
    );
    let y = PAD + (tallest - heightOf(stack)) / 2;
    for (const group of stack) {
      const nodes = inGroup(group.id);
      let cell = y + BOX_HEAD + BOX_PAD;
      for (const node of nodes) {
        const size = sizeOf(node);
        points[node.id] = { x: x + (columnWidth - size.width) / 2, y: cell };
        cell += size.height + CELL_GAP;
      }
      y += boxHeight(nodes) + BOX_GAP;
    }
    x += columnWidth + BOX_PAD * 2 + COLUMN_GAP;
  }
  return points;
}

function wrapLabel(label: string, width = 12): string[] {
  const lines: string[] = [];
  for (const word of label.split(" ")) {
    const last = lines[lines.length - 1];
    if (last !== undefined && `${last} ${word}`.length <= width) {
      lines[lines.length - 1] = `${last} ${word}`;
    } else {
      lines.push(word);
    }
  }
  return lines.length > 2
    ? [
        lines[0],
        `${lines
          .slice(1)
          .join(" ")
          .slice(0, width - 1)}…`,
      ]
    : lines;
}

/** What a step says on its face: a draft is named by us, a design step by what it does. */
function stepText(node: BlueprintNode, isDraft: boolean) {
  if (!node.step)
    return { title: wrapLabel(node.label, 13), sub: [], code: "" };
  return isDraft
    ? {
        title: wrapLabel(node.label, 13),
        sub: wrapLabel(node.step.line, 17),
        code: "",
      }
    : {
        title: wrapLabel(node.step.line, 13),
        sub: [],
        code: shortLabel(node.label, 24),
      };
}

/** Next-column lines stay curves; one that loops back or skips a step goes around the row. */
function stepRoutes(
  graph: BlueprintGraph,
  point: (id: string) => Point,
): (DrawnEdge & { d: string; labelX: number; labelY: number })[] {
  const points = graph.nodes.map((node) => point(node.id));
  const top = Math.min(...points.map((p) => p.y));
  const bottom = Math.max(...points.map((p) => p.y)) + HEIGHT;
  let over = 0;
  let under = 0;
  return mergeEdges(graph.edges).map((edge) => {
    const from = point(edge.source);
    const to = point(edge.target);
    const back = to.x <= from.x;
    const skips = points.some((p) => p.x > from.x + 1 && p.x < to.x - 1);
    if (!back && !skips) {
      const x1 = from.x + WIDTH;
      const y1 = from.y + HEIGHT / 2;
      const x2 = to.x;
      const y2 = to.y + HEIGHT / 2;
      const bend = Math.max(36, Math.abs(x2 - x1) / 2);
      return {
        ...edge,
        d: `M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2 - 6} ${y2}`,
        labelX: (x1 + x2) / 2,
        labelY: (y1 + y2) / 2 - 5,
      };
    }
    const lane = back
      ? bottom + STEP_LANE_FIRST + under++ * STEP_LANE_NEXT
      : top - STEP_LANE_FIRST - over++ * STEP_LANE_NEXT;
    // Apart at the ends, so a step that loops to itself still draws a line.
    const shift = back ? 24 : 0;
    const startX = from.x + WIDTH / 2 + shift;
    const endX = to.x + WIDTH / 2 - shift;
    return {
      ...edge,
      d: roundedPath([
        { x: startX, y: back ? from.y + HEIGHT : from.y },
        { x: startX, y: lane },
        { x: endX, y: lane },
        { x: endX, y: back ? to.y + HEIGHT + 6 : to.y - 6 },
      ]),
      labelX: (startX + endX) / 2,
      labelY: lane + 4,
    };
  });
}

const MODULE_W = 176;
const MODULE_GATE_H = 60;
const MODULE_H = 92;
const MODULE_PAIR_GAP = 22;
const MODULE_UNIT = MODULE_GATE_H + MODULE_PAIR_GAP + MODULE_H;
const MODULE_COLUMN_GAP = 56;
const MODULE_ROW_GAP = 48;
const MODULE_LANE = 14;
const EMPTY_GRAPH: BlueprintGraph = { nodes: [], edges: [] };
const NO_OFFSET: Point = { x: 0, y: 0 };

/** One column per step of the order, each module under its start conditions. */
export function layoutModules(modules: ModulePlan[]) {
  const columns = [...new Set(modules.map((module) => module.column))].sort(
    (a, b) => a - b,
  );
  const inColumn = (column: number) =>
    modules.filter((module) => module.column === column);
  const heightOf = (count: number) =>
    count * MODULE_UNIT + Math.max(0, count - 1) * MODULE_ROW_GAP;
  const tallest = Math.max(
    0,
    ...columns.map((c) => heightOf(inColumn(c).length)),
  );
  const at: Record<string, Point> = {};
  columns.forEach((column, index) => {
    const members = inColumn(column);
    const top = PAD + (tallest - heightOf(members.length)) / 2;
    members.forEach((module, row) => {
      at[module.id] = {
        x: PAD + index * (MODULE_W + MODULE_COLUMN_GAP),
        y: top + row * (MODULE_UNIT + MODULE_ROW_GAP),
      };
    });
  });
  return {
    at,
    width:
      PAD * 2 +
      columns.length * MODULE_W +
      Math.max(0, columns.length - 1) * MODULE_COLUMN_GAP +
      MODULE_LANE,
    height: PAD * 2 + tallest,
  };
}

const moduleKey = (part: "gate" | "module", id: string) => `${part}:${id}`;

// Which module of the build order makes each box of the system view.
const GROUP_MODULE: Record<string, string> = {
  client: "client",
  app: "api",
  model: "agent",
  data: "data",
  ops: "ops",
};

function ModuleDiagram({
  modules,
  at,
  open,
  onPick,
}: {
  modules: ModulePlan[];
  at: Record<string, Point>;
  open: string | null;
  onPick: (key: string) => void;
}) {
  const gateMid = (id: string) => at[id].y + MODULE_GATE_H / 2;
  const moduleTop = (id: string) => at[id].y + MODULE_GATE_H + MODULE_PAIR_GAP;
  const edges = modules.flatMap((module) =>
    module.after
      .filter((after) => at[after.module])
      .map((after) => {
        const from = at[after.module];
        const to = at[module.id];
        if (after.gate_only) {
          // Only the other module's start conditions hold this one back.
          const lane = from.x + MODULE_W + MODULE_LANE;
          return {
            key: `${after.module}>${module.id}`,
            dashed: true,
            d: roundedPath([
              { x: from.x + MODULE_W, y: gateMid(after.module) },
              { x: lane, y: gateMid(after.module) },
              { x: lane, y: gateMid(module.id) },
              { x: to.x + MODULE_W + 6, y: gateMid(module.id) },
            ]),
          };
        }
        const x1 = from.x + MODULE_W;
        const y1 = moduleTop(after.module) + MODULE_H / 2;
        const x2 = to.x;
        const y2 = gateMid(module.id);
        const bend = Math.max(24, (x2 - x1) / 2);
        return {
          key: `${after.module}>${module.id}`,
          dashed: false,
          d: `M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2 - 6} ${y2}`,
        };
      }),
  );
  const part = (
    key: string,
    x: number,
    y: number,
    height: number,
    className: string,
    lines: { text: string; className: string }[],
    label: string,
  ) => (
    <g
      key={key}
      className={`bp-order ${className}${open === key ? " selected" : ""}`}
      transform={`translate(${x} ${y})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-expanded={open === key}
      onClick={() => onPick(key)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onPick(key);
        }
      }}
    >
      <rect width={MODULE_W} height={height} rx={6} />
      {lines.map((line, index) => (
        <text
          key={line.text}
          className={line.className}
          x={MODULE_W / 2}
          y={height / 2 - (lines.length - 1) * 9 + index * 19 + 4}
        >
          {line.text}
        </text>
      ))}
    </g>
  );
  return (
    <>
      {edges.map((edge) => (
        <path
          key={edge.key}
          className={edge.dashed ? "bp-edge dashed" : "bp-edge"}
          d={edge.d}
          markerEnd="url(#blueprint-arrow)"
        />
      ))}
      {modules.map((module) => {
        const { x, y } = at[module.id];
        const open = module.criteria.filter((c) => c.source === "open");
        const status = open.length
          ? `정할 값 ${open.length}개`
          : `완료 기준 ${module.criteria.length}개`;
        return (
          <g key={module.id}>
            <path
              className="bp-edge"
              d={`M${x + MODULE_W / 2} ${y + MODULE_GATE_H}V${moduleTop(module.id) - 6}`}
              markerEnd="url(#blueprint-arrow)"
            />
            {part(
              moduleKey("gate", module.id),
              x,
              y,
              MODULE_GATE_H,
              "gate",
              [
                { text: `${module.name} 시작 조건`, className: "bp-kind" },
                {
                  text: `확인할 것 ${module.gates.length}개`,
                  className: "bp-label",
                },
              ],
              `${module.name} 시작 조건, 확인할 것 ${module.gates.length}개`,
            )}
            {part(
              moduleKey("module", module.id),
              x,
              moduleTop(module.id),
              MODULE_H,
              open.length ? "module open-value" : "module",
              [
                { text: `${module.column + 1}단계`, className: "bp-kind" },
                { text: shortLabel(module.name, 14), className: "bp-label" },
                {
                  text: status,
                  className: open.length ? "bp-kind warn" : "bp-kind",
                },
              ],
              `${module.column + 1}단계 ${module.name}, ${status}`,
            )}
          </g>
        );
      })}
    </>
  );
}

const MODULE_SOURCE: Record<ModulePlan["gates"][number]["source"], string> = {
  rule: "규칙",
  design: "설계 초안",
  chat: "내가 정함",
  open: "정할 값",
};

/** One field of a module, edited in place. Lists are one item per line. */
function FieldEdit({
  label,
  initial,
  multiline,
  busy,
  save,
}: {
  label: string;
  initial: string;
  multiline?: boolean;
  busy: boolean;
  save: (text: string) => Promise<string>;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(initial);
  const [error, setError] = useState("");
  if (!open)
    return (
      <button
        className="quiet module-edit"
        disabled={busy}
        aria-label={`${label} 고치기`}
        onClick={() => {
          setText(initial);
          setError("");
          setOpen(true);
        }}
      >
        고치기
      </button>
    );
  async function submit(event: FormEvent) {
    event.preventDefault();
    const failure = await save(text);
    if (failure) setError(failure);
    else setOpen(false);
  }
  return (
    <form className="module-edit-form" onSubmit={(event) => void submit(event)}>
      {multiline ? (
        <textarea
          aria-label={`${label} (한 줄에 하나)`}
          rows={3}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      ) : (
        <input
          aria-label={label}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      )}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      <div className="row">
        <button className="primary" disabled={busy}>
          저장
        </button>
        <button type="button" className="quiet" onClick={() => setOpen(false)}>
          취소
        </button>
      </div>
    </form>
  );
}

function ModuleDetail({
  modules,
  open,
  busy,
  edit,
  onClose,
  onShowFlow,
}: {
  modules: ModulePlan[];
  open: string;
  busy: boolean;
  edit?: ModuleEdit;
  onClose: () => void;
  onShowFlow: () => void;
}) {
  const [part, id] = open.split(":");
  const module = modules.find((item) => item.id === id);
  if (!module) return null;
  const lines = (text: string) =>
    text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  const editList = (field: "include" | "exclude", label: string) =>
    edit && (
      <FieldEdit
        label={`${module.name} ${label}`}
        initial={module[field].map((item) => item.text).join("\n")}
        multiline
        busy={busy}
        save={(text) => edit({ module: module.id, field, items: lines(text) })}
      />
    );
  const names = Object.fromEntries(modules.map((m) => [m.id, m.name]));
  const tag = (source: ModulePlan["gates"][number]["source"]) => (
    <span className={`step-source ${source}`}>{MODULE_SOURCE[source]}</span>
  );
  const empty = (text: string) => <p className="step-empty">{text}</p>;
  const head = (title: string, sub: string) => (
    <div className="step-head">
      <div>
        <p className="step-title">{title}</p>
        <p>{sub}</p>
      </div>
      <button className="quiet" onClick={onClose}>
        설명 닫기
      </button>
    </div>
  );
  if (part === "gate") {
    return (
      <div
        className="step-detail"
        role="region"
        aria-label={`${module.name} 시작 조건`}
      >
        {head(
          `${module.name} 시작 조건`,
          "모두 확인하고 빌드 묶음의 docs/gates.md에 기록하면 이 모듈을 시작해요. 규칙에서 정한 조건이라 뺄 수 없어요.",
        )}
        <ul className="module-rows">
          {module.gates.map((gate) => (
            <li key={gate.text}>
              <span className="module-box" aria-hidden />
              <span className="module-main">
                {gate.text}
                <small>빼면 안 되는 이유: {gate.why}</small>
              </span>
              {tag(gate.source)}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  const waits = module.after.map((after) =>
    after.gate_only
      ? `${names[after.module]}의 시작 조건 확인 후`
      : `${names[after.module]} 완료 후`,
  );
  const items = (list: ModulePlan["include"], blank: string) =>
    list.length === 0 ? (
      empty(blank)
    ) : (
      <ul className="module-rows">
        {list.map((item) => (
          <li key={item.text}>
            <span className="module-main">{item.text}</span>
            {tag(item.source)}
          </li>
        ))}
      </ul>
    );
  return (
    <div
      className="step-detail"
      role="region"
      aria-label={`${module.name} 내용`}
    >
      {head(
        `${module.column + 1}단계 · ${module.name}`,
        [
          module.stack.join(" · "),
          waits.length ? `먼저 끝낼 것: ${waits.join(", ")}` : "",
        ]
          .filter(Boolean)
          .join(" / "),
      )}
      {module.id === "agent" && (
        <p>
          <button onClick={onShowFlow}>에이전트 흐름 보기</button>
        </p>
      )}
      <div className="step-columns">
        <div className="module-field">
          <p className="module-label">목표</p>
          {module.goal
            ? items([module.goal], "")
            : empty("아직 정하지 않았어요.")}
          {edit && (
            <FieldEdit
              label={`${module.name} 목표`}
              initial={module.goal?.text ?? ""}
              busy={busy}
              save={(value) =>
                edit({ module: module.id, field: "goal", value })
              }
            />
          )}
        </div>
        <div className="module-field">
          <p className="module-label">할 일</p>
          {module.tasks.length === 0 ? (
            empty("아직 이 모듈에 배정된 할 일이 없어요.")
          ) : (
            <ul className="module-rows">
              {module.tasks.map((task) => (
                <li key={task}>
                  <span className="module-main">{task}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="module-field">
          <p className="module-label">이번에 만들 것</p>
          {items(module.include, "아직 정하지 않았어요.")}
          {editList("include", "이번에 만들 것")}
        </div>
        <div className="module-field">
          <p className="module-label">이번에 안 만들 것</p>
          {items(module.exclude, "아직 없어요.")}
          {editList("exclude", "이번에 안 만들 것")}
        </div>
      </div>
      <div className="module-field">
        <p className="module-label">완료 기준</p>
        <ul className="module-rows">
          {module.criteria.map((criterion) => (
            <li key={criterion.text}>
              <span className="module-main">
                <span>
                  <span className="module-kind">
                    {criterion.kind === "quantitative" ? "정량" : "정성"}
                  </span>
                  {criterion.text}
                  {criterion.target
                    ? `: ${criterion.target}`
                    : criterion.source === "open" && ": 목표치를 정해야 해요"}
                </span>
                {criterion.how && <small>확인: {criterion.how}</small>}
                {edit && criterion.needs_target && (
                  <FieldEdit
                    label={`${criterion.text} 목표치`}
                    initial={criterion.target ?? ""}
                    busy={busy}
                    save={(value) =>
                      edit({
                        module: module.id,
                        field: "target",
                        criterion: criterion.text,
                        value,
                      })
                    }
                  />
                )}
              </span>
              {tag(criterion.source)}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const ACCESS_LABEL: Record<BlueprintStep["tools"][number]["access"], string> = {
  read: "읽기",
  write: "내부 쓰기",
  external_write: "외부 쓰기 (승인 필요)",
};

function StepRow({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="step-row">
      <dt>{label}</dt>
      <dd>
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </dd>
    </div>
  );
}

function CodeRow({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="step-row">
      <dt>{label}</dt>
      <dd>
        {items.length === 0 ? (
          "없어요."
        ) : (
          <ul>
            {items.map((item) => (
              <li key={item}>
                <code>{item}</code>
              </li>
            ))}
          </ul>
        )}
      </dd>
    </div>
  );
}

const present = (value: string | null) => (value ? [value] : []);

function StepDetail({
  node,
  isDraft,
  canOpen,
  open,
  onClose,
}: {
  node: BlueprintNode;
  isDraft: boolean;
  canOpen: (target: BlueprintNode) => boolean;
  open: (target: BlueprintNode) => void;
  onClose: () => void;
}) {
  const step = node.step!;
  return (
    <div
      className="step-detail"
      role="region"
      aria-label={`${node.label} 설명`}
    >
      <div className="step-head">
        <div>
          <p className="step-title">
            {KIND_LABEL[node.kind]} ·{" "}
            {isDraft ? node.label : <code>{node.label}</code>}
          </p>
          <p>{step.line}</p>
        </div>
        <button className="quiet" onClick={onClose}>
          설명 닫기
        </button>
      </div>
      {isDraft ? (
        <div className="step-columns">
          <dl>
            <StepRow label="확정된 것" items={step.fixed} />
          </dl>
          <dl className="step-open">
            <StepRow label="아직 모름" items={step.unknown} />
            <StepRow
              label="언제 정해지나"
              items={["결정을 모두 마치면 생성되는 설계에서 정해져요."]}
            />
          </dl>
        </div>
      ) : (
        <div className="step-columns">
          <dl>
            <CodeRow label="입력" items={step.inputs} />
            <CodeRow label="출력" items={step.outputs} />
            <StepRow label="구현 방식" items={present(step.how)} />
            <div className="step-row">
              <dt>도구와 권한</dt>
              <dd>
                {step.tools.length === 0 ? (
                  "쓰지 않아요."
                ) : (
                  <ul>
                    {step.tools.map((tool) => (
                      <li key={tool.name}>
                        <code>{tool.name}</code>{" "}
                        <span
                          className={
                            tool.access === "external_write"
                              ? "step-access external"
                              : "step-access"
                          }
                        >
                          {ACCESS_LABEL[tool.access]}
                        </span>
                        <br />
                        {tool.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </dd>
            </div>
          </dl>
          <dl>
            <StepRow label="완료 기준" items={present(step.done_when)} />
            <StepRow label="실패하면" items={present(step.on_failure)} />
            <StepRow label="확인 사례" items={step.checks} />
            <StepRow label="첫 작업" items={present(step.first_task)} />
          </dl>
        </div>
      )}
      {step.decisions.length > 0 && (
        <div className="step-decisions">
          <span>이 칸을 만든 결정</span>
          {step.decisions.map((decision) => {
            const target = decisionNode(decision);
            return (
              <button
                key={decision.card_id}
                disabled={!canOpen(target)}
                aria-label={`${decision.label} 다시 고르기`}
                onClick={() => open(target)}
              >
                {decision.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ServiceGlyph({ icon }: { icon: string | null }) {
  const mark = icon ? SERVICE_ICONS[icon] : undefined;
  if (mark) {
    return (
      <>
        {/* Brand colors are made for light grounds, so dark mode puts a plate behind them. */}
        <rect
          className="bp-plate"
          x={-3}
          y={-3}
          width={30}
          height={30}
          rx={6}
        />
        <path d={mark.path} fill={mark.hex} />
      </>
    );
  }
  const generic = icon ? GENERIC_GLYPHS[icon] : undefined;
  if (!generic) {
    return (
      <text className="bp-unknown" x={12} y={18}>
        ?
      </text>
    );
  }
  return <path className="bp-generic" d={generic} />;
}

/** The mark beside an option in a card. */
export function OptionIcon({ icon }: { icon: string }) {
  return (
    <span className="option-icon" aria-hidden>
      <svg width="24" height="24" viewBox="0 0 24 24">
        <ServiceGlyph icon={icon} />
      </svg>
    </span>
  );
}

/** Where lines may touch a node: a tile's mark, or a shared service's heading. */
function edgePoints(node: BlueprintNode, at: Point) {
  const { width, height } = sizeOf(node);
  const stacked = node.rows.length > 0;
  const halfMark = (stacked ? width : TILE) / 2;
  const centre = at.x + width / 2;
  return {
    centre,
    left: centre - halfMark,
    right: centre + halfMark,
    top: at.y,
    bottom: at.y + height,
    middle: at.y + (stacked ? STACK_HEAD : TILE + 4) / 2,
  };
}

type EdgeEnd = ReturnType<typeof edgePoints>;
type Bounds = { left: number; top: number; right: number; bottom: number };

function roundedPath(points: Point[]): string {
  const toward = (from: Point, to: Point) => {
    const length = Math.hypot(to.x - from.x, to.y - from.y);
    const step = length ? Math.min(LANE_CORNER, length / 2) / length : 0;
    return {
      x: from.x + (to.x - from.x) * step,
      y: from.y + (to.y - from.y) * step,
    };
  };
  return points.reduce((path, at, index) => {
    if (index === 0) return `M${at.x} ${at.y}`;
    if (index === points.length - 1) return `${path}L${at.x} ${at.y}`;
    const into = toward(at, points[index - 1]);
    const out = toward(at, points[index + 1]);
    return `${path}L${into.x} ${into.y}Q${at.x} ${at.y} ${out.x} ${out.y}`;
  }, "");
}

/** A line that would cross a column goes around its boxes, so it never runs over a service. */
function laneEdge(
  source: EdgeEnd,
  target: EdgeEnd,
  from: Bounds,
  to: Bounds,
  between: Bounds[],
  over: boolean,
) {
  const lane = over
    ? Math.min(...between.map((box) => box.top)) - LANE_CLEARANCE
    : Math.max(...between.map((box) => box.bottom)) + LANE_CLEARANCE;
  const leave = from.right + LANE_GAP;
  const arrive = to.left - LANE_GAP;
  return {
    d: roundedPath([
      { x: source.right, y: source.middle },
      { x: leave, y: source.middle },
      { x: leave, y: lane },
      { x: arrive, y: lane },
      { x: arrive, y: target.middle },
      { x: target.left - 6, y: target.middle },
    ]),
    labelX: (leave + arrive) / 2,
    labelY: lane + 4,
  };
}

function serviceEdge(source: EdgeEnd, target: EdgeEnd) {
  if (Math.abs(source.centre - target.centre) < SERVICE_W / 2) {
    const down = target.top >= source.top;
    const x = source.centre;
    const y1 = down ? source.bottom : source.top;
    const y2 = down ? target.top - 6 : target.bottom + 6;
    return {
      d: `M${x} ${y1}L${x} ${y2}`,
      labelX: x + 30,
      labelY: (y1 + y2) / 2 + 4,
    };
  }
  const right = target.centre > source.centre;
  const x1 = right ? source.right : source.left;
  const x2 = right ? target.left - 6 : target.right + 6;
  const y1 = source.middle;
  const y2 = target.middle;
  const bend = Math.max(30, Math.abs(x2 - x1) / 2) * (right ? 1 : -1);
  return {
    d: `M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`,
    labelX: (x1 + x2) / 2,
    labelY: (y1 + y2) / 2 - 5,
  };
}

function SharedService({
  node,
  at,
  nodeClass,
  nodeProps,
  handleProps,
}: {
  node: BlueprintNode;
  at: Point;
  nodeClass?: (node: BlueprintNode) => string;
  nodeProps?: (node: BlueprintNode, handle: string) => SVGProps<SVGGElement>;
  handleProps?: (node: BlueprintNode) => SVGProps<SVGGElement>;
}) {
  const { width, height } = sizeOf(node);
  const glyph = 20;
  return (
    <g
      className={`bp-stack ${nodeClass?.(node) ?? ""}`}
      transform={`translate(${at.x} ${at.y})`}
    >
      <rect className="bp-stack-fill" width={width} height={height} rx={6} />
      <g className="bp-stack-head" {...handleProps?.(node)}>
        <title>{node.label}</title>
        <path className="bp-hit" d={`M0 0H${width}V${STACK_HEAD}H0Z`} />
        <g
          transform={`translate(10 ${(STACK_HEAD - glyph) / 2}) scale(${glyph / 24})`}
        >
          <ServiceGlyph icon={node.icon} />
        </g>
        <text className="bp-stack-name" x={38} y={STACK_HEAD / 2 + 4}>
          {node.label}
        </text>
      </g>
      {node.rows.map((row, index) => {
        const line = rowNode(node, row);
        return (
          <g
            key={row.card_id}
            className={`bp-row ${nodeClass?.(line) ?? ""}`}
            transform={`translate(0 ${STACK_HEAD + index * ROW_H})`}
            {...nodeProps?.(line, node.id)}
          >
            <title>{line.label}</title>
            <rect width={width} height={ROW_H} />
            <text className="bp-row-role" x={12} y={ROW_H / 2 - 4}>
              {row.role}
            </text>
            <text className="bp-row-value" x={12} y={ROW_H / 2 + 14}>
              {shortLabel(row.label, MAX_ROW_LABEL)}
            </text>
          </g>
        );
      })}
      <rect className="bp-stack-frame" width={width} height={height} rx={6} />
    </g>
  );
}

/** The system view: services with their marks, inside the box of what they do. */
export function ServiceDiagram({
  graph,
  point,
  nodeClass,
  nodeProps,
  handleProps,
  stepOf,
}: {
  graph: BlueprintGraph;
  point: (id: string) => Point;
  nodeClass?: (node: BlueprintNode) => string;
  nodeProps?: (node: BlueprintNode, handle?: string) => SVGProps<SVGGElement>;
  handleProps?: (node: BlueprintNode) => SVGProps<SVGGElement>;
  /** The step of the build order that makes this box, shown beside its title. */
  stepOf?: (group: string) => number | undefined;
}) {
  const boxes = SERVICE_GROUPS.flatMap((group) => {
    const members = graph.nodes.filter((node) => groupOf(node) === group.id);
    if (!group.title || members.length === 0) return [];
    const placed = members.map((node) => ({
      at: point(node.id),
      size: sizeOf(node),
    }));
    const left = Math.min(...placed.map((p) => p.at.x)) - BOX_PAD;
    const top = Math.min(...placed.map((p) => p.at.y)) - BOX_PAD - BOX_HEAD;
    const right =
      Math.max(...placed.map((p) => p.at.x + p.size.width)) + BOX_PAD;
    const bottom =
      Math.max(...placed.map((p) => p.at.y + p.size.height)) + BOX_PAD;
    return [{ ...group, left, top, right, bottom }];
  });
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const pointsOf = (id: string) => edgePoints(nodeById.get(id)!, point(id));
  const boxOf = (id: string) =>
    boxes.find((box) => box.id === groupOf(nodeById.get(id)!));
  // Alternating keeps two crossing lines from sharing a lane.
  let crossings = 0;
  const routeOf = (edge: DrawnEdge) => {
    const source = pointsOf(edge.source);
    const target = pointsOf(edge.target);
    const from = boxOf(edge.source);
    const to = boxOf(edge.target);
    const between =
      from && to
        ? boxes.filter((box) => box.left >= from.right && box.right <= to.left)
        : [];
    if (!from || !to || between.length === 0) {
      return serviceEdge(source, target);
    }
    return laneEdge(source, target, from, to, between, crossings++ % 2 === 0);
  };
  return (
    <>
      {boxes.map((box) => (
        <g key={box.id}>
          <rect
            className="bp-box"
            x={box.left}
            y={box.top}
            width={box.right - box.left}
            height={box.bottom - box.top}
            rx={8}
          />
          <text className="bp-box-title" x={box.left + 10} y={box.top + 18}>
            {box.title}
            {stepOf?.(box.id) !== undefined && ` · ${stepOf(box.id)}단계`}
          </text>
        </g>
      ))}
      {mergeEdges(graph.edges).map((edge) => {
        const line = routeOf(edge);
        return (
          <g key={`${edge.source}>${edge.target}`}>
            <path
              className={edge.dashed ? "bp-edge dashed" : "bp-edge"}
              d={line.d}
              markerEnd="url(#blueprint-arrow)"
            />
            <EdgeLabel x={line.labelX} y={line.labelY} labels={edge.labels} />
          </g>
        );
      })}
      {graph.nodes.map((node) => {
        const at = point(node.id);
        if (node.rows.length > 0) {
          return (
            <SharedService
              key={node.id}
              node={node}
              at={at}
              nodeClass={nodeClass}
              nodeProps={nodeProps}
              handleProps={handleProps}
            />
          );
        }
        const lines = wrapLabel(node.label);
        const tileX = (SERVICE_W - TILE) / 2;
        return (
          <g
            key={node.id}
            className={`bp-service ${node.kind} ${nodeClass?.(node) ?? ""}`}
            transform={`translate(${at.x} ${at.y})`}
            {...nodeProps?.(node)}
          >
            <title>{node.label}</title>
            <path className="bp-hit" d={`M0 0H${SERVICE_W}V${SERVICE_H}H0Z`} />
            <rect
              className="bp-tile"
              x={tileX}
              y={2}
              width={TILE}
              height={TILE}
              rx={10}
            />
            <g
              transform={`translate(${(SERVICE_W - GLYPH) / 2} ${2 + (TILE - GLYPH) / 2}) scale(${GLYPH / 24})`}
            >
              <ServiceGlyph icon={node.icon} />
            </g>
            {lines.map((line, index) => (
              <text
                className="bp-service-label"
                key={line}
                x={SERVICE_W / 2}
                y={TILE + 20 + index * 15}
              >
                {line}
              </text>
            ))}
          </g>
        );
      })}
    </>
  );
}

const SAMPLE_NODE = (
  id: string,
  label: string,
  group: string,
  icon: string,
): BlueprintNode =>
  ({
    id,
    label,
    kind: "sys",
    card_id: null,
    step: null,
    icon,
    group,
    rows: [],
  }) as BlueprintNode;
const SAMPLE_EDGE = (source: string, target: string) => ({
  source,
  target,
  label: null,
  dashed: false,
});
// An illustration of the result, not anyone's project: nothing here is read from a journey.
const SAMPLE_GRAPH: BlueprintGraph = {
  nodes: [
    SAMPLE_NODE("users", "사용자", "people", "person"),
    SAMPLE_NODE("surface", "웹 화면", "client", "browser"),
    SAMPLE_NODE("api", "백엔드 API", "app", "server"),
    SAMPLE_NODE("runner", "에이전트 실행", "app", "agent"),
    SAMPLE_NODE("model", "Gemini", "model", "googlegemini"),
    SAMPLE_NODE("database", "PostgreSQL", "data", "postgresql"),
    SAMPLE_NODE("cloud", "로컬", "ops", "laptop"),
  ],
  edges: [
    SAMPLE_EDGE("users", "surface"),
    SAMPLE_EDGE("surface", "api"),
    SAMPLE_EDGE("api", "runner"),
    SAMPLE_EDGE("runner", "model"),
    SAMPLE_EDGE("runner", "database"),
    SAMPLE_EDGE("api", "cloud"),
  ],
};

export function SamplePreview() {
  const layout = layoutSystem(SAMPLE_GRAPH);
  const points = Object.values(layout);
  const width = Math.max(...points.map((p) => p.x)) + SERVICE_W + PAD + BOX_PAD;
  const height =
    Math.max(...points.map((p) => p.y)) + SERVICE_H + PAD + BOX_PAD;
  return (
    <svg
      className="sample-preview"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="완성된 시스템 구성도 예시"
    >
      <ArrowMarker />
      <ServiceDiagram graph={SAMPLE_GRAPH} point={(id) => layout[id]} />
    </svg>
  );
}

function ArrowMarker() {
  return (
    <defs>
      <marker
        id="blueprint-arrow"
        viewBox="0 0 8 8"
        refX="7"
        refY="4"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path className="bp-arrow" d="M0 0L8 4L0 8Z" />
      </marker>
    </defs>
  );
}

/** Nodes that appeared or changed, and the ends of new connections. */
export function changedNodes(
  before: BlueprintGraph,
  after: BlueprintGraph,
): Set<string> {
  const old = new Map(decisionNodes(before).map((node) => [node.id, node]));
  const edge = (e: BlueprintGraph["edges"][number]) =>
    `${e.source}>${e.target}>${e.label ?? ""}`;
  const oldEdges = new Set(before.edges.map(edge));
  const changed = new Set(
    decisionNodes(after)
      .filter((node) => {
        const was = old.get(node.id);
        return !was || was.label !== node.label || was.icon !== node.icon;
      })
      .map((node) => node.id),
  );
  for (const item of after.edges) {
    if (!oldEdges.has(edge(item))) changed.add(item.target);
  }
  return changed;
}

const HINT_KEY = "starter-pack:graph-hint:v1";

function firstVisit(): boolean {
  try {
    if (localStorage.getItem(HINT_KEY)) return false;
    localStorage.setItem(HINT_KEY, "seen");
  } catch {
    // Without storage the hint simply shows again next time.
  }
  return true;
}

export function BlueprintPanel({
  journey,
  busy,
  act,
  cardOpen,
  onToggleCard,
  onLayerChange,
  editModule,
}: {
  journey: Journey;
  busy: boolean;
  act: (action: Action) => void;
  cardOpen?: boolean;
  onToggleCard?: () => void;
  onLayerChange?: (layer: Layer) => void;
  editModule?: ModuleEdit;
}) {
  // A finished journey opens on the architecture; a running one follows its card below.
  const [layer, setLayer] = useState<Layer>(
    journey.prompt ? "agent" : "system",
  );
  const layerChanged = useRef(onLayerChange);
  layerChanged.current = onLayerChange;
  const firstLayer = useRef(true);
  useEffect(() => {
    // Only a tab someone opened moves the side panel, not the tab the screen started on.
    if (firstLayer.current) {
      firstLayer.current = false;
      return;
    }
    layerChanged.current?.(layer);
  }, [layer]);
  const [showHint] = useState(firstVisit);
  const [lastChange, setLastChange] = useState("");
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const previous = useRef(journey);
  const cardInFocus =
    journey.prompt?.type === "decision" ? journey.prompt.card : undefined;
  const focusLayer = cardInFocus?.layer;
  const focusId = cardInFocus?.card_id;

  useEffect(() => {
    if (focusLayer) setLayer(focusLayer === "agent" ? "agent" : "system");
  }, [focusId, focusLayer]);

  useEffect(() => {
    const before = previous.current;
    previous.current = journey;
    if (before === journey) return;
    const decided = journey.cards.find((card) => {
      const was = before.cards.find((c) => c.card_id === card.card_id);
      return (
        card.option_name &&
        card.by !== "implied" &&
        was?.option_name !== card.option_name
      );
    });
    if (!decided) return;
    setLastChange(`${decided.title} → ${decided.option_name}`);
    setChanged(
      new Set([
        ...changedNodes(before.blueprint.agent, journey.blueprint.agent),
        ...changedNodes(before.blueprint.system, journey.blueprint.system),
      ]),
    );
  }, [journey]);

  const [examples, setExamples] = useState<BlueprintExample[] | null>(null);
  const [loadingExamples, setLoadingExamples] = useState(false);
  const [exampleId, setExampleId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [moved, setMoved] = useState<Record<string, Point>>({});
  const [failure, setFailure] = useState("");
  const drag = useRef<{
    id: string;
    startX: number;
    startY: number;
    origin: Point;
    scale: number;
    moved: boolean;
  } | null>(null);
  const seen = useRef(new Map<string, Set<string>>());
  const svgRef = useRef<SVGSVGElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const pan = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
    offset: Point;
    scale: number;
  } | null>(null);
  // How far the fitted view has been dragged, in drawing units.
  const [offset, setOffset] = useState<Point>(NO_OFFSET);
  // The diagram point that must stay under the cursor after a zoom.
  const anchor = useRef<{
    x: number;
    y: number;
    clientX: number;
    clientY: number;
  } | null>(null);
  // Null follows the panel; a number is the size the person asked for.
  const [zoom, setZoom] = useState<number | null>(null);
  const zoomAtLatest = useRef<
    (factor: number, clientX: number, clientY: number) => void
  >(() => {});

  const example = examples?.find((item) => item.id === exampleId) ?? null;
  const blueprint = example?.blueprint ?? journey.blueprint;
  // Examples carry no decisions of this project, so they have no build order.
  const modules = example ? [] : journey.modules;
  const isOrder = layer === "order" && modules.length > 0;
  const graph = isOrder || layer === "order" ? EMPTY_GRAPH : blueprint[layer];
  const scope = `${exampleId ?? "mine"}/${layer}`;
  const isSystem = layer === "system";
  const isAgent = layer === "agent";
  const moduleLayout = layoutModules(modules);
  useEffect(() => {
    if (layer === "order" && modules.length === 0) setLayer("system");
  }, [layer, modules.length]);
  const layout = isSystem ? layoutSystem(graph) : layoutBlueprint(graph);
  const point = (id: string) => moved[`${scope}/${id}`] ?? layout[id];

  const known = seen.current.get(scope);
  const isFresh = (id: string) => known !== undefined && !known.has(id);
  const nodeKey = decisionNodes(graph)
    .map((node) => node.id)
    .join("\n");
  useEffect(() => {
    const ids = nodeKey ? nodeKey.split("\n") : [];
    seen.current.set(scope, new Set(ids));
  }, [scope, nodeKey]);
  useEffect(() => {
    setZoom(null);
    setOffset(NO_OFFSET);
  }, [scope]);

  const cardOf = (node: BlueprintNode | undefined) =>
    node?.card_id
      ? journey.cards.find((card) => card.card_id === node.card_id)
      : undefined;
  const canFocus = (node: BlueprintNode | undefined) => {
    const card = cardOf(node);
    return (
      !example &&
      !busy &&
      journey.prompt?.type === "decision" &&
      (card?.state === "pending" || card?.state === "deferred")
    );
  };

  // The same rule as the stage strip's "다시 고르기".
  const canChange = (node: BlueprintNode | undefined) =>
    !example &&
    !busy &&
    cardOf(node)?.state === "decided" &&
    !cardOf(node)?.editing &&
    (journey.prompt?.type === "decision" || journey.can_reopen === true);

  function openCard(node: BlueprintNode) {
    if (canFocus(node)) {
      act({ action: "focus", card_id: node.card_id! });
    } else if (canChange(node)) {
      act({ action: "revise", card_id: node.card_id! });
    }
  }

  function pick(node: BlueprintNode) {
    setLastChange("");
    if (node.step) {
      setSelected(selected === node.id ? null : node.id);
      return;
    }
    setSelected(node.id);
    openCard(node);
  }

  function onPointerDown(event: PointerEvent<SVGGElement>, handle: string) {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = {
      id: handle,
      startX: event.clientX,
      startY: event.clientY,
      origin: point(handle),
      scale: drawnScale(event.currentTarget.ownerSVGElement, width),
      moved: false,
    };
  }

  function onPointerMove(event: PointerEvent<SVGGElement>) {
    const current = drag.current;
    if (!current) return;
    const dx = event.clientX - current.startX;
    const dy = event.clientY - current.startY;
    if (!current.moved && Math.hypot(dx, dy) < DRAG_START) return;
    current.moved = true;
    setMoved((old) => ({
      ...old,
      [`${scope}/${current.id}`]: {
        x: Math.max(4, current.origin.x + dx / current.scale),
        y: Math.max(4, current.origin.y + dy / current.scale),
      },
    }));
  }

  function onPointerUp(node: BlueprintNode) {
    const wasDrag = drag.current?.moved;
    drag.current = null;
    if (!wasDrag) pick(node);
  }

  function onKeyDown(
    event: KeyboardEvent,
    node: BlueprintNode,
    handle: string,
  ) {
    const move = KEY_MOVES[event.key];
    if (move) {
      event.preventDefault();
      const at = point(handle);
      setMoved((old) => ({
        ...old,
        [`${scope}/${handle}`]: {
          x: Math.max(4, at.x + move.x),
          y: Math.max(4, at.y + move.y),
        },
      }));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      pick(node);
    }
  }

  async function showExamples() {
    setFailure("");
    setLoadingExamples(true);
    try {
      setExamples(examples ?? (await getBlueprintExamples()));
    } catch (error) {
      setFailure(
        error instanceof Error ? error.message : "예시를 불러오지 못했어요.",
      );
    } finally {
      setLoadingExamples(false);
    }
  }

  const extents = graph.nodes.map((node) => {
    const at = point(node.id);
    const size = isSystem ? sizeOf(node) : { width: WIDTH, height: HEIGHT };
    return { right: at.x + size.width, bottom: at.y + size.height };
  });
  const extra = PAD + (isSystem ? BOX_PAD : STEP_LANE_ROOM);
  // A node moved up or left takes its box and the lines routed above it along, so the drawing
  // starts wherever the content does, not at zero.
  const placed = graph.nodes.map((node) => point(node.id));
  const originX = isOrder
    ? 0
    : Math.min(
        0,
        ...placed.map((p) => p.x - (isSystem ? BOX_PAD : 0) - PAD / 2),
      );
  const originY = isOrder
    ? 0
    : Math.min(
        0,
        ...placed.map(
          (p) =>
            p.y -
            (isSystem
              ? BOX_HEAD + BOX_PAD + LANE_CLEARANCE + LABEL_LINE
              : STEP_LANE_ROOM),
        ),
      );
  const width = isOrder
    ? moduleLayout.width
    : Math.max(0, ...extents.map((e) => e.right)) + extra - originX;
  const height = isOrder
    ? moduleLayout.height
    : Math.max(0, ...extents.map((e) => e.bottom)) + extra - originY;
  function zoomAt(factor: number, clientX: number, clientY: number) {
    const svg = svgRef.current;
    const scale = zoom ?? drawnScale(svg, width);
    const box = svg?.getBoundingClientRect();
    anchor.current = {
      x: (clientX - (box?.left ?? 0)) / scale,
      y: (clientY - (box?.top ?? 0)) / scale,
      clientX,
      clientY,
    };
    setZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, scale * factor)));
  }

  function resize(factor: number) {
    const box = canvasRef.current?.getBoundingClientRect();
    zoomAt(
      factor,
      (box?.left ?? 0) + (box?.width ?? 0) / 2,
      (box?.top ?? 0) + (box?.height ?? 0) / 2,
    );
  }

  function startPan(event: PointerEvent<HTMLDivElement>) {
    const canvas = event.currentTarget;
    // Measured from the canvas: offsetX belongs to whatever was pressed, often the wider drawing.
    const frame = canvas.getBoundingClientRect();
    const onScrollbar =
      event.clientX - frame.left > canvas.clientWidth ||
      event.clientY - frame.top > canvas.clientHeight;
    const onNode = (event.target as Element).closest(
      '[role="button"], .bp-stack-head',
    );
    if (event.button !== 0 || onNode || onScrollbar) return;
    canvas.setPointerCapture?.(event.pointerId);
    pan.current = {
      x: event.clientX,
      y: event.clientY,
      left: canvas.scrollLeft,
      top: canvas.scrollTop,
      offset,
      scale: drawnScale(svgRef.current, width),
    };
  }

  function movePan(event: PointerEvent<HTMLDivElement>) {
    const start = pan.current;
    if (!start) return;
    const canvas = event.currentTarget;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    // Scroll where there is room to; otherwise (fitted, or zoomed out) move the view itself.
    const scrollsX =
      zoom !== null && canvas.scrollWidth > canvas.clientWidth + 1;
    const scrollsY =
      zoom !== null && canvas.scrollHeight > canvas.clientHeight + 1;
    if (scrollsX) canvas.scrollLeft = start.left - dx;
    if (scrollsY) canvas.scrollTop = start.top - dy;
    setOffset({
      x: scrollsX ? start.offset.x : start.offset.x + dx / start.scale,
      y: scrollsY ? start.offset.y : start.offset.y + dy / start.scale,
    });
  }

  function endPan() {
    pan.current = null;
  }

  // Not a React prop: only a non-passive listener can stop the browser zooming the whole page.
  zoomAtLatest.current = zoomAt;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      zoomAtLatest.current(
        event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP,
        event.clientX,
        event.clientY,
      );
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  useLayoutEffect(() => {
    const point = anchor.current;
    const svg = svgRef.current;
    const canvas = canvasRef.current;
    if (!point || !svg || !canvas) return;
    anchor.current = null;
    const box = svg.getBoundingClientRect();
    const scale = drawnScale(svg, width);
    canvas.scrollLeft += box.left + point.x * scale - point.clientX;
    canvas.scrollTop += box.top + point.y * scale - point.clientY;
  }, [zoom, width]);

  // A shared service moves as a whole, whichever of its lines is held.
  const interactions = (node: BlueprintNode, handle = node.id) => ({
    tabIndex: 0,
    role: "button",
    "aria-label": `${KIND_LABEL[node.kind]} ${node.label}${node.step ? " 설명 보기" : canChange(node) ? " 다시 고르기" : ""}`,
    "aria-expanded": node.step ? selected === node.id : undefined,
    onPointerDown: (event: PointerEvent<SVGGElement>) =>
      onPointerDown(event, handle),
    onPointerMove,
    onPointerUp: () => onPointerUp(node),
    onKeyDown: (event: KeyboardEvent) => onKeyDown(event, node, handle),
  });
  const headingDrag = (node: BlueprintNode) => ({
    onPointerDown: (event: PointerEvent<SVGGElement>) =>
      onPointerDown(event, node.id),
    onPointerMove,
    onPointerUp: () => {
      drag.current = null;
    },
  });
  const stateClass = (node: BlueprintNode) =>
    [
      selected === node.id && "selected",
      (node.step || canFocus(node) || canChange(node)) && "editable",
      (cardOf(node)?.state === "current" || cardOf(node)?.editing) && "current",
      !example && changed.has(node.id) && "changed",
      cardOf(node)?.needs_review && "review",
      isFresh(node.id) && "fresh",
    ]
      .filter(Boolean)
      .join(" ");
  const blankCount =
    journey.blueprint.agent.nodes.filter((n) => n.kind === "blank").length +
    journey.blueprint.system.nodes.filter((n) => n.kind === "blank").length;
  const notes = isSystem ? blueprint.notes : [];
  const current = [...decisionNodes(graph), ...notes.map(noteNode)].find(
    (node) => node.id === selected,
  );
  const currentCard = cardOf(current);

  return (
    <section className="blueprint" aria-label="설계 그래프">
      <div className="blueprint-bar">
        <div className="segment" role="group" aria-label="그래프 종류">
          <button
            className={layer === "agent" ? "on" : ""}
            aria-pressed={layer === "agent"}
            onClick={() => setLayer("agent")}
          >
            에이전트 흐름
          </button>
          <button
            className={layer === "system" ? "on" : ""}
            aria-pressed={layer === "system"}
            onClick={() => setLayer("system")}
          >
            시스템 구성
          </button>
          {modules.length > 0 && (
            <button
              className={layer === "order" ? "on" : ""}
              aria-pressed={layer === "order"}
              onClick={() => setLayer("order")}
            >
              만드는 순서
            </button>
          )}
        </div>
        <span className="muted blueprint-count">
          {blankCount > 0 ? `아직 정할 곳 ${blankCount}개` : ""}
        </span>
        {examples === null ? (
          <button
            className="quiet"
            disabled={loadingExamples}
            onClick={() => void showExamples()}
          >
            {loadingExamples ? "예시를 불러오는 중…" : "완성 예시"}
          </button>
        ) : (
          <div className="segment" role="group" aria-label="완성 예시">
            <button
              className={exampleId === null ? "on" : ""}
              aria-pressed={exampleId === null}
              onClick={() => setExampleId(null)}
            >
              내 작업
            </button>
            {examples.map((item) => (
              <button
                key={item.id}
                className={exampleId === item.id ? "on" : ""}
                aria-pressed={exampleId === item.id}
                onClick={() => setExampleId(item.id)}
              >
                {item.name}
              </button>
            ))}
          </div>
        )}
        {journey.design && !example && (
          <a className="button quiet" href={designViewUrl(journey.journey_id)}>
            그래프 편집
          </a>
        )}
        {onToggleCard && (
          <button
            className="quiet card-toggle"
            aria-expanded={cardOpen}
            onClick={onToggleCard}
          >
            {cardOpen ? "카드 닫기" : "카드 열기"}
          </button>
        )}
      </div>
      {failure && (
        <p className="alert" role="alert">
          {failure}
        </p>
      )}
      <p className="blueprint-note">
        {example
          ? `완성 예시예요. ${example.note}`
          : layer === "agent" && blueprint.agent_is_draft
            ? "결정을 마치면 실제 설계로 바뀌어요."
            : layer === "agent"
              ? "생성된 설계예요."
              : isOrder
                ? "모듈마다 시작 조건을 먼저 확인해요. 같은 열의 모듈은 동시에 진행할 수 있어요."
                : ""}
      </p>
      <div
        ref={canvasRef}
        className={`blueprint-canvas${zoom === null ? " fit" : ""}`}
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={endPan}
        onPointerCancel={endPan}
      >
        <svg
          ref={svgRef}
          width={width * (zoom ?? MAX_SCALE)}
          height={height * (zoom ?? MAX_SCALE)}
          viewBox={`${originX - offset.x} ${originY - offset.y} ${width} ${height}`}
          style={
            zoom === null
              ? {
                  minWidth: width * MIN_SCALE,
                  maxWidth: width * MAX_SCALE,
                  maxHeight: height * MAX_SCALE,
                }
              : undefined
          }
          role="group"
          aria-label={
            isOrder ? "만드는 순서" : isAgent ? "에이전트 흐름" : "시스템 구성"
          }
        >
          <ArrowMarker />
          {isOrder && (
            <ModuleDiagram
              modules={modules}
              at={moduleLayout.at}
              open={selected}
              onPick={(key) => {
                setLastChange("");
                setSelected(selected === key ? null : key);
              }}
            />
          )}
          {isSystem && (
            <ServiceDiagram
              graph={graph}
              point={point}
              nodeClass={stateClass}
              nodeProps={interactions}
              handleProps={headingDrag}
              stepOf={(group) => {
                const made = modules.find((m) => m.id === GROUP_MODULE[group]);
                return made ? made.column + 1 : undefined;
              }}
            />
          )}
          {isAgent &&
            stepRoutes(graph, point).map((edge) => (
              <g key={`${edge.source}>${edge.target}`}>
                <path
                  className={edge.dashed ? "bp-edge dashed" : "bp-edge"}
                  d={edge.d}
                  markerEnd="url(#blueprint-arrow)"
                />
                <EdgeLabel
                  x={edge.labelX}
                  y={edge.labelY}
                  labels={edge.labels}
                />
              </g>
            ))}
          {isAgent &&
            graph.nodes.map((node) => {
              const at = point(node.id);
              const review = cardOf(node)?.needs_review;
              const text = stepText(node, blueprint.agent_is_draft);
              const firstLine = 44;
              const afterTitle = firstLine + text.title.length * 17;
              return (
                <g
                  key={node.id}
                  className={`bp-node ${node.kind} ${stateClass(node)}`}
                  transform={`translate(${at.x} ${at.y})`}
                  {...interactions(node)}
                >
                  <title>{node.label}</title>
                  <path
                    className="bp-hit"
                    d={`M0 ${-HIT_PAD}H${WIDTH}V${HEIGHT + HIT_PAD}H0Z`}
                  />
                  <rect width={WIDTH} height={HEIGHT} rx={7} />
                  <text className="bp-kind" x={WIDTH / 2} y={22}>
                    {review ? "다시 확인" : KIND_LABEL[node.kind]}
                  </text>
                  {text.title.map((line, index) => (
                    <text
                      className="bp-label"
                      key={line}
                      x={WIDTH / 2}
                      y={firstLine + index * 17}
                    >
                      {line}
                    </text>
                  ))}
                  {text.sub.map((line, index) => (
                    <text
                      className="bp-kind"
                      key={line}
                      x={WIDTH / 2}
                      y={afterTitle + index * 14}
                    >
                      {line}
                    </text>
                  ))}
                  {text.code && (
                    <text className="bp-code" x={WIDTH / 2} y={afterTitle + 2}>
                      {text.code}
                    </text>
                  )}
                </g>
              );
            })}
        </svg>
      </div>
      {isOrder && selected?.includes(":") && (
        <ModuleDetail
          modules={modules}
          open={selected}
          busy={busy}
          edit={editModule}
          onClose={() => setSelected(null)}
          onShowFlow={() => {
            setSelected(null);
            setLayer("agent");
          }}
        />
      )}
      {isAgent && current?.step && (
        <StepDetail
          node={current}
          isDraft={blueprint.agent_is_draft}
          canOpen={(target) => canFocus(target) || canChange(target)}
          open={openCard}
          onClose={() => setSelected(null)}
        />
      )}
      {notes.length > 0 && (
        <div className="bp-notes" role="group" aria-label="칸이 없는 결정">
          {SERVICE_GROUPS.filter((group) =>
            notes.some((note) => note.group === group.id),
          ).map((group) => (
            <div className="bp-notes-area" key={group.id}>
              <span>{group.title}</span>
              {notes
                .filter((note) => note.group === group.id)
                .map((note) => {
                  const target = noteNode(note);
                  const card = example ? undefined : cardOf(target);
                  return (
                    <button
                      key={note.card_id}
                      className={`quiet bp-note${card?.editing ? " current" : ""}`}
                      disabled={!canChange(target)}
                      aria-current={card?.editing ? "true" : undefined}
                      aria-label={`${note.label}${canChange(target) ? " 다시 고르기" : ""}`}
                      onClick={() => pick(target)}
                    >
                      {note.label}
                      {card?.needs_review && " · 다시 확인"}
                    </button>
                  );
                })}
            </div>
          ))}
        </div>
      )}
      <div className="blueprint-detail">
        {lastChange && !example ? (
          <span>
            <strong>방금 반영:</strong> {lastChange}
          </span>
        ) : current && !current.step ? (
          <>
            <strong>{current.label}</strong>
            {currentCard && (
              <span className="muted">
                {currentCard.title}:{" "}
                {currentCard.option_name ?? "아직 정하지 않았어요"}
              </span>
            )}
          </>
        ) : (
          showHint && (
            <span className="muted">
              {isSystem
                ? "아이콘을 누르면 그 결정을 고칠 수 있어요."
                : "칸을 누르면 구현 설명이 열려요."}{" "}
              Ctrl+휠로 확대·축소, 빈 곳을 끌어 화면을 옮겨요.
            </span>
          )
        )}
        <div className="zoom" role="group" aria-label="그래프 크기">
          <button
            className="quiet"
            aria-label="축소"
            disabled={zoom !== null && zoom <= ZOOM_MIN}
            onClick={() => resize(1 / ZOOM_STEP)}
          >
            −
          </button>
          <span className="zoom-value">
            {zoom === null ? "맞춤" : `${Math.round(zoom * 100)}%`}
          </span>
          <button
            className="quiet"
            aria-label="확대"
            disabled={zoom !== null && zoom >= ZOOM_MAX}
            onClick={() => resize(ZOOM_STEP)}
          >
            +
          </button>
          <button
            className="quiet"
            disabled={zoom === null && offset.x === 0 && offset.y === 0}
            onClick={() => {
              setZoom(null);
              setOffset(NO_OFFSET);
            }}
          >
            화면 맞춤
          </button>
        </div>
      </div>
    </section>
  );
}
