import { z } from "zod";
import { designSchema } from "./design/types";
import type { Design } from "./design/types";

const optionViewSchema = z.object({
  option: z.object({
    id: z.string(),
    name: z.string(),
    summary: z.string(),
    pros: z.array(z.string()),
    cons: z.array(z.string()),
    learning_difficulty: z.enum(["low", "medium", "high"]),
    ops_burden: z.enum(["low", "medium", "high"]),
    cost_nature: z.string(),
  }),
  note: z.string(),
  blocked_reason: z.string().nullable(),
  icon: z.string().nullable().optional(),
  implied_messages: z.array(z.string()),
  warnings: z.array(z.string()),
  must_change: z.array(z.string()).default([]), // Absent from journeys saved before it existed.
});

const recommendationSchema = z.object({
  status: z.enum(["recommended", "needs_comparison"]),
  option_id: z.string().nullable(),
  confidence: z.number().nullable(),
  reason: z.string(),
  decider: z.string(),
});

const issueSchema = z.object({
  rule_id: z.string(),
  severity: z.enum(["error", "warning"]),
  message: z.string(),
  card_ids: z.array(z.string()),
});

const promptSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("gcb"),
    questions: z
      .array(z.object({ field: z.string(), question: z.string() }))
      .optional(),
    draft: z.object({
      goal: z.string(),
      context: z.string(),
      boundary: z.string(),
    }),
    source: z.string(),
    error: z.string().nullable(),
  }),
  z.object({
    type: z.literal("clarify"),
    round: z.number(),
    questions: z.array(z.object({ field: z.string(), question: z.string() })),
  }),
  z.object({
    type: z.literal("decision"),
    current_option_id: z.string().nullable().optional(),
    card: z.object({
      card_id: z.string(),
      layer: z.string(),
      question: z.string(),
      options: z.array(optionViewSchema),
      recommendation: recommendationSchema,
      advice_source: z.string(),
      to_review: z.array(z.string()).default([]), // As with must_change.
      evidence: z.array(
        z.object({
          source_id: z.string(),
          title: z.string(),
          kind: z.string(),
          location: z.string(),
          why: z.string(),
          url: z.string().nullable(),
        }),
      ),
      div_refs: z.array(z.string()),
    }),
    qa: z.array(
      z.object({
        question: z.string(),
        answer: z.string(),
        answered_by: z.string(),
      }),
    ),
    conflicts: z.array(issueSchema),
    error: z.string().nullable(),
  }),
  z.object({
    type: z.literal("issues"),
    issues: z.array(issueSchema),
    error: z.string().nullable(),
  }),
]);

const blueprintGraphSchema = z.object({
  nodes: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      kind: z.enum(["code", "agent", "human", "blank", "sys"]),
      card_id: z.string().nullable(),
      icon: z.string().nullable(),
      group: z.string().nullable(),
      rows: z.array(
        z.object({
          role: z.string(),
          label: z.string(),
          card_id: z.string(),
        }),
      ),
      step: z
        .object({
          line: z.string(),
          fixed: z.array(z.string()),
          unknown: z.array(z.string()),
          inputs: z.array(z.string()),
          outputs: z.array(z.string()),
          how: z.string().nullable(),
          tools: z.array(
            z.object({
              name: z.string(),
              access: z.enum(["read", "write", "external_write"]),
              reason: z.string(),
            }),
          ),
          done_when: z.string().nullable(),
          on_failure: z.string().nullable(),
          checks: z.array(z.string()),
          first_task: z.string().nullable(),
          decisions: z.array(
            z.object({ card_id: z.string(), label: z.string() }),
          ),
        })
        .nullable(),
    }),
  ),
  edges: z.array(
    z.object({
      source: z.string(),
      target: z.string(),
      label: z.string().nullable(),
      dashed: z.boolean(),
    }),
  ),
});

const blueprintSchema = z.object({
  agent: blueprintGraphSchema,
  system: blueprintGraphSchema,
  notes: z.array(
    z.object({
      group: z.string(),
      label: z.string(),
      card_id: z.string(),
    }),
  ),
  agent_is_draft: z.boolean(),
});

const blueprintExamplesSchema = z.array(
  z.object({
    id: z.string(),
    name: z.string(),
    note: z.string(),
    blueprint: blueprintSchema,
  }),
);

const moduleItemSchema = z.object({
  text: z.string(),
  how: z.string().nullable(),
  source: z.enum(["rule", "design", "chat", "open"]),
});

const modulePlanSchema = z.object({
  id: z.string(),
  name: z.string(),
  stack: z.array(z.string()),
  cards: z.array(z.string()),
  column: z.number(),
  after: z.array(z.object({ module: z.string(), gate_only: z.boolean() })),
  goal: moduleItemSchema.nullable(),
  include: z.array(moduleItemSchema),
  exclude: z.array(moduleItemSchema),
  gates: z.array(moduleItemSchema.extend({ why: z.string() })),
  criteria: z.array(
    moduleItemSchema.extend({
      kind: z.enum(["quantitative", "qualitative"]),
      needs_target: z.boolean().default(false),
      target: z.string().nullable().default(null),
    }),
  ),
  tasks: z.array(z.string()),
});

const startFieldSchema = z.object({
  name: z.string(),
  label: z.string(),
  kind: z.enum(["text", "choice", "multi"]),
  choices: z.array(z.object({ value: z.string(), label: z.string() })),
  free_text: z.boolean(),
  rule_read: z.boolean(),
  value: z.union([z.string(), z.array(z.string())]).nullable(),
  display: z.string().nullable(),
  source: z.enum(["said", "picked", "default", "recommended"]).nullable(),
  why: z.string().nullable(),
});

const startSchema = z.object({
  mode: z.enum(["model", "form"]),
  fields: z.array(startFieldSchema),
  chat: z.array(
    z.object({
      role: z.enum(["user", "assistant"]),
      text: z.string(),
      changes: z.array(z.string()),
      rejected: z.array(z.string()),
    }),
  ),
  revision: z.number(),
  missing: z.array(z.string()),
  submit: z.record(z.string(), z.unknown()),
});

const moduleTurnSchema = z.object({
  role: z.enum(["user", "assistant"]),
  text: z.string(),
  changes: z.array(z.string()),
  rejected: z.array(z.string()),
});

const journeySchema = z.object({
  journey_id: z.string().uuid(),
  revision: z.number(),
  status: z.enum(["in_progress", "needs_fix", "completed"]),
  idea: z.string(),
  prompt: promptSchema.nullable(),
  cards: z.array(
    z.object({
      card_id: z.string(),
      layer: z.string(),
      stage: z.number(),
      needs_review: z.boolean(),
      editing: z.boolean().optional(),
      title: z.string(),
      question: z.string(),
      state: z.enum([
        "decided",
        "implied",
        "deferred",
        "current",
        "pending",
        "skipped",
      ]),
      option_name: z.string().nullable(),
      by: z.enum(["user", "recommended", "implied"]).nullable(),
      rationale: z.string(),
      skip_confidence: z.number().nullable().optional(),
    }),
  ),
  warnings: z.array(z.string()),
  notice: z.string().nullable(),
  design: z
    .object({
      status: z.string(),
      source: z.string(),
      error: z.string().nullable(),
      nodes: z.array(
        z.object({
          id: z.string(),
          kind: z.string(),
          responsibility: z.string(),
        }),
      ),
      first_task: z.string(),
      first_task_check: z.string(),
      unknowns: z.array(z.string()),
      warnings: z.array(z.string()),
      files: z.array(z.string()),
    })
    .nullable()
    .optional(),
  blueprint: blueprintSchema,
  modules: z.array(modulePlanSchema),
  module_mode: z.enum(["model", "form", "closed"]).default("closed"),
  module_chat: z.array(moduleTurnSchema).default([]),
  module_revision: z.number().default(0),
  module_undo_count: z.number().default(0),
  start: startSchema.nullable().default(null),
  can_reopen: z.boolean().optional().default(false),
});

export type Journey = z.infer<typeof journeySchema>;
export type Prompt = NonNullable<Journey["prompt"]>;
export type DecisionPrompt = Extract<Prompt, { type: "decision" }>;
export type GcbPrompt = Extract<Prompt, { type: "gcb" }>;
export type ClarifyPrompt = Extract<Prompt, { type: "clarify" }>;
export type IssuesPrompt = Extract<Prompt, { type: "issues" }>;
export type CardStatus = Journey["cards"][number];
export type Blueprint = Journey["blueprint"];
export type BlueprintGraph = Blueprint["agent"];
export type BlueprintNode = BlueprintGraph["nodes"][number];
export type BlueprintRow = BlueprintNode["rows"][number];
export type BlueprintStep = NonNullable<BlueprintNode["step"]>;
export type ModulePlan = Journey["modules"][number];
export type ModuleTurn = Journey["module_chat"][number];
export type StartView = NonNullable<Journey["start"]>;
export type StartField = StartView["fields"][number];
export type StartChange = { field: string; value?: string; values?: string[] };
export type ModuleChange =
  | { module: string; field: "goal"; value: string }
  | { module: string; field: "include" | "exclude"; items: string[] }
  | { module: string; field: "target"; criterion: string; value: string };
export type BlueprintNote = Blueprint["notes"][number];
export type BlueprintExample = z.infer<typeof blueprintExamplesSchema>[number];

export type Action =
  | { action: "select"; option_id: string; rationale?: string }
  | { action: "accept_recommendation" }
  | { action: "defer" }
  | { action: "ask"; question: string }
  | { action: "reopen"; card_id: string }
  | { action: "revise"; card_id: string }
  | { action: "focus"; card_id: string }
  | { action: "keep"; card_id: string }
  | { action: "clarify"; answers: Record<string, unknown> }
  | {
      action: "gcb";
      goal: string;
      context: string;
      boundary: string;
      answers?: Record<string, unknown>;
    };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
  }
}

// The last decision also generates the design: up to two long model calls on the server.
const REQUEST_TIMEOUT_MS = 300000;
const OFFLINE =
  "서버에 연결할 수 없어요. 백엔드 실행 상태를 확인하고 다시 시도해 주세요.";

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = z
        .object({ error: z.object({ code: z.string(), message: z.string() }) })
        .safeParse(body);
      if (detail.success)
        throw new ApiError(detail.data.error.message, detail.data.error.code);
      throw new ApiError(OFFLINE, "unavailable");
    }
    const parsed = schema.safeParse(body);
    if (!parsed.success)
      throw new ApiError(
        "결과 형식을 확인하지 못했어요. 다시 시도해 주세요.",
        "invalid_output",
      );
    return parsed.data;
  } catch (error) {
    if (controller.signal.aborted)
      throw new ApiError(
        "응답 시간이 초과됐어요. 다시 시도해 주세요.",
        "timeout",
      );
    if (error instanceof TypeError) throw new ApiError(OFFLINE, "unavailable");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function startJourney(idea: string): Promise<Journey> {
  return request("/api/v1/journeys", journeySchema, {
    method: "POST",
    body: JSON.stringify({ idea: idea.trim() }),
  });
}

export function getJourney(id: string): Promise<Journey> {
  return request(`/api/v1/journeys/${id}`, journeySchema);
}

export function getDesign(id: string): Promise<Design> {
  return request(`/api/v1/journeys/${id}/design`, designSchema);
}

export function saveDesign(
  id: string,
  design: Design,
  renames: Record<string, string>,
): Promise<Design> {
  return request(`/api/v1/journeys/${id}/design`, designSchema, {
    method: "POST",
    body: JSON.stringify({
      design_revision: design.design_revision,
      nodes: design.nodes,
      workflow: design.workflow,
      requirement_nodes: Object.fromEntries(
        design.requirements.map((item) => [item.id, item.node_ids]),
      ),
      renames,
    }),
  });
}

export function getBlueprintExamples(): Promise<BlueprintExample[]> {
  return request("/api/v1/blueprint/examples", blueprintExamplesSchema);
}

export function designViewUrl(id: string): string {
  return `/?design=${id}`;
}

export function packageUrl(id: string): string {
  return `/api/v1/journeys/${id}/package.zip`;
}

export function summaryUrl(id: string): string {
  return `/api/v1/journeys/${id}/summary.md`;
}

function startRequest(
  journey: Journey,
  path: "messages" | "edits" | "fill",
  body: object,
): Promise<Journey> {
  return request(
    `/api/v1/journeys/${journey.journey_id}/start/${path}`,
    journeySchema,
    {
      method: "POST",
      body: JSON.stringify({ revision: journey.start?.revision ?? 0, ...body }),
    },
  );
}

export function sendStartMessage(
  journey: Journey,
  text: string,
  focus: string | null,
): Promise<Journey> {
  return startRequest(journey, "messages", { text: text.trim(), focus });
}

export function editStart(
  journey: Journey,
  change: StartChange,
): Promise<Journey> {
  return startRequest(journey, "edits", { change });
}

export function fillStart(journey: Journey): Promise<Journey> {
  return startRequest(journey, "fill", {});
}

function moduleRequest(
  journey: Journey,
  path: "messages" | "edits" | "undo",
  body: object,
): Promise<Journey> {
  return request(
    `/api/v1/journeys/${journey.journey_id}/modules/${path}`,
    journeySchema,
    {
      method: "POST",
      body: JSON.stringify({ revision: journey.module_revision, ...body }),
    },
  );
}

export function sendModuleMessage(
  journey: Journey,
  text: string,
): Promise<Journey> {
  return moduleRequest(journey, "messages", { text: text.trim() });
}

export function editModule(
  journey: Journey,
  change: ModuleChange,
): Promise<Journey> {
  return moduleRequest(journey, "edits", { change });
}

export function undoModule(journey: Journey): Promise<Journey> {
  return moduleRequest(journey, "undo", {});
}

export function sendAction(journey: Journey, action: Action): Promise<Journey> {
  return request(
    `/api/v1/journeys/${journey.journey_id}/decisions`,
    journeySchema,
    {
      method: "POST",
      body: JSON.stringify({ revision: journey.revision, action }),
    },
  );
}
