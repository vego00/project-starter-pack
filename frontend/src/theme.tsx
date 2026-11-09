import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const KEY = "starter-pack:theme:v1";
const listeners = new Set<() => void>();

function initial(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Without storage the system setting still decides.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

let theme = initial();
// Set while this module loads, so the first paint already has the right colors.
document.documentElement.dataset.theme = theme;

function toggle() {
  theme = theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // The choice still holds until the page is closed.
  }
  listeners.forEach((listener) => listener());
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (changed) => {
      listeners.add(changed);
      return () => listeners.delete(changed);
    },
    () => theme,
  );
}

export function ThemeToggle() {
  const current = useTheme();
  return (
    <button onClick={toggle}>
      {current === "dark" ? "라이트 모드" : "다크 모드"}
    </button>
  );
}
