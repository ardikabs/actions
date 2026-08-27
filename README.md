# Reusable GitHub Actions

This repository is a collection of custom, reusable GitHub Actions developed for automating release workflows, CI/CD, and project maintenance.

## Actions Directory

### 📦 Container Deployments on AWS

- **Path**: [`build/container-on-aws/`](./build/container-on-aws)
- **Description**: Reusable action for container deployments on AWS.

### 🍒 Cherry-Pick Hotfix & Completion Lifecycle

- **Path**: [`release/cherry-pick-hotfix/`](./release/cherry-pick-hotfix)
- **Description**: A unified workflow action that cherry-picks target-labeled commits into persistent version branches and opens PRs (`mode: hotfix`), and resolves/labels original source PRs as completed once the hotfix is merged (`mode: completed`).
- **Details**: Please see the [action README](./release/cherry-pick-hotfix/README.md) for detailed inputs, outputs, and workflow configurations.
