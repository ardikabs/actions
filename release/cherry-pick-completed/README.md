# Cherry-Pick Completed Labeler Action

A reusable GitHub Action for automatically labeling original Pull Requests with `cherry-pick-completed` once the corresponding hotfix Pull Request is merged into a maintenance branch.

## Features

- 🔎 Analyzes commit history in the merged hotfix PR to find cherry-picked commit SHAs (`(cherry picked from commit <SHA>)`).
- 🗺️ Maps squash SHAs back to the original Pull Requests on the default branch (`main`/`master`).
- 🏷️ Automatically labels those original Pull Requests with `cherry-pick-completed`.

## Usage

### In Your Workflow

Create `.github/workflows/hotfix-completed.yaml` in your repository:

```yaml
name: Hotfix Cherry-Pick Completed Labeler

on:
  pull_request_target:
    types:
      - closed
    branches:
      - 'release/*'
      - 'release/v*'

permissions:
  issues: write
  pull-requests: write

jobs:
  label-completed:
    name: Label Source PRs as Completed
    if: |
      github.event.pull_request.merged == true &&
      contains(github.event.pull_request.labels.*.name, 'cherry-pick')
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6

      - name: Run completed labeler automation
        uses: ardikabs/actions/release/cherry-pick-completed@main
        with:
          github-token: ${{ secrets.PAT }}
          pr-number: ${{ github.event.pull_request.number }}
```
