import { z } from "zod";

// Mirrors the parts of the backend `ServiceDesign` contract this screen reads.
const port = z.object({ name: z.string(), type: z.string() });
const node = z.object({
  id: z.string(),
  kind: z.enum(["code", "agent", "human"]),
  responsibility: z.string(),
  inputs: z.array(port),
  outputs: z.array(port),
  tools: z.array(
    z.object({
      name: z.string(),
      access: z.enum(["read", "write", "external_write"]),
      reason: z.string(),
    }),
  ),
  done_when: z.string(),
  on_failure: z.string(),
  model: z
    .object({ capability: z.string(), provider_scope: z.string() })
    .optional(),
});
const edge = z.object({
  source: z.string(),
  target: z.string(),
  condition: z.string().nullable().default(null),
  on_failure: z.boolean().default(false),
});

export const designSchema = z.object({
  design_revision: z.number().optional(),
  requirements: z.array(
    z.object({
      id: z.string(),
      problem: z.string(),
      success_example: z.string(),
      evidence: z.string().nullable().default(null),
      core: z.boolean(),
      node_ids: z.array(z.string()),
    }),
  ),
  nodes: z.array(node),
  workflow: z.object({
    entry: z.string(),
    exits: z.array(z.string()),
    edges: z.array(edge),
    loop_limits: z
      .array(
        z.object({
          node_ids: z.array(z.string()),
          max_iterations: z.number(),
          on_exceeded: z.string(),
        }),
      )
      .default([]),
    max_model_calls: z.number().nullable().default(null),
  }),
  unknowns: z.array(
    z.object({ text: z.string(), blocks_confirmation: z.boolean() }),
  ),
  warnings: z.array(z.string()),
});

export type Design = z.infer<typeof designSchema>;
export type DesignNode = Design["nodes"][number];
export type DesignEdge = Design["workflow"]["edges"][number];
export type NodeKind = DesignNode["kind"];

export const KIND_LABEL: Record<NodeKind, string> = {
  code: "코드",
  agent: "에이전트",
  human: "사람",
};
