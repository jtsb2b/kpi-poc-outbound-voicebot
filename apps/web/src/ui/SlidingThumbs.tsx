import { useEffect } from "react";

const TRACKS = ".tabs, .segmented";
const SELECTED = ':scope > [aria-selected="true"], :scope > [aria-pressed="true"]';

/** Measure each tab/segmented track and place its glass thumb under the selected item. */
function place(track: HTMLElement) {
  const selected = track.querySelector<HTMLElement>(SELECTED);
  if (!selected) {
    track.classList.remove("has-thumb");
    return;
  }
  track.style.setProperty("--thumb-x", `${selected.offsetLeft}px`);
  track.style.setProperty("--thumb-w", `${selected.offsetWidth}px`);
  if (!track.classList.contains("has-thumb")) {
    track.classList.add("has-thumb");
    // Arrive in place on first paint, then animate every later move.
    requestAnimationFrame(() => requestAnimationFrame(() => track.classList.add("thumb-ready")));
  }
}

/**
 * One glass thumb per tab bar and segmented control that slides (with a little spring) to the
 * selected item instead of jumping. Works on every track in the app without touching the
 * components: it watches selection attributes and track sizes.
 */
export function SlidingThumbs() {
  useEffect(() => {
    const sized = new ResizeObserver((entries) => entries.forEach((e) => place(e.target as HTMLElement)));
    const watched = new WeakSet<Element>();
    const scan = () =>
      document.querySelectorAll<HTMLElement>(TRACKS).forEach((track) => {
        if (!watched.has(track)) {
          watched.add(track);
          sized.observe(track);
        }
        place(track);
      });
    const changes = new MutationObserver(scan);
    changes.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-selected", "aria-pressed"],
    });
    scan();
    void document.fonts?.ready.then(scan);
    return () => {
      changes.disconnect();
      sized.disconnect();
    };
  }, []);
  return null;
}
