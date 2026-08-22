# Cherry-Pick Completed Versioned Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modify `CherryPickCompletedAutomation` to add version-specific `cherry-pick-completed/vM.m` labels and add generic `cherry-pick-completed` only when all versions are complete.

**Architecture:** Extend the existing `CherryPickCompletedAutomation` class with three new helper methods. The core logic remains in the `run()` method which orchestrates the flow.

**Tech Stack:** Python, PyGithub

---

### Task 1: Add helper methods to CherryPickCompletedAutomation

**Files:**
- Modify: `release/cherry-pick-hotfix/src/main.py:399-482` (add new methods after `__init__`)

- [ ] **Step 1: Add parse_version_labels method**

Add this method to the `CherryPickCompletedAutomation` class (around line 404):

```python
def parse_version_labels(self, pr) -> List[VersionTarget]:
    """Extract version targets from cherry-pick/release-vM.m labels on a PR."""
    version_pattern = re.compile(r'^cherry-pick/release-v?(\d+)\.(\d+)$')
    versions = {}

    for label in pr.labels:
        match = version_pattern.match(label.name)
        if match:
            major, minor = int(match.group(1)), int(match.group(2))
            key = f"{major}.{minor}"
            versions[key] = VersionTarget(major=major, minor=minor)

    return list(versions.values())
```

- [ ] **Step 2: Add add_completed_labels method**

Add this method after `parse_version_labels`:

```python
def add_completed_labels(self, pr, target_versions: List[VersionTarget]) -> List[str]:
    """Add cherry-pick-completed/vM.m labels for each target version."""
    added_labels = []
    for target in target_versions:
        label_name = f"cherry-pick-completed/v{target.version_string}"
        try:
            pr.add_to_labels(label_name)
            added_labels.append(label_name)
            print(f"Added label '{label_name}' to PR #{pr.number}")
        except Exception as e:
            print(f"Failed to add label '{label_name}' to PR #{pr.number}: {e}")
    return added_labels
```

- [ ] **Step 3: Add check_and_add_generic_label method**

Add this method after `add_completed_labels`:

```python
def check_and_add_generic_label(self, pr) -> bool:
    """Check if all version labels have completed labels, add generic if so."""
    version_pattern = re.compile(r'^cherry-pick/release-v?(\d+)\.(\d+)$')
    completed_pattern = re.compile(r'^cherry-pick-completed/v(\d+)\.(\d+)$')

    source_versions = set()
    completed_versions = set()

    for label in pr.labels:
        version_match = version_pattern.match(label.name)
        if version_match:
            source_versions.add(f"{version_match.group(1)}.{version_match.group(2)}")

        completed_match = completed_pattern.match(label.name)
        if completed_match:
            completed_versions.add(f"{completed_match.group(1)}.{completed_match.group(2)}")

    if source_versions and source_versions == completed_versions:
        try:
            pr.add_to_labels('cherry-pick-completed')
            print(f"Added generic label 'cherry-pick-completed' to PR #{pr.number} (all versions complete)")
            return True
        except Exception as e:
            print(f"Failed to add generic label to PR #{pr.number}: {e}")
    return False
```

- [ ] **Step 4: Run a quick syntax check**

Run: `python -m py_compile release/cherry-pick-hotfix/src/main.py`
Expected: No output (success)

- [ ] **Step 5: Commit**

```bash
git add release/cherry-pick-hotfix/src/main.py
git commit -m "feat: add helper methods for versioned completed labels"
```

---

### Task 2: Modify run() method to use new helper methods

**Files:**
- Modify: `release/cherry-pick-hotfix/src/main.py:405-482` (the `run` method)

- [ ] **Step 1: Find the labeling logic section in run() method**

The current code (around lines 454-459) does:
```python
print(f"Found source PR #{pr.number}. Adding label 'cherry-pick-completed'...")
try:
    pr.add_to_labels('cherry-pick-completed')
    labeled_prs.append(pr.number)
```

Replace this block with:

```python
print(f"Found source PR #{pr.number}. Processing labels...")

# Get target versions from the source PR's labels
target_versions = self.parse_version_labels(pr)
if target_versions:
    print(f"Source PR has version labels: {[v.version_string for v in target_versions]}")

    # Add version-specific completed labels
    self.add_completed_labels(pr, target_versions)

    # Check if all versions are complete, add generic label if so
    self.check_and_add_generic_label(pr)
else:
    # Fallback: no version labels, just add generic (backward compat)
    print(f"No version labels found on source PR. Adding generic 'cherry-pick-completed'...")
    try:
        pr.add_to_labels('cherry-pick-completed')
    except Exception as label_err:
        print(f"Failed to add label to PR #{pr.number}: {label_err}")

labeled_prs.append(pr.number)
```

- [ ] **Step 2: Also update the fallback search API block**

The fallback code (around lines 470-475) has similar logic. Find and replace:
```python
print(f"Found source PR #{pr.number} via search. Adding label...")
try:
    pr.add_to_labels('cherry-pick-completed')
    labeled_prs.append(pr.number)
```

With:
```python
print(f"Found source PR #{pr.number} via search. Processing labels...")

# Get target versions from the source PR's labels
target_versions = self.parse_version_labels(pr)
if target_versions:
    print(f"Source PR has version labels: {[v.version_string for v in target_versions]}")

    # Add version-specific completed labels
    self.add_completed_labels(pr, target_versions)

    # Check if all versions are complete, add generic label if so
    self.check_and_add_generic_label(pr)
else:
    # Fallback: no version labels, just add generic (backward compat)
    print(f"No version labels found on source PR. Adding generic 'cherry-pick-completed'...")
    try:
        pr.add_to_labels('cherry-pick-completed')
    except Exception as label_err:
        print(f"Failed to add label to PR #{pr.number}: {label_err}")

labeled_prs.append(pr.number)
```

- [ ] **Step 3: Run syntax check**

Run: `python -m py_compile release/cherry-pick-hotfix/src/main.py`
Expected: No output (success)

- [ ] **Step 4: Commit**

```bash
git add release/cherry-pick-hotfix/src/main.py
git commit -m "feat: add version-specific completed label logic in run method"
```

---

### Task 3: Update summary output in main()

**Files:**
- Modify: `release/cherry-pick-hotfix/src/main.py:501-516`

- [ ] **Step 1: Update the summary output**

The current summary (line 512) says:
```python
summary_lines.append(f"- PR #{pr_num} labeled with `cherry-pick-completed`")
```

This is still accurate since we add the generic label when all complete. No change needed to the summary - it will still show which PRs were labeled.

- [ ] **Step 2: Commit**

```bash
git add release/cherry-pick-hotfix/src/main.py
git commit -m "docs: clarify summary output for completed labels"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full syntax check**

Run: `python -m py_compile release/cherry-pick-hotfix/src/main.py`
Expected: No output (success)

- [ ] **Step 2: Check if there are any tests**

Run: `find release/cherry-pick-hotfix -name "test*.py" -o -name "*_test.py" 2>/dev/null`
Expected: Likely no tests exist yet

- [ ] **Step 3: Review the final diff**

Run: `git diff HEAD~3 --stat`
Expected: Shows modified files

---

## Summary

This plan adds version-specific labels (`cherry-pick-completed/vM.m`) to source PRs when a hotfix is successfully merged, and adds the generic `cherry-pick-completed` label only when ALL versions have been completed (count matches). The implementation is backward compatible - PRs without version labels will still get the generic label.