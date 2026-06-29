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
          round2: "false"
```

Use provider API keys through normal GitHub Actions secrets when configuring non-mock reviewers.

For real reviewers:

```yaml
- uses: ./integrations/github-action
  with:
    plan: docs/plans/change.md
    reviewers: openai:gpt-4.1,openai:o4-mini
    round2: "true"
    require-diversity: "true"
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

For hosted Quorum packs, create a `KU_TOKEN` repository secret and pin the
package spec to a published release:

```yaml
- uses: KrystalUnity/krystal-quorum/integrations/github-action@v0.6.5
  with:
    plan: docs/plans/change.md
    reviewers: hosted:quick
    package-spec: "krystal-quorum==0.6.5"
  env:
    KU_TOKEN: ${{ secrets.KU_TOKEN }}
```

Set `package-spec` to a pinned release when this action is copied into another repository.
