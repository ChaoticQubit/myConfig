#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ln -sfn "$DIR" ~/.dotfiles
( cd "$DIR" && nix flake update nix-homebrew )
exec sudo nix run nix-darwin/master#darwin-rebuild -- switch --flake ~/.dotfiles#myMac
