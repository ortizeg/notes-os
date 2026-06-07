#!/usr/bin/env bash
# =============================================================================
# scripts/setup-branch-protection.sh
#
# PURPOSE:
#   Apply branch protection on `main` + squash-merge + delete-on-merge settings
#   to the GitHub repository via the `gh` CLI.
#
# USAGE:
#   bash scripts/setup-branch-protection.sh
#
# NOTE:
#   Run this ONCE after the GitHub remote is created. It is IDEMPOTENT — safe
#   to re-run; GitHub's API overwrites the settings on each call.
#
# PREREQUISITES:
#   1. A GitHub remote named `origin` must be configured.
#   2. `gh` CLI must be installed (https://cli.github.com/).
#   3. `gh auth login` must have been run at least once.
#
# CI STATUS CHECK NAMES:
#   The required status checks reference the job names from .github/workflows/:
#     lint       (ruff check + format)
#     typecheck  (mypy strict)
#     test       (pytest)
#   Update these names if the workflow job IDs change.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Guard 1: remote must exist
# ---------------------------------------------------------------------------
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "No 'origin' remote configured — skipping branch protection." \
       "Add a GitHub remote and re-run this script." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# Guard 2: gh CLI must be installed
# ---------------------------------------------------------------------------
if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not installed — skipping branch protection." \
       "Install from https://cli.github.com/ and re-run." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# Guard 3: gh must be authenticated
# ---------------------------------------------------------------------------
if ! gh auth status >/dev/null 2>&1; then
  echo "gh CLI is not authenticated — skipping branch protection." \
       "Run 'gh auth login' and re-run this script." >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# Resolve OWNER/REPO from the remote URL
# ---------------------------------------------------------------------------
REPO_WITH_OWNER=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null || true)

if [[ -z "$REPO_WITH_OWNER" ]]; then
  echo "Could not determine repository name from 'gh repo view'." \
       "Ensure the origin URL points to a GitHub repository." >&2
  exit 1
fi

OWNER="${REPO_WITH_OWNER%/*}"
REPO_NAME="${REPO_WITH_OWNER#*/}"

echo "Configuring repository: ${REPO_WITH_OWNER}"

# ---------------------------------------------------------------------------
# Apply merge strategy settings
# ---------------------------------------------------------------------------
echo "→ Setting merge strategy: squash-only, delete-branch-on-merge …"
gh repo edit "${REPO_WITH_OWNER}" \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge

# ---------------------------------------------------------------------------
# Apply branch protection on main
# ---------------------------------------------------------------------------
echo "→ Applying branch protection on main …"
gh api \
  --method PUT \
  "/repos/${OWNER}/${REPO_NAME}/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "typecheck", "test"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_squash_merge": true,
  "allow_merge_commit": false,
  "allow_rebase_merge": false,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Branch protection applied to ${REPO_WITH_OWNER}:"
echo "  ✓ Squash-merge only (no merge commits, no rebase)"
echo "  ✓ Delete branch on merge"
echo "  ✓ Required status checks (strict): lint, typecheck, test"
echo "  ✓ Required PR review with CODEOWNERS enforcement"
echo "  ✓ Force-pushes and deletions to main are blocked"
