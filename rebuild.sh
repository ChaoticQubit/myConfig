#!/usr/bin/env bash
#
# Rebuilds the nix-darwin system from this flake.
# Symlinks the repo to ~/.dotfiles, refreshes the nix-homebrew flake input, grants
# the Homebrew trust entries that the third-party taps declared in
# configuration.nix require, then activates the myMac configuration.
# Inputs: none. Outputs: an activated system generation; non-zero exit on failure.
#
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ln -sfn "$DIR" ~/.dotfiles
( cd "$DIR" && nix flake update nix-homebrew )
brew trust --formula hashicorp/tap/terraform
brew trust --tap entireio/tap
exec sudo nix run nix-darwin/master#darwin-rebuild -- switch --flake ~/.dotfiles#myMac
