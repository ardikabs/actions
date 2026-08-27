CONFLICT_COMMENT = """\
⚠️ **Cherry-pick Conflict Alert** ⚠️

We tried to automatically cherry-pick the squash commit `{{ short_sha }}`
into the hotfix branch `{{ hotfix_branch }}` targeting `{{ release_branch }}`.

However, git reported conflicts during the cherry-pick.
Please checkout the hotfix branch `{{ hotfix_branch }}{{ pr_info }}` and resolve the conflicts manually.

```bash
git fetch origin
git checkout {{ hotfix_branch }}
git cherry-pick -x {{ squash_sha }}
# Resolve conflicts, add files, and commit...
git push origin {{ hotfix_branch }}
```
"""

HOTFIX_PR_BODY = """\
## 🍒 Hotfix for `{{ release_branch }}`

This Pull Request accumulates cherry-picked hotfixes targeting the maintenance branch.

### 📋 Accumulated Changes

{% for hotfix in hotfixes %}
{{ hotfix }}
{% endfor %}

---

> This PR was automatically created and is updated by the hotfix automation workflow.
> Please review and merge using **Rebase and Merge** or **Merge Commit** to preserve the cherry-pick commit history for changelog and tracking tooling.
"""

HOTFIX_PR_BODY_CONFLICT = """\
## ⚠️ MERGE CONFLICTS DETECTED - MANUAL RESOLUTION REQUIRED

Commit `{{ short_sha }}` could not be automatically cherry-picked into `{{ hotfix_branch }}`.

---

{{ body }}
"""

COMPLETED_COMMENT = """\
This PR has been included in hotfix release {{ version }} 🎉
(See [Hotfix PR #{{ pr_number }}]({{ hotfix_pr_url }}))
"""

SUMMARY_HOTFIX = """\
## 🍒 Hotfix Cherry-Pick Summary

Processed hotfix cherry-pick from PR #{{ config.pr_number }}

**Squash commit**: `{{ config.squash_sha[:7] }}`

{% if results.created_prs %}
### ✅ Created/Updated Hotfix PRs

{% for pr in results.created_prs %}
- v{{ pr.version }}: [PR #{{ pr.number }}]({{ pr.url }})
{% endfor %}
{% endif %}
{% if results.accumulated_prs %}
### 📋 Accumulated PRs in Hotfix Branch

{% for pr_num in results.accumulated_prs %}
- #{{ pr_num }}
{% endfor %}
{% endif %}
{% if results.skipped_versions %}
### ⚠️ Skipped Versions

{% for skip in results.skipped_versions %}
- v{{ skip.version }}: {{ skip.reason }}
{% endfor %}
{% endif %}
"""

SUMMARY_COMPLETED = """\
## 🏷️ Cherry-Pick Completed Labeler Summary

Processed hotfix PR #{{ config.pr_number }}

{% if labeled_prs %}
### ✅ Labeled Pull Requests

{% for pr_num in labeled_prs %}
- PR #{{ pr_num }} labeled with `cherry-pick-completed`
{% endfor %}
{% else %}
### ℹ️ No original Pull Requests were labeled.
{% endif %}
"""