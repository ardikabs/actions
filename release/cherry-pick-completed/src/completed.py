#!/usr/bin/env python3
import os
import sys
import json
import re
from typing import List
from pydantic import BaseModel
import github


class CompletedConfig(BaseModel):
    github_token: str
    pr_number: int


class CherryPickCompletedAutomation:
    def __init__(self, config: CompletedConfig):
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
    config = CompletedConfig(
        github_token=os.environ['INPUT_GITHUB_TOKEN'],
        pr_number=int(os.environ['INPUT_PR_NUMBER'])
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

    action_path = os.environ.get('GITHUB_ACTION_PATH', '.')
    with open(f"{action_path}/summary.txt", 'w') as f:
        f.write(summary)

    print(summary)


if __name__ == '__main__':
    main()
