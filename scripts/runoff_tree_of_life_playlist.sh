#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

exec op run --env-file=.env -- uv run python scripts/create_tree_of_life_playlist.py "$@"
