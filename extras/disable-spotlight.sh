#!/usr/bin/env bash
# Disable the Spotlight *index* (same as the TUI Spotlight row).
# Does NOT launchctl-disable KeepAlive mds / corespotlightd — that is a
# separate catalog section, gated [macos>=27], because mdutil -d leaves mds
# resident. Reverse of *this* script is extras/enable-spotlight.sh (mdutil
# only). Reversing the KeepAlive cut is the TUI / --restore / --enable-all.
#
# Loss: Cmd-Space *file* search, Finder Cmd-F, Mail content search.
# Keep: the Cmd-Space overlay (on 27 that is com.apple.campo, not mds).
# Empty Spotlight is blank; use a Dock Applications stack for an icon grid.
# CLI find / fd / rg are unaffected.
set -e

echo "==> disabling Spotlight indexing and search on all volumes"
# `-i off` leaves the Data volume's indexer running on macOS 26; `-d` stops it.
sudo mdutil -a -d

echo "==> erasing existing index (frees disk; rebuilt if you re-enable)"
sudo mdutil -a -E

echo "==> verifying"
sudo mdutil -a -s

echo "Done. Reverse with extras/enable-spotlight.sh"
echo "KeepAlive mds is unchanged; that cut is the TUI section, not this script."
