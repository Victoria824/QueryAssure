# Seven-day public launch plan

The MVP is deliberately small: one delightful playground, one trustworthy synthetic
dataset, one framework-independent test contract, and one clean contributor path.

| Day | Ship | Exit criterion |
|---|---|---|
| 1 | Positioning, repo structure, Northstar schema | a new visitor understands the project in 20 seconds |
| 2 | deterministic generator and data-quality contracts | regeneration passes integrity, privacy, and signal checks |
| 3 | reference SQL Agent and inspectable FastAPI trace | zero-key question → grounded, read-only result |
| 4 | YAML eval runner, validators, result equivalence | five golden contracts pass locally and in CI |
| 5 | public chat/eval playground, Docker, social card | one-command demo and shareable experience |
| 6 | mutation runner and first external-agent adapters | schema drift, PII, writes, and hallucinations fail safely |
| 7 | docs polish, launch benchmark, GitHub release | tagged `v0.1.0`, demo video, launch posts, contributor issues |

## Scope discipline

Do not build another data platform. DataAgentKit owns the quality boundary around a data
agent. Warehouses, semantic layers, model providers, and agent frameworks remain adapters.

## Launch checklist

- record a 60–90 second GIF: ask → inspect SQL/context → run the same case in CI
- publish a reproducible benchmark report for deterministic mode and one live model
- open 6–10 labelled issues (`good first issue`, `adapter`, `validator`, `dataset`)
- add GitHub topics: `text-to-sql`, `llm-evaluation`, `agentic-ai`, `sql`, `data-engineering`
- post the failure-first message: “Stop shipping SQL agents without regression tests”
- ask early users for failing traces, not feature wishlists

## Success measures for the first week

- 25 independent installs
- 10 external issues or discussions
- 3 first-time contributors
- 1 adapter contributed outside the core team
- 100 stars as an evidence checkpoint; 1,000 stars remains an outcome, not a release claim
