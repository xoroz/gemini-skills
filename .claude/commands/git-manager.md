Skill: git-manager

Automated Git synchronization using conventional commits and token-based authentication.

## Workflow

### 1. Sync state

```bash
git fetch origin
git pull origin $(git branch --show-current)
git status
```

### 2. Stage and commit

Stage all modified/new files (excluding .env, venv/, scrapes/, sites/):

```bash
git add scripts/ skills/ assets/ *.sh *.py *.md *.txt requirements.txt .gitignore .claude/ 2>/dev/null || git add -u
```

Determine commit message using this priority:

- **Priority A:** If there are specific staged changes, write a conventional commit message (`feat:`, `fix:`, `chore:`, `docs:`) that summarises the *why*, not just the *what*.
- **Priority B:** Fallback format: `[YYYY-MM-DD] chore: auto-sync`

Commit:

```bash
git commit -m "<MESSAGE>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

### 3. Authenticated push

Check for `GITHUB_API_KEY` in the environment or `.env`:

```bash
# If GITHUB_API_KEY is set:
REMOTE=$(git remote get-url origin | sed 's|https://||')
git push https://$GITHUB_API_KEY@$REMOTE

# If not set — standard push:
git push

# If no upstream yet:
git push --set-upstream origin $(git branch --show-current)
```

### 4. Confirm

```bash
git status
git log --oneline -3
```
