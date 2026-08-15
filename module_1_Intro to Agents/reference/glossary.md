# Glossary (Source of Truth)

Master list of terms for this module. `study-material/key-concepts.md` repeats the subset most relevant to the lesson itself; this file is the fuller reference.

- **LLM (Large Language Model)**: An AI model trained on massive amounts of text and code to learn language patterns and generate text by repeatedly predicting the most likely next token given the context so far.
- **Token**: A unit of text a model processes: a whole word, part of a word, a punctuation mark, or any other small unit of text.
- **Prompt**: The input text given to a model to produce a response.
- **AI agent**: Software that interacts with its environment, collects data, and uses that data to take self-determined steps toward a goal, rather than simply responding once and stopping.
- **Agent formula**: Agent = LLM + Tools/Actions + State. The LLM decides, tools let it act, and state (the results of those actions) feeds back in so the process can continue.
- **State**: The output captured from a tool or action, which becomes part of what the LLM sees on its next decision.
- **Tool / Action**: An external capability an agent can invoke: web search, a code interpreter, file access, an API call, a database query.
- **Automation agent**: An agent following a fixed, predefined workflow with a known, finite execution path. Level 1 of agent sophistication.
- **ReAct agent**: "Reasoning and Acting." An agent that interleaves chain-of-thought reasoning with tool use in a loop: think, act, observe, repeat. Level 2 of agent sophistication.
- **Multi-agent system**: Multiple specialized agents collaborating and delegating tasks to solve a problem no single agent handles well alone. Level 3 of agent sophistication.
- **Agent harness**: The deterministic execution and orchestration layer surrounding an LLM that lets it operate as an autonomous, stateful agent rather than a simple text predictor.
- **Context management**: The discipline of deciding what an agent's working memory includes, excludes, and updates, and why each choice matters, across a long-running task.
- **Agent loop**: The repeating cycle: the harness supplies context/tools/memory, the LLM chooses an action, the harness executes it, the result is observed, and the outcome feeds back to the LLM. Continues until a stop condition is met.
- **Building blocks of a harness**: Tools, Memory/Context, Planning, Execution, and Rules/Instructions: the five capabilities any working harness must provide.
- **CLAUDE.md**: A project memory and instructions file, loaded automatically by Claude Code at the start of every session.
- **Skill**: A reusable instruction pack (a `SKILL.md` file plus optional supporting files) that Claude auto-invokes by description, or that a user triggers directly with `/skill-name`.
- **MCP (Model Context Protocol)**: The standard protocol connecting an AI agent to external tools and data sources (GitHub, Slack, Figma, databases). Flow: agent → MCP server → tool → result → agent.
- **Subagent**: A delegate with its own fully isolated context, system prompt, tool access, and model preference, spawned for one focused task and discarded afterward.
- **Hook**: A deterministic automation, typically a shell command, that runs on an event (before or after a tool executes) with guaranteed, not merely probable, enforcement.
- **Deterministic hook**: A hook implemented as a plain script, guaranteeing an outcome without relying on the LLM's judgment.
- **LLM-based hook**: A hook that uses a model to evaluate a condition, transform text, or perform a delegated check.
- **`.claude/` folder**: The per-project Claude Code configuration directory: `commands/`, `agents/`, `skills/`, `settings.json`, `hooks.json`.
- **PRD (Product Requirements Document)**: A structured specification (problem, users, goals, non-goals, user stories, acceptance criteria) that turns a rough idea into something an agent can build against.
