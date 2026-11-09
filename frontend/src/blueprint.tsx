import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, SVGProps } from "react";
import { designViewUrl, getBlueprintExamples } from "./api";
import { SERVICE_ICONS } from "./serviceIcons";
import type {
  Action,
  BlueprintExample,
  BlueprintGraph,
  BlueprintNode,
  Journey,
} from "./api";

export type Point = { x: number; y: number };
type Layer = "agent" | "system";

const WIDTH = 148;
const HEIGHT = 58;
const GAP_X = 66;
const GAP_Y = 34;
const PAD = 26;
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
        y: PAD + (index + offset) * (HEIGHT + GAP_Y),
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

function shortLabel(label: string): string {
  return label.length > MAX_LABEL ? `${label.slice(0, MAX_LABEL - 1)}…` : label;
}

const SERVICE_W = 112;
const SERVICE_H = 94;
const TILE = 52;
const GLYPH = 30;
const BOX_PAD = 16;
const BOX_HEAD = 24;
const CELL_GAP = 18;
const COLUMN_GAP = 62;
const BOX_GAP = 26;

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

/** Boxes in columns, each column centred against the tallest. */
export function layoutSystem(graph: BlueprintGraph): Record<string, Point> {
  const columns = [...new Set(SERVICE_GROUPS.map((group) => group.column))];
  const inGroup = (id: string) =>
    graph.nodes.filter((node) => groupOf(node) === id);
  const boxHeight = (count: number) =>
    BOX_HEAD + BOX_PAD * 2 + count * SERVICE_H + (count - 1) * CELL_GAP;
  const stacks = columns.map((column) =>
    SERVICE_GROUPS.filter(
      (group) => group.column === column && inGroup(group.id).length > 0,
    ),
  );
  const heightOf = (stack: typeof SERVICE_GROUPS) =>
    stack.reduce(
      (sum, group, index) =>
        sum + boxHeight(inGroup(group.id).length) + (index ? BOX_GAP : 0),
      0,
    );
  const tallest = Math.max(0, ...stacks.map(heightOf));
  const points: Record<string, Point> = {};
  stacks
    .filter((stack) => stack.length > 0)
    .forEach((stack, at) => {
      const x = PAD + BOX_PAD + at * (SERVICE_W + BOX_PAD * 2 + COLUMN_GAP);
      let y = PAD + (tallest - heightOf(stack)) / 2;
      for (const group of stack) {
        const nodes = inGroup(group.id);
        nodes.forEach((node, index) => {
          points[node.id] = {
            x,
            y: y + BOX_HEAD + BOX_PAD + index * (SERVICE_H + CELL_GAP),
          };
        });
        y += boxHeight(nodes.length) + BOX_GAP;
      }
    });
  return points;
}

function wrapLabel(label: string): string[] {
  const lines: string[] = [];
  for (const word of label.split(" ")) {
    const last = lines[lines.length - 1];
    if (last !== undefined && `${last} ${word}`.length <= 12) {
      lines[lines.length - 1] = `${last} ${word}`;
    } else {
      lines.push(word);
    }
  }
  return lines.length > 2
    ? [lines[0], `${lines.slice(1).join(" ").slice(0, 11)}…`]
    : lines;
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

function serviceEdge(from: Point, to: Point) {
  const centre = SERVICE_W / 2;
  if (Math.abs(from.x - to.x) < centre) {
    const down = to.y >= from.y;
    const x = from.x + centre;
    const y1 = down ? from.y + SERVICE_H : from.y;
    const y2 = down ? to.y - 6 : to.y + SERVICE_H + 6;
    return {
      d: `M${x} ${y1}L${x} ${y2}`,
      labelX: x + 30,
      labelY: (y1 + y2) / 2 + 4,
    };
  }
  const right = to.x > from.x;
  const side = right ? TILE / 2 : -TILE / 2;
  const x1 = from.x + centre + side;
  const x2 = to.x + centre - side - (right ? 6 : -6);
  const y1 = from.y + TILE / 2 + 2;
  const y2 = to.y + TILE / 2 + 2;
  const bend = Math.max(30, Math.abs(x2 - x1) / 2) * (right ? 1 : -1);
  return {
    d: `M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`,
    labelX: (x1 + x2) / 2,
    labelY: (y1 + y2) / 2 - 5,
  };
}

/** The system view: services with their marks, inside the box of what they do. */
export function ServiceDiagram({
  graph,
  point,
  nodeClass,
  nodeProps,
}: {
  graph: BlueprintGraph;
  point: (id: string) => Point;
  nodeClass?: (node: BlueprintNode) => string;
  nodeProps?: (node: BlueprintNode) => SVGProps<SVGGElement>;
}) {
  const boxes = SERVICE_GROUPS.flatMap((group) => {
    const members = graph.nodes.filter((node) => groupOf(node) === group.id);
    if (!group.title || members.length === 0) return [];
    const points = members.map((node) => point(node.id));
    const left = Math.min(...points.map((p) => p.x)) - BOX_PAD;
    const top = Math.min(...points.map((p) => p.y)) - BOX_PAD - BOX_HEAD;
    const right = Math.max(...points.map((p) => p.x)) + SERVICE_W + BOX_PAD;
    const bottom = Math.max(...points.map((p) => p.y)) + SERVICE_H + BOX_PAD;
    return [{ ...group, left, top, right, bottom }];
  });
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
          </text>
        </g>
      ))}
      {mergeEdges(graph.edges).map((edge) => {
        const line = serviceEdge(point(edge.source), point(edge.target));
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
  ({ id, label, kind: "sys", card_id: null, icon, group }) as BlueprintNode;
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
  const old = new Map(before.nodes.map((node) => [node.id, node]));
  const edge = (e: BlueprintGraph["edges"][number]) =>
    `${e.source}>${e.target}>${e.label ?? ""}`;
  const oldEdges = new Set(before.edges.map(edge));
  const changed = new Set(
    after.nodes
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
}: {
  journey: Journey;
  busy: boolean;
  act: (action: Action) => void;
  cardOpen?: boolean;
  onToggleCard?: () => void;
}) {
  // A finished journey opens on the architecture; a running one follows its card below.
  const [layer, setLayer] = useState<Layer>(
    journey.prompt ? "agent" : "system",
  );
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
  } | null>(null);
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
  const graph = blueprint[layer];
  const scope = `${exampleId ?? "mine"}/${layer}`;
  const isSystem = layer === "system";
  const layout = isSystem ? layoutSystem(graph) : layoutBlueprint(graph);
  const point = (id: string) => moved[`${scope}/${id}`] ?? layout[id];

  const known = seen.current.get(scope);
  const isFresh = (id: string) => known !== undefined && !known.has(id);
  const nodeKey = graph.nodes.map((node) => node.id).join("\n");
  useEffect(() => {
    const ids = nodeKey ? nodeKey.split("\n") : [];
    seen.current.set(scope, new Set(ids));
  }, [scope, nodeKey]);
  useEffect(() => setZoom(null), [scope]);

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

  function pick(node: BlueprintNode) {
    setSelected(node.id);
    setLastChange("");
    if (canFocus(node)) {
      act({ action: "focus", card_id: node.card_id! });
    } else if (canChange(node)) {
      act({ action: "revise", card_id: node.card_id! });
    }
  }

  function onPointerDown(
    event: PointerEvent<SVGGElement>,
    node: BlueprintNode,
  ) {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = {
      id: node.id,
      startX: event.clientX,
      startY: event.clientY,
      origin: point(node.id),
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

  function onKeyDown(event: KeyboardEvent, node: BlueprintNode) {
    const move = KEY_MOVES[event.key];
    if (move) {
      event.preventDefault();
      const at = point(node.id);
      setMoved((old) => ({
        ...old,
        [`${scope}/${node.id}`]: {
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

  const points = graph.nodes.map((node) => point(node.id));
  const extra = isSystem ? BOX_PAD : 0;
  const width =
    Math.max(0, ...points.map((p) => p.x)) +
    (isSystem ? SERVICE_W : WIDTH) +
    PAD +
    extra;
  const height =
    Math.max(0, ...points.map((p) => p.y)) +
    (isSystem ? SERVICE_H : HEIGHT) +
    PAD +
    extra;
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
    const onScrollbar =
      event.nativeEvent.offsetX > canvas.clientWidth ||
      event.nativeEvent.offsetY > canvas.clientHeight;
    const onNode = (event.target as Element).closest('[role="button"]');
    if (event.button !== 0 || onNode || onScrollbar) return;
    canvas.setPointerCapture?.(event.pointerId);
    pan.current = {
      x: event.clientX,
      y: event.clientY,
      left: canvas.scrollLeft,
      top: canvas.scrollTop,
    };
  }

  function movePan(event: PointerEvent<HTMLDivElement>) {
    const start = pan.current;
    if (!start) return;
    event.currentTarget.scrollLeft = start.left - (event.clientX - start.x);
    event.currentTarget.scrollTop = start.top - (event.clientY - start.y);
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

  const interactions = (node: BlueprintNode) => ({
    tabIndex: 0,
    role: "button",
    "aria-label": `${KIND_LABEL[node.kind]} ${node.label}${canChange(node) ? " 다시 고르기" : ""}`,
    onPointerDown: (event: PointerEvent<SVGGElement>) =>
      onPointerDown(event, node),
    onPointerMove,
    onPointerUp: () => onPointerUp(node),
    onKeyDown: (event: KeyboardEvent) => onKeyDown(event, node),
  });
  const stateClass = (node: BlueprintNode) =>
    [
      selected === node.id && "selected",
      (canFocus(node) || canChange(node)) && "editable",
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
  const current = graph.nodes.find((node) => node.id === selected);
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
          viewBox={`0 0 ${width} ${height}`}
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
          aria-label={layer === "agent" ? "에이전트 흐름" : "시스템 구성"}
        >
          <ArrowMarker />
          {isSystem && (
            <ServiceDiagram
              graph={graph}
              point={point}
              nodeClass={stateClass}
              nodeProps={interactions}
            />
          )}
          {!isSystem &&
            mergeEdges(graph.edges).map((edge) => {
              const from = point(edge.source);
              const to = point(edge.target);
              const x1 = from.x + WIDTH;
              const y1 = from.y + HEIGHT / 2;
              const x2 = to.x;
              const y2 = to.y + HEIGHT / 2;
              const bend = Math.max(36, Math.abs(x2 - x1) / 2);
              return (
                <g key={`${edge.source}>${edge.target}`}>
                  <path
                    className={edge.dashed ? "bp-edge dashed" : "bp-edge"}
                    d={`M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2 - 6} ${y2}`}
                    markerEnd="url(#blueprint-arrow)"
                  />
                  <EdgeLabel
                    x={(x1 + x2) / 2}
                    y={(y1 + y2) / 2 - 5}
                    labels={edge.labels}
                  />
                </g>
              );
            })}
          {!isSystem &&
            graph.nodes.map((node) => {
              const at = point(node.id);
              const review = cardOf(node)?.needs_review;
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
                  <text className="bp-kind" x={WIDTH / 2} y={19}>
                    {review ? "다시 확인" : KIND_LABEL[node.kind]}
                  </text>
                  <text className="bp-label" x={WIDTH / 2} y={41}>
                    {shortLabel(node.label)}
                  </text>
                </g>
              );
            })}
        </svg>
      </div>
      <div className="blueprint-detail">
        {lastChange && !example ? (
          <span>
            <strong>방금 반영:</strong> {lastChange}
          </span>
        ) : current ? (
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
              아이콘을 누르면 그 결정을 고칠 수 있어요. Ctrl+휠로 확대·축소, 빈
              곳을 끌어 화면을 옮겨요.
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
            disabled={zoom === null}
            onClick={() => setZoom(null)}
          >
            화면 맞춤
          </button>
        </div>
      </div>
    </section>
  );
}
