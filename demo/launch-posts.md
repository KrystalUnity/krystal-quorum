# Krystal Quorum Launch Posts

Goal: make the free open-source repo the hero. The hosted service is useful, but it belongs at the end as an optional path for people who do not have multiple reviewers configured.

Primary links:

- GitHub: https://github.com/KrystalUnity/krystal-quorum
- PyPI: https://pypi.org/project/krystal-quorum/
- Demo video: https://youtu.be/6kcWH5NKS0Q
- Optional hosted reviewer: https://krystalunity.com/quorum

Core positioning:

> Krystal Quorum is a preflight sanity check for AI coding agents. It reviews the plan before the agent writes code.

Use this framing everywhere:

- Not "AI code review after the damage"
- Not "another coding agent"
- Not primarily SaaS
- Yes "unit tests for AI implementation plans"
- Yes "shift-left review for agentic coding"
- Yes "BYO local models, APIs, or command-line agents"

---

## 1. Hacker News - Show HN

Title option A:

```text
Show HN: Krystal Quorum - a preflight sanity check for AI coding agents
```

Title option B:

```text
Show HN: Krystal Quorum - review AI coding plans before code is written
```

Body:

```text
Hi HN,

I built Krystal Quorum because I kept hitting the same failure mode with AI coding agents: the code was not the first problem. The plan was.

An agent would start from a vague markdown plan, miss acceptance criteria, skip rollback, ignore test gaps, then confidently implement the wrong thing. By the time I noticed, the diff was already large.

Krystal Quorum is a local CLI that reviews markdown implementation plans before code is written.

How it works:

- write a markdown implementation plan
- run it through one or more reviewers: mock, Ollama, OpenAI, OpenAI-compatible APIs, or local command reviewers
- each reviewer returns a strict APPROVE / REVISE / BLOCK verdict
- Quorum reconciles the findings into one human-triage summary
- artifacts are written locally, with exit codes for CI

The reconciliation is deliberately safety-biased rather than majority-rule. A single BLOCK can block the merged result, and a single unresolved blocking issue forces at least REVISE. The goal is not to let models outvote each other; it is to catch risky plans early enough that a human can fix them cheaply.

Quick demo:

pip install krystal-quorum
krystal-quorum demo

That runs a bundled weak plan through the no-key mock reviewer and prints a REVISE verdict. No clone, no API key.

It also has agent import packs:

krystal-quorum init --target claude-code
krystal-quorum init --target codex
krystal-quorum init --target hermes
krystal-quorum init --target claw
krystal-quorum init --target opencode

Repo: https://github.com/KrystalUnity/krystal-quorum
PyPI: https://pypi.org/project/krystal-quorum/
Demo video: https://youtu.be/6kcWH5NKS0Q

There is an optional hosted reviewer if someone does not have multiple local/API reviewers configured, but the open-source CLI is fully usable on its own.

I would love feedback on the reconciliation model, command-reviewer interface, and whether this fits how people are using Claude Code / Codex / Cursor / Aider in real projects.
```

First comment, if the post gets traction:

```text
A bit more context on why I built this:

My own workflow had become "ask one model to write a plan, ask another model to review it, then maybe run a local model or coding agent against it." That worked, but it was manual and inconsistent.

Krystal Quorum turns that pattern into a repeatable gate:

- reviewers can be local Ollama models, API models, or command-line agents
- malformed model output is retried
- collapsed quorums are surfaced for human triage
- low model-family diversity reduces confidence
- artifacts are persisted so the review is auditable

The important bit for me is that it runs before implementation. Once an agent has generated a 3,000-line diff, the review problem is much harder.
```

---

## 2. X / Twitter Launch Thread

Tweet 1:

```text
I kept watching AI coding agents build the wrong thing for a boring reason:

the plan was weak before the code started.

So I built Krystal Quorum: an open-source CLI that reviews implementation plans before your agent writes code.

GitHub: https://github.com/KrystalUnity/krystal-quorum
```

Tweet 2:

```text
The failure mode:

- vague acceptance criteria
- no rollback
- hand-wavy tests
- hidden security/dependency assumptions
- agent confidently builds anyway

Krystal Quorum catches those problems at the plan stage, while they are still cheap to fix.
```

Tweet 3:

```text
How it works:

1. Write a markdown plan
2. Run one or more reviewers
3. Each returns APPROVE / REVISE / BLOCK
4. Quorum reconciles the findings
5. You get local artifacts + CI-friendly exit codes

No hidden model call is used for reconciliation.
```

Tweet 4:

```text
Bring your own reviewers:

- mock reviewer, no keys
- local Ollama models
- OpenAI API
- OpenAI-compatible APIs
- command reviewers that wrap local coding agents/scripts

It is not an agent runtime. It is the gate before the agent runs.
```

Tweet 5:

```text
Try it:

pip install krystal-quorum
krystal-quorum demo

That runs a bundled weak plan and prints REVISE.

Then:

krystal-quorum demo --plan good

prints APPROVE.
```

Tweet 6:

```text
It also installs project-local review packs for common agent workflows:

krystal-quorum init --target claude-code
krystal-quorum init --target codex
krystal-quorum init --target hermes
krystal-quorum init --target claw
krystal-quorum init --target opencode
```

Tweet 7:

```text
This is open source and BYO-first.

The optional hosted reviewer exists for people who do not have multiple local/API reviewers set up, but the repo is the main thing:

https://github.com/KrystalUnity/krystal-quorum

Demo video:
https://youtu.be/6kcWH5NKS0Q
```

Tweet 8:

```text
The design goal:

review the plan before agents edit code.

If you use Claude Code, Codex, Cursor, Aider, OpenCode, or local coding agents, I would love feedback on whether this review gate fits your workflow.
```

---

## 3. Reddit - r/LocalLLaMA

Title:

```text
I built an open-source CLI that uses local LLMs to review AI coding plans before code is written
```

Body:

```text
I built Krystal Quorum, a local CLI for reviewing markdown implementation plans before an AI coding agent starts writing code.

The use case is pretty simple: a large model or coding agent can produce a plan that sounds confident but is missing acceptance criteria, rollback, test coverage, security assumptions, or dependency details. Quorum lets you run that plan through one or more reviewers first.

For local LLM users, the important part is that it is bring-your-own-model.

Example:

krystal-quorum review plan.md --reviewers ollama:qwen2.5:14b --format pretty

Multiple local reviewers:

krystal-quorum review plan.md --reviewers ollama:qwen2.5:14b,ollama:llama3.3:70b --round2 --format pretty

Round 2 asks reviewers to cross-audit each other's findings before the final reconciliation.

Features:

- works with Ollama
- supports OpenAI-compatible local/gateway servers
- supports command reviewers, so you can wrap local scripts or installed coding agents
- deterministic consensus matching, no embedding call for reconciliation
- safety-biased verdicts: APPROVE / REVISE / BLOCK
- reviewer diversity reporting, so two similar model families are not treated as fully independent
- local artifact bundle with reconciled JSON, summary, and per-reviewer output
- CI-friendly exit codes

Zero-key demo:

pip install krystal-quorum
krystal-quorum demo

That uses the bundled mock reviewer against a weak plan and prints REVISE. No clone, no API key, no network.

Repo:
https://github.com/KrystalUnity/krystal-quorum

PyPI:
https://pypi.org/project/krystal-quorum/

Demo video:
https://youtu.be/6kcWH5NKS0Q

There is an optional hosted reviewer for people who do not have multiple reviewers configured, but the CLI is fully usable locally. The local/Ollama path is the main reason I thought this community might care.

I would especially like feedback on the reviewer interface and whether the consensus/diversity model feels useful or overbuilt.
```

---

## 4. Reddit - AI Coding Communities

Targets:

- r/ChatGPTCoding
- r/cursor, if self-promo rules allow it
- r/aider, if self-promo rules allow it
- r/programming only with a more general engineering-practice angle

Title option A:

```text
I got tired of AI agents building from weak plans, so I made a preflight reviewer
```

Title option B:

```text
Open-source CLI: review an AI coding plan before the agent writes code
```

Body:

```text
I built an open-source CLI called Krystal Quorum because I kept running into the same failure with AI coding agents:

the generated code was bad because the plan was bad first.

The agent would start from a markdown plan that sounded reasonable, but it was missing acceptance criteria, rollback, test details, or security/dependency assumptions. Then it would confidently produce a large diff.

Krystal Quorum is a preflight review gate for that stage.

You run:

pip install krystal-quorum
krystal-quorum demo

or against your own plan:

krystal-quorum review plan.md --reviewers mock --format pretty

It supports:

- local Ollama reviewers
- OpenAI / OpenAI-compatible reviewers
- command reviewers for local coding agents or scripts
- agent import packs for Claude Code, Codex, Hermes, Claw/OpenClaw, and OpenCode
- CI exit codes
- persisted artifacts

The output is an APPROVE / REVISE / BLOCK verdict with specific issues and suggestions. The reconciliation is safety-biased rather than majority-rule, because I would rather have a human inspect a risky plan than let two models outvote a blocker.

Repo:
https://github.com/KrystalUnity/krystal-quorum

Demo:
https://youtu.be/6kcWH5NKS0Q

I would be interested in how other people are handling plan review with Claude Code, Codex, Cursor, Aider, or local agents. Are you doing this manually today, or do you let the agent go straight from plan to implementation?
```

---

## 5. Discord / Community Short Posts

Three-line version:

```text
I built an open-source CLI that reviews AI coding plans before the agent writes code:
https://github.com/KrystalUnity/krystal-quorum

It works with mock, Ollama, OpenAI-compatible APIs, and command reviewers for local agents/scripts.

Try: pip install krystal-quorum && krystal-quorum demo
```

Longer version:

```text
Sharing a tool I built because it may fit how people here use coding agents.

Krystal Quorum is an open-source CLI that reviews a markdown implementation plan before Claude Code / Codex / Cursor / Aider-style agents start writing code.

It supports local Ollama models, OpenAI-compatible APIs, and command reviewers that wrap local agents or scripts. It returns APPROVE / REVISE / BLOCK, writes local artifacts, and has CI-friendly exit codes.

Quick try:

pip install krystal-quorum
krystal-quorum demo

Repo:
https://github.com/KrystalUnity/krystal-quorum

Demo video:
https://youtu.be/6kcWH5NKS0Q
```

---

## 6. Reply Bank / FAQ

Use these for HN, Reddit, or X replies.

### Why not just ask Claude to review the plan?

```text
You can, and that manual workflow is basically what this grew out of.

The difference is repeatability: Quorum gives the reviewer a strict schema, preserves artifacts, returns CI exit codes, tracks abstentions/collapsed quorums, and can compare multiple reviewer backends in one run.
```

### Does this run fully local?

```text
Yes. The mock reviewer needs no network, and the real local path is Ollama or command reviewers. Command reviewers can wrap any local script or installed coding agent as long as it returns the strict JSON contract.
```

### Is hosted required?

```text
No. The hosted reviewer is optional. The open-source CLI works with mock, Ollama, OpenAI-compatible endpoints, and command reviewers.
```

### Why safety-biased instead of majority vote?

```text
For this use case, I care more about catching risky plans than averaging opinions. A lone blocker might be wrong, but it is cheap for a human to inspect before implementation. It is much more expensive after an agent has created a large diff.
```

### What about correlated models?

```text
Quorum reports reviewer diversity and reduces system confidence when reviewers come from the same model family. You can also use --require-diversity to fail closed before review if the reviewer set is too correlated.
```

### What about secrets?

```text
Artifacts are written locally and may include the plan text and reviewer outputs, so people should not paste secrets into plans. Command reviewers are explicit opt-in automation; use trusted wrappers and avoid giving third-party commands unnecessary environment access.
```

### Is it doing semantic consensus with another model?

```text
No. The consensus matcher is deterministic and explainable. It uses public matching logic for common review concepts rather than making a hidden model call to decide whether two findings match.
```

### What is the evidence that this helps?

```text
Right now it is a practical workflow tool, not a benchmark paper. The repo includes public benchmark fixtures and artifacts so people can inspect behavior. The claim I am comfortable making is narrower: it creates a repeatable pre-implementation review gate and catches common plan gaps early.
```

---

## 7. X Reply Targets

Before replying, verify each target live in the browser. Do not paste blind replies into old or unrelated threads.

Potential angles:

1. Someone discussing plan-first coding agents:
   - "This is the exact failure mode I built around: the plan needs review before implementation starts."

2. Someone discussing adversarial model review:
   - "I turned that manual pattern into a CLI: model/API/local command reviewers, deterministic reconciliation, local artifacts."

3. Someone discussing local LLM workflows:
   - "The local path is the interesting bit here: Ollama reviewers and command reviewers are first-class."

4. Someone discussing agent safety:
   - "I think the cheap intervention point is before code exists. Once the agent has made a huge diff, review is much harder."

Soft reply template:

```text
This is close to the problem I was trying to solve. I kept doing plan -> reviewer -> implementation manually, so I open-sourced a small CLI that makes the preflight review repeatable:

https://github.com/KrystalUnity/krystal-quorum

It works with local Ollama models or command reviewers too, not just APIs.
```

---

## 8. Launch Sequence

Do not post everywhere at once.

Suggested order:

1. Post Show HN.
2. Watch and reply for 2-3 hours.
3. Post r/LocalLLaMA after HN slows down.
4. Post the X thread with the video.
5. Use Discord/community posts only where the conversation naturally fits.

Timing:

- HN: Tuesday to Thursday, 8-10am Pacific.
- Reddit: US morning.
- X: weekday morning US, or immediately after HN if HN has momentum.
- Discord: slower, conversational, no drive-by link drops.

Pre-flight checklist:

- Confirm README top section still starts with the open-source CLI story.
- Confirm `pip install krystal-quorum` and `krystal-quorum demo` still work.
- Confirm GitHub release and PyPI point to the same version.
- Keep the hosted link present but secondary.
- Prepare to answer comments for at least the first few hours.
