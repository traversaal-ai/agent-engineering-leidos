# Module 1: Exercises

No coding required for any of these. Exercises 2, 3, and 5 ask you to apply the lesson to your own PRD and your own app once you've generated one with the PRD Builder and built something from it. Do Exercise 1 and 4 any time; do 2, 3, and 5 once you have your own files to point at.

## Exercise 1: LLM or agent?

**Goal:** Practice telling an LLM call apart from an agent, using tools you already use.

**Steps:**
1. List three AI tools you use today (from ChatGPT to Notion AI to a code assistant).
2. For each one, decide: is it acting as a plain LLM in this use case (answers, then stops), or as an agent (plans, uses tools, keeps going toward a goal)? Same tool can be either, depending on what you ask it.
3. For each "agent" case, name the specific tool or action it used that a plain LLM could not have used on its own (web access, file access, code execution, etc.).

**Done when:** You have three examples, each labeled LLM or agent, with a one-line justification naming the actual capability that made the difference.

## Exercise 2: Read your own CLAUDE.md as a harness artifact

**Goal:** See the five harness building blocks (tools, memory/context, planning, execution, rules/instructions) as real content in a real file, not just a diagram.

**Prerequisite:** You've asked Claude Code to write a CLAUDE.md for your own app (assignment 1a), or Claude Code has generated one while building against your PRD.

**Steps:**
1. Open your app's `CLAUDE.md`.
2. Find one sentence or section that maps to each of the five building blocks from Concept 6 of the lesson. Some blocks may show up more than once; some sections may map to more than one block.
3. For the "Rules / Instructions" block specifically, quote the exact guardrail you wrote or asked Claude to write (for example, a line about not adding features you didn't ask for, or about staying local-only).

**Done when:** You have five quotes from your own file, one per building block, plus a one-line note on anything from the five blocks that your CLAUDE.md does *not* cover (hint: does it mention tools, like MCP servers, at all? Why might that be fine for your project specifically?).

## Exercise 3: Trace the loop through your own PRD

**Goal:** Hand-trace the agent loop, using a PRD you actually generated as the input instead of a hypothetical.

**Prerequisite:** You've generated a PRD with the PRD Builder for an idea of your own.

**Steps:**
1. Open your saved `prd.md` and pick one Must-have user story.
2. Write the "goal" as the agent would receive it (a one-line restatement of that story).
3. Name what the harness would need to hand the LLM to work on it (which file(s) would it need to read? Any rules from your CLAUDE.md that constrain the approach?).
4. Name the action(s) the LLM would choose (e.g., "edit `src/lib/types.ts`", "add a new component").
5. Describe what "the result is observed" would look like for this specific story (what would you actually check to know it worked?).

**Done when:** You can point to a concrete file the harness would touch, and a concrete way you'd verify the story is actually done, not just that code was written.

## Exercise 4: Classify a task into the three agent levels

**Goal:** Practice picking the right level of agent sophistication for a task, and defending why a heavier level would be wasted effort.

**Steps:**
1. Pick three tasks: one from work, one personal, one from this course.
2. For each, decide: Level 1 (automation), Level 2 (ReAct), or Level 3 (multi-agent)? Name the deciding factor (is the process fixed and known, does it need dynamic reasoning over an ambiguous request, does it need multiple specialists coordinating?).
3. For the task you rated Level 1, explain specifically why jumping to Level 3 would be wasted complexity, not just "more expensive."

**Done when:** Each task has a level and a one-line justification naming the actual deciding factor, not just a guess.

## Exercise 5: Skill, subagent, or main agent?

**Goal:** Build the instinct for which construct fits which situation, using the skills already installed in this module as a reference point.

**Steps:**
1. Look at the two skills already installed at [`.claude/skills/`](../.claude/skills/): `prd-generator` and `user-story-writer`. Read one `SKILL.md` fully.
2. Explain why this is a skill rather than a subagent: what about the task makes "inject reusable instructions into the current conversation" the right shape, instead of "spin up an isolated worker"?
3. Now imagine a different task, applied to whatever app you build: "review every file in `src/` for unused imports and report back a single list." Would you reach for a skill, a subagent, or neither? Justify using the context-isolation and role distinctions from Concept 11.

**Done when:** You can explain, in your own words and without re-reading the lesson, why the second task is a better fit for a subagent than a skill.
