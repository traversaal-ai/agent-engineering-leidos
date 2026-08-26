"use client";

import { useRef, useState } from "react";
import { Entry, EntryType } from "@/lib/types";
import { newEntryId } from "@/lib/storage";

type ExtractedEntry = { type: EntryType; text: string; owner: string };

type Props = {
  onExtracted: (result: { title: string; seriesName: string; entries: Entry[] }) => void;
  /** Text for the button that opens the modal. */
  triggerLabel?: string;
  /** Styling for the trigger button; defaults to a small outline button. */
  triggerClassName?: string;
  /** Existing meeting series names, so Claude can reuse one instead of inventing a duplicate. */
  existingSeries?: string[];
};

export default function TranscriptUpload({
  onExtracted,
  triggerLabel = "Upload transcript",
  triggerClassName = "shrink-0 rounded-md border border-neutral-200 px-2.5 py-1 text-xs text-neutral-600 hover:border-neutral-400",
  existingSeries = [],
}: Props) {
  const [open, setOpen] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setError(null);
    try {
      const text = await file.text();
      setTranscript(text);
    } catch {
      setError("Could not read that file. Try a plain .txt export of the transcript.");
    }
  }

  async function handleGenerate() {
    if (!transcript.trim()) {
      setError("Paste or upload a transcript first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/extract-actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, existingSeries }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.error || "Something went wrong extracting action items.");
        return;
      }
      const extracted: ExtractedEntry[] = data.entries ?? [];
      if (extracted.length === 0) {
        setError("No decisions or action items were found in that transcript.");
        return;
      }
      const entries: Entry[] = extracted.map((e) => ({
        id: newEntryId(),
        text: e.text,
        type: e.type,
        owner: e.owner,
        done: false,
      }));
      onExtracted({
        title: typeof data.title === "string" ? data.title : "",
        seriesName: typeof data.seriesName === "string" ? data.seriesName : "",
        entries,
      });
      setOpen(false);
      setTranscript("");
    } catch {
      setError("Could not reach the server. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className={triggerClassName}>
        {triggerLabel}
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white p-5 shadow-xl dark:bg-neutral-900">
        <div className="mb-3 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
              Generate action items from a transcript
            </h2>
            <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Paste a transcript or upload a .txt file. Claude will find the decisions and
              action items and add them as entries you can edit before saving.
            </p>
          </div>
          <button
            onClick={() => {
              setOpen(false);
              setError(null);
            }}
            className="shrink-0 text-neutral-400 hover:text-neutral-700 dark:text-neutral-500 dark:hover:text-neutral-300"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder="Paste the meeting transcript here..."
          rows={8}
          className="w-full resize-none rounded-md border border-neutral-200 bg-white p-2.5 text-sm outline-none placeholder:text-neutral-400 focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />

        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,text/plain"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
            e.target.value = "";
          }}
        />

        {error && (
          <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>
        )}

        <div className="mt-3 flex items-center justify-between">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs text-neutral-600 hover:border-neutral-400 dark:border-neutral-700 dark:text-neutral-300 dark:hover:border-neutral-500"
          >
            Choose .txt file
          </button>
          <div className="flex gap-2">
            <button
              onClick={() => {
                setOpen(false);
                setError(null);
              }}
              className="rounded-md px-3 py-1.5 text-xs text-neutral-500 hover:text-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-100"
            >
              Cancel
            </button>
            <button
              onClick={handleGenerate}
              disabled={loading}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
            >
              {loading ? "Generating..." : "Generate action items"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
