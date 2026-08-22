#!/usr/bin/env python3
import os
import sys
import json
import re
import subprocess
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import github
from git import Repo
from pydantic import BaseModel


class CherryPickConfig(BaseModel):
    github_token: str
    pr_number: int
    mode: str = "hotfix"
    squash_sha: Optional[str] = None
    pr_title: Optional[str] = None
    pr_url: Optional[str] = None
    labels: Optional[List[str]] = None
    dry_run: bool = False


@dataclass
class VersionTarget:
    major: int
    minor: int

    @property
    def release_branch(self) -> str:
        return f"release/v{self.major}.{self.minor}"

    @property
    def version_string(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass
class HotfixResult:
    version: VersionTarget
    success: bool
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    error: Optional[str] = None
    has_conflicts: bool = False


class CherryPickAutomation:
    def __init__(self, config: CherryPickConfig):
        self.config = config
        self.repo = Repo(os.getcwd())
        self.gh = github.Github(config.github_token)
        self.gh_repo = self.gh.get_repo(os.environ.get('GITHUB_REPOSITORY', ''))

    def parse_version_labels(self) -> List[VersionTarget]:
        version_pattern = re.compile(r'^cherry-pick/release-v?(\d+)\.(\d+)$')
        versions = {}

        for label in self.config.labels:
            match = version_pattern.match(label)
            if match:
                major, minor = int(match.group(1)), int(match.group(2))
                key = f"{major}.{minor}"
                versions[key] = VersionTarget(major=major, minor=minor)

        return list(versions.values())

    def remote_branch_exists(self, branch_name: str) -> bool:
        try:
            self.gh_repo.get_branch(branch_name)
            return True
        except github.GithubException as e:
            if e.status == 404:
                return False
            raise

    def find_release_branch(self, target: VersionTarget) -> Optional[str]:
        options = [
            f"release/v{target.version_string}",
            f"release/{target.version_string}"
        ]
        for branch in options:
            if self.remote_branch_exists(branch):
                return branch
        return None

    def get_open_pull_request(self, hotfix_branch: str, release_branch: str) -> Optional[github.PullRequest.PullRequest]:
        try:
            head_query = f"{self.gh_repo.owner.login}:{hotfix_branch}"
            pulls = self.gh_repo.get_pulls(state='open', head=head_query, base=release_branch)
            if pulls.totalCount > 0:
                return pulls[0]
        except Exception as e:
            print(f"Error checking open pull requests: {e}")
        return None

    def post_conflict_comment(self, target: VersionTarget, hotfix_branch: str):
        try:
            short_sha = self.config.squash_sha[:7]
            found_release_branch = self.find_release_branch(target) or f"release/v{target.version_string}"

            pr = self.get_open_pull_request(hotfix_branch, found_release_branch)
            pr_info = f" or PR #{pr.number}" if pr else ""

            comment_body = (
                f"⚠️ **Cherry-pick Conflict Alert** ⚠️\n\n"
                f"We tried to automatically cherry-pick the squash commit `{short_sha}` "
                f"into the hotfix branch `{hotfix_branch}` targeting `{found_release_branch}`.\n\n"
                f"However, git reported conflicts during the cherry-pick. "
                f"Please checkout the hotfix branch `{hotfix_branch}`{pr_info} and resolve the conflicts manually.\n\n"
                f"```bash\n"
                f"git fetch origin\n"
                f"git checkout {hotfix_branch}\n"
                f"git cherry-pick -x {self.config.squash_sha}\n"
                f"# Resolve conflicts, add files, and commit...\n"
                f"git push origin {hotfix_branch}\n"
                f"```"
            )

            issue = self.gh_repo.get_issue(self.config.pr_number)
            issue.create_comment(comment_body)
            print(f"Posted conflict comment to PR #{self.config.pr_number}")
        except Exception as e:
            print(f"Failed to post conflict comment: {e}")

    def cherry_pick_commit(self, sha: str) -> Tuple[bool, bool]:
        try:
            self.repo.git.config('user.name', 'ardikabs')
            self.repo.git.config('user.email', 'me@ardikabs.com')
            self.repo.git.cherry_pick(sha, '-x')
            return (True, False)
        except subprocess.CalledProcessError as e:
            if 'conflict' in str(e).lower():
                try:
                    self.repo.git.cherry_pick('--abort')
                except:
                    pass
                return (False, True)
            return (False, False)

    def push_branch(self, branch_name: str) -> bool:
        try:
            self.repo.git.push('origin', branch_name)
            return True
        except Exception as e:
            print(f"Failed to push branch {branch_name}: {e}")
            return False

    def get_accumulated_prs(self, release_branch: str, hotfix_branch: str) -> List[int]:
        """Return a list of PR numbers accumulated in the hotfix branch relative to the release branch."""
        try:
            commits = list(self.repo.iter_commits(f"origin/{release_branch}..{hotfix_branch}"))
        except Exception as e:
            print(f"Error iterating commits to collect accumulated PRs: {e}")
            return []

        pr_numbers = []
        for commit in commits:
            pr_match = re.search(r'\(#(\d+)\)$', commit.summary)
            if pr_match:
                pr_numbers.append(int(pr_match.group(1)))
        return list(dict.fromkeys(reversed(pr_numbers)))  # dedup, preserve order (oldest first)

    def generate_pr_body(self, target: VersionTarget, release_branch: str, hotfix_branch: str) -> str:
        try:
            commits = list(self.repo.iter_commits(f"origin/{release_branch}..{hotfix_branch}"))
        except Exception as e:
            print(f"Error iterating commits to generate PR body: {e}")
            commits = []

        hotfixes = []
        for commit in commits:
            summary = commit.summary
            pr_match = re.search(r'\(#(\d+)\)$', summary)
            if pr_match:
                pr_num = pr_match.group(1)
                clean_summary = summary[:pr_match.start()].strip()
                pr_link = f"[#{pr_num}](https://github.com/{self.gh_repo.full_name}/pull/{pr_num})"
                hotfixes.append(f"- {clean_summary} ({pr_link})")
            else:
                body_match = re.search(r'\(cherry picked from commit ([0-9a-f]{40})\)', commit.message, re.IGNORECASE)
                if body_match:
                    orig_sha = body_match.group(1)
                    sha_link = f"[`{orig_sha[:7]}`](https://github.com/{self.gh_repo.full_name}/commit/{orig_sha})"
                    hotfixes.append(f"- {summary} ({sha_link})")
                else:
                    hotfixes.append(f"- {summary}")

        if not hotfixes:
            hotfixes.append("- No cherry-picked hotfixes detected yet.")

        hotfixes.reverse()

        body_lines = [
            f"## 🍒 Hotfix for `{release_branch}`",
            "",
            "This Pull Request accumulates cherry-picked hotfixes targeting the maintenance branch.",
            "",
            "### 📋 Accumulated Changes",
            ""
        ]
        body_lines.extend(hotfixes)
        body_lines.extend([
            "",
            "---",
            "",
            "> This PR was automatically created and is updated by the hotfix automation workflow."
            "> Please review and merge using **Rebase and Merge** or **Merge Commit** to preserve the cherry-pick commit history for changelog and tracking tooling."
        ])

        return "\n".join(body_lines)

    def create_pull_request(self, target: VersionTarget, hotfix_branch: str, release_branch: str, body: str) -> Tuple[str, int]:
        title = f"chore(release): hotfix v{target.version_string}"
        pr = self.gh_repo.create_pull(
            title=title,
            body=body,
            base=release_branch,
            head=hotfix_branch
        )
        try:
            pr.add_to_labels('hotfix', 'cherry-pick')
        except Exception as e:
            print(f"Failed to add labels to PR: {e}")
        return (pr.html_url, pr.number)

    def process_version(self, target: VersionTarget) -> HotfixResult:
        short_sha = self.config.squash_sha[:7]

        release_branch = self.find_release_branch(target)
        if not release_branch:
            return HotfixResult(
                version=target,
                success=False,
                error=f"Maintenance branch release/v{target.version_string} or release/{target.version_string} does not exist"
            )

        if self.config.dry_run:
            print(f"[DRY RUN] Would cherry-pick {short_sha} to {release_branch}")
            return HotfixResult(version=target, success=True)

        hotfix_branch = f"hotfix/v{target.version_string}.x"

        try:
            # Configure git user if not set
            try:
                self.repo.git.config('user.name')
            except Exception:
                self.repo.git.config('user.name', 'github-actions[bot]')
            try:
                self.repo.git.config('user.email')
            except Exception:
                self.repo.git.config('user.email', 'github-actions[bot]@users.noreply.github.com')

            # Ensure branch exists on remote first, based on release branch (not main/HEAD)
            if not self.remote_branch_exists(hotfix_branch):
                print(f"Hotfix branch {hotfix_branch} does not exist on remote. Creating from {release_branch}...")
                self.repo.git.fetch('origin', release_branch)
                self.repo.git.checkout('-B', hotfix_branch, f"origin/{release_branch}")
                if not self.push_branch(hotfix_branch):
                    return HotfixResult(
                        version=target,
                        success=False,
                        error=f"Failed to create and push hotfix branch {hotfix_branch} to remote"
                    )

            # Fetch and checkout the remote hotfix branch
            self.repo.git.fetch('origin', hotfix_branch)
            self.repo.git.checkout('-B', hotfix_branch, f"origin/{hotfix_branch}")

            # Run cherry-pick
            success, has_conflicts = self.cherry_pick_commit(self.config.squash_sha)

            if success:
                if self.push_branch(hotfix_branch):
                    pr_body = self.generate_pr_body(target, release_branch, hotfix_branch)
                    pr = self.get_open_pull_request(hotfix_branch, release_branch)
                    if pr:
                        pr_url = pr.html_url
                        pr_number = pr.number
                        print(f"Push successful. PR already exists: {pr_url}. Updating PR body...")
                        try:
                            pr.edit(body=pr_body)
                        except Exception as edit_err:
                            print(f"Failed to update PR body: {edit_err}")
                    else:
                        pr_url, pr_number = self.create_pull_request(target, hotfix_branch, release_branch, pr_body)
                        print(f"Push successful. Created new PR: {pr_url}")

                    self.repo.git.checkout('main')
                    return HotfixResult(
                        version=target,
                        success=True,
                        pr_url=pr_url,
                        pr_number=pr_number
                    )
                else:
                    self.repo.git.checkout('main')
                    return HotfixResult(
                        version=target,
                        success=False,
                        error="Failed to push cherry-picked commit to remote"
                    )
            else:
                self.repo.git.checkout('main')
                if has_conflicts:
                    self.post_conflict_comment(target, hotfix_branch)
                    return HotfixResult(
                        version=target,
                        success=False,
                        error="Cherry-pick failed due to merge conflicts",
                        has_conflicts=True
                    )
                return HotfixResult(
                    version=target,
                    success=False,
                    error="Cherry-pick failed"
                )

        except Exception as e:
            try:
                self.repo.git.checkout('main')
            except:
                pass

            return HotfixResult(
                version=target,
                success=False,
                error=str(e)
            )

    def run(self) -> Dict:
        targets = self.parse_version_labels()

        if not targets:
            print("No hotfix labels found")
            return {
                'created_prs': [],
                'skipped_versions': [],
                'accumulated_prs': [],
                'errors': [],
                'has_labels': False
            }

        results = []
        accumulated_prs_all = []
        for target in targets:
            print(f"\n{'='*60}")
            print(f"Processing version: v{target.version_string}")
            rel_br = self.find_release_branch(target) or f"release/v{target.version_string} (not found)"
            print(f"Release branch: {rel_br}")
            print(f"{'='*60}")

            result = self.process_version(target)
            results.append(result)

            # Collect accumulated PRs from the hotfix branch after processing
            if result.success:
                hotfix_branch = f"hotfix/v{target.version_string}.x"
                found_rel_br = self.find_release_branch(target)
                if found_rel_br:
                    accumulated = self.get_accumulated_prs(found_rel_br, hotfix_branch)
                    accumulated_prs_all.extend(accumulated)

        created_prs = [
            {'version': r.version.version_string, 'url': r.pr_url, 'number': r.pr_number}
            for r in results if r.success and r.pr_url
        ]

        skipped_versions = [
            {'version': r.version.version_string, 'reason': r.error}
            for r in results if not r.success
        ]

        # Deduplicate accumulated PRs while preserving order
        seen = set()
        dedup_accumulated = [p for p in accumulated_prs_all if not (p in seen or seen.add(p))]

        return {
            'created_prs': created_prs,
            'skipped_versions': skipped_versions,
            'accumulated_prs': dedup_accumulated,
            'has_labels': True,
            'results': [
                {
                    'version': r.version.version_string,
                    'success': r.success,
                    'pr_url': r.pr_url,
                    'has_conflicts': r.has_conflicts,
                    'error': r.error
                }
                for r in results
            ]
        }


class CherryPickCompletedAutomation:
    def __init__(self, config: CherryPickConfig):
        self.config = config
        self.gh = github.Github(config.github_token)
        self.gh_repo = self.gh.get_repo(os.environ.get('GITHUB_REPOSITORY', ''))

    def run(self) -> List[int]:
        print(f"Fetching hotfix Pull Request #{self.config.pr_number}...")
        try:
            hotfix_pr = self.gh_repo.get_pull(self.config.pr_number)
        except Exception as e:
            print(f"Failed to fetch hotfix PR #{self.config.pr_number}: {e}")
            sys.exit(1)

        # Retrieve commits from the PR
        commits = hotfix_pr.get_commits()
        print(f"Analyzing {commits.totalCount} commit(s) in hotfix PR #{self.config.pr_number}...")

        # Find cherry-picked SHAs
        # Format of -x helper: (cherry picked from commit <SHA>)
        cherry_picked_pattern = re.compile(r'\(cherry picked from commit ([0-9a-f]{40})\)', re.IGNORECASE)
        original_shas = []

        for commit in commits:
            message = commit.commit.message
            for line in message.splitlines():
                match = cherry_picked_pattern.search(line)
                if match:
                    sha = match.group(1)
                    original_shas.append(sha)
                    print(f"Found cherry-pick reference: {sha}")

        if not original_shas:
            print("No cherry-picked commit references found in PR commits.")
            return []

        # Deduplicate SHAs while preserving order
        dedup_shas = []
        for sha in original_shas:
            if sha not in dedup_shas:
                dedup_shas.append(sha)

        labeled_prs = []
        for sha in dedup_shas:
            print(f"Locating original Pull Request for commit {sha[:7]}...")
            try:
                # Find PRs associated with the squash commit
                associated_commit = self.gh_repo.get_commit(sha)
                prs = associated_commit.get_pulls()

                if prs.totalCount > 0:
                    for pr in prs:
                        if pr.number == self.config.pr_number:
                            continue

                        print(f"Found source PR #{pr.number}. Adding label 'cherry-pick-completed'...")
                        try:
                            pr.add_to_labels('cherry-pick-completed')
                            labeled_prs.append(pr.number)
                        except Exception as label_err:
                            print(f"Failed to add label to PR #{pr.number}: {label_err}")
                else:
                    # Fallback search using search API if get_pulls is empty
                    print(f"No direct PR found for {sha[:7]} via get_pulls. Trying search API...")
                    query = f"repo:{self.gh_repo.full_name} is:pr is:merged {sha}"
                    search_results = self.gh.search_issues(query=query)
                    if search_results.totalCount > 0:
                        for issue in search_results:
                            pr = self.gh_repo.get_pull(issue.number)
                            if pr.number == self.config.pr_number:
                                continue
                            print(f"Found source PR #{pr.number} via search. Adding label...")
                            try:
                                pr.add_to_labels('cherry-pick-completed')
                                labeled_prs.append(pr.number)
                            except Exception as label_err:
                                print(f"Failed to add label to PR #{pr.number}: {label_err}")
                    else:
                        print(f"Could not associate commit {sha[:7]} with any Pull Request.")
            except Exception as e:
                print(f"Error resolving commit {sha[:7]}: {e}")

        # Deduplicate labeled PR numbers
        return sorted(list(set(labeled_prs)))


def main():
    mode = os.environ.get('INPUT_MODE', 'hotfix').lower()

    if mode == 'completed':
        config = CherryPickConfig(
            github_token=os.environ['INPUT_GITHUB_TOKEN'],
            pr_number=int(os.environ['INPUT_PR_NUMBER']),
            mode=mode
        )

        automation = CherryPickCompletedAutomation(config)
        labeled_prs = automation.run()

        with open(os.environ.get('GITHUB_OUTPUT', '/dev/stdout'), 'a') as f:
            f.write(f"labeled-prs={json.dumps(labeled_prs)}\n")

        summary_lines = [
            "## 🏷️ Cherry-Pick Completed Labeler Summary",
            "",
            f"Processed hotfix PR #{config.pr_number}",
            ""
        ]

        if labeled_prs:
            summary_lines.append("### ✅ Labeled Pull Requests")
            summary_lines.append("")
            for pr_num in labeled_prs:
                summary_lines.append(f"- PR #{pr_num} labeled with `cherry-pick-completed`")
            summary_lines.append("")
        else:
            summary_lines.append("### ℹ️ No original Pull Requests were labeled.")
            summary_lines.append("")

        summary = '\n'.join(summary_lines)
    else:
        config = CherryPickConfig(
            github_token=os.environ['INPUT_GITHUB_TOKEN'],
            squash_sha=os.environ['INPUT_SQUASH_SHA'],
            pr_number=int(os.environ['INPUT_PR_NUMBER']),
            pr_title=os.environ['INPUT_PR_TITLE'],
            pr_url=os.environ['INPUT_PR_URL'],
            labels=json.loads(os.environ.get('INPUT_LABELS', '[]')),
            dry_run=os.environ.get('INPUT_DRY_RUN', 'false').lower() == 'true',
            mode=mode
        )

        automation = CherryPickAutomation(config)
        results = automation.run()

        with open(os.environ.get('GITHUB_OUTPUT', '/dev/stdout'), 'a') as f:
            f.write(f"created-prs={json.dumps(results['created_prs'])}\n")
            f.write(f"skipped-versions={json.dumps(results['skipped_versions'])}\n")
            f.write(f"accumulated-prs={json.dumps(results['accumulated_prs'])}\n")

        summary_lines = [
            "## 🍒 Hotfix Cherry-Pick Summary",
            "",
            f"Processed hotfix cherry-pick from PR #{config.pr_number}",
            "",
            f"**Squash commit**: `{config.squash_sha[:7]}`",
            ""
        ]

        if results['created_prs']:
            summary_lines.append("### ✅ Created/Updated Hotfix PRs")
            summary_lines.append("")
            for pr in results['created_prs']:
                summary_lines.append(f"- v{pr['version']}: [PR #{pr['number']}]({pr['url']})")
            summary_lines.append("")

        if results['accumulated_prs']:
            summary_lines.append("### 📋 Accumulated PRs in Hotfix Branch")
            summary_lines.append("")
            for pr_num in results['accumulated_prs']:
                summary_lines.append(f"- #{pr_num}")
            summary_lines.append("")

        if results['skipped_versions']:
            summary_lines.append("### ⚠️ Skipped Versions")
            summary_lines.append("")
            for skip in results['skipped_versions']:
                summary_lines.append(f"- v{skip['version']}: {skip['reason']}")
            summary_lines.append("")

        summary = '\n'.join(summary_lines)

    print(summary)

    if mode == 'hotfix':
        if results['has_labels'] and not results['created_prs']:
            sys.exit(1)


if __name__ == '__main__':
    main()