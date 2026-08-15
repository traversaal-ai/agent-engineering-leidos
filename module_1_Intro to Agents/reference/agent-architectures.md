# Reference: The Three Levels of Agent Sophistication

Deep dive on Concept 4 of the lesson. Not every task needs the same amount of agentic machinery. This is the progression, from least to most autonomous.

## Level 1: Automation agents

Follows a fixed, predefined workflow. The execution path is known, finite, and mapped out in advance, like a flowchart with clear decision points at every branch.

- **Best for:** predictable, repetitive tasks where the process itself is settled and does not need to be figured out on the fly.
- **Key technology:** no-code platforms are a natural fit here, since the workflow can be built visually and does not need dynamic reasoning to execute.
- **Signal you're at the right level:** the task can be drawn as a flowchart with a manageable number of branches, and that flowchart doesn't change from run to run.

## Level 2: ReAct agents (Reason + Act)

Uses the ReAct framework: **Reasoning and Acting**, combining chain-of-thought reasoning with external tool use.

- **How it works:** the agent thinks (forms a thought about what to do next), acts (takes an action, usually a tool call), and observes (looks at what came back). It then decides: is the answer found, or does it loop again? This repeats until the goal is met or the agent gives up.
- **Powered by memory:** short-term memory holds the current task's state (what has been tried, what came back). Longer-term memory can hold things like user preferences or past decisions that persist across sessions.
- **Best for:** requests where the right sequence of steps is not known in advance, and the agent needs to figure it out based on what it learns along the way.
- **Signal you're at the right level:** you cannot pre-draw the flowchart, because the path genuinely depends on intermediate results.

## Level 3: Multi-agent systems

Multiple specialized agents work together, delegating tasks to solve a problem too broad or too varied for one agent to handle well alone.

- **How it works:** collaborative agent teams, each agent with a narrow, well-defined role, coordinate toward one shared outcome. This is the highest level of both autonomy and complexity.
- **Key frameworks:** Crew AI uses micro-agents for specific roles within one team. Google's A2A (Agent-to-Agent) protocol connects agents running on entirely different platforms, so coordination isn't limited to agents built with the same framework.
- **Best for:** work that naturally decomposes into distinct specialities, for example "find candidates, schedule interviews, then start background checks," where each piece benefits from a differently-tuned agent rather than one generalist trying to do all three.
- **Signal you're at the right level:** the work has genuinely separate specialities, and a single agent juggling all of them would be worse at each one than a team of focused agents would be at its own piece.

## Applying this in practice

The three levels are not a ladder you climb for prestige. Going to a higher level than a task needs adds complexity, more points of failure, and slower iteration for no real benefit. The discipline worth building is: identify which level a task actually needs, and resist the pull to reach for multi-agent orchestration when a fixed workflow would do the job just as well, more reliably, and far more cheaply.

A caution that applies at every level, but bites hardest as you climb: reliability compounds. If each step in a workflow is 95% accurate, a 30-step process very rarely completes end to end without a single wrong step somewhere in the chain. Going from a working prototype to something reliable at scale is usually the hardest part of building at Level 2 or Level 3, and it is a different problem from getting the first version working at all.
