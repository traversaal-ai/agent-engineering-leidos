# Reference: Evaluating Skills and Subagents

Deep dive behind the module's evaluation sections. Module 4 (see `../../module_4_Agentic RAG & Evaluation/reference/rag-evaluation.md`) taught you how to evaluate a *RAG system's* output. This module asks the same question one layer up: given a skill or a subagent you just built, how do you know it actually works, before you ship it?

## Before you evaluate an agent, define what "right" looks like

**Ground truth = the expected behavior you measure the agent against.** There isn't one kind of ground truth — which kind you need depends on what kind of output you're judging.

| Type | Best for | Example | Pass condition |
|---|---|---|---|
| **Exact Match** | Structured outputs, one correct answer or format | Extract contact info, return JSON with name, email, company | Output matches exactly (the right fields and format) |
| **Rubric-Based** | Wording can vary | Summarize a contract, score on accuracy, completeness, citation quality, clarity | Output meets the minimum score on each criterion (e.g. ≥ 4/5) |
| **Comparative** | Quality is subjective | Run two prompts or two models, choose which output you'd actually use | Human reviewers prefer the output (e.g. ≥ 70% win rate) |

Skills and subagents map onto the first two rows almost exactly, and the reason why is the core idea of this whole reference:

## Skills are deterministic — exact-match is the easiest thing to evaluate rigorously

A skill produces the same shape of output every time it's given the same kind of input. That determinism is what makes exact-match ground truth possible: you can write out, word for word, what a correct output looks like, and then hold every real output up against it.

### Build your eval dataset like a test case

For every real input, define the expected behavior and what counts as a pass.

| Input | Expected Behavior (Golden Output) | Pass Criteria |
|---|---|---|
| "Fixed login bug and reviewed 2 PRs." | Yesterday: fixed login bug, reviewed 2 PRs. Today: ... Blockers: ... | Has Yesterday/Today/Blockers. No invented work. Clear and concise. |
| "Not sure what I did lol." | Ask one clarifying question, e.g. "Can you share what you worked on yesterday or what are you currently focusing on?" | Asks a clarifying question. Does not fabricate a standup. Supportive and professional tone. |
| *[empty input]* | Ask the user to provide an update, e.g. "Please share what you worked on yesterday, what you plan to do today, and any blockers." | Requests more information. No hallucination. Graceful handling. |

Notice the shape: every row has an **input**, an **expected behavior** (the golden output), and **pass criteria** (how you'll judge it's correct, or good enough). The middle row is doing the real work here — a vague or empty input is where a skill's failure mode actually lives, and the pass criteria for it aren't "matches this exact string," they're "did the right *kind* of thing happen" (asked instead of invented).

### The 4-step skill eval loop

1. **Write the golden output before you build.** Write the exact expected output for a representative input.
2. **Run 5 input variations.** Test the skill on 5 real input variations, not just the one you designed around.
3. **Use Claude-as-judge anchored to your ground truth.** Compare actual output to the golden output; score 1-5 on each dimension (format match, factual accuracy, completeness).
4. **Fix in `SKILL.md`, rerun until 5/5 pass.**

```
The Claude Code Skill Evaluation Loop

1. DEFINE SUCCESS  ->  2. WRITE GOLDEN OUTPUT  ->  3. TEST VARIATIONS  ->  4. COMPARE TO GROUND TRUTH  ->  5. DECIDE
Write the rule.        Input: "Fix login bug,     Run the skill on 5      Claude output <-> golden      5/5  ->  PASS
What does "right"        reviewed 2 PRs,             real input variations   output. Exact match or       <5/5 ->  IMPROVE
look like?                meeting at 3pm"            (icon, mobile,          rubric score against the     SKILL.md and retest
                          -> golden output             question mark,         golden output.
                          (write the exact             pencil, clock icon)
                          expected output)

5/5 PASS -> SHIP IT              ANYTHING ELSE -> IMPROVE SKILL
The skill is reliable            Fix the constraint or examples.
and consistent. Ship             Then run 5 variations again.
with confidence.

A Skill is ready when it produces the right output, every time, for real inputs.
```

### The copy-paste EVAL prompt

```
## Ground truth
Input: "Fixed login bug, reviewed 2 PRs, design meeting at 3pm"

Golden output:
Yesterday: Fixed login bug, reviewed 2 PRs.
Today: Design meeting at 3pm.
Blockers: None.

## Actual output
[paste the Skill's output here]

## Eval task
Compare actual output to golden output.
Score 1-5 on each dimension:
- Format match (structure, sections, length)
- Factual accuracy (nothing invented)
- Completeness (nothing omitted)
Flag any gap. Suggest one fix.
```

### Reading the result

- **Pass:** format matches, no invented facts, nothing omitted from the input.
- **Fail:** vague input -> invented content. Fix by adding a constraint to `SKILL.md`: *"If input is ambiguous, ask ONE clarifying question. Never invent."*
- **Ship threshold: 5/5 input variations pass the ground-truth check. Not 4. Not "mostly."** If one variation fails, the skill isn't ready — fix the constraint first.

The pattern behind every fix: the failure is almost always "vague input -> invented content," because an LLM asked to produce a fixed shape of output, given an input that doesn't clearly support that shape, will fill the gap rather than say so. The fix is never "reword the prompt to be nicer" — it's a specific behavioral constraint the model can follow.

## Subagents are non-deterministic — you need a rubric, not exact-match

A skill produces the same format every time — you can differentiate it against a golden output. A subagent makes autonomous decisions: what to search, what to include, what to skip. The output varies. You can't exact-match it.

**The solution: rubric-based ground truth.** Instead of defining the exact output, you define the acceptance criteria every output must satisfy — and you put that rubric *inside the agent*, so it evaluates itself before responding.

### The 4 rubric dimensions for any subagent

| Dimension | What it checks |
|---|---|
| **Scope adherence** | Did it do only what it was asked? No more, no less. |
| **Source citation** | Every factual claim has a verifiable source URL or file reference. |
| **Uncertainty flagging** | What it couldn't find is explicitly stated. "I couldn't verify X" is a passing result. Confident silence is not. |
| **Format compliance** | Output matches the structure defined in the agent's description (e.g. "3-5 findings as bullet points"). |

These four generalize across almost any subagent, because they're really asking one question from four angles: *did this worker stay honest about what it did and didn't do, within the boundaries it was given?*

### Embed the rubric inside the agent

```yaml
---
name: research-agent
description: TRIGGER when asked to research competitors, trends, or background context.
model: claude-opus-4-6
tools: WebSearch, WebFetch
---

## Job
Return 3-5 findings with source URLs.
Flag anything you couldn't verify.

## Ground truth rubric
Before responding, check every dimension:
☐ Scope: only researched what was asked?
☐ Citations: every claim has a source URL?
☐ Uncertainty: stated what I couldn't find?
☐ Format: 3-5 bullets, source on each line?

If any box is unchecked -> fix before sending.
```

**The embedded rubric turns the agent into its own QA layer.** You still spot-check — but you're auditing a self-reviewing agent, not catching every error yourself.

### External spot-check prompt (run after any agent output)

```
Review the research-agent output above.
For each finding:
1. Is there a source URL? (no URL = fail)
2. Does the claim match the source?
3. Is anything outside the original scope?
4. What was flagged as uncertain?
Score each dimension 1-5. Flag any failure.
```

```
1. WHY SUBAGENTS ARE HARDER TO EVAL
   User request: "Research competitors in AI coding tools"
   -> Agent -> Search / Decide / Synthesize (many valid paths, outputs vary)
   ✗ Many valid paths. Outputs vary.
   ✓ Use a rubric to evaluate behavior, not one "right" answer.

2. THE RUBRIC LENS                              3. EMBEDDED QA LOOP
   Agent Output -> 1. Scope Adherence  ✓         Subagent generates draft output
                -> 2. Citations Present ✓                    |
                -> 3. Uncertainty Flagged ✓                   v
                -> 4. Format Compliance ✓          Self-check with rubric (4 dimensions)
                                                          PASS  ->  Return final response
                                                          FAIL  ->  Fix and revise -> (loop back)
```

## The eval loop is the same shape either way — only the ground truth differs

| | Skills — Exact Match | Sub-Agents — Rubric Match |
|---|---|---|
| **Ground truth type** | Exact output — you write the golden answer word for word | Rubric — 4 criteria every output must satisfy (scope / citations / uncertainty / format) |
| **Primary failure mode** | Hallucination on ambiguous or missing input — the skill fills in what it doesn't know | Confident output with no sources — the agent asserts things it can't verify |
| **Eval method** | Compare actual output to golden output. Score: format match + no invented facts + nothing omitted | Score against rubric dimensions. Embedded self-review in agent + external spot-check after each run |
| **Fix location** | `SKILL.md` system prompt — add the constraint that closes the failure | Agent job description — tighten the rubric constraint that failed, embedded so the agent self-checks |
| **Ship threshold** | 5/5 input variations pass exact-match check | 8/10 ground truth examples pass rubric on all 4 dimensions |

Both failure modes are the same shape wearing different clothes: an agent — skill or subagent — asked to produce something, given input that doesn't fully support it, fills the gap with invented confidence rather than admitting the gap exists. The fix is always a constraint that forces the agent to name the gap instead of papering over it.

## Evals are a loop, not a checklist

### The 5-step eval loop

1. **Write 10 ground truth examples.**
2. **Run the eval against each example.**
3. **Score and find the failure pattern.**
4. **Fix in the system prompt, not the output.** Patching one bad output by hand fixes nothing the next time the same failure shape appears — the fix has to live in the instructions the agent follows every time.
5. **Don't ship below 8/10.**

### The confidence scorecard

| Score | Decision | Action |
|---|---|---|
| 10/10 examples pass | Ship it | Add to eval suite, monitor in prod |
| 8-9/10 pass | Ship with caution | Document known edge cases, fix in next cycle |
| 5-7/10 pass | Fix first | Find the failure pattern, tighten system prompt |
| Under 5/10 pass | Rethink the design | The scope or prompt structure is broken, not just the constraints |

**The eval suite is a living document.** Every time you change the system prompt, rerun all 10 examples. Every time you add a feature, add 3 new ground truth examples. The suite grows with the product.

> Kevin Weil, CPO of OpenAI: "Writing evals is going to become a core skill for product managers." This is the workflow he means — not code, not CI. Ground truth + rubric + loop.

## Common failure modes for evals

| Failure mode | Skills | Sub-agents | Agent teams |
|---|---|---|---|
| **Wrong trigger** | Skill fires when it shouldn't, or doesn't fire when it should | Sub-agent used for tasks beyond its scope | Lead misassigns tasks, or teammates overstep roles |
| **Wrong process** | Agent skips steps, misuses tools specified in the skill | Sub-agent uses too many tools or violates its limited toolset | Teammates skip dependencies, race each other, or duplicate work |
| **Wrong output format** | Output doesn't match skill's expected schema or style | Sub-agent returns verbose reasoning instead of compressed result | Team output is inconsistent, fragmented, or not aligned with task list |
| **Efficiency issue** | Skill causes redundant tool calls or long detours | Sub-agent loops or over-explores, wasting tokens | Team spends too much time negotiating or re-communicating |

Notice the pattern across the row for each failure mode: it's the same underlying problem (trigger, process, format, efficiency), but it gets *worse* as coordination increases — an inefficient skill wastes tool calls; an inefficient subagent wastes tokens looping; an inefficient team wastes something harder to get back, time spent negotiating instead of working. This is the same cost curve from the module's "single fork in the road" (subagents ~1-1.5x token cost; agent teams 3-4x typical, 7x in plan mode) showing up as a failure-severity curve, not just a spend curve.

**Check:** A subagent you built keeps returning long paragraphs of reasoning instead of the "3-5 findings as bullet points" its description promises. Using the failure-mode table above, name the failure mode, and using the rubric dimensions, name the specific dimension its output would fail on.
