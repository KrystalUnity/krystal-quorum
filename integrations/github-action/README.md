# GitHub Action

This wrapper runs the same local Krystal Quorum CLI inside GitHub Actions.

```yaml
name: Review plan

on:
  pull_request:
    paths:
      - "docs/plans/**.md"

jobs:
  quorum:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./integrations/github-action
        with:
          plan: docs/plans/example.md
          reviewers: mock
```

Use provider API keys through normal GitHub Actions secrets when configuring non-mock reviewers.
