# Benchmark Fixtures

This folder is a small public evidence harness for Krystal Quorum.

It does not prove that quorum review always beats a single strong reviewer. It gives maintainers and users a repeatable way to compare:

- one reviewer
- several diverse reviewers
- round 1 only
- round 1 plus round 2 cross-audit

## Run

From the repository root:

```bash
python benchmarks/run_quorum_benchmark.py \
  --reviewers mock \
  --out benchmark-results.jsonl
```

For real evidence, replace `mock` with your reviewer set:

```bash
python benchmarks/run_quorum_benchmark.py \
  --reviewers openai:gpt-4.1,ollama:qwen2.5:14b \
  --round2 \
  --require-diversity \
  --out benchmark-results.jsonl
```

Each JSONL row records the fixture, expected topics, command exit code, parsed CLI payload, and raw output. Keep API keys in your environment; do not commit private benchmark outputs.

## Fixtures

`expected-findings.json` lists the intended defect topics for each fixture. Use it to compare whether different reviewer sets find the expected issues and whether quorum review surfaces more complete findings than a single reviewer.
