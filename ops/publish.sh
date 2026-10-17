#!/usr/bin/env bash
# Run from the source checkout. Only GitHub Actions calls the publishing mode.
set -euo pipefail

case "${1:-}" in
  restore)
    if [[ -e site ]]; then
      echo 'Refusing to replace an existing site directory.' >&2
      exit 1
    fi
    # Exit 2 means no matching ref. Authentication/network errors must fail closed.
    if git ls-remote --exit-code --heads origin refs/heads/gh-pages >/dev/null; then
      git fetch --no-tags origin refs/heads/gh-pages:refs/remotes/origin/gh-pages
      git worktree add --detach site refs/remotes/origin/gh-pages
    else
      status=$?
      if [[ "$status" -ne 2 ]]; then
        echo "Could not inspect gh-pages (git exit $status)." >&2
        exit "$status"
      fi
      git worktree add --detach site HEAD
      # switch --orphan removes tracked source files from this new worktree.
      git -C site switch --orphan gh-pages
    fi
    ;;
  publish)
    if [[ ! -e site/.git ]]; then
      echo 'Restore the site worktree before publishing.' >&2
      exit 1
    fi
    git -C site add --all
    if git -C site diff --cached --quiet; then
      echo 'No changed observations or pages; no commit or push.'
      exit 0
    else
      status=$?
      if [[ "$status" -ne 1 ]]; then
        echo "Could not compare staged pages (git exit $status)." >&2
        exit "$status"
      fi
    fi
    git -C site config user.name 'github-actions[bot]'
    git -C site config user.email '41898282+github-actions[bot]@users.noreply.github.com'
    git -C site commit -m 'Update ECB reference rates and pages'
    # No force: an unexpected concurrent writer must fail rather than lose data.
    git -C site push origin HEAD:refs/heads/gh-pages
    echo 'Updated gh-pages history and pages.'
    ;;
  *)
    echo 'Usage: bash ops/publish.sh restore|publish' >&2
    exit 2
    ;;
esac
