"use client";

/**
 * First screen a new visitor sees. The PRD rules out accounts and login
 * entirely, so "Continue as a guest" is the only way in.
 *
 * The illustration is an inline SVG on purpose: no network request, no asset
 * to ship, and it works offline, which matches the local-first constraint.
 */

type Props = {
  onContinue: () => void;
};

export default function LandingScreen({ onContinue }: Props) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-neutral-50 px-6 py-12 dark:bg-neutral-950">
      <MeetingIllustration />

      <h1 className="mt-8 text-4xl font-bold tracking-tight text-neutral-900 dark:text-neutral-100">
        Recapp
      </h1>
      <p className="mt-2 text-base text-neutral-500 dark:text-neutral-400">
        Meeting notes worth keeping.
      </p>

      <button
        onClick={onContinue}
        className="mt-8 rounded-lg bg-neutral-900 px-8 py-3 text-sm font-semibold text-white transition-colors hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
      >
        Continue as a guest
      </button>
    </main>
  );
}

/**
 * Three people around a table, with a speech bubble carrying a checkmark:
 * a conversation that turns into something tracked.
 */
function MeetingIllustration() {
  return (
    <svg
      viewBox="0 0 240 180"
      role="img"
      aria-label="Three people around a meeting table with a checkmark above them"
      className="h-auto w-56"
    >
      {/* Speech bubble with a checkmark */}
      <path
        d="M92 14h56a12 12 0 0 1 12 12v26a12 12 0 0 1-12 12h-30l-12 12v-12h-14a12 12 0 0 1-12-12V26a12 12 0 0 1 12-12z"
        fill="#0ea5e9"
      />
      <path
        d="M110 39.5l7.5 7.5L134 30.5"
        fill="none"
        stroke="#ffffff"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* People are drawn first so the table below overlaps them, which reads
          as seated at the table rather than floating on top of it. */}
      <circle cx="56" cy="104" r="12" fill="#fbbf24" />
      <path d="M38 138c0-11 8-18 18-18s18 7 18 18z" fill="#fbbf24" />

      <circle cx="120" cy="96" r="14" fill="#292524" />
      <path d="M99 134c0-12 9-20 21-20s21 8 21 20z" fill="#292524" />

      <circle cx="184" cy="104" r="12" fill="#38bdf8" />
      <path d="M166 138c0-11 8-18 18-18s18 7 18 18z" fill="#38bdf8" />

      {/* Table, drawn last so it sits in front and hides only the waist down */}
      <ellipse cx="120" cy="156" rx="76" ry="18" fill="#e7e5e4" />
      <ellipse cx="120" cy="152" rx="76" ry="18" fill="#fafaf9" />
      <ellipse
        cx="120"
        cy="152"
        rx="76"
        ry="18"
        fill="none"
        stroke="#d6d3d1"
        strokeWidth="1.5"
      />
    </svg>
  );
}
