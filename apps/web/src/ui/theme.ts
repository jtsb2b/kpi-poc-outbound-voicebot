import { flushSync } from "react-dom";

/** Light/dark appearance. Follows the system until the operator picks one, then remembers it. */
export type Theme = "light" | "dark";

const KEY = "kpi-theme";

export function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function applyTheme(theme: Theme, remember: boolean): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0a1122" : "#f3f6fb");
  if (!remember) return;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

interface ViewTransition {
  ready: Promise<void>;
  updateCallbackDone: Promise<void>;
  finished: Promise<void>;
}
type Doc = Document & { startViewTransition?: (cb: () => void) => ViewTransition };

/** Run a state change as a view transition (cross-fade between screens) where the browser supports it. */
export function transition(update: () => void, kind: "page" | "theme" = "page"): Promise<void> {
  const doc = document as Doc;
  if (!doc.startViewTransition || prefersReducedMotion()) {
    update();
    return Promise.resolve();
  }
  const root = document.documentElement;
  root.dataset.vt = kind;
  const vt = doc.startViewTransition(() => flushSync(update));
  // A transition is skipped when another starts or the tab is hidden; the update still applies.
  vt.ready.catch(() => undefined);
  vt.updateCallbackDone.catch(() => undefined);
  return vt.finished.catch(() => undefined).finally(() => {
    delete root.dataset.vt;
  });
}

/** Switch appearance with a circular reveal that grows from the toggle the operator pressed. */
export function switchTheme(next: Theme, origin?: { x: number; y: number }): void {
  const root = document.documentElement;
  if (origin) {
    const r = Math.hypot(Math.max(origin.x, innerWidth - origin.x), Math.max(origin.y, innerHeight - origin.y));
    root.style.setProperty("--vt-x", `${origin.x}px`);
    root.style.setProperty("--vt-y", `${origin.y}px`);
    root.style.setProperty("--vt-r", `${r}px`);
  }
  void transition(() => applyTheme(next, true), "theme");
}
