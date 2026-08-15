# Module 1: Quiz

## Q1. Is ChatGPT an LLM?
- Type: recall
- **Answer:** Not exactly. ChatGPT is an AI product built around an LLM, enhanced with tools, context, memory, and orchestration. The LLM itself only predicts the next token; everything else (web browsing, file analysis, remembering earlier messages) comes from what's built around it.
- **Hint:** What does the LLM alone actually do, versus what ChatGPT as a whole can do?

## Q2. Complete the formula: Agent = LLM + ___ + ___.
- Type: recall
- **Answer:** Tools/Actions and State. The LLM decides, tools let it act on the world, and state is what comes back from those actions, fed back in so the loop can continue.
- **Hint:** One piece lets the agent reach outward. The other lets it remember what happened.

## Q3. In one sentence, what is the real difference between an LLM and an agent?
- Type: explain-why
- **Answer:** An LLM responds and stops; an agent works toward a goal, planning, using tools, remembering state, and continuing until the goal is actually met.
- **Hint:** "LLMs respond. Agents ___."

## Q4. A task has a clear, repeatable process with no ambiguity in how to execute it, and the same steps every time. Which agent level fits, and why would Level 3 be wasted here?
- Type: application
- **Answer:** Level 1, automation. The process is fixed and known, so a deterministic workflow handles it completely. Level 3 (multi-agent coordination) adds complexity and points of failure for a problem that doesn't have any ambiguity or need for multiple specialists to begin with.
- **Hint:** Ask what problem each level is actually solving. Does this task have that problem?

## Q5. In one sentence, what does the agent harness do that the LLM itself does not?
- Type: explain-why
- **Answer:** The model thinks (reasons and decides); the harness does; it manages context, runs the agent loop, executes tools, tracks memory, and enforces permissions.
- **Hint:** "The model thinks. The harness ___."

## Q6. Name the five building blocks of an agent harness.
- Type: recall
- **Answer:** Tools, Memory/Context, Planning, Execution, Rules/Instructions.
- **Hint:** One connects to the outside world. One remembers. One breaks the goal down. One carries the plan out. One sets the guardrails.

## Q7. Put the agent loop in order: (a) harness executes the action, (b) LLM chooses an action, (c) result is observed and captured, (d) harness provides context/tools/memory, (e) results go back to the LLM.
- Type: recall
- **Answer:** d → b → a → c → e (then repeat from the top: the LLM asks what to do next given the new state).
- **Hint:** The harness has to hand the LLM what it needs *before* the LLM can decide anything.

## Q8. Match each Claude Code construct to what it provides: CLAUDE.md, Skills, MCP servers, Subagents, Hooks.
- Type: recall
- **Answer:** CLAUDE.md = project memory and rules, read every session. Skills = reusable instruction packs, auto-invoked or triggered with `/name`. MCP servers = tool connections to external systems. Subagents = isolated parallel delegates for focused work. Hooks = deterministic automations on events, enforced not just suggested.
- **Hint:** Which one is markdown you write once and never repeat? Which one is a shell script that runs no matter what?

## Q9. Why would you build a hook instead of just writing "never force-push" in CLAUDE.md?
- Type: explain-why
- **Answer:** CLAUDE.md is a prompt-level instruction: the model usually follows it, but "usually" is probabilistic, roughly 95% reliable. A hook is a deterministic shell command that blocks the action every time, with no dependence on the model's judgment. If a failure would cause real, irreversible harm, you want the 100% guarantee, not the 95% one.
- **Hint:** What does "deterministic" mean, and why does that matter more for some failures than others?

## Q10. What is the fundamental difference between a skill and a subagent?
- Type: application
- **Answer:** A skill is reusable knowledge injected on demand into whatever context window is currently active; it shares that context. A subagent has its own 100% isolated context, spun up fresh for one job and discarded when done. Use a skill to hand the current agent a recipe; use a subagent when you want the work to happen somewhere separate from your main conversation.
- **Hint:** Which one shares your current conversation, and which one gets its own blank slate?
