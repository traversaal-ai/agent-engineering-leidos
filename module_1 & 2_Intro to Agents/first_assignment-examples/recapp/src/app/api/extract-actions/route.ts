import { NextRequest, NextResponse } from "next/server";
import { anthropicConfig } from "@/lib/anthropic.mjs";

/**
 * Turns a pasted/uploaded transcript into candidate entries (decisions and
 * action items with an owner) using Claude. The transcript itself is only
 * ever sent out for this one extraction call; it is never persisted
 * server-side. The API key stays in this route and is never sent to the
 * browser. ANTHROPIC_BASE_URL decides where the call goes, so the transcript
 * reaches your own LLM proxy instead of api.anthropic.com when you set it.
 */

const MAX_TRANSCRIPT_CHARS = 60_000;

const EXTRACT_TOOL = {
  name: "record_entries",
  description: "Record the decisions and action items found in a meeting transcript.",
  input_schema: {
    type: "object" as const,
    properties: {
      title: {
        type: "string",
        description:
          "A short, specific title for this meeting based on what was discussed, e.g. 'Product Launch Sync' or 'Client Check-in with Acme Corp'. 2-6 words.",
      },
      seriesName: {
        type: "string",
        description:
          "The recurring meeting series this belongs to, so similar meetings can be grouped together, e.g. 'Weekly Standup', 'Acme Corp Check-ins', 'Design Review'. " +
          "Infer this from the cadence and subject implied by the transcript (who's involved, what kind of meeting it sounds like). 2-4 words. Do not just repeat the title.",
      },
      entries: {
        type: "array",
        items: {
          type: "object",
          properties: {
            type: {
              type: "string",
              enum: ["decision", "action"],
              description: "'decision' for something the group agreed on, 'action' for a task someone owns.",
            },
            text: {
              type: "string",
              description: "A short, standalone statement of the decision or task.",
            },
            owner: {
              type: "string",
              description: "First name of the person responsible. Empty string if the transcript does not say.",
            },
          },
          required: ["type", "text", "owner"],
        },
      },
    },
    required: ["title", "seriesName", "entries"],
  },
};

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "Server is missing ANTHROPIC_API_KEY. Add it to .env.local and restart." },
      { status: 500 }
    );
  }

  let transcript: unknown;
  let existingSeries: unknown;
  try {
    const body = await req.json();
    transcript = body?.transcript;
    existingSeries = body?.existingSeries;
  } catch {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  if (typeof transcript !== "string" || !transcript.trim()) {
    return NextResponse.json({ error: "Transcript text is required." }, { status: 400 });
  }

  const trimmed = transcript.slice(0, MAX_TRANSCRIPT_CHARS);
  const seriesList = Array.isArray(existingSeries)
    ? existingSeries.filter((s): s is string => typeof s === "string" && s.trim().length > 0)
    : [];

  const { baseUrl, model } = anthropicConfig();

  const response = await fetch(`${baseUrl}/v1/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model,
      max_tokens: 4096,
      system:
        "You extract a title, a meeting series name, decisions, and action items from raw meeting transcripts. " +
        "A decision is something the group explicitly agreed on. An action item is a task assigned " +
        "to a specific person. Skip small talk and general discussion that isn't a decision or a task. " +
        "Keep each entry short and standalone so it reads on its own outside the transcript. " +
        (seriesList.length > 0
          ? `The user already has these meeting series: ${seriesList.join(", ")}. ` +
            "If this transcript is clearly another session of one of those series, reuse that exact name for seriesName. " +
            "Otherwise propose a new short series name."
          : "Propose a short series name for grouping future meetings like this one."),
      messages: [{ role: "user", content: trimmed }],
      tools: [EXTRACT_TOOL],
      tool_choice: { type: "tool", name: "record_entries" },
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    return NextResponse.json(
      { error: err?.error?.message || `Claude request failed (${response.status}).` },
      { status: 502 }
    );
  }

  const data = await response.json();
  const toolUse = data.content?.find(
    (block: { type: string }) => block.type === "tool_use"
  );
  const entries = toolUse?.input?.entries;
  const title = toolUse?.input?.title;
  const seriesName = toolUse?.input?.seriesName;

  if (!Array.isArray(entries)) {
    return NextResponse.json({ error: "Claude did not return any entries." }, { status: 502 });
  }

  const cleaned = entries
    .filter(
      (e): e is { type: string; text: string; owner: string } =>
        e && typeof e.text === "string" && e.text.trim().length > 0
    )
    .map((e) => ({
      type: e.type === "action" ? "action" : "decision",
      text: e.text.trim(),
      owner: typeof e.owner === "string" ? e.owner.trim() : "",
    }));

  return NextResponse.json({
    title: typeof title === "string" ? title.trim() : "",
    seriesName: typeof seriesName === "string" ? seriesName.trim() : "",
    entries: cleaned,
  });
}
