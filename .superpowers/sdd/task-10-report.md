# Task 10 Report: Agent-Native Quorum v0.7.0

## Scope

- Added the `copilot` init target and its project skill at
  `.github/skills/krystal-quorum-review/SKILL.md`.
- Updated Claude Code, Codex, Hermes, OpenClaw/Claw, and OpenCode packs to
  automatically delegate non-trivial implementation work to the shared
  two-gate workflow.
- Made the shared workflow require a repository-bound plan approval before
  edits, then a verified diff review using the emitted approval receipt.
- Kept skills as policy automation, the GitHub Action as the hard enforcement
  layer, `mock` as installation smoke-only, and all commit/push/deploy decisions
  under human control.
- Updated package data, public documentation, security guidance, CI coverage,
  and the package version to `0.7.0`.

## TDD Evidence

### Red

Before implementation, the required focused command was run:

```text
python -m pytest tests/test_init_command.py tests/test_agent_workflow.py tests/test_public_readiness.py tests/test_version.py -q
```

Result: `10 failed, 23 passed`.

The failures covered the missing Copilot target and skill, old plan-only agent
workflow text, absent Copilot wheel data, the `0.6.7` version expectation, and
the prior single-platform CI matrix.

### Green

After implementation, the same focused command passed:

```text
33 passed
```

`tests/test_agent_workflow.py` verifies the shared two-gate contract, target
auto-invocation language, no Copilot pre-approved tools, and that the built
wheel contains every integration file.

## Full Verification

```text
python -m pytest -q
464 passed, 6 skipped in 121.90s

python -m ruff check .
All checks passed!

python -m build
Successfully built krystal_quorum-0.7.0.tar.gz and krystal_quorum-0.7.0-py3-none-any.whl

python -m twine check dist/*
Checking dist\krystal_quorum-0.7.0-py3-none-any.whl: PASSED
Checking dist\krystal_quorum-0.7.0.tar.gz: PASSED
```

The initial full suite exposed one stale release assertion in
`tests/test_cli.py`: the hosted client header still expected
`krystal-quorum/0.6.7`. It was updated to `krystal-quorum/0.7.0`, its focused
test passed, and the complete suite was rerun successfully.

## Notes

- `tests/test_cli.py` is included in this task's scope because the required
  version bump necessarily changes the asserted hosted client-version header.
- No auto-commit, push, deployment, or hard-enforcement claim was added to the
  agent packs. GitHub Actions remain the standalone enforcement boundary.

## Review-Fix Evidence

### Red

```text
python -m pytest tests/test_init_command.py tests/test_public_readiness.py -q
2 failed, 28 passed, 1 skipped
```

The failures proved that `integrations/github-action/README.md` still pinned
v0.6.7 and that public guidance incorrectly described untracked diff input.

### Green

```text
python -m pytest tests/test_init_command.py tests/test_agent_workflow.py tests/test_public_readiness.py tests/test_version.py -q
35 passed, 1 skipped

python -m ruff check .
All checks passed!

python -m build
Successfully built krystal_quorum-0.7.0.tar.gz and krystal_quorum-0.7.0-py3-none-any.whl
```

The public-doc regression test now requires all three affected documents to
state that local diff review includes eligible untracked files by default and
persists them locally, that external review additionally requires
`--allow-untracked-external`, and that `--no-include-untracked` omits those
files.

`test_init_command_refuses_symlinked_destination_outside_path` creates a real
directory symlink and verifies the CLI refuses a resolved destination outside
`--path`. It skips only when the host rejects symlink creation for access or
privilege reasons. This Windows session reported that permitted-platform skip;
the test remains active on platforms where symlink or junction creation is
available.
