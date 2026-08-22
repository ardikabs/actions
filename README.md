# Reusable GitHub Actions

This repository is a collection of custom, reusable GitHub Actions developed for automating release workflows, CI/CD, and project maintenance.

## Repository Structure

```text
├── build/
│   └── container-on-aws/        # Reusable action for container deployments on AWS
└── release/
    ├── cherry-pick-hotfix/      # Auto cherry-pick merged PRs to version hotfix branches
    └── cherry-pick-completed/   # Label original source PRs once hotfixes are merged
```

---

## 🍒 release/cherry-pick-hotfix

Automates the hotfix cherry-picking process. When a PR is squash-merged to the main branch with version targeting labels (e.g. `cherry-pick/release-v1.2` or `cherry-pick/release-1.2`), this action cherry-picks the commit into a persistent hotfix branch (`hotfix/v1.2.x`) and opens a Pull Request targeting the maintenance branch (`release/v1.2` or `release/1.2`).

### Key Features
- **Persistent Branches**: Uses a single accumulating branch `hotfix/vM.m.x` per minor release.
- **Auto PR Generation & Updates**: Creates an open PR if not exists. If it exists, it pushes to the branch and automatically updates the PR.
- **Dynamic PR Descriptions**: Compiles a running changelog of all accumulated hotfixes in the PR description, linking back to their original PRs (similar to `release-please`).
- **Graceful Conflict Alerting**: On git cherry-pick conflicts, it aborts the operation, posts a helper comment on the original PR with manual resolution steps, and fails the runner.

---

## 🏷️ release/cherry-pick-completed

A follow-up action designed to run when a hotfix Pull Request is merged into a target maintenance branch. It resolves the original PRs that were cherry-picked and labels them as completed.

### Key Features
- **Git Log Parsing**: Scans all commits of the merged PR for `(cherry picked from commit <SHA>)` headers created by `git cherry-pick -x`.
- **Source Resolution**: Resolves the original PRs associated with those squash commit SHAs on the default branch.
- **Status Labeling**: Adds the `cherry-pick-completed` label to original PRs to signal that they have successfully landed in the release branch.
