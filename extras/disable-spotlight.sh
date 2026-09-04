#!/usr/bin/env bash
# Permanently disable macOS Spotlight indexing.
# Saves ~700MB-1GB RAM (mds_stores + Spotlight.app + corespotlightd + mds).
# CLI `find` / `fd` / `rg` still work. Loss: Cmd-Space file search, Finder Cmd-F, Mail content search.
# Reverse: extras/enable-spotlight.sh
set -e

echo "==> disabling Spotlight indexing and search on all volumes"
# `-i off` leaves the Data volume's indexer running on macOS 26; `-d` stops it.
sudo mdutil -a -d

echo "==> erasing existing index (optional, frees disk; index would be rebuilt if re-enabled)"
# Comment next line if you want to keep current index in case you re-enable later
sudo mdutil -E /

echo "==> verifying"
sudo mdutil -a -s

echo "Done. Reverse with extras/enable-spotlight.sh"
