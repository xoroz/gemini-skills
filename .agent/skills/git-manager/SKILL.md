Skill: git-manager

Description: Automated Git synchronization using OpenSpec-driven commit messages and ENV-based authentication.
Goal

To maintain a clean, updated repository state by automating the fetch-commit-push cycle with context-aware metadata.
Workflow
1. Sync State

Before performing any work, synchronize the local environment with the remote:

    git fetch origin

    git pull origin $(git branch --show-current)

    git status (Verify a clean state or identify pending changes).

2. Determine Commit Message

The agent should use the following hierarchy to determine the commit message:

Priority A: OpenSpec Context

    Look for active proposals in openspec/changes/*/proposal.md.

    Extract the first line (e.g., # Change: Add user login).

    Format: feat: <extracted_text> or fix: <extracted_text> based on the file content.

Priority B: Automated Fallback

    If no OpenSpec is found, generate a concise summary of staged changes.

    Format: [YYYY-MM-DD] Auto-commit: <brief_summary_of_diff>

3. Stage and Commit

    git add .

    git commit -m "<MESSAGE>"

4. Authenticated Push Logic

    Check Auth: Identify if the GITHUB_API_KEY environment variable is available.

    Authenticated Execution: * If GITHUB_API_KEY exists: * Extract the remote URL (e.g., github.com/owner/repo). * Execute: git push https://$GITHUB_API_KEY@github.com/<owner>/<repo>.git

    Standard Execution: * If no key exists: git push

    Upstream Handling: * If the push fails due to a missing upstream, retry with: git push --set-upstream origin $(git branch --show-current)

