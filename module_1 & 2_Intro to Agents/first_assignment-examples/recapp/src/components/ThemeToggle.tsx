"use client";

import { useEffect, useState } from "react";
import { getTheme, setTheme, Theme } from "@/lib/storage";

export default function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of a browser-only preference on mount
    setThemeState(getTheme());
  }, []);

  if (!theme) return null;

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  }

  return (
    <button
      onClick={toggle}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      className="rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs text-neutral-600 hover:border-neutral-400 dark:border-neutral-700 dark:text-neutral-300 dark:hover:border-neutral-500"
    >
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}
