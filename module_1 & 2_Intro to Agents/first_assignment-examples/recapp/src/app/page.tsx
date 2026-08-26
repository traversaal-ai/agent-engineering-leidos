"use client";

import { useEffect, useMemo, useState } from "react";
import { Entry, Recap } from "@/lib/types";
import {
  loadRecaps,
  saveRecaps,
  newRecapId,
  newEntryId,
  touch,
  exportAllAsJson,
  hasEntered,
  markEntered,
} from "@/lib/storage";
import { openActionItems } from "@/lib/search";
import { buildSampleRecaps } from "@/lib/sampleData";
import RecapSidebar from "@/components/RecapSidebar";
import RecapEditor from "@/components/RecapEditor";
import LandingScreen from "@/components/LandingScreen";
import ThemeToggle from "@/components/ThemeToggle";

export default function Home() {
  const [recaps, setRecaps] = useState<Recap[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [showOpenItems, setShowOpenItems] = useState(false);
  const [entered, setEntered] = useState(false);
  const [ownerFilter, setOwnerFilter] = useState("");
  const [historySeries, setHistorySeries] = useState<string | null>(null);

  // Load once on mount. This has to happen in an effect rather than a lazy
  // useState initializer: localStorage does not exist during server rendering,
  // so reading it in render would break hydration.
  useEffect(() => {
    const initial = loadRecaps();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time sync from a browser-only store on mount
    setRecaps(initial);
    if (initial.length > 0) {
      const newest = [...initial].sort((a, b) => b.updatedAt - a.updatedAt)[0];
      setSelectedId(newest.id);
    }
    // Returning visitors, and anyone who already has recaps, skip the intro.
    setEntered(hasEntered() || initial.length > 0);
    setLoaded(true);
  }, []);

  function handleContinueAsGuest() {
    markEntered();
    setEntered(true);

    // Seed sample recaps so the app opens with something to look at rather
    // than an empty screen. Only ever done when there is nothing stored, so a
    // returning user who deleted them does not get them back.
    if (recaps.length === 0) {
      const samples = buildSampleRecaps();
      setRecaps(samples);
      setSelectedId(samples[0].id);
    }
  }

  // Autosave. The PRD requires persistence with no explicit save action.
  useEffect(() => {
    if (!loaded) return;
    saveRecaps(recaps);
  }, [recaps, loaded]);

  const seriesOptions = useMemo(
    () =>
      [...new Set(recaps.map((r) => r.seriesName.trim()).filter(Boolean))].sort(),
    [recaps]
  );

  const openItems = useMemo(() => openActionItems(recaps), [recaps]);

  const UNASSIGNED = "__unassigned__";

  const owners = useMemo(
    () =>
      [...new Set(openItems.map(({ entry }) => entry.owner.trim()).filter(Boolean))].sort(),
    [openItems]
  );

  const filteredOpenItems = useMemo(() => {
    if (!ownerFilter) return openItems;
    if (ownerFilter === UNASSIGNED) {
      return openItems.filter(({ entry }) => !entry.owner.trim());
    }
    return openItems.filter(({ entry }) => entry.owner.trim() === ownerFilter);
  }, [openItems, ownerFilter]);

  function handleCreateBlank() {
    const recap: Recap = {
      id: newRecapId(),
      title: "",
      seriesName: "",
      date: new Date().toISOString().slice(0, 10),
      entries: [],
      updatedAt: Date.now(),
    };
    setRecaps((prev) => [recap, ...prev]);
    setSelectedId(recap.id);
    setShowOpenItems(false);
  }

  function handleCreateFromTranscript({
    title,
    seriesName,
    entries,
  }: {
    title: string;
    seriesName: string;
    entries: Entry[];
  }) {
    const recap: Recap = {
      id: newRecapId(),
      title: title || "Untitled meeting",
      seriesName,
      date: new Date().toISOString().slice(0, 10),
      entries,
      updatedAt: Date.now(),
    };
    setRecaps((prev) => [recap, ...prev]);
    setSelectedId(recap.id);
    setShowOpenItems(false);
  }

  function handleDuplicate(source: Recap) {
    // Copies the agenda structure for the next occurrence of a recurring
    // meeting: same title, series, and line items, but a fresh date and
    // every action item reset to open, since last time's completion status
    // does not carry over to a new session.
    const recap: Recap = {
      id: newRecapId(),
      title: source.title,
      seriesName: source.seriesName,
      date: new Date().toISOString().slice(0, 10),
      entries: source.entries.map((entry) => ({
        ...entry,
        id: newEntryId(),
        done: false,
      })),
      updatedAt: Date.now(),
    };
    setRecaps((prev) => [recap, ...prev]);
    setSelectedId(recap.id);
    setShowOpenItems(false);
  }

  function handleChange(updated: Recap) {
    const stamped = touch(updated);
    setRecaps((prev) => prev.map((r) => (r.id === stamped.id ? stamped : r)));
  }

  function handleDelete(id: string) {
    setRecaps((prev) => prev.filter((r) => r.id !== id));
    setSelectedId((current) => (current === id ? null : current));
  }

  const selected = recaps.find((r) => r.id === selectedId) ?? null;

  // Render nothing until localStorage has been read, so returning visitors do
  // not see the landing screen flash before it is skipped.
  if (!loaded) return null;

  if (!entered) return <LandingScreen onContinue={handleContinueAsGuest} />;

  return (
    <div className="flex h-screen flex-col bg-white dark:bg-neutral-950">
      <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-3 dark:border-neutral-800">
        <div>
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            Recapp
          </h1>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            Meeting decisions and action items, saved locally in this browser. No
            account needed.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            onClick={() => setShowOpenItems((v) => !v)}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
              showOpenItems
                ? "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-700 dark:bg-sky-950 dark:text-sky-300"
                : "border-neutral-200 text-neutral-600 hover:border-neutral-400 dark:border-neutral-700 dark:text-neutral-300 dark:hover:border-neutral-500"
            }`}
          >
            Open action items ({openItems.length})
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-80 shrink-0">
          <RecapSidebar
            recaps={recaps}
            selectedId={selectedId}
            onSelect={(id) => {
              setSelectedId(id);
              setShowOpenItems(false);
            }}
            onCreateFromTranscript={handleCreateFromTranscript}
            onCreateBlank={handleCreateBlank}
            onExport={() => exportAllAsJson(recaps)}
          />
        </div>

        <div className="flex-1 overflow-hidden">
          {showOpenItems ? (
            <div className="h-full overflow-y-auto p-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
                  Open action items across all meetings
                </h2>
                {owners.length > 0 && (
                  <select
                    value={ownerFilter}
                    onChange={(e) => setOwnerFilter(e.target.value)}
                    className="rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-xs text-neutral-700 outline-none focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300"
                  >
                    <option value="">All owners</option>
                    {owners.map((owner) => (
                      <option key={owner} value={owner}>
                        {owner}
                      </option>
                    ))}
                    <option value={UNASSIGNED}>Unassigned</option>
                  </select>
                )}
              </div>
              {openItems.length === 0 && (
                <p className="text-sm text-neutral-400 dark:text-neutral-500">
                  Nothing outstanding. Action items you add will show up here
                  until they are marked done.
                </p>
              )}
              {openItems.length > 0 && filteredOpenItems.length === 0 && (
                <p className="text-sm text-neutral-400 dark:text-neutral-500">
                  No open action items for that owner.
                </p>
              )}
              <ul className="space-y-2">
                {filteredOpenItems.map(({ recap, entry }) => (
                  <li
                    key={entry.id}
                    className="rounded-md border border-neutral-200 p-3 dark:border-neutral-800"
                  >
                    <div className="text-sm text-neutral-900 dark:text-neutral-100">
                      {entry.text}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-neutral-500 dark:text-neutral-400">
                      <span>
                        {entry.owner.trim() ? (
                          <>Owner: {entry.owner}</>
                        ) : (
                          <span className="rounded bg-red-100 px-1.5 py-0.5 font-semibold text-red-700 dark:bg-red-950 dark:text-red-400">
                            unassigned
                          </span>
                        )}
                      </span>
                      <span>in</span>
                      <button
                        onClick={() => {
                          setSelectedId(recap.id);
                          setShowOpenItems(false);
                        }}
                        className="font-medium text-neutral-700 underline hover:text-neutral-900 dark:text-neutral-300 dark:hover:text-neutral-100"
                      >
                        {recap.title || "Untitled"}
                      </button>
                      <span>{recap.date}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : selected ? (
            <RecapEditor
              recap={selected}
              onChange={handleChange}
              onDelete={handleDelete}
              onDuplicate={handleDuplicate}
              seriesOptions={seriesOptions}
            />
          ) : (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm text-neutral-400 dark:text-neutral-500">
              Select a recap, or name a new one in the sidebar to get started.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
