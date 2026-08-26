// Sanity-checks that ANTHROPIC_API_KEY (loaded from .env.local) is valid.
// Never logs the key itself. Run with: npm run test:key
const apiKey = process.env.ANTHROPIC_API_KEY;

if (!apiKey) {
  console.error("ANTHROPIC_API_KEY is not set. Add it to .env.local.");
  process.exit(1);
}

const response = await fetch("https://api.anthropic.com/v1/messages", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "x-api-key": apiKey,
    "anthropic-version": "2023-06-01",
  },
  body: JSON.stringify({
    model: "claude-sonnet-5",
    max_tokens: 16,
    messages: [{ role: "user", content: "Reply with the single word: ok" }],
  }),
});

if (!response.ok) {
  const err = await response.json().catch(() => ({}));
  console.error(`API key check failed (${response.status}):`, err?.error?.message || "unknown error");
  process.exit(1);
}

const data = await response.json();
console.log("API key is valid. Model responded:", data.content?.[0]?.text?.trim());
