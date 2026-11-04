import { z } from "zod";

const responseSchema = z.object({
  request_id: z.string().uuid(),
  provider: z.literal("mock"),
  is_mock: z.literal(true),
  notice: z.string(),
  starter_pack: z.object({
    pain_point: z.string(),
    goal: z.string(),
    assumptions: z.array(z.string()),
    agent_recommended: z.boolean().nullable(),
    agent_blueprint: z.object({
      architecture: z.enum([
        "undetermined",
        "single_agent",
        "multi_agent",
        "rule_based",
      ]),
      roles: z.array(z.string()),
      workflow: z.array(z.string()),
      tools: z.array(z.string()),
    }),
    next_steps: z.array(z.string()).min(1),
  }),
});

export type GenerateResponse = z.infer<typeof responseSchema>;

export async function generatePack(
  painPoint: string,
  context: string,
): Promise<GenerateResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch("/api/v1/starter-packs/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pain_point: painPoint.trim(),
        context: context.trim(),
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const messages: Record<number, string> = {
        422: "입력 길이를 확인해 주세요. 문제는 10~3,000자, 참고 맥락은 2,000자까지 입력할 수 있어요.",
        502: "결과 형식을 확인하지 못했어요. 다시 시도해 주세요.",
        504: "응답 시간이 초과됐어요. 잠시 후 다시 시도해 주세요.",
      };
      throw new Error(
        messages[response.status] ||
          "서버에 연결할 수 없어요. 백엔드 실행 상태를 확인하고 다시 시도해 주세요.",
      );
    }
    const parsed = responseSchema.safeParse(await response.json());
    if (!parsed.success)
      throw new Error("결과 형식을 확인하지 못했어요. 다시 시도해 주세요.");
    return parsed.data;
  } catch (error) {
    if (controller.signal.aborted)
      throw new Error("응답 시간이 초과됐어요. 다시 시도해 주세요.");
    if (error instanceof TypeError)
      throw new Error(
        "서버에 연결할 수 없어요. 백엔드 실행 상태를 확인하고 다시 시도해 주세요.",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
