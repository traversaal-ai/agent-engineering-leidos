# Reference: Voice AI Architectures — Speech-to-Speech vs. Cascaded

Deep dive on the module's "Voice AI Architectures" section. Voice AI is presented as becoming the new interface, enterprise-ready voice agents for automated phone calls, regulated industries, customer conversations, AI call centers, and inbound call handling are now offered across a wide range of vendor products.

## Two fundamental approaches

There are **two** fundamental approaches to building a voice agent: a direct **Speech-to-Speech (1 hop)** pipeline for low latency, and a **Cascading (3 hops)** pipeline that trades speed for flexibility and control.

```
Speech-to-Speech — 1 hop
User Speech -> [Speech-to-Speech Model: audio in -> audio out, natively] -> Agent Speech
                         (single model, both directions)

Cascaded — 3 hops
User Speech -> [STT: speech -> text] -> [LLM: understand + respond] -> [TTS: text -> speech] -> Agent Speech
```

## How an S2S model differs from a standard text LLM

| | Standard Text LLM (GPT, Claude, Llama, Gemini) | Speech-to-Speech Model (gpt-realtime, Gemini Live, native audio) |
|---|---|---|
| Input | Input text (typed prompt / API request) | Input audio (encoded to audio tokens) |
| Token stream | Text tokens only (one modality) | Unified token stream: audio + text + image + video |
| Core | Decoder-only transformer (masked/causal self-attention) | Decoder-only transformer (cross-modal reasoning) — **same core** |
| Mid-stream | Tool / function calling | Tool calls mid-turn, optional text transcript |
| Output | Output text tokens (next-token prediction / logits) | Output audio tokens (decoded to 24kHz PCM) |
| Delivery | Text response (detokenized, batch or text stream) | Full-duplex streaming (VAD + barge-in over WebSocket) |

The headline point: an S2S model shares the **same core** transformer architecture as a standard text LLM. What changes is the modality at the boundary, audio in and audio out instead of text in and text out, and the fact that a single forward pass produces the response instead of a separate text-generation-then-TTS step.

## One transformer, full-duplex, native barge-in

The model layer for S2S is native audio and multimodal:

- **Audio encoded into tokens**, mixed with text/image/video in one stream.
- A **single transformer** reasons across all modalities together.
- Generates output **audio tokens** directly, no separate TTS step.
- Optional **parallel text transcript** (the only way to get text out).
- Streams in/out over a **full-duplex WebSocket** with built-in **VAD** (Voice Activity Detection) and **barge-in** (see `voice-ai-frameworks.md` and the key terms list below for definitions).
- **Tool calling** still works mid-turn.

## Comparing closed-source S2S models

| Provider | Model | Cost (input) | Cost (output) | Latency |
|---|---|---|---|---|
| Google | gemini-3.1-flash-live-preview | $3.00/M audio tok (~$0.005/min) | $12.00/M audio tok (~$0.018/min) | ~960ms-2.98s |
| OpenAI | gpt-realtime-2.1-mini | $10.00/M audio tok / $0.60/M text tok | $20.00/M audio tok / $2.40/M text tok | ~500ms |
| xAI | Grok Voice Agent API | $0.05/minute (all-in, audio in+out) | — (single flat rate covers both directions) | <1s time-to-first-audio |

## Open-source S2S is still immature across every option

- **Fun-Audio-Chat-8B**: Most capable open S2S model with actual speech function calling benchmarks, but no LiveKit plugin exists.
- **Nemotron VoiceChat 12B**: Strongest on-paper agentic voice model, but weights are gated behind early access, no LiveKit plugin, and requires two 48 to 80GB GPUs.
- **Qwen3/Qwen3.5-Omni**: Open weights support function calling, but the realtime speech "Talker" only ships through Alibaba's closed hosted DashScope API.
- **Freeze-Omni 7B**: Older 2024-generation model with no tool support, no LiveKit plugin, and a non-standard license/protocol.
- **PersonaPlex-7B**: Only open S2S model with an official LiveKit plugin, self-hostable on a single 24GB GPU, but has no function calling, transcripts, or conversation memory.

## S2S: fast and natural, less control

| ✅ Pros | ❌ Cons |
|---|---|
| Lower latency (~200-400ms) | Voice quality below dedicated TTS; no custom/cloned voices |
| Hears emotion, tone, and pace natively | No transcripts by default; need a separate STT pass |
| Better barge-in and interruption handling | Weak tool use; hard to add guardrails mid-pipeline |
| Simpler architecture; one API, one vendor | Lower STT accuracy on accents and domain jargon |
| No transcription errors corrupting LLM input | Only 3-4 real model options vs. dozens of cascaded combos |
| No context lost between pipeline handoffs | Audio tokens expensive; long calls hit limits fast |
| Consistent voice character end-to-end | Locked to model's built-in voice and behavior |
| Handles filler words and noise without artifacts | Hard to observe or debug; no text to inspect mid-pipeline |

## Cascaded: three swappable, tunable stages

Three *discrete, independently swappable* models chained with **text at every boundary**. You pick each stage independently (accuracy, cost, language, voice).

```
1. Audio Input (user speaks or provides audio input)
2. Speech-to-Text / STT/ASR (audio is transcribed into text)
3. LLM Reasoning (LLM analyzes the text, applies knowledge, generates a response)
4. Text Response (response is structured as text)
5. Text-to-Speech / TTS (text is converted to natural-sounding audio for the user)
        |
   (Continuous Conversation Loop)
```

## Comparing closed-source cascaded models

| Provider | STT | LLM | TTS | Cumulative Cost (input) | Cumulative Cost (output) | Cumulative Latency |
|---|---|---|---|---|---|---|
| Google | gemini-3.1-flash-lite | gemini-2.5-flash | gemini-3.1-flash-tts-preview | $1.80/M tok | $24.00/M tok | ~1.5-3s+ to first audio, thinking-dependent |
| OpenAI | gpt-4o-mini-transcribe | gpt-5.4-mini | gpt-4o-mini-tts | $2.60/M tok | $21.50/M tok | ~1.5-3s (STT + LLM + TTS chained, each adds ~150-400ms network overhead) |
| xAI | Grok Speech-to-Text | Grok 4.3 | Grok Text-to-Speech | $16.25/M tok | $2.50/M tok + $0.20/hr streaming ($0.10/hr batch) | Not officially published; components are individually fast (streaming STT, Grok 4.3, low-latency TTS) but no combined figure exists |

## Cascaded: more control, more latency

| ✅ Pros | ❌ Cons |
|---|---|
| Any voice; custom, cloned, brand voice | Higher latency; 3 sequential handoffs (~500-800ms) |
| Best-in-class STT accuracy (Deepgram, Scribe) | More moving parts; more to break and monitor |
| Full conversation transcripts out of the box | Context can be lost or distorted between STT -> LLM -> TTS |
| Easy tool calls, RAG, and mid-pipeline guardrails | Transcription errors propagate to the LLM |
| Dozens of provider combos supported | Turn-taking feels less natural with batch STT |
| Cheaper at scale with efficient model choices | Three vendor relationships, three bills |
| Swap any component independently | Barge-in handling requires extra engineering |
| Observable, i.e. inspect text at every step | Emotion and tone lost when audio becomes text |

## Open-source now covers every cascade stage

Unlike open-source S2S (still immature, see above), open-source options exist for every cascaded stage:

- **Open-source TTS models**: Fish Audio S2 Pro; Step Audio EditX (Mar 2026); Voxtral TTS (Mistral).
- **Open-source STT/ASR models**: Nemotron 3 ASR (0.6B); Voxtral Mini/Realtime 4B (Mistral); Qwen3-ASR-1.7B.
- **Open-source LLMs**: GLM-5.2 (Z.ai); DeepSeek V4 Pro (Max); Kimi K2.6 / K2.7.

## NVIDIA and Soniox win cheap-and-fast

Plotting price ($/hr conversation) against latency (est. added time-to-first-audio, STT+TTS) across cascaded STT+TTS combinations places providers into quadrants:

| Provider | Price | Latency | Quadrant |
|---|---|---|---|
| NVIDIA* | $0.15/hr | ~300ms | Cheap & fast (sweet spot) |
| Soniox | $0.82/hr | ~350ms | Cheap & fast (sweet spot) |
| Qwen (Alibaba) | $0.67/hr | ~700ms | Cheap, slower |
| xAI | $1.01/hr | ~650ms | Cheap, slower (borderline) |
| OpenAI | $1.26/hr | ~950ms | Slow & pricey (avoid) |
| Google | $2.58/hr | ~850ms | Slow & pricey (avoid) |
| ElevenLabs | $3.09/hr | ~225ms | Fast, premium price |

*NVIDIA figures are detailed further in the Appendix (see `../study-material/lesson.md`'s appendix notes and the deck's Latency vs. Price Matrix).

## S2S wins speed; Cascaded wins flexibility

| Dimension | Native S2S | Cascaded (STT -> LLM -> TTS) |
|---|---|---|
| Latency | ~200-300ms possible; ~30-60% faster vs. streamed cascade; ~85% only vs. naive unstreamed; single forward pass | Naive form ~2s; fully streamed pipeline approaches slowest single stage (~400-600ms) |
| Naturalness | Preserves pitch, pace, and emotion natively; native barge-in and duplex feel | Text intermediary strips paralinguistic nuance; harder to add back after the fact |
| Cost | Provider-dependent and unpredictable; grows with call length as context is re-billed each turn. OpenAI Realtime is multiples pricier than cascaded (~$0.15/min early -> ~$1.20/min by ~7 min), while some S2S models (Gemini Flash Live ~$0.023/min, Amazon Nova Sonic ~$0.02/min) match or undercut a cascade | Predictable per-minute (~$0.01-$0.17/min); flat regardless of conversation length (e.g. Deepgram Nova-3 + Gemini Flash + Cartesia sonic-2 ~$0.03-0.05/min) |
| Debuggability | Opaque; failures silent and hard to attribute; requires a parallel text transcript to inspect | Text logs at every boundary; component-level isolation and audit trails by default |
| Flexibility / Lock-in | Tight coupling to one provider streaming API (OpenAI, Google, Amazon); migration requires a full rewrite | Mix and match STT, LLM, and TTS vendors independently |
| Enterprise adoption (2026) | Emerging; adopted where latency and naturalness dominate | Still dominates production deployments for control, cost, and compliance |

## Cheaper architecture depends on the provider

| Provider | Cascaded / turn | S2S / turn | Cheaper architecture |
|---|---|---|---|
| Google | $0.0164 | $0.0119 | S2S is ~27% cheaper |
| OpenAI | $0.0101 | $0.0246 | Cascaded is ~59% cheaper |
| xAI | $0.0049 | $0.0500 | Cascaded is ~90% cheaper |

There is no universal winner on cost, it flips per provider, which is why the choice has to be made per vendor and per use case rather than assumed from the architecture name alone.

## S2S for speed, Cascaded for control

| Choose S2S when... | Choose Cascaded when... |
|---|---|
| Latency is the top priority (<400ms target) | You need a specific, cloned, or brand voice |
| Emotional context matters; therapy, coaching, companionship | High STT accuracy required; medical, legal, heavy accents |
| Simple conversational agent with no complex tool use | You need full conversation transcripts for compliance or analytics |
| Natural interruption and barge-in is critical | Structured tool calls, RAG, or mid-conversation guardrails are needed |
| Minimal infrastructure; one API, one vendor | Cost sensitivity at scale with high usage volumes |
| The conversation is short and self-contained | Provider flexibility and avoiding lock-in matter |

**Check:** For a compliance-heavy customer-support line that needs full transcripts, a specific brand voice, and mid-call guardrails, which architecture does this table point to, and which single cascaded-pipeline pro from the table above matters most for the "compliance" requirement specifically? Now do the same for a low-latency companionship or coaching app where emotional tone matters more than transcripts, which architecture, and which single S2S pro matters most?
