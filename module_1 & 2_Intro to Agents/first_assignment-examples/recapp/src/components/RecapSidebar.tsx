"use client";

import { useMemo, useState } from "react";
import { Entry, Recap } from "@/lib/types";
import { searchRecaps } from "@/lib/search";
import TranscriptUpload from "./TranscriptUpload";

type Props = {
  recaps: Recap[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreateFromTranscript: (result: {
    title: string;
    seriesName: string;
    entries: Entry[];
  }) => void;
  onCreateBlank: () => void;
  onExport: () => void;
};

const UNGROUPED = "Ungrouped";

export default function RecapSidebar({
  recaps,
  selectedId,
  onSelect,
  onCreateFromTranscript,
  onCreateBlank,
  onExport,
}: Props) {
  const [query, setQuery] = useState("");

  const hits = useMemo(() => searchRecaps(recaps, query), [recaps, query]);

  // Group recaps by series, newest first within each group.
  const groups = useMemo(() => {
    const map = new Map<string, Recap[]>();
    for (const r of recaps) {
      const key = r.seriesName.trim() || UNGROUPED;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    for (const list of map.values()) {
      list.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [recaps]);

  const seriesNames = useMemo(
    () => [...new Set(recaps.map((r) => r.seriesName.trim()).filter(Boolean))],
    [recaps]
  );

  return (
    <div className="flex h-full flex-col border-r border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="border-b border-neutral-200 p-3 dark:border-neutral-800">
        <TranscriptUpload
          triggerLabel="New from transcript"
          triggerClassName="w-full rounded-md bg-neutral-900 px-3 py-2 text-xs font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
          onExtracted={onCreateFromTranscript}
          existingSeries={seriesNames}
        />
        <button
          onClick={onCreateBlank}
          className="mt-1.5 w-full text-center text-[11px] text-neutral-400 hover:text-neutral-600 hover:underline dark:text-neutral-500 dark:hover:text-neutral-300"
        >
          or start a blank recap
        </button>
      </div>

      <div className="border-b border-neutral-200 p-3 dark:border-neutral-800">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search all recaps"
          className="w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm outline-none focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {query.trim() ? (
          <div className="p-2">
            <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500">
              {hits.length} result{hits.length === 1 ? "" : "s"}
            </p>
            {hits.length === 0 && (
              <p className="px-1 text-sm text-neutral-400 dark:text-neutral-500">
                No results found.
              </p>
            )}
            {hits.map((hit, i) => (
              <button
                key={`${hit.recap.id}-${hit.entry?.id ?? "recap"}-${i}`}
                onClick={() => onSelect(hit.recap.id)}
                className="mb-1.5 block w-full rounded-md border border-neutral-200 bg-white p-2 text-left hover:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:hover:border-neutral-500"
              >
                <div className="truncate text-xs font-semibold text-neutral-900 dark:text-neutral-100">
                  {hit.recap.title || "Untitled"}
                </div>
                <div className="truncate text-[11px] text-neutral-500 dark:text-neutral-400">
                  {hit.entry ? hit.entry.text : "matched the meeting name"}
                </div>
              </button>
            ))}
          </div>
        ) : (
          <>
            {recaps.length === 0 && (
              <p className="p-4 text-sm text-neutral-400 dark:text-neutral-500">
                No recaps yet. Upload a transcript above to get started.
              </p>
            )}
            {groups.map(([series, list]) => (
              <div key={series} className="mb-1">
                <p className="px-3 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500">
                  {series}
                </p>
                {list.map((recap) => {
                  const open = recap.entries.filter(
                    (e) => e.type === "action" && !e.done
                  ).length;
                  return (
                    <button
                      key={recap.id}
                      onClick={() => onSelect(recap.id)}
                      className={`block w-full px-3 py-2 text-left transition-colors ${
                        selectedId === recap.id
                          ? "bg-white dark:bg-neutral-800"
                          : "hover:bg-neutral-100 dark:hover:bg-neutral-800/60"
                      }`}
                    >
                      <div className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">
                        {recap.title || "Untitled"}
                      </div>
                      <div className="text-[11px] text-neutral-500 dark:text-neutral-400">
                        {recap.date || "no date"}
                        {open > 0 && (
                          <span className="ml-2 rounded-full bg-sky-100 px-1.5 py-0.5 text-sky-700 dark:bg-sky-950 dark:text-sky-400">
                            {open} open
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            ))}
          </>
        )}
      </div>

      <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">
        <button
          onClick={onExport}
          className="w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-xs text-neutral-600 hover:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:border-neutral-500"
        >
          Export backup (.json)
        </button>
      </div>
    </div>
  );
}
