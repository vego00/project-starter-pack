import { DESIGN_CASES } from "./mock";
import type { DesignCase } from "./mock";

// The one place to swap for the real API. The screen only knows `DesignCase`.
export function loadDesignCases(): DesignCase[] {
  return DESIGN_CASES;
}
