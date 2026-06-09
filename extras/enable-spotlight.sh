#!/usr/bin/env bash
# Re-enable macOS Spotlight indexing (revert disable-spotlight.sh).
# Will trigger a full reindex — heavy CPU + RAM for ~10-30 min after.
set -e

echo "==> enabling Spotlight indexing"
sudo mdutil -a -i on

echo "==> verifying"
sudo mdutil -a -s

echo "Done. Reindex will run in background."
