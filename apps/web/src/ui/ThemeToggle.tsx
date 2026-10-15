import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "../icons";
import { applyTheme, currentTheme, storedTheme, switchTheme, systemTheme, type Theme } from "./theme";

export function ThemeToggle({ className = "icon-btn" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>(currentTheme);

  useEffect(() => {
    // Keep following the system while the operator has not chosen.
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const follow = () => {
      if (storedTheme()) return;
      const next = systemTheme();
      applyTheme(next, false);
      setTheme(next);
    };
    media?.addEventListener("change", follow);
    return () => media?.removeEventListener("change", follow);
  }, []);

  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className={className}
      aria-label={next === "dark" ? "เปลี่ยนเป็นโหมดมืด" : "เปลี่ยนเป็นโหมดสว่าง"}
      title={next === "dark" ? "โหมดมืด" : "โหมดสว่าง"}
      onClick={(e) => {
        const box = e.currentTarget.getBoundingClientRect();
        switchTheme(next, { x: box.left + box.width / 2, y: box.top + box.height / 2 });
        setTheme(next);
      }}
    >
      <span className="theme-icon" data-shown={theme}>
        <SunIcon size={18} />
        <MoonIcon size={18} />
      </span>
    </button>
  );
}
