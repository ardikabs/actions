# Cherry-Pick Hotfix Action

A reusable, unified GitHub Action for automatically cherry-picking merged PRs to maintenance branches based on labels and labeling original PRs as completed when the hotfix PR merges.

## Features

- 🍒 **Persistent Accumulating Branches**: Cherry-picks version-labeled commits to a single `hotfix/vM.m.x` branch per target minor version.
- 📋 **Dynamic PR Descriptions**: Automatically generates and updates the Pull Request description (release-please style) listing all accumulated changes with links to original PRs.
- ⚠️ **Graceful Conflict Handling**: Aborts cleanly on merge conflicts, posts manual resolution instructions on the source PR, and alerts maintainers.
- 🏷️ **Lifecycle Tracking**: Resolves and labels original PRs when the hotfix PR merges.

---

## Configuration & Inputs

### Inputs

| Input | Description | Required | Default |
| --- | --- | --- | --- |
| `github-token` | GitHub token with repo/workflow scopes (e.g. `secrets.PAT`) | **Yes** | |
| `pr-number` | The Pull Request number being processed | **Yes** | |
| `mode` | Execution mode: `hotfix` or `completed` | No | `hotfix` |
| `squash-sha` | Squash commit SHA from the merged PR (required for `hotfix` mode) | No | |
| `pr-title` | Title of the merged PR (required for `hotfix` mode) | No | |
| `pr-url` | HTML URL of the merged PR (required for `hotfix` mode) | No | |
| `labels` | JSON array of labels from the PR (required for `hotfix` mode) | No | |
| `dry-run` | If `true`, simulates cherry-picking without committing/pushing | No | `false` |

### Outputs

| Output | Description | Mode |
| --- | --- | --- |
| `created-prs` | JSON array of created/updated hotfix PR URLs | `hotfix` |
| `skipped-versions` | JSON array of skipped version targets due to missing branches | `hotfix` |
| `accumulated-prs` | JSON array of PR numbers accumulated in the hotfix branch | `hotfix` |
| `labeled-prs` | JSON array of original PR numbers that were labeled | `completed` |

---

## Usage Example

Create `.github/workflows/hotfix-automation.yaml` in your repository to configure the complete hotfix lifecycle:

```yaml
name: Hotfix Automation Workflow

on:
  pull_request_target:
    types:
      - closed

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  hotfix-lifecycle:
    name: Manage Hotfixes
    runs-on: ubuntu-latest
    steps:
      # Step 1: Cherry-pick merged PRs to hotfix branch (mode: hotfix)
      - name: Checkout Repository
        if: |
          github.event.pull_request.merged == true &&
          github.event.pull_request.base.ref == 'main'
        uses: actions/checkout@v6
        with:
          fetch-depth: 0
          token: ${{ secrets.PAT }}

      - name: Run Cherry-Pick Accumulator
        if: |
          github.event.pull_request.merged == true &&
          github.event.pull_request.base.ref == 'main'
        uses: ardikabs/actions/release/cherry-pick-hotfix@main
        with:
          github-token: ${{ secrets.PAT }}
          mode: 'hotfix'
          squash-sha: ${{ github.event.pull_request.merge_commit_sha }}
          pr-number: ${{ github.event.pull_request.number }}
          pr-title: ${{ github.event.pull_request.title }}
          pr-url: ${{ github.event.pull_request.html_url }}
          labels: ${{ toJson(github.event.pull_request.labels.*.name) }}

      # Step 2: Resolve and label source PRs as completed when the hotfix PR merges
      - name: Label Source PRs as Completed
        if: |
          github.event.pull_request.merged == true &&
          startsWith(github.event.pull_request.base.ref, 'release/')
        uses: ardikabs/actions/release/cherry-pick-hotfix@main
        with:
          github-token: ${{ secrets.PAT }}
          mode: 'completed'
          pr-number: ${{ github.event.pull_request.number }}
```
