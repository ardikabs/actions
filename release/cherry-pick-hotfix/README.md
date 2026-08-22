# Cherry-Pick Hotfix Action

A reusable GitHub Action for automatically cherry-picking merged PRs to maintenance branches based on labels.

## Features

- 🍒 Automatic cherry-pick from squashed commits on `main`
- 🏷️ Label-based version targeting (`cherry-pick/release-v1.6`)
- 🔀 Rebase-friendly PR creation for changelog tooling
- ⚠️ Conflict detection and PR annotation
- 📦 Reusable across multiple repositories

## Usage

### In Your Workflow (example for hibernator-like repos)

Create `.github/workflows/hotfix.yaml` in your repository:

```yaml
name: Hotfix Cherry-Pick

on:
  pull_request_target:
    types:
      - closed
    branches:
      - main

permissions:
  contents: write
  pull-requests: write

jobs:
  cherry-pick:
    name: Cherry-pick to Maintenance Branches
    if: |
      github.event.pull_request.merged == true &&
      github.event.pull_request.merged_by != null
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          fetch-depth: 0
          token: ${{ secrets.PAT }}

      - name: Run cherry-pick automation
        uses: ardikabs/actions/release/cherry-pick-hotfix@main
        with:
          github-token: ${{ secrets.PAT }}
          squash-sha: ${{ github.event.pull_request.merge_commit_sha }}
          pr-number: ${{ github.event.pull_request.number }}
          pr-title: ${{ github.event.pull_request.title }}
          pr-url: ${{ github.event.pull_request.html_url }}
          labels: ${{ toJson(github.event.pull_request.labels.*.name) }}
```
