import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "herdr" / "afplay"
PLAYER_ERROR = "AudioFileOpen failed"


class HerdrAfplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="herdr afplay ")
        self.temp = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def play(self, *arguments, temp=None):
        return subprocess.run(
            [str(WRAPPER), *arguments],
            env={"PATH": "/usr/bin:/bin", "TMPDIR": str(temp or self.temp)},
            capture_output=True, text=True, timeout=10,
        )

    def missing(self, name):
        path = self.temp / name
        self.assertFalse(path.exists())
        return str(path)

    def assertSkipped(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def assertPlayed(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(PLAYER_ERROR, result.stderr)

    def test_finished_sound_is_skipped(self):
        self.assertSkipped(self.play(self.missing("home/.config/herdr/sounds/silent.mp3")))

    def test_request_sound_reaches_player_when_lock_is_free(self):
        request = self.missing("herdr-sound-1-1.mp3")
        self.assertPlayed(self.play(request))
        self.assertPlayed(self.play(request))

    def test_request_sound_is_skipped_while_another_plays(self):
        holder = subprocess.Popen(
            ["/usr/bin/lockf", "-k", str(self.temp / "herdr-afplay.lock"),
             "/bin/sh", "-c", "echo held; exec /bin/sleep 10"],
            stdout=subprocess.PIPE, text=True, start_new_session=True,
        )
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(os.killpg, holder.pid, signal.SIGKILL)
        self.assertEqual(holder.stdout.readline(), "held\n")
        self.assertSkipped(self.play(self.missing("herdr-sound-2-1.mp3")))

    def test_request_sound_plays_when_lock_cannot_be_created(self):
        request = self.missing("herdr-sound-3-1.mp3")
        self.assertPlayed(self.play(request, temp=self.missing("no-such-directory")))

    def test_other_calls_pass_through(self):
        self.assertPlayed(self.play(self.missing("other.mp3")))
        silent = self.missing("home/.config/herdr/sounds/silent.mp3")
        self.assertPlayed(self.play("-v", "1", silent))


if __name__ == "__main__":
    unittest.main()
