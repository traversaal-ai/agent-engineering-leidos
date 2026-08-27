// Resolves which endpoint and model the app calls, so it can reach an LLM proxy
// instead of api.anthropic.com. Plain .mjs, because both the API route and the
// scripts/ checks import it, and node runs those scripts without a build step.

const DEFAULT_BASE_URL = "https://api.anthropic.com";
const DEFAULT_MODEL = "claude-sonnet-5";

/**
 * Drops a trailing bracket suffix from a model name, so
 * your-model-name[1m] becomes your-model-name.
 * Claude Code reads the bracket as a routing hint, but a proxy rejects the
 * bracketed name on /v1/messages with a 400. Keeps the original name if
 * stripping leaves nothing.
 *
 * @param {string} model
 * @returns {string}
 */
export function stripAliasSuffix(model) {
  const trimmed = model.trim();
  const stripped = trimmed.replace(/\[[^\]]*\]$/, "");
  return stripped || trimmed;
}

/**
 * The base URL and model to call. ANTHROPIC_BASE_URL and
 * ANTHROPIC_DEFAULT_SONNET_MODEL set them, and each one falls back to the
 * public API. Next loads .env.local into the environment for you, and a value
 * already exported in your shell wins over that file.
 *
 * The variables hold a base URL only. Pasting the full endpoint is an easy
 * mistake, so a trailing /v1/messages comes off rather than being sent twice.
 *
 * @param {Record<string, string | undefined>} [env]
 * @returns {{ baseUrl: string, model: string }}
 */
export function anthropicConfig(env = process.env) {
  const baseUrl = (env.ANTHROPIC_BASE_URL || "").trim() || DEFAULT_BASE_URL;
  const model = (env.ANTHROPIC_DEFAULT_SONNET_MODEL || "").trim() || DEFAULT_MODEL;
  return {
    baseUrl: baseUrl.replace(/\/+$/, "").replace(/\/v1\/messages$/, ""),
    model: stripAliasSuffix(model),
  };
}
