"use client";

import { Entry, EntryType } from "@/lib/types";

const TYPE_LABELS: Record<EntryType, string> = {
  note: "Note",
  decision: "Decision",
  action: "Action",
};

const TYPE_STYLES: Record<EntryType, string> = {
  note: "bg-neutral-100 text-neutral-600 border-neutral-200 dark:bg-neutral-800 dark:text-neutral-300 dark:border-neutral-700",
  decision:
    "bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-400 dark:border-amber-800",
  action:
    "bg-sky-50 text-sky-800 border-sky-300 dark:bg-sky-950 dark:text-sky-400 dark:border-sky-800",
};

type Props = {
  entry: Entry;
  onChange: (entry: Entry) => void;
  onRemove: (id: string) => void;
};

export default function EntryRow({ entry, onChange, onRemove }: Props) {
  function cycleType() {
    const order: EntryType[] = ["note", "decision", "action"];
    const next = order[(order.indexOf(entry.type) + 1) % order.length];
    onChange({ ...entry, type: next });
  }

  const isAction = entry.type === "action";
  const unassigned = isAction && entry.owner.trim() === "";

  return (
    <div
      className={`rounded-md border p-2 ${
        entry.type === "note"
          ? "border-neutral-200 dark:border-neutral-700"
          : TYPE_STYLES[entry.type]
      }`}
    >
      <div className="flex items-start gap-2">
        <button
          onClick={cycleType}
          title="Click to change type"
          className={`shrink-0 rounded border px-2 py-0.5 text-[11px] font-semibold ${TYPE_STYLES[entry.type]}`}
        >
          {TYPE_LABELS[entry.type]}
        </button>

        {isAction && (
          <input
            type="checkbox"
            checked={entry.done}
            onChange={() => onChange({ ...entry, done: !entry.done })}
            title="Mark done"
            className="mt-1 h-4 w-4 shrink-0 accent-sky-600"
          />
        )}

        <input
          value={entry.text}
          onChange={(e) => onChange({ ...entry, text: e.target.value })}
          placeholder="What was said, decided, or assigned"
          className={`min-w-0 flex-1 border-none bg-transparent text-sm outline-none placeholder:text-neutral-400 dark:placeholder:text-neutral-500 ${
            entry.done
              ? "text-neutral-400 line-through dark:text-neutral-500"
              : "text-neutral-900 dark:text-neutral-100"
          }`}
        />

        <button
          onClick={() => onRemove(entry.id)}
          className="shrink-0 text-xs text-neutral-400 hover:text-red-600 dark:text-neutral-500 dark:hover:text-red-400"
        >
          remove
        </button>
      </div>

      {isAction && (
        <div className="mt-1.5 flex items-center gap-2 pl-1">
          <label className="text-[11px] font-medium text-neutral-500 dark:text-neutral-400">
            Owner
          </label>
          <input
            value={entry.owner}
            onChange={(e) => onChange({ ...entry, owner: e.target.value })}
            placeholder="unassigned"
            className="w-40 rounded border border-neutral-200 bg-white px-1.5 py-0.5 text-xs outline-none focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-500"
          />
          {unassigned && (
            <span className="rounded bg-red-100 px-1.5 py-0.5 text-[11px] font-semibold text-red-700 dark:bg-red-950 dark:text-red-400">
              unassigned
            </span>
          )}
        </div>
      )}
    </div>
  );
}
