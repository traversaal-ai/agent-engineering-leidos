# Module 5: Exercises

All seven exercises need no coding and no running app — they use the module's own diagrams, worked examples, and comparison tables from `reference/subagents.md` and `reference/agent-evaluation.md`. Unlike Module 4, this module has no running demo app (no `axis/`-equivalent); every exercise is done on paper against the frontmatter, rubrics, and worked examples the lesson already gave you.

## Exercise 1: Cross the single fork in the road

**Goal:** Practice applying "do your workers need to talk to each other?" to real scenarios, not just reciting the rule.

**Steps:**
1. For each of the following five tasks, decide subagent or agent team, and write one sentence justifying it using the fork-in-the-road question: (a) summarize 60 customer support tickets into a weekly themes report, (b) build a feature where a backend schema change must immediately update a frontend form and its tests, (c) review three vendor contracts and flag risky clauses in each, independently, (d) debug a failing test where two competing hypotheses about the root cause need to be explored and compared before either is ruled out, (e) generate onboarding tooltip copy for 12 different UI screens.
2. For the two you marked "agent team," name specifically *what* one specialist would need to tell another mid-task, and what would go wrong if that message had to be relayed through you instead.
3. Using the 9/10 rule, which of the five tasks above is the "10%" case, and which four are squarely in the "90%"?

**Done when:** All five tasks have a subagent/team decision and a one-sentence justification, the two team cases have a concrete mid-task message identified, and you've named the one "10%" case.

## Exercise 2: Write a subagent from scratch — all six fields

**Goal:** Practice the three-step build process (create the file, write the frontmatter, write the system prompt) on a task you didn't see worked out in the lesson.

**Steps:**
1. Pick one task: a subagent that reads customer support transcripts and returns the top 3 recurring complaints with ticket references, or one of your own choosing from your own work.
2. Write the full `name`, `description`, `model`, `tools`, `memory`, and `skills` frontmatter fields for it, following the pattern in `reference/subagents.md`. Justify your `model` choice using the model selection rule, and your `tools` choice using least privilege.
3. Write the system prompt in plain English, under 200 words, specifying the exact output format.
4. Write a `description` for a vaguer version of the same subagent, one that would fail to fire reliably, and explain in one sentence what specifically makes yours better.

**Done when:** You have all six fields filled in with justification for model and tools, a system prompt under 200 words with a locked output format, and a vague counter-example with an explanation of the fix.

## Exercise 3: Design the tool scoping for a three-agent pipeline

**Goal:** Apply least-privilege tooling across a sequential pipeline (Pattern 2), the way `research-agent` / `writer` / `editor` are scoped in `reference/subagents.md`.

**Steps:**
1. Design a three-stage sequential pipeline for a task other than blog writing (e.g. a support-ticket triage pipeline: `intake-agent` -> `router-agent` -> `resolution-drafter`, or one of your own).
2. For each of the three agents, specify its tools and justify why it needs exactly those and no more. At least one agent in your pipeline must be read-only, and you must explain what capability being read-only specifically denies it.
3. Explain, using the "editor never touches the draft" example as a model, why keeping two roles (e.g. drafting and reviewing) on separate agents with separate tool access matters even though a single agent with all the tools could technically do both jobs.

**Done when:** Three agents each have a tools list and a one-sentence justification, one is read-only with a stated denied capability, and you've written the separation-of-roles explanation.

## Exercise 4: Score a subagent output against the 4 rubric dimensions

**Goal:** Practice using rubric-based ground truth the way you'd actually use it: reading a real output and scoring it, not just reciting the four dimension names.

**Steps:**
1. Here is a `research-agent` output for the request "Research the top competitors to our project-management SaaS product":

   > Our main competitors are Asana, Monday.com, and ClickUp. Asana is known for its clean interface and strong task-dependency features. Monday.com has powerful automation and a highly visual board system that many teams love. ClickUp is the most feature-dense of the three, offering docs, goals, and time tracking in one place, and is generally considered the best value option on the market today.

2. Score this output 1-5 on each of the four rubric dimensions (Scope adherence, Source citation, Uncertainty flagging, Format compliance), using the pass/fail description of each dimension from `reference/agent-evaluation.md`. For any dimension that scores 3 or below, quote the exact phrase in the output that caused the low score.
3. Rewrite the embedded rubric checklist (the `☐` list from `reference/agent-evaluation.md`) into one sentence you'd add to this specific agent's system prompt that would have prevented the worst-scoring dimension's failure.

**Done when:** All four dimensions have a 1-5 score with a quoted phrase for anything scoring 3 or below, and you have one system-prompt sentence that targets the worst failure specifically.

## Exercise 5: Diagnose the failure mode

**Goal:** Practice placing a described failure on the common-failure-modes table, the way Module 4's exercises practiced placing a failure on the Five Pillars.

**Steps:**
1. For each of the following five situations, name the failure mode (wrong trigger, wrong process, wrong output format, efficiency issue) and whether it's occurring at the skill, subagent, or agent-team tier: (a) a `code-reviewer` subagent keeps calling WebSearch even though its job is a local diff and it wasn't given that tool, (b) a `/standup` skill fires when the user asks an unrelated question about deployment steps, (c) a three-agent team spends most of its trace re-explaining context to each other because none of them saw the original task in full, (d) a `data-analyst` subagent returns four paragraphs of narrative reasoning instead of the "key stats, anomalies, trends" bullet format its description promised, (e) a `research-agent` opens and re-reads the same three URLs eleven times across one run.
2. For (a) specifically: the subagent isn't supposed to have WebSearch at all. Explain what that tells you about whether this is really a "wrong process" failure or something that should have been caught earlier, at the tools field, before the agent ever ran.
3. Pick the one situation above you think is hardest to catch with an external spot-check alone (i.e. without looking at the trace), and explain why.

**Done when:** All five situations have a failure mode and a tier, you've explained the "caught earlier" point for (a), and you've named and justified the hardest-to-catch case.

## Exercise 6: Run the skill eval loop by hand

**Goal:** Feel the difference between "looks fine" and "5/5 passes," the way the lesson's standup example does, using a skill you design yourself.

**Steps:**
1. Design a skill of your own (e.g. `/exec-summary`, turning a long document into a 3-bullet executive summary) and write its golden output for one representative input.
2. Write 5 input variations: at minimum, one clean/typical input, one vague/ambiguous input, and one edge case (e.g. empty input, or input far outside the skill's intended scope).
3. For each of the 5 variations, write what you predict the skill's actual output would be, and score it against your golden output on the three dimensions from `reference/agent-evaluation.md` (format match, factual accuracy, completeness).
4. If fewer than 5/5 pass, write the specific constraint you'd add to `SKILL.md` to fix the failure, following the "if input is ambiguous, ask ONE clarifying question, never invent" pattern.

**Done when:** You have a golden output, 5 scored variations, and — if you didn't hit 5/5 — a specific fix written as a `SKILL.md` constraint, not a vague "be more careful" note.

## Exercise 7: Map the procurement audit system to the three patterns

**Goal:** Read a real multi-agent system and correctly identify which of the module's building blocks each stage uses, the way you'd need to when reading (or designing) a system of your own.

**Steps:**
1. Using the procurement audit system in `reference/subagents.md`, list every step from Rule Extraction through the final human sign-off, and for each one mark whether it is a **skill**, a **subagent**, or part of an **agent team**.
2. Identify which single pair of steps forms an instance of Pattern 1 (parallel exploration), and explain in one sentence what makes them independent of each other.
3. Identify the one step where the system switches from subagents to an agent team, and explain — using the single fork in the road — exactly what changed at that step that required lateral communication.
4. The system has two human-review gates, not one. Name both, and explain what would go wrong if either gate were removed, in terms of what an agent (not a human) is and isn't positioned to judge.

**Done when:** Every step is labeled skill/subagent/team, the parallel pair is identified with its independence explained, the fork-crossing step is identified with its justification, and both human gates are named with a reason each is necessary.
