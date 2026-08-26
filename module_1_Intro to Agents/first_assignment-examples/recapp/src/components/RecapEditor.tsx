"use client";

import { useState } from "react";
import { Entry, Recap } from "@/lib/types";
import { newEntryId } from "@/lib/storage";
import EntryRow from "./EntryRow";
import TranscriptUpload from "./TranscriptUpload";

type Props = {
  recap: Recap;
  onChange: (recap: Recap) => void;
  onDelete: (id: string) => void;
  onDuplicate: (recap: Recap) => void;
  seriesOptions: string[];
};

export default function RecapEditor({
  recap,
  onChange,
  onDelete,
  onDuplicate,
  seriesOptions,
}: Props) {
  const [draft, setDraft] = useState("");

  function update<K extends keyof Recap>(key: K, value: Recap[K]) {
    onChange({ ...recap, [key]: value });
  }

  function addEntry() {
    const text = draft.trim();
    if (!text) return;
    const entry: Entry = {
      id: newEntryId(),
      text,
      type: "note",
      owner: "",
      done: false,
    };
    onChange({ ...recap, entries: [...recap.entries, entry] });
    setDraft("");
  }

  function updateEntry(updated: Entry) {
    onChange({
      ...recap,
      entries: recap.entries.map((e) => (e.id === updated.id ? updated : e)),
    });
  }

  function removeEntry(id: string) {
    onChange({ ...recap, entries: recap.entries.filter((e) => e.id !== id) });
  }

  function addExtractedEntries({
    entries,
  }: {
    title: string;
    seriesName: string;
    entries: Entry[];
  }) {
    onChange({ ...recap, entries: [...recap.entries, ...entries] });
  }

  const decisions = recap.entries.filter((e) => e.type === "decision").length;
  const openActions = recap.entries.filter(
    (e) => e.type === "action" && !e.done
  ).length;

  return (
    <div className="flex h-full flex-col overflow-y-auto p-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <input
          value={recap.title}
          onChange={(e) => update("title", e.target.value)}
          placeholder="Meeting name"
          className="w-full border-none bg-transparent text-xl font-semibold text-neutral-900 outline-none placeholder:text-neutral-300 dark:text-neutral-100 dark:placeholder:text-neutral-600"
        />
        <div className="flex shrink-0 items-center gap-2">
          <TranscriptUpload onExtracted={addExtractedEntries} />
          <button
            onClick={() => onDuplicate(recap)}
            title="Start a new session with the same agenda structure"
            className="rounded-md border border-neutral-200 px-2.5 py-1 text-xs text-neutral-600 hover:border-neutral-400 dark:border-neutral-700 dark:text-neutral-300 dark:hover:border-neutral-500"
          >
            Duplicate
          </button>
          <button
            onClick={() => onDelete(recap.id)}
            className="rounded-md border border-neutral-200 px-2.5 py-1 text-xs text-neutral-500 hover:border-red-300 hover:text-red-600 dark:border-neutral-700 dark:text-neutral-400 dark:hover:border-red-800 dark:hover:text-red-400"
          >
            Delete
          </button>
        </div>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <input
          type="date"
          value={recap.date}
          onChange={(e) => update("date", e.target.value)}
          className="rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-sm text-neutral-700 outline-none focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300"
        />
        <input
          list="series-options"
          value={recap.seriesName}
          onChange={(e) => update("seriesName", e.target.value)}
          placeholder="Meeting series, e.g. Weekly Standup"
          className="min-w-[220px] flex-1 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-sm text-neutral-700 outline-none placeholder:text-neutral-400 focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:placeholder:text-neutral-500"
        />
        <datalist id="series-options">
          {seriesOptions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </div>

      <div className="mb-3 flex gap-3 text-xs text-neutral-500 dark:text-neutral-400">
        <span>{decisions} decision{decisions === 1 ? "" : "s"}</span>
        <span>{openActions} open action{openActions === 1 ? "" : "s"}</span>
      </div>

      <div className="mb-3 flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") addEntry();
          }}
          placeholder="Type a line and press Enter"
          className="flex-1 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-sm outline-none placeholder:text-neutral-400 focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        <button
          onClick={addEntry}
          className="rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
        >
          Add
        </button>
      </div>

      <div className="space-y-2">
        {recap.entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            onChange={updateEntry}
            onRemove={removeEntry}
          />
        ))}
        {recap.entries.length === 0 && (
          <p className="text-sm text-neutral-400 dark:text-neutral-500">
            No lines yet. Add one above, then click its type label to mark it as a
            decision or an action item.
          </p>
        )}
      </div>
    </div>
  );
}
