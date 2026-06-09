#!/usr/bin/env bash
# Disable macOS UI animations + Liquid Glass effects.
# Saves WindowServer/UI memory + CPU. Mitigates known Tahoe Liquid Glass leak.
# Reversible: run extras/enable-animations.sh
set -e

echo "==> reducing motion + transparency (Liquid Glass leak workaround)"
defaults write com.apple.universalaccess reduceMotion -bool true
defaults write com.apple.universalaccess reduceTransparency -bool true

echo "==> disabling window/dock animations"
defaults write -g NSAutomaticWindowAnimationsEnabled -bool false
defaults write -g NSWindowResizeTime -float 0.001
defaults write -g NSScrollAnimationEnabled -bool false
defaults write com.apple.dock launchanim -bool false
defaults write com.apple.dock expose-animation-duration -float 0.1
defaults write com.apple.dock springboard-show-duration -float 0
defaults write com.apple.dock springboard-hide-duration -float 0
defaults write com.apple.dock springboard-page-duration -float 0
defaults write com.apple.dock autohide-time-modifier -float 0
defaults write com.apple.dock autohide-delay -float 0

echo "==> disabling Mail animations (if Mail installed)"
defaults write com.apple.mail DisableSendAnimations -bool true 2>/dev/null || true
defaults write com.apple.mail DisableReplyAnimations -bool true 2>/dev/null || true

echo "==> disabling Finder animations"
defaults write com.apple.finder DisableAllAnimations -bool true

echo "==> reloading UI"
killall Dock 2>/dev/null || true
killall Finder 2>/dev/null || true
killall SystemUIServer 2>/dev/null || true

echo "Done. Reverse with extras/enable-animations.sh"
