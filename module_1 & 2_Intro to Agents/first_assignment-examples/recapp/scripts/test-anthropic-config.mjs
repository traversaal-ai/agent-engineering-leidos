// Checks the endpoint and model resolver in src/lib/anthropic.mjs. Makes no
// network call and needs no API key. Run with: npm run test:config
import assert from "node:assert/strict";
import { anthropicConfig, stripAliasSuffix } from "../src/lib/anthropic.mjs";

const defaults = { baseUrl: "https://api.anthropic.com", model: "claude-sonnet-5" };

assert.deepEqual(anthropicConfig({}), defaults, "nothing set");

assert.deepEqual(
  anthropicConfig({ ANTHROPIC_BASE_URL: "  ", ANTHROPIC_DEFAULT_SONNET_MODEL: "  " }),
  defaults,
  "blank values"
);

assert.deepEqual(
  anthropicConfig({
    ANTHROPIC_BASE_URL: "https://proxy.example.com/",
    ANTHROPIC_DEFAULT_SONNET_MODEL: "some-sonnet[1m]",
  }),
  { baseUrl: "https://proxy.example.com", model: "some-sonnet" },
  "a trailing slash and an alias suffix both come off"
);

assert.equal(
  anthropicConfig({ ANTHROPIC_BASE_URL: "https://proxy.example.com/v1/messages" }).baseUrl,
  "https://proxy.example.com",
  "a pasted full endpoint is not doubled"
);

assert.equal(stripAliasSuffix("plain-model"), "plain-model", "no suffix to strip");
assert.equal(stripAliasSuffix("a[1m] "), "a", "trailing space after the suffix");
assert.equal(stripAliasSuffix("a[1m]-b"), "a[1m]-b", "suffix not at the end, left alone");
assert.equal(stripAliasSuffix("[1m]"), "[1m]", "nothing left, so keep the original");

console.log("config selftest ok");
