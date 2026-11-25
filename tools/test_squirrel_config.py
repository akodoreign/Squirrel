import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import squirrel_config as config
import squirrels_navigation as navigation


class ConfigurationTests(unittest.TestCase):
    def test_external_paths_are_shared_by_runner_and_scheduler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, SQUIRRELS_TRAVELER_ROOT=str(root / "game"),
                       SQUIRRELS_OUTPUT_ROOT=str(root / "results"))
            script = (
                "import markerchase as m, squirrel_loop as s, squirrels_navigation as n; "
                "print(m.TOOL); print(m.OUT); print(s.OUT); print(n.POLICY_FILE)"
            )
            result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parent,
                                    env=env, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.splitlines(), [
                str(root / "game" / "_tools" / "rpgcobo-tool"),
                str(root / "results"),
                str(root / "results"),
                str(root / "results" / "squirrels_walking_policy.py"),
            ])

    def test_missing_game_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "ENGINE_ROOT", Path(directory)):
            with self.assertRaisesRegex(SystemExit, "SQUIRRELS_TRAVELER_ROOT"):
                config.validate_traveler()

    def test_walking_hints_are_saved_as_runtime_data(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(navigation, "POLICY_FILE", Path(directory) / "data" / "hints.py"):
            self.assertTrue(navigation.store_hint("story_0_crab", "M101 1 2", "M101",
                                                  (2.0, 3.0), [(2.0, 3.0)]))
            self.assertEqual(navigation.read_hints()[
                ("story_0_crab", "M101 1 2", "M101")], (2.0, 3.0))


if __name__ == "__main__":
    unittest.main()
