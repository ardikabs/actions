# Cherry-Pick Completed Versioned Labels Design

## Problem

When a source PR has multiple `cherry-pick/release-vM.m` labels and a hotfix PR is successfully merged to one of those maintenance branches, the current `completed` mode adds only the generic `cherry-pick-completed` label. This is misleading because:
- Not all versions have been backported (only the one in the merged hotfix PR)
- The label doesn't reflect which specific version was successfully cherry-picked

## Solution

Modify `CherryPickCompletedAutomation` in `release/cherry-pick-hotfix/src/main.py` to:

### 1. Add Version-Specific Completed Labels
For each source PR found from the cherry-pick commit:
- Parse its existing `cherry-pick/release-vM.m` labels to get target versions
- Add `cherry-pick-completed/vM.m` label for each version

### 2. Add Generic Label When All Versions Complete
After adding version-specific labels:
- Count `cherry-pick/release-vM.m` labels on the source PR
- Count `cherry-pick-completed/vM.m` labels on the source PR
- If counts are equal (all versions have been backported), add generic `cherry-pick-completed` label

## Implementation Changes

### `CherryPickCompletedAutomation` class

1. **New method: `parse_version_labels(pr)`** - Extract version targets from PR labels using the same regex pattern from `CherryPickAutomation.parse_version_labels()`

2. **New method: `add_completed_labels(pr, target_versions)`** - Add `cherry-pick-completed/vM.m` for each version in target_versions

3. **New method: `check_and_add_generic_label(pr)`** - Check if all version labels have corresponding completed labels, add generic `cherry-pick-completed` if so

4. **Modify `run()` method**:
   - After finding source PR, call `parse_version_labels()` to get target versions
   - Call `add_completed_labels()` to add version-specific labels
   - Call `check_and_add_generic_label()` to add generic label if all complete

## Example Flow

Source PR #100 has labels: `cherry-pick/release-v1.2`, `cherry-pick/release-v1.3`

Hotfix PR #200 (targeting v1.2) is merged → `completed` mode runs:

1. Find source PR #100 from cherry-pick commit
2. Parse labels: versions = [v1.2, v1.3]
3. Add `cherry-pick-completed/v1.2` label
4. Check: 2 source labels, 1 completed label → don't add generic
5. Source PR now has: `cherry-pick/release-v1.2`, `cherry-pick/release-v1.3`, `cherry-pick-completed/v1.2`

Later, hotfix PR #201 (targeting v1.3) is merged → `completed` mode runs:

1. Find source PR #100 from cherry-pick commit
2. Parse labels: versions = [v1.2, v1.3]
3. Add `cherry-pick-completed/v1.3` label
4. Check: 2 source labels, 2 completed labels → add `cherry-pick-completed`
5. Source PR now has: all version labels + completed labels + `cherry-pick-completed`

## Backward Compatibility

- Existing behavior for single-version labels remains the same (adds both version-specific and generic when complete)
- Generic label only added when ALL versions are complete