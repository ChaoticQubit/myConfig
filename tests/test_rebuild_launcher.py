import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "rebuild.sh").read_text().split(
    "brew trust --tap entireio/tap\n", 1
)[1]


class RebuildLauncherTests(unittest.TestCase):
    def launch(self, installed, status=0):
        with tempfile.TemporaryDirectory(prefix="rebuild launcher ") as directory:
            binaries = Path(directory)
            sudo = binaries / "sudo"
            sudo.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nexit "$TEST_STATUS"\n')
            sudo.chmod(0o700)
            executable = binaries / "darwin-rebuild"
            if installed:
                executable.write_text("#!/bin/bash\nexit 99\n")
                executable.chmod(0o700)
            repo = "/tmp/dotfiles with spaces;$(false)"
            result = subprocess.run(
                ["/bin/bash", "-c", "set -euo pipefail\n" + LAUNCHER],
                env={"PATH": directory, "DIR": repo, "TEST_STATUS": str(status)},
                capture_output=True, text=True, timeout=5,
            )
            return result, str(executable), repo

    def test_installed_launcher_uses_absolute_path_and_root_home(self):
        result, executable, repo = self.launch(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ["-H", executable, "switch", "--flake", repo + "#myMac"])

    def test_bootstrap_uses_repository_package_and_preserves_path(self):
        result, _, repo = self.launch(False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ["-H", "nix", "run", repo + "#darwin-rebuild", "--",
                          "switch", "--flake", repo + "#myMac"])

    def test_installed_failure_does_not_fall_back_to_bootstrap(self):
        result, executable, repo = self.launch(True, 37)
        self.assertEqual(result.returncode, 37)
        self.assertEqual(result.stdout.splitlines(),
                         ["-H", executable, "switch", "--flake", repo + "#myMac"])

    def test_bootstrap_failure_is_propagated(self):
        result, _, _ = self.launch(False, 42)
        self.assertEqual(result.returncode, 42)
        self.assertEqual(result.stderr, "")

    def test_flake_preserves_locked_input_packages_for_both_architectures(self):
        expression = '''let
          flake = import ./flake.nix;
          outputs = flake.outputs {
            self = {}; nixpkgs = {}; home-manager = {}; nix-homebrew = {};
            nix-darwin.packages = {
              aarch64-darwin.darwin-rebuild = "locked-arm";
              x86_64-darwin.darwin-rebuild = "locked-intel";
            };
          };
        in map (system: outputs.packages.${system}.darwin-rebuild)
          [ "aarch64-darwin" "x86_64-darwin" ]'''
        result = subprocess.run(
            ["nix-instantiate", "--eval", "--strict", "--json", "--expr", expression],
            cwd=ROOT, env=os.environ, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '["locked-arm","locked-intel"]')


if __name__ == "__main__":
    unittest.main()
