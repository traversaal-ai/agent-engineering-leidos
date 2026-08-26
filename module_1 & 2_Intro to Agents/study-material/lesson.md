# Module 1: Introduction to AI Agents and the Agent Harness

## Learning objectives

By the end of this module you can:

- Explain the difference between an LLM and an agent, in your own words
- Name the three things that turn an LLM into an agent: tools, context, and orchestration
- Describe why agents exist: what an LLM alone cannot do that an agent can
- Distinguish the three levels of agent sophistication: automation, ReAct, multi-agent
- Explain what an agent harness is, and the five building blocks inside one
- Describe how the harness powers the agent loop, step by step
- Name Claude Code's five constructs (CLAUDE.md, Skills, MCP servers, Subagents, Hooks) and what each one does
- Explain the difference between a skill, a subagent, and the main agent

## Prerequisites

You have used ChatGPT or Claude before. You do not need to have built anything yet.

---

## Concept 1: Is ChatGPT an LLM?

Not exactly. This is the question the whole module hangs off, so it is worth sitting with.

An **LLM** (Large Language Model) is a model trained on massive amounts of text and code to learn language patterns. Give it text, it predicts what comes next, one token at a time. That is genuinely all it does. Feed it "The capital of France is", and it looks at the context, ranks the likely next tokens (`Paris` at 72%, `the` at 8%, `located` at 5%...), picks the top one, appends it, and repeats. It keeps doing this until it decides to stop. That is the entire mechanism. No web browsing, no file access, no memory of yesterday's conversation.

**ChatGPT** is not that. ChatGPT is an AI product **built around** an LLM, with tools, context, memory, and orchestration bolted on. That is why ChatGPT can browse the web, analyze a file you upload, write and run code, and remember what you said three messages ago, even though the LLM at its core still only predicts the next token.

So: `LLM + Tools + Context + Memory + Orchestration = ChatGPT-like AI product.`

**Check:** If the LLM only ever predicts the next token, where does "browse the web" actually happen? (It is not the model doing it. Something else is.)

---

## Concept 2: What is an agent, and why do we need one?

The plain definition: an AI agent is software that interacts with its environment, collects data, and uses that data to perform self-determined steps toward a goal.

Here is the sharper way to hold onto it:

> **LLMs respond. Agents work toward goals.**

An LLM alone can answer, summarize, explain, and generate ideas. It stops the moment it has produced a response. An agent can plan, use tools, make decisions, and act, continuing until the goal is actually met, not until it has said something plausible.

Concretely:

| Ask an LLM | Ask an agent |
|---|---|
| "Write a PRD for a note-taking app." | "Build a note-taking app." |
| **Output:** a written PRD. | **Output:** PRD -> task list -> code files -> tested -> working prototype. |

The LLM gives you a document. The agent gives you the finished thing, because it keeps going: it breaks the goal into steps, uses tools and files, remembers task state as it works, makes decisions along the way, and only stops when there is a real result.

**Why this matters practically:** LLMs are powerful at generating text, but on their own they cannot take action, use tools, remember context across steps, or complete something that takes more than one turn. Agents exist to close exactly that gap.

**Check:** In one sentence, what is the actual behavioral difference between "the model responds" and "the agent works toward a goal"?

---

## Concept 3: Agent = LLM + Tools/Actions + State

Strip away the diagrams and an agent is a small, deliberately simple loop:

```
        Tools/Actions
       ↗            ↘
   LLM                (results feed back in)
       ↖            ↙
         State
```

- **LLM** is the brain. It decides what to do next.
- **Tools/Actions** are what the LLM can reach into the world with: web search, a code interpreter, file access, an API call.
- **State** is what comes back from using a tool, which then becomes part of what the LLM sees next.

That third piece is the one people underrate. Without state feeding back in, the LLM would call a tool once and have no way to know what happened. State is what lets the loop actually loop.

This is also the answer to "how does ChatGPT browse the web if it only predicts tokens?" It doesn't, not directly. The harness runs a web search tool, gets a result, and folds that result back into what the LLM sees. The LLM still only ever predicts the next token. Everything else is scaffolding around it.

**Check:** If you removed "state" from the diagram entirely, what specifically would break?

---

## Concept 4: Three levels of agent sophistication

Not every agent needs the same amount of machinery. There is a real progression here, and knowing where a task sits on it tells you what to build.

**Level 1: Automation agents.** These follow a fixed, predefined workflow. The execution path is known and finite, mapped out in advance, like a flowchart with clear decision points. Best for predictable, repetitive tasks where the process itself is not in question, only its execution. No-code platforms live comfortably at this level.

**Level 2: ReAct agents (Reason + Act).** This is where dynamic planning and reasoning enter. A ReAct agent thinks, acts, and observes in a loop: it forms a thought, takes an action, observes the result, and decides whether it has the answer or needs to loop again. It is not following a fixed script; it is deciding its own next step based on what just happened. This is powered by memory, short-term for the current task, longer-term for things like user preferences across sessions.

**Level 3: Multi-agent systems.** Multiple specialized agents work together, delegating tasks to solve a problem no single agent handles well alone. This is the highest level of autonomy and complexity: collaborative agent teams, each with a narrow role, coordinating toward one outcome. Frameworks built for this (Crew AI, Google's A2A) exist specifically to let agents delegate to and communicate with each other, sometimes across different platforms entirely.

The progression is genuinely cumulative: a Level 2 ReAct agent still benefits from the clear structure Level 1 gives certain sub-tasks, and a Level 3 multi-agent system is usually a team of Level 2 agents, each doing its own reasoning loop, coordinated by an orchestrator.

**Check:** A task has a clear, repeatable process with no ambiguity in how to execute it. Which level does it belong at, and why would jumping straight to Level 3 be wasted effort?

---

## Concept 5: How an agent actually works, end to end

Take a concrete goal: *"Build me a note-taking app."* Here is the path an agent takes, mapped to what changed for each learner's own course project:

1. **Plan.** Understand the goal, break it into steps.
2. **Write a spec.** Turn the goal into a structured document (a PRD): the problem, the users, what's in scope, what's explicitly out of scope.
3. **Create tasks.** Generate and prioritize a concrete task list from the spec.
4. **Use tools.** Code editors, browsers, databases, APIs, whatever the task calls for.
5. **Build.** Implement the app, step by step.
6. **Check the result.** Test, refine, and keep iterating until the goal is actually met, not until something merely runs once.

Notice this is not one LLM call. It is a sequence of decisions, each one informed by what happened in the step before. That sequence, running under a goal until a stopping condition is met, is the agent loop.

**Check:** Which single step in that list is the one an LLM alone, with no harness, genuinely cannot do?

---

## Concept 6: The agent harness

Here is the question the deck raises directly: **who makes all of this work together?**

Who gives the LLM access to tools? Who keeps track of context and state across dozens of steps? Who controls what the agent is allowed to touch? Who actually executes code and edits files? Who passes results back to the LLM in a form it can use?

The answer to all five is the same thing: **the agent harness.**

> The agent harness is the deterministic execution and orchestration layer that surrounds an LLM, letting it operate as an autonomous, stateful agent rather than a simple text predictor.

The one-line version worth memorizing: **the model thinks, the harness does.**

The harness sits in layers around the LLM:

```
Harness
└── Context Management
    └── Agent Loop
        └── Tools · Memory · Permissions
            └── LLM (the brain)
```

Each layer wraps the one inside it. The LLM sits at the center doing the one thing it does: reason and predict. Everything around it is what turns that reasoning into real, completed work.

**Check:** Using the layering diagram, which layer would you touch if you wanted to change what the agent is and isn't allowed to do?

---

## Concept 7: The five building blocks of a harness

Any working harness gives the agent five capabilities. Losing any one of them breaks the agent in a specific, predictable way.

| Block | What it does | What breaks without it |
|---|---|---|
| **Tools** | Connects the agent to external capabilities: web search, code execution, file access, APIs. | The agent can only talk, never act. |
| **Memory / Context** | Stores information about past steps, decisions, and important details so the agent stays consistent. | The agent forgets what it already decided, and contradicts itself. |
| **Planning** | Breaks the goal into smaller steps and builds a path to the goal. | The agent attacks the whole problem at once and gets lost. |
| **Execution** | Actually carries out the plan: runs tools, edits files, checks progress. | Plans exist only on paper, nothing gets done. |
| **Rules / Instructions** | Sets guidelines, constraints, and success criteria the agent must follow. | The agent has no way to know when it's done, or what it's not allowed to do. |

These five are not abstract. They map directly onto what Claude Code actually gives you: CLAUDE.md is rules/instructions, skills are reusable planning and execution recipes, MCP servers are tools, subagents are parallelized execution, and the project's memory files are, literally, memory.

**Check:** Pick one of the five blocks. Name a moment (in this course or elsewhere) where you saw an AI tool fail specifically because that block was missing or weak.

---

## Concept 8: The agent loop, and how the harness powers it

Put concepts 3 through 6 together and you get the actual loop a harness runs:

1. **Agent asks the LLM what to do.** Based on the current goal and current state.
2. **Harness provides what the LLM needs.** Tools, context, memory, rules, environment: everything the LLM would otherwise have no way to see.
3. **LLM chooses an action.** It decides the best next step given what it can see.
4. **Harness executes the action.** Runs the tool, the code, or the operation, safely and within whatever permissions apply.
5. **Result is observed and captured.** Outputs, files, data, logs: whatever came back gets collected.
6. **Results go back to the LLM.** The LLM sees the outcome and updates its plan. Back to step 1.

This repeats until a stop condition is met: the goal is satisfied, a limit is hit, or something requires you to step back in.

Notice the harness appears on *both sides* of the LLM in this loop: it hands the LLM what it needs before the decision (step 2), and it is what turns that decision into a real-world effect afterward (step 4). The LLM only ever occupies step 3. Everything else is the harness.

**Check:** In the loop above, at which step would a human need to approve an action before it proceeds? (This is the seed of what "permissions" and "hooks" are for; you don't need the answer yet, just the instinct.)

---

## Concept 9: Claude Code is an ecosystem, not a chatbot

The deck says this directly, and it's worth taking literally: **the entire idea of using Claude Code is to not use it as a chatbot.** A chatbot answers. Claude Code is a harness: it reads your codebase, writes files, runs commands, and ships things, end to end, from your terminal.

Claude Code's harness has five constructs. Each is a different way of giving the agent something it needs from the building blocks in Concept 6.

| Construct | What it is | Which building block it fills |
|---|---|---|
| **CLAUDE.md** | Project memory. A markdown file, read automatically at the start of every session. | Rules / Instructions, and Memory |
| **Skills** | Reusable instruction packs (a `SKILL.md` plus optional supporting files), auto-invoked when Claude judges them relevant, or triggered directly with `/skill-name`. | Planning and Execution, saved and reused |
| **MCP servers** | Model Context Protocol servers. They connect Claude to external tools and data: GitHub, Slack, Figma, a database. | Tools |
| **Subagents** | Parallel delegates with their own isolated context, their own system prompt, their own tool access, and their own model preference. | Execution, parallelized |
| **Hooks** | Deterministic automations that run on an event, before or after a tool executes. | Rules / Instructions, enforced rather than merely suggested |

**On CLAUDE.md specifically:** without it, you re-explain your stack, your conventions, and your constraints every single session. With it, Claude already knows, and you just describe the task. It lives at your project root, and Claude reads it automatically, every time, before writing any code. You can auto-generate a starting point with `claude /init`, which has Claude read your codebase and draft one for you.

A good CLAUDE.md typically covers five things: a project overview (what it does, tech stack), common commands (how to run, test, build), coding standards, architecture patterns, and constraints or guardrails (what NOT to do). Once you generate your own PRD and start building against it, writing one of these for your own app is assignment 1a, and Exercise 2 in `exercises.md` has you inspect it against these five building blocks.

**On skills specifically:** a skill turns a long, repeated prompt into one slash command. Without a skill, you type out "Build the auth flow. Add login, signup, reset password, protect routes, and show success/error states" every time you need this. With a skill, you type `/build-auth-flow` and Claude does the whole thing, the same way, every time. That is faster, more consistent, repeatable, and it scales. Skills are markdown files. No code is required to create one.

**Check:** Of the five constructs, which one is doing the "Rules / Instructions" job, and which one is doing it by *enforcing* rather than merely *suggesting* them? (Hint: prompts suggest at roughly 95% reliability. One of these five constructs is built to guarantee 100%.)

---

## Concept 10: Hooks, the deterministic control layer

Hooks deserve a concept of their own because they solve a specific problem: prompts are probabilistic. Even a well-written instruction in CLAUDE.md is a *suggestion* the model usually follows. If a failure would cause real, irreversible harm (deleting files, force-pushing to a shared branch), "usually" is not good enough.

A hook is a user-defined shell command that runs automatically before or after a tool executes, no exceptions, every time. There are two flavors:

- **Deterministic hooks:** plain shell scripts. They guarantee something happens (or is blocked) without relying on the LLM's judgment at all. Example: a `PreToolUse` hook that intercepts an `rm -rf` command and blocks it outright, or a `PostToolUse` hook that auto-formats code or runs the test suite after every edit.
- **LLM-based hooks:** hooks that use a model to evaluate something, transform text, or delegate a check, for example asking a model to return `{"ok": true}` if a task is genuinely complete before letting the agent report success.

The rule of thumb from the deck: **if a failure would cause real-world harm, build a hook. Don't rely on a prompt.**

**Check:** Why is "the CLAUDE.md says never force-push" a weaker guarantee than "a hook blocks force-push"?

---

## Concept 11: Skills vs. subagents vs. the main agent

These three get confused constantly because they all involve "Claude doing a focused thing." The distinction is really about two axes: **how isolated the context is**, and **what role the thing plays**.

| | Context window | Role | Scope |
|---|---|---|---|
| **Main agent** | Shared and monolithic; grows with the whole chat history. | System orchestrator, interface manager, the primary planner. | Your interactive terminal session. |
| **Subagent** | 100% isolated. Spawned fresh, discarded on completion. | A focused background specialist: deep documentation search, complex debugging, one narrow job. | A process-specific sandbox. |
| **Skill** | Injected on demand, directly into whatever window is currently active. | Reusable domain knowledge: a recipe, a set of conventions, a repeatable procedure. | Cross-platform. Works wherever it's invoked. |

The simplest way to hold this: a **skill** is knowledge you hand to whichever agent is currently working. A **subagent** is a separate worker with its own clean slate, spun up to do one job and then gone. The **main agent** is you, at the terminal, holding the whole conversation and deciding when to reach for either of the other two.

**Check:** You need Claude to do a deep, multi-file investigation that would otherwise flood your main conversation with search results you don't need to see. Skill, subagent, or neither? Why?

---

## Summary

1. An LLM predicts the next token. An agent is an LLM plus tools, context, memory, and orchestration, working toward a goal instead of just responding.
2. Agents exist because LLMs alone cannot take action, remember across steps, or complete multi-step work.
3. Agents range from fixed-workflow automation, to reasoning ReAct loops, to collaborating multi-agent teams. Pick the level the task actually needs.
4. The agent harness is the deterministic layer around the LLM. The model thinks, the harness does.
5. A harness provides five things: tools, memory/context, planning, execution, and rules/instructions.
6. The agent loop is the harness handing the LLM what it needs, the LLM deciding, and the harness executing and feeding results back, repeated until done.
7. Claude Code's five constructs, CLAUDE.md, Skills, MCP servers, Subagents, and Hooks, are concrete implementations of those five building blocks.
8. Hooks exist because prompts are probabilistic and some failures cannot be allowed to happen even 5% of the time.
9. Skills, subagents, and the main agent differ in context isolation and role, not in "how smart" each one is.

## Where to next

Do `exercises.md` for hands-on practice. Generate a real PRD with the PRD Builder in `prd-generator/` and build a real app from it, that project becomes your own ready-made example for the exercises that need one. Or ask to be quizzed (`quiz.md`).
