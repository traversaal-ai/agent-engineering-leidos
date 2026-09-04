# Reference: Voice AI Frameworks

Deep dive on the module's "Voice AI Frameworks" section. Once you've picked an architecture (S2S or Cascaded, see `voice-ai-architectures.md`), you still need something to actually run it, that's what a voice AI framework is for.

## The voice landscape

The module maps the voice AI ecosystem across two layers:

- **Application Layer**: vertical products built on voice AI, grouped by industry, Call Center, Customer Service/Support, Restaurant/Hospitality, Emergency Response, Finance/Banks, Home Services, Real Estate, Insurance, Logistics/Fleet, Medical, Sales, Recruiting, each with multiple named vendor products.
- **Infrastructure Layer**: the underlying building blocks these products are assembled from, grouped as Voice to Voice, Voice Eval and Testing, Voice Middleware, Automatic Speech Recognition (ASR), Text to Speech (TTS), and Language Models (LLMs/SLMs), again with multiple named vendor products in each category.

The point of laying it out this way: a huge number of application-layer products exist, but nearly all of them are assembled from the same, much smaller set of infrastructure-layer building blocks (ASR, TTS, an LLM, and middleware to glue them together).

## Debunking the voice stack: four layers

```
Layer 4: Reasoning (Optional)
  General agent framework (e.g. LangGraph) for memory, multi-step workflows, and tools.

Layer 3: Orchestration
  Turn-taking, barge-in, VAD, state, and latency budgeting.

Layer 2: Intelligence
  STT -> LLM -> TTS, or a single Speech-to-Speech (S2S) model.

Layer 1: Transport / Media
  Real-time audio streams (WebRTC, WebSocket, SIP), jitter, and echo cancellation.
```

- **Layer 1, Transport/Media**: gets the raw audio moving in real time, reliably, this is where WebRTC, WebSocket, and SIP live (see the key terms in `glossary.md`), along with jitter and echo cancellation.
- **Layer 2, Intelligence**: the actual voice-to-response logic, either the cascaded chain (STT -> LLM -> TTS) or a single S2S model, this is the layer covered in depth in `voice-ai-architectures.md`.
- **Layer 3, Orchestration**: the layer that makes a pipeline feel like a real conversation rather than a walkie-talkie, turn-taking, barge-in, VAD, state, and latency budgeting all live here.
- **Layer 4, Reasoning (optional)**: a general agent framework, for memory, multi-step workflows, and tools, layered on top when the voice agent needs to do more than answer in a single turn.

**The "which framework" question is ultimately about who owns these layers and how freely you can swap each block.** A framework that owns all four layers for you trades flexibility for speed of setup; a framework that only owns orchestration and lets you plug in your own transport, models, and reasoning trades speed of setup for control.

## Two categories of framework

```
Model-Agnostic Orchestrators              Full-Stack Managed Platforms
Build it yourself. Frameworks that        Hosted and configured. Bundled
own timing and integration,               telephony, orchestration, and
allowing you to bring your own            models behind a managed API.
models.
```

### Orchestrators: build and self-host the stack

For teams that need control over latency, cost, model choice, or self-hosted deployment, model-agnostic orchestration frameworks let you assemble your own STT/LLM/TTS stack on your own infrastructure, instead of being locked into one vendor's bundle.

Examples named in this module: **LiveKit Agents**, **Pipecat**.

### Managed platforms: everything behind one API

For teams that want to move fast without managing infrastructure, full-stack managed platforms bundle telephony, orchestration, and models behind a single managed API.

Examples named in this module: **ElevenLabs**, **Vapi**.

### ElevenAgents: no-code templates

For simple use cases, users don't even need to set up an agent development kit (ADK) agent and can instead use fully managed voice agent platforms with browsable templates. Example named in this module: **ElevenAgents**.

## Live demo: Iris, Traversaal.ai's customer support agent

The module includes a live demo of **Iris**, Traversaal.ai's own customer support voice agent, built as a workflow (Start -> Initial Inquiry -> branch on the caller's primary interest -> Provide Information & Next Steps -> branch on whether all relevant information has been provided -> Wrap Up), deployed and demoed live at `https://traversaal-iris.vercel.app/`.

## Managed for speed, open-source for control

| | Vapi | ElevenLabs | LiveKit Agents | Pipecat |
|---|---|---|---|---|
| Type | Managed SaaS | Managed SaaS | Open-source | Open-source |
| Platform cost/min | $0.05 + providers | $0.08 bundled | $0 self-hosted | $0 self-hosted |
| Free tier | 60+ min/mo | 15 min/mo | 1,000 min/mo | WebRTC free |
| STT | 6+ providers (BYOK) | Own Scribe v2 only | 3+ via plugins | 20+ providers |
| LLM | 10+ providers | 10+ (BYO endpoint) | Any | Any (20+) |
| Self-hostable | No | No | Yes | Yes |
| SIP / telephony | Yes | Yes | Yes | Cloud only |
| Website embed | Widget + SDK | Widget (easiest) | WebRTC SDK | DIY only |
| Lock-in | Low-Medium | High | Very Low | Very Low |
| Best for | BYOK + flexibility | Best voice quality | Scale + cost | Custom pipelines |

The framing that ties this table back to the two categories above: Vapi and ElevenLabs (managed) win on time-to-first-working-agent and bundled quality; LiveKit Agents and Pipecat (open-source, self-hosted) win on lock-in and long-run cost, at the price of owning the infrastructure yourself.

**Check:** A team needs SIP/telephony support and a self-hosted deployment with no per-minute platform fee, which two frameworks in the table qualify on both counts, and which of those two would you pick if the deciding factor is "20+ STT providers" specifically? Now, per the Key Takeaways (see `../study-material/lesson.md`), what two properties should you specifically confirm a framework provides before selecting it, regardless of which category it falls into?
