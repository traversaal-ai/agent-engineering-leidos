import { Entry, Recap } from "./types";

export type SearchHit = {
  recap: Recap;
  /** The matching entry, or null when only the title or series matched. */
  entry: Entry | null;
};

/**
 * Keyword search across every recap. The PRD requires results to show which
 * recap and which line contain the keyword, so hits carry both.
 */
export function searchRecaps(recaps: Recap[], query: string): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];

  const hits: SearchHit[] = [];

  for (const recap of recaps) {
    const matchingEntries = recap.entries.filter(
      (e) =>
        e.text.toLowerCase().includes(q) || e.owner.toLowerCase().includes(q)
    );

    if (matchingEntries.length > 0) {
      for (const entry of matchingEntries) hits.push({ recap, entry });
      continue;
    }

    // Fall back to a recap-level match so searching a meeting name still works.
    if (
      recap.title.toLowerCase().includes(q) ||
      recap.seriesName.toLowerCase().includes(q)
    ) {
      hits.push({ recap, entry: null });
    }
  }

  return hits;
}

/** Every unresolved action item across all recaps, newest recap first. */
export function openActionItems(
  recaps: Recap[]
): Array<{ recap: Recap; entry: Entry }> {
  return [...recaps]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .flatMap((recap) =>
      recap.entries
        .filter((e) => e.type === "action" && !e.done)
        .map((entry) => ({ recap, entry }))
    );
}
