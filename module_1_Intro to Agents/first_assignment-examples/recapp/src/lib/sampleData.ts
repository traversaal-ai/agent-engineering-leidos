import { Entry, EntryType, Recap } from "./types";

/**
 * Five sample recaps seeded on first use, so a new visitor lands on a working
 * app instead of an empty screen. They are chosen to show every feature at
 * once: two recaps in the same series (so the grouping is visible), decisions,
 * action items with and without owners, and some already marked done.
 *
 * Users can delete any of them with the Delete button, and they are only ever
 * seeded once.
 */

type SeedEntry = [EntryType, string, string?, boolean?];

type SeedRecap = {
  title: string;
  series: string;
  /** How many days before today this meeting happened. */
  daysAgo: number;
  entries: SeedEntry[];
};

const SEED: SeedRecap[] = [
  {
    title: "Product Standup",
    series: "Weekly Standup",
    daysAgo: 0,
    entries: [
      ["note", "Priya walked through last week's signup numbers."],
      ["decision", "Delaying the beta launch by one week to finish onboarding."],
      ["action", "Send the revised launch date to the wider team", "Priya"],
      ["action", "Finish the empty state copy", "Alex"],
      ["note", "Nobody is blocked this week."],
    ],
  },
  {
    title: "Product Standup",
    series: "Weekly Standup",
    daysAgo: 7,
    entries: [
      ["note", "Reviewed the onboarding drop-off from the last release."],
      [
        "decision",
        "Keeping the two-step signup rather than collapsing it into one.",
      ],
      ["action", "Pull the funnel numbers for next week", "Priya", true],
      ["action", "Write up the drop-off findings", "Sam", true],
    ],
  },
  {
    title: "Northwind quarterly review",
    series: "Client Check-in",
    daysAgo: 3,
    entries: [
      ["note", "Northwind is happy with response times since the migration."],
      ["decision", "Agreed to the extra seats as a change order, not a new contract."],
      ["action", "Send the change order for signature", "Marcus"],
      ["action", "Book the next quarterly review", ""],
      ["note", "They asked about SSO again. Still not on the roadmap."],
    ],
  },
  {
    title: "1:1 with Dana",
    series: "1:1s",
    daysAgo: 5,
    entries: [
      ["note", "Dana wants more time on the reporting work."],
      ["decision", "Dana moves off support rotation for the next two sprints."],
      ["action", "Update the rotation schedule", "Sam"],
      ["action", "Share the reporting spec with Dana", "Dana", true],
    ],
  },
  {
    title: "Settings redesign review",
    series: "Design Review",
    daysAgo: 9,
    entries: [
      ["note", "Walked through three layouts for the settings page."],
      ["decision", "Going with the sidebar layout over the tabbed version."],
      ["decision", "Search stays out of scope for this pass."],
      ["action", "Update the mockups to the sidebar layout", "Alex"],
      ["action", "Check the sidebar against mobile widths", ""],
    ],
  },
];

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export function buildSampleRecaps(): Recap[] {
  const now = Date.now();

  return SEED.map((seed, recapIndex) => {
    const entries: Entry[] = seed.entries.map(
      ([type, text, owner = "", done = false], entryIndex) => ({
        id: `sample_entry_${recapIndex}_${entryIndex}`,
        text,
        type,
        owner,
        done,
      })
    );

    return {
      id: `sample_recap_${recapIndex}`,
      title: seed.title,
      seriesName: seed.series,
      date: isoDaysAgo(seed.daysAgo),
      entries,
      // Offset so the most recent meeting sorts to the top of the list.
      updatedAt: now - seed.daysAgo * 24 * 60 * 60 * 1000,
    };
  });
}
