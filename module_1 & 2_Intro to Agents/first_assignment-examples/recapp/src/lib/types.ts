/**
 * Data model for Recapp, derived from the PRD in ../02-prd-generator/recapp/prd.md
 *
 * A recap is an ordered list of entries rather than one free-text blob. The PRD
 * requires marking an individual line as a decision or an action item with an
 * owner (must-have stories 3 and 4), which a single text field cannot express
 * without fragile parsing.
 */

export type EntryType = "note" | "decision" | "action";

export type Entry = {
  id: string;
  text: string;
  type: EntryType;
  /** Only meaningful when type is "action". Empty string means unassigned. */
  owner: string;
  /** Only meaningful when type is "action". */
  done: boolean;
};

export type Recap = {
  id: string;
  /** Meeting name, required by the PRD ("prompted to enter a name"). */
  title: string;
  /**
   * Recurring meeting series this recap belongs to, e.g. "Weekly Standup".
   * Stored as a plain string so grouping needs no separate entity.
   */
  seriesName: string;
  /** ISO date, YYYY-MM-DD. */
  date: string;
  entries: Entry[];
  updatedAt: number;
};
