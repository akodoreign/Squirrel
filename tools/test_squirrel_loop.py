import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import markerchase as mc
import squirrel_loop as loop


class FollowupTests(unittest.TestCase):
    def setUp(self):
        queued = patch.object(mc, "queued_minigames", return_value=[])
        queued.start()
        self.addCleanup(queued.stop)

    def state(self, phase="side", cycles=0):
        return {"name": "crab", "phase": phase, "cycles": cycles, "same": 0,
                "last_goal": "", "broken": [], "busy": ""}

    def judge(self, text):
        state = self.state()
        with patch.object(loop, "log_of", return_value=text), patch.object(mc, "path_quests", return_value=[100, 101]):
            loop.judge(0, state)
        return state

    def test_broken_and_missing_markers_are_not_verified(self):
        state = self.judge("[RT] CHASE QUESTDONE 100 (no goal left for it)\n"
                           "[RT] CHASE QUESTBROKEN 101\n")
        self.assertEqual(state["phase"], "side")
        self.assertEqual(state["pending"], [100, 101])

    def test_only_all_expected_completion_flags_unlock_conversations(self):
        text = "[RT] CHASE QUESTDONE 100 (completion flag set)\n"
        self.assertEqual(self.judge(text)["phase"], "side")
        state = self.judge(text + "[RT] CHASE QUESTBROKEN 101\n"
                           "[RT] CHASE QUESTDONE 101 (completion flag set)\n")
        self.assertEqual(state["phase"], "conversations")
        self.assertEqual(state["broken"], [])

    def test_conversations_are_not_starved_by_stalled_side_quests(self):
        states = {"0": self.state("parked (side): needs Claude", 25),
                  "1": self.state("conversations", 24)}
        self.assertEqual(loop.pick(states, "w1"), ("conversations", 1))
        states["1"]["cycles"] = 26
        self.assertEqual(loop.pick(states, "w1"), ("sidequests", 0))

    def test_minigames_alternate_with_existing_followup_and_skip_busy_roads(self):
        states = {"0": self.state("side"), "1": dict(self.state("story"), busy="w2")}
        with patch.object(mc, "queued_minigames", return_value=["Miko dance"]):
            self.assertEqual(loop.pick(states, "w1"), ("games", 0))
            states["0"]["last_mode"] = "games"
            self.assertEqual(loop.pick(states, "w1"), ("sidequests", 0))
            states["0"]["last_mode"] = "sidequests"
            self.assertEqual(loop.pick(states, "w1"), ("games", 0))

    def test_games_are_queued_on_parked_roads_too(self):
        states = {"0": self.state("parked (story): needs Claude")}
        with patch.object(mc, "queued_minigames", return_value=["Sadane"]):
            self.assertEqual(loop.pick(states, "w1"), ("games", 0))

    def test_conversation_end_does_not_claim_exhaustive_coverage(self):
        state = self.state("conversations")
        loop.judge(0, state)
        self.assertEqual(state["phase"], "conversations")

    def test_failed_runner_stops_without_counting_a_run(self):
        state = self.state("story")
        states = {"0": state}
        stop = threading.Event()
        with patch.object(loop, "run", return_value=1), patch.object(loop, "write_state"), \
                patch.object(loop, "pick", return_value=("story", 0)):
            loop.worker(states, "w1", "main", 60, stop)
        self.assertTrue(stop.is_set())
        self.assertEqual(state["cycles"], 0)
        self.assertEqual(state["phase"], "story")
        self.assertEqual(state["busy"], "")
        self.assertNotIn("active_mode", state)

    def test_observed_choices_survive_interruption_and_replay_tries_another(self):
        with tempfile.TemporaryDirectory() as directory:
            know = {}
            with patch.object(mc, "KNOW", str(Path(directory) / "knowledge.json")), \
                    patch.object(mc, "PLAYER_RUNS", directory), patch.object(mc, "wtool", return_value=directory):
                mc.record_conversations("conversation_0_crab", [
                    "[RT] CHASE CHOICE Ask about the shrine|1 => 0 (Ask about the shrine / Leave)"], know)
                self.assertEqual(json.loads((Path(directory) / "knowledge.json").read_text()),
                                 know)
                path, _ = mc.policy_for("conversation_0_crab", know)
                policy = json.loads((Path(directory) / path).read_text())
                self.assertEqual(policy["Ask about the shrine|1"], 1)

    def test_replays_do_not_change_traveler_selection(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(mc, "wtool", return_value=directory):
            know = {"conversation_0_crab": {"menus": {
                "Hiruma Natsuko (Crab)|8": {"tried": [0], "n": 8, "options": "Crab / Crane"}}}}
            path, _ = mc.policy_for("conversation_0_crab", know)
            self.assertNotIn("Hiruma Natsuko (Crab)|8", json.loads((Path(directory) / path).read_text()))

    def test_minigame_replay_selects_play_invitation_without_changing_traveler(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(mc, "wtool", return_value=directory):
            know = {"minigame_0_crab": {"menus": {
                "Leave|1": {"tried": [0], "n": 1, "options": "Leave / Play."},
                "Hiruma Natsuko (Crab)|8": {"tried": [0], "n": 8, "options": "Crab / Crane"}}}}
            path, _ = mc.policy_for("minigame_0_crab", know)
            policy = json.loads((Path(directory) / path).read_text())
            self.assertEqual(policy["Leave|1"], 1)
            self.assertNotIn("Hiruma Natsuko (Crab)|8", policy)
            know["minigame_0_crab"]["menus"]["Leave|1"]["tried"] = [1]
            path, _ = mc.policy_for("minigame_0_crab", know)
            self.assertEqual(json.loads((Path(directory) / path).read_text())["Leave|1"], 0)


class MinigameQueueTests(unittest.TestCase):
    def test_requested_games_and_clan_games_are_persisted_as_pending(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(mc, "MINIGAME_QUEUE", str(Path(directory) / "queue.json")):
            tasks = mc.queue_minigames()
            self.assertTrue({"sadane", "dance", "kabuki", "memory", "yumi", "race", "go",
                             "ink", "kitsuki", "rings", "yabusame"} <= tasks.keys())
            self.assertTrue(all(task["status"] == "pending" for task in tasks.values()))
            self.assertEqual(len(mc.queued_minigames()), len(tasks))

    def test_open_or_narrated_fallback_is_not_an_observed_result(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(mc, "MINIGAME_QUEUE", str(Path(directory) / "queue.json")):
            mc.queue_minigames()
            mc.record_minigames("minigame_0_crab", "[RT] mini-game memory open\n"
                               "[RT] mini-game memory result 0\n")
            tasks = json.loads(Path(mc.MINIGAME_QUEUE).read_text())
            self.assertEqual(tasks["memory"]["status"], "pending")
            mc.record_minigames("minigame_0_crab", "[RT] mini-game memory result 2\n"
                               "[RT] sadane: rival duel vs Soshi Kagero -> 1\n")
            tasks = json.loads(Path(mc.MINIGAME_QUEUE).read_text())
            self.assertEqual(tasks["memory"]["status"], "observed")
            self.assertEqual(tasks["memory"]["results"][0]["result"], 2)
            self.assertEqual(tasks["sadane"]["status"], "observed")

    def test_kabuki_requires_all_four_acts_at_one_difficulty(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(mc, "MINIGAME_QUEUE", str(Path(directory) / "queue.json")):
            mc.queue_minigames()
            for difficulty, act in [("hard", 1), ("easy", 2), ("hard", 3), ("hard", 4)]:
                mc.record_minigames("minigame_1_crane", f"[RT] mini-game kabuki_{difficulty}_{act} result 1\n")
            self.assertEqual(json.loads(Path(mc.MINIGAME_QUEUE).read_text())["kabuki"]["status"], "pending")
            mc.record_minigames("minigame_1_crane", "[RT] mini-game kabuki_hard_2 result 1\n")
            self.assertEqual(json.loads(Path(mc.MINIGAME_QUEUE).read_text())["kabuki"]["status"], "observed")
            self.assertEqual(mc.queue_minigames()["kabuki"]["status"], "observed")


class ConversationReviewTests(unittest.TestCase):
    def test_exposition_review_receives_actual_dialogue_choices_and_map_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "log.txt").write_text(
                "[RT] CHASE MAP M101\n[RT] MSG Elder: The old gate is sealed.\n"
                "[RT] CHASE CHOICE Ask why|1 => 0 (Ask why / Leave)\n"
                "[RT] MSG Elder: My son is trapped beyond it.\n", encoding="utf-8")
            model = Mock(ok=True)
            model.ask.return_value = {"text": "M101, Elder: 'My son is trapped beyond it.' gives the lore personal stakes."}
            with patch.object(mc, "record_minigames"):
                mc.notes({"job": "conversation_0_crab"}, directory, model, "time limit", 60)
            request = model.ask.call_args.args[0]
            self.assertEqual(request["task"], "conversation_review")
            self.assertIn("L2 [M101] [RT] MSG Elder: The old gate is sealed.", request["evidence"])
            self.assertIn("Ask why / Leave", request["evidence"])
            report = (root / "notes.md").read_text(encoding="utf-8")
            self.assertIn("## Exposition review\n\nM101, Elder:", report)
            self.assertNotIn("Pending: no local-model exposition review", report)
            self.assertIn("sad emote is crying, not mild sadness", report)

    def test_review_excerpt_discloses_omissions_and_keeps_context(self):
        lines = ["[RT] CHASE MAP M101"] + [
            f"[RT] MSG Elder: Remember the gate {number}." for number in range(30)]
        evidence = mc.conversation_review_evidence("\n".join(lines), limit=150)
        self.assertIn("omitted scenes remain unreviewed", evidence)
        self.assertIn("[M101]", evidence)
        self.assertIn("Remember the gate 29.", evidence)
        self.assertNotIn("Remember the gate 0.", evidence)

    def test_offline_review_remains_pending_not_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "log.txt").write_text("[RT] CHASE MAP M101\n", encoding="utf-8")
            model = Mock(ok=False)
            with patch.object(mc, "record_minigames"):
                mc.notes({"job": "conversation_0_crab"}, directory, model, "blocked", 60)
            model.ask.assert_not_called()
            self.assertIn("Pending: no local-model exposition review",
                          (root / "notes.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
