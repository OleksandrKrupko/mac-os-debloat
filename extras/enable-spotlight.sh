#!/usr/bin/env bash
# Re-enable macOS Spotlight indexing (revert disable-spotlight.sh).
# Will trigger a full reindex — heavy CPU + RAM for ~10-30 min after.
set -e

echo "==> enabling Spotlight indexing"
sudo mdutil -a -i on

# `-i on` only sets the flag; a previously disabled index stays "unknown" and
# never rebuilds (Finder metadata queries then hang). Force a clean reindex.
echo "==> erasing + rebuilding index"
sudo mdutil -a -E

echo "==> verifying"
sudo mdutil -a -s

echo "Done. Reindex will run in background."
