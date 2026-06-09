#!/usr/bin/env bash
# Re-enable macOS UI animations + transparency (revert disable-animations.sh).
set -e

defaults write com.apple.universalaccess reduceMotion -bool false
defaults write com.apple.universalaccess reduceTransparency -bool false
defaults delete -g NSAutomaticWindowAnimationsEnabled 2>/dev/null || true
defaults delete -g NSWindowResizeTime 2>/dev/null || true
defaults delete -g NSScrollAnimationEnabled 2>/dev/null || true
defaults delete com.apple.dock launchanim 2>/dev/null || true
defaults delete com.apple.dock expose-animation-duration 2>/dev/null || true
defaults delete com.apple.dock springboard-show-duration 2>/dev/null || true
defaults delete com.apple.dock springboard-hide-duration 2>/dev/null || true
defaults delete com.apple.dock springboard-page-duration 2>/dev/null || true
defaults delete com.apple.dock autohide-time-modifier 2>/dev/null || true
defaults delete com.apple.dock autohide-delay 2>/dev/null || true
defaults delete com.apple.mail DisableSendAnimations 2>/dev/null || true
defaults delete com.apple.mail DisableReplyAnimations 2>/dev/null || true
defaults delete com.apple.finder DisableAllAnimations 2>/dev/null || true

killall Dock 2>/dev/null || true
killall Finder 2>/dev/null || true
killall SystemUIServer 2>/dev/null || true

echo "Animations restored."
