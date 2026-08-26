import { Recap } from "./types";

const STORAGE_KEY = "recapp:recaps";
const ENTERED_KEY = "recapp:entered";
const THEME_KEY = "recapp:theme";

export type Theme = "light" | "dark";

/**
 * Reads the stored theme, falling back to the OS preference the first time
 * there is nothing stored yet. Kept separate from the inline script in
 * layout.tsx, which does the same read before paint to avoid a flash.
 */
export function getTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function setTheme(theme: Theme): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(THEME_KEY, theme);
  document.documentElement.classList.toggle("dark", theme === "dark");
}

/**
 * Whether the visitor has already come past the landing screen. There are no
 * accounts in this app, so this is only a "do not show the intro again" flag,
 * not a session or any kind of identity.
 */
export function hasEntered(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(ENTERED_KEY) === "true";
}

export function markEntered(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ENTERED_KEY, "true");
}

/**
 * All reads and writes to localStorage go through this module so persistence
 * stays in one place rather than scattered across components.
 */

export function loadRecaps(): Recap[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Recap[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    // Corrupted or unreadable data should not crash the app on load.
    return [];
  }
}

export function saveRecaps(recaps: Recap[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(recaps));
}

function id(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function newRecapId(): string {
  return id("recap");
}

export function newEntryId(): string {
  return id("entry");
}

/** Stamps updatedAt outside of render, keeping components pure. */
export function touch(recap: Recap): Recap {
  return { ...recap, updatedAt: Date.now() };
}

/**
 * The PRD flags permanent data loss as its top risk: everything lives in
 * localStorage with no backend and no recovery. A JSON export is cheap
 * insurance against a cleared cache.
 */
export function exportAllAsJson(recaps: Recap[]): void {
  const blob = new Blob([JSON.stringify(recaps, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "recapp-backup.json";
  a.click();
  URL.revokeObjectURL(url);
}
