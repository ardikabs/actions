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
from jinja2 import Environment

try:
    from src import templates
except ModuleNotFoundError:
    import templates

class CherryPickConfig(BaseModel):
    github_token: str
    pr_number: int
    mode: str = "hotfix"
    squash_sha: Optional[str] = None
    pr_title: Optional[str] = None
    pr_url: Optional[str] = None
    labels: Optional[List[str]] = None
    dry_run: bool = False
    include_completed_comment: bool = False


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


class CherryPickHotfixAutomation:
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

            env = Environment(trim_blocks=True, lstrip_blocks=True)
            template = env.from_string(templates.CONFLICT_COMMENT)
            comment_body = template.render(
                short_sha=short_sha,
                hotfix_branch=hotfix_branch,
                release_branch=found_release_branch,
                pr_info=pr_info,
                squash_sha=self.config.squash_sha
            )

            issue = self.gh_repo.get_issue(self.config.pr_number)
            issue.create_comment(comment_body)
            print(f"Posted conflict comment to PR #{self.config.pr_number}")
        except Exception as e:
            print(f"Failed to post conflict comment: {e}")

    def cherry_pick_commit(self, sha: str) -> Tuple[bool, bool]:
        try:
            # Identity is already configured in process_version()
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

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        template = env.from_string(templates.HOTFIX_PR_BODY)
        return template.render(
            release_branch=release_branch,
            hotfixes=hotfixes
        )

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
            # Configure Git Identity first (Global for safety)
            # We set it globally for the runner context to ensure all operations use it.
            self.repo.config_writer().set_value("user", "name", "github-actions[bot]").release()
            self.repo.config_writer().set_value("user", "email", "github-actions[bot]@users.noreply.github.com").release()

            # Hard Reset to ensure no leftover files from previous steps
            print("Ensuring clean working directory...")
            self.repo.git.reset('--hard', 'HEAD')
            self.repo.git.clean('-fd')

            # Clear any stuck cherry-pick state from previous runs
            try:
                self.repo.git.cherry_pick('--abort')
            except:
                pass

            # Ensure we are on 'main' (or a known baseline) before starting
            # This prevents "already on branch" errors or unexpected states
            self.repo.git.checkout('main')

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
                if has_conflicts:
                    pr_body = self.generate_pr_body(target, release_branch, hotfix_branch)
                    env = Environment(trim_blocks=True, lstrip_blocks=True)
                    template = env.from_string(templates.HOTFIX_PR_BODY_CONFLICT)
                    pr_body = template.render(
                        short_sha=short_sha,
                        hotfix_branch=hotfix_branch,
                        body=pr_body
                    )

                    pr = self.get_open_pull_request(hotfix_branch, release_branch)
                    if not pr:
                        print("Conflict detected. Creating draft PR for manual resolution...")
                        pr_url, pr_number = self.create_pull_request(
                            target,
                            hotfix_branch,
                            release_branch,
                            pr_body)
                    else:
                        pr_url = pr.html_url
                        pr_number = pr.number
                        print(f"Conflict detected. Existing PR found: {pr_url}")

                    self.post_conflict_comment(target, hotfix_branch)

                    # Abort the cherry-pick to release the lock/conflict state
                    try:
                        self.repo.git.cherry_pick('--abort')
                    except:
                        pass

                    self.repo.git.checkout('main')
                    return HotfixResult(
                        version=target,
                        success=False,
                        error="Cherry-pick failed due to merge conflicts",
                        has_conflicts=True
                    )

                try:
                    self.repo.git.cherry_pick('--abort')
                except:
                    pass

                self.repo.git.checkout('main')
                return HotfixResult(
                    version=target,
                    success=False,
                    error="Cherry-pick failed for unknown reason"
                )

        except Exception as e:

            self.repo.git.checkout('main')
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
                'has_labels': False,
                'is_noop': True
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
            'is_noop': len(created_prs) == 0 and len(skipped_versions) > 0,
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

    def parse_version_labels(self, pr) -> List[VersionTarget]:
        version_pattern = re.compile(r'^cherry-pick/release-v?(\d+)\.(\d+)$')
        versions = {}

        for label in pr.labels:
            match = version_pattern.match(label.name)
            if match:
                major, minor = int(match.group(1)), int(match.group(2))
                key = f"{major}.{minor}"
                versions[key] = VersionTarget(major=major, minor=minor)

        return list(versions.values())

    def add_completed_labels(self, pr, target_versions: List[VersionTarget]) -> List[str]:
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

    def check_and_add_generic_label(self, pr) -> bool:
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

    def get_hotfix_version_from_branch(self, branch_name: str) -> Optional[str]:
        match = re.match(r'hotfix/v(\d+)\.(\d+)\.x', branch_name)
        if match:
            return f"{match.group(1)}.{match.group(2)}"
        return None

    def get_latest_tag_for_minor(self, minor_version: str) -> Optional[str]:
        try:
            tags = self.gh_repo.get_tags()
            prefix = f"v{minor_version}."
            latest = None
            for tag in tags:
                if tag.name.startswith(prefix):
                    if latest is None or tag.name > latest:
                        latest = tag.name
            return latest
        except Exception as e:
            print(f"Failed to get latest tag for v{minor_version}: {e}")
            return None

    def post_completed_comment(self, pr, version: str, hotfix_pr_url: str) -> None:
        try:
            env = Environment(trim_blocks=True, lstrip_blocks=True)
            template = env.from_string(templates.COMPLETED_COMMENT)
            comment_body = template.render(
                version=version,
                pr_number=self.config.pr_number,
                hotfix_pr_url=hotfix_pr_url
            )
            pr.create_comment(comment_body)
            print(f"Posted completed comment to PR #{pr.number} for version v{version}")
        except Exception as e:
            print(f"Failed to post completed comment to PR #{pr.number}: {e}")

    def run(self) -> List[int]:
        print(f"Fetching hotfix Pull Request #{self.config.pr_number}...")
        try:
            hotfix_pr = self.gh_repo.get_pull(self.config.pr_number)
        except Exception as e:
            print(f"Failed to fetch hotfix PR #{self.config.pr_number}: {e}")
            sys.exit(1)

        hotfix_pr_url = hotfix_pr.html_url
        hotfix_version = self.get_hotfix_version_from_branch(hotfix_pr.head.ref)

        latest_tag_version = None
        if self.config.include_completed_comment and hotfix_version:
            latest_tag_version = self.get_latest_tag_for_minor(hotfix_version)
            print(f"Latest tag for v{hotfix_version}: {latest_tag_version}" if latest_tag_version else f"No tags found for v{hotfix_version}")

        comment_version = latest_tag_version or (f"v{hotfix_version}" if hotfix_version else None)
        print(f"Hotfix version: v{hotfix_version}" if hotfix_version else "Hotfix version: not determined from branch")

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

                        print(f"Found source PR #{pr.number}. Processing labels...")

                        target_versions = self.parse_version_labels(pr)
                        if target_versions:
                            print(f"Source PR has version labels: {[v.version_string for v in target_versions]}")

                            self.add_completed_labels(pr, target_versions)

                            self.check_and_add_generic_label(pr)
                        else:
                            print(f"No version labels found on source PR. Adding generic 'cherry-pick-completed'...")
                            try:
                                pr.add_to_labels('cherry-pick-completed')
                            except Exception as label_err:
                                print(f"Failed to add label to PR #{pr.number}: {label_err}")

                        if self.config.include_completed_comment and comment_version:
                            self.post_completed_comment(pr, comment_version, hotfix_pr_url)

                        labeled_prs.append(pr.number)
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
                            print(f"Found source PR #{pr.number} via search. Processing labels...")

                            target_versions = self.parse_version_labels(pr)
                            if target_versions:
                                print(f"Source PR has version labels: {[v.version_string for v in target_versions]}")

                                self.add_completed_labels(pr, target_versions)

                                self.check_and_add_generic_label(pr)
                            else:
                                print(f"No version labels found on source PR. Adding generic 'cherry-pick-completed'...")
                                try:
                                    pr.add_to_labels('cherry-pick-completed')
                                except Exception as label_err:
                                    print(f"Failed to add label to PR #{pr.number}: {label_err}")

                            if hotfix_version:
                                self.post_completed_comment(pr, hotfix_version, hotfix_pr_url)

                            labeled_prs.append(pr.number)
                    else:
                        print(f"Could not associate commit {sha[:7]} with any Pull Request.")
            except Exception as e:
                print(f"Error resolving commit {sha[:7]}: {e}")

        # Deduplicate labeled PR numbers
        return sorted(list(set(labeled_prs)))


def check_and_exit(results: dict) -> None:
    if results.get('is_noop', False):
        print("💡 No-op: No PRs were created (all versions were skipped).", file=sys.stderr)
        sys.exit(0)
    if results.get('has_labels') and not results.get('created_prs'):
        print("❌ Error: Labels were found but no PRs were created.", file=sys.stderr)
        sys.exit(1)


def generate_summary(config, results=None, labeled_prs=None) -> str:
    env = Environment(trim_blocks=True, lstrip_blocks=True)
    if config.mode == 'hotfix':
        template = env.from_string(templates.SUMMARY_HOTFIX)
        return template.render(config=config, results=results)
    elif config.mode == 'completed':
        template = env.from_string(templates.SUMMARY_COMPLETED)
        return template.render(config=config, labeled_prs=labeled_prs)
    else:
        raise ValueError(f"Unknown mode: {config.mode}")


def main():
    mode = os.environ.get('INPUT_MODE', 'hotfix').lower()

    summary = "N/A"

    if mode == 'completed':
        config = CherryPickConfig(
            github_token=os.environ['INPUT_GITHUB_TOKEN'],
            pr_number=int(os.environ['INPUT_PR_NUMBER']),
            mode=mode,
            include_completed_comment=os.environ.get('INPUT_INCLUDE_COMPLETED_COMMENT', 'false').lower() == 'true'
        )

        automation = CherryPickCompletedAutomation(config)
        labeled_prs = automation.run()

        with open(os.environ.get('GITHUB_OUTPUT', '/dev/stdout'), 'a') as f:
            f.write(f"labeled-prs={json.dumps(labeled_prs)}\n")

        summary = generate_summary(config, labeled_prs=labeled_prs)
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

        automation = CherryPickHotfixAutomation(config)
        results = automation.run()

        with open(os.environ.get('GITHUB_OUTPUT', '/dev/stdout'), 'a') as f:
            f.write(f"created-prs={json.dumps(results['created_prs'])}\n")
            f.write(f"skipped-versions={json.dumps(results['skipped_versions'])}\n")
            f.write(f"accumulated-prs={json.dumps(results['accumulated_prs'])}\n")
            f.write(f"is-noop={str(results.get('is_noop', False)).lower()}\n")

        check_and_exit(results)
        summary = generate_summary(config, results=results)

    print(summary)


if __name__ == '__main__':
    main()