# Module 5: Quiz

## Q1. What is the module's core framing for building a good agent system, in two parts?
- Type: recall
- **Answer:** Build a good agent system (skills, subagents, agent teams, guardrails, context — the ingredients) AND build good outputs from that system (evals, benchmarks, test suites, human review, success metrics — the taste test). A well-built system enables the agent, but quality is proven by the outputs; you need both dimensions.
- **Hint:** The module draws this as two stacked rows: "1. Build the system" and "2. Evaluate the output."

## Q2. What is a skill, and why does the module call it "a saved prompt with superpowers"?
- Type: recall
- **Answer:** A skill turns a block of written instructions (e.g. ~200 words) into a single slash command, e.g. `/write-prd SSO for enterprise` instead of retyping the full PRD instructions each time. The skill stores the full instructions; you only type the name and the topic.
- **Hint:** Compare the "Without a Skill" box to the "With a Skill" box in the lesson.

## Q3. What single question decides whether you should build subagents or an agent team?
- Type: recall
- **Answer:** "Do your workers need to talk to each other?" No -> use subagents (each task can be completed independently). Yes -> use agent teams (one team member's decision changes what another needs to do, and waiting for you to relay the message wastes time and budget).
- **Hint:** The module calls this "the single fork in the road."

## Q4. Compare token cost and stability between subagents and agent teams.
- Type: recall
- **Answer:** Subagents: ~1-1.5x token cost vs. a single session, stable since July 2025. Agent teams: 3-4x typical, up to 7x in plan mode, experimental since Feb 2026.
- **Hint:** One of these two is roughly ten times more expensive in the worst case than the other.

## Q5. State the 9/10 rule, and what it implies about which tier to try first when you're unsure.
- Type: explain-why
- **Answer:** Subagents handle roughly 90% of real-world parallelization needs; agent teams cover the 10% where lateral coordination genuinely changes the outcome. If you're unsure which tier a task needs, start with subagents — you can always escalate to an agent team when you actually hit the coordination wall.
- **Hint:** It's phrased as a ratio of "real-world parallelization needs" split two ways.

## Q6. Name the six fields of a subagent's frontmatter, and identify the single most important one.
- Type: recall
- **Answer:** `name` (unique identifier), `description` (the trigger — the most important field), `model` (match task to tier), `tools` (least privilege), `memory` (learns across sessions), `skills` (bakes in domain knowledge). `description` is the most important because Claude reads it to decide when to delegate at all.
- **Hint:** One of the six fields is described as "the trigger" in its own right.

## Q7. Why does `description: Helps with articles.` fail to fire reliably, and what would fix it?
- Type: explain-why
- **Answer:** It's too vague — it doesn't state a condition for when Claude should delegate to this agent. The fix is to write it as a specific condition: e.g. "Draft a full SEO article from an outline. Use when asked to write or draft copy." The rule: "Use when asked to..." — the more specific the condition, the more reliably it fires.
- **Hint:** Claude matches your request against this field to decide whether to delegate. What can it match against a description with no condition in it?

## Q8. A subagent is given WebSearch, WebFetch, and Read. A different subagent in the same pipeline is given only Read and Grep. What principle explains the difference, and what does it buy you?
- Type: application
- **Answer:** Least-privilege tooling: give each subagent only the tools its job needs. The first (a research agent) needs the open web to pull sources; the second (an editor) is read-only so it can flag issues but literally cannot rewrite or break the draft it's reviewing. Fewer tools means a safer, faster, more predictable agent — a tool it doesn't have is a mistake it cannot make.
- **Hint:** One of these two subagents' jobs is to judge output, not produce or fetch it.

## Q9. Why can't you exact-match a subagent's output the way you can a skill's?
- Type: explain-why
- **Answer:** A skill produces the same shape of output every time it's given the same kind of input — deterministic, so you can write one exact golden output. A subagent makes autonomous decisions (what to search, what to include, what to skip), so its output varies run to run — non-deterministic, so exact-match ground truth doesn't apply. You need rubric-based ground truth instead.
- **Hint:** One of the two always follows the same fixed steps; the other decides its own steps each time.

## Q10. Name the four rubric dimensions used to evaluate a subagent, and give the pass condition for "uncertainty flagging" specifically.
- Type: recall
- **Answer:** Scope adherence, Source citation, Uncertainty flagging, Format compliance. For uncertainty flagging: what the agent couldn't find is explicitly stated ("I couldn't verify X" is a passing result); confident silence about a gap is a failing result.
- **Hint:** One dimension is specifically about *not* pretending to know something you don't.

## Q11. What does "embedding the rubric inside the agent" mean, and why doesn't it replace an external spot-check?
- Type: explain-why
- **Answer:** It means writing the four rubric dimensions directly into the subagent's own system prompt as a checklist it runs through before responding (e.g. "☐ Scope: only researched what was asked? ... If any box is unchecked -> fix before sending"), turning the agent into its own first-pass QA layer. It doesn't replace the external spot-check because the agent is grading its own work — you're still auditing a self-reviewing agent, just auditing less of it by hand, not skipping verification entirely.
- **Hint:** The module's own phrase is "you're auditing a self-reviewing agent, not catching every error yourself" — note it doesn't say "not catching *any* errors."

## Q12. Compare the ship thresholds for skills and for subagents, and explain why they're different numbers.
- Type: application
- **Answer:** Skills: 5/5 input variations must pass exact-match. Subagents: 8/10 ground truth examples must pass the rubric on all four dimensions. They differ because a skill's determinism makes a stricter bar achievable and meaningful (any failure out of 5 means a real, reproducible gap), while a subagent's non-determinism means some run-to-run variance is expected and normal, so the bar allows for a small number of edge-case misses without meaning the design is broken.
- **Hint:** One of the two ground-truth types produces the exact same output every time it's correct; the other doesn't.

## Q13. In the confidence scorecard, what's the difference between "8-9/10 pass" and "5-7/10 pass" as decisions?
- Type: recall
- **Answer:** 8-9/10 pass -> "Ship with caution": document the known edge cases and fix them in the next cycle, but ship now. 5-7/10 pass -> "Fix first": find the failure pattern and tighten the system prompt before shipping at all. The dividing line is whether the failures are a small number of documentable edge cases or frequent enough to indicate a real, unresolved pattern.
- **Hint:** Only one of these two scores results in something going out the door this cycle.

## Q14. A subagent keeps returning long paragraphs of reasoning instead of the "3-5 findings as bullet points" format its own description promised. Name the failure mode from the common-failure-modes table, and the rubric dimension its output fails.
- Type: application
- **Answer:** Failure mode: wrong output format (sub-agent returns verbose reasoning instead of compressed result). Rubric dimension: format compliance (output doesn't match the structure defined in the agent's description).
- **Hint:** Two different frameworks in this module both have a category for "the shape of the output is wrong" — name both.
