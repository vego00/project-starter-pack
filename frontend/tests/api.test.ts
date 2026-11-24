// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, getJourney } from "../src/api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("an expired sign-in sends the user to Google sign-in and back", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("", { status: 401 })),
  );
  const assign = vi.fn();
  vi.stubGlobal("location", {
    ...window.location,
    pathname: "/",
    search: "?journey=abc",
    assign,
  });

  await expect(getJourney("abc")).rejects.toMatchObject({
    code: "login_required",
  });
  expect(assign).toHaveBeenCalledWith("/oauth2/start?rd=%2F%3Fjourney%3Dabc");
});

test("other errors keep their server message", async () => {
  const body = {
    error: { code: "journey_not_found", message: "여정을 찾을 수 없어요." },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(Response.json(body, { status: 404 })),
  );

  const error = await getJourney("abc").catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ code: "journey_not_found" });
});
