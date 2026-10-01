import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

import farmer


CONFIG = dict(account="muxu9", repo="muxu9/achievment-farmer", coauthor="torvalds",
              coauthor_name="Linus Torvalds", coauthor_email="1024025+torvalds@users.noreply.github.com",
              author_name="muxu9", author_email="243730108+muxu9@users.noreply.github.com",
              campaign="test", title="Pair practice")


class FarmerTests(unittest.TestCase):
    def test_wrong_account_stops_before_writes(self):
        with patch.object(farmer, "api", return_value={"login": "Eve-146T"}) as api:
            with self.assertRaises(farmer.FarmerError):
                farmer.identity(CONFIG)
            api.assert_called_once_with("user")

    def test_trailer_injection_rejected(self):
        with self.assertRaises(farmer.FarmerError):
            farmer.validate(CONFIG | {"coauthor_name": "Linus\nCo-authored-by: Other"})

    def test_dry_run_is_offline(self):
        # Keep all temporary test artifacts inside the project.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            config = Path(directory) / "farmer.json"
            config.write_text(json.dumps(CONFIG))
            with patch.object(farmer, "api", side_effect=AssertionError("network")):
                result = CliRunner().invoke(farmer.app, ["run", "--dry-run", "--config", str(config)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Linus Torvalds", result.output)

    def test_merged_step_is_not_repeated(self):
        pr = {"merged_at": "2026-10-01", "number": 1}
        with patch.object(farmer, "api") as api:
            self.assertEqual(farmer.step(CONFIG, 1, {"farmer/test/0001": pr}), (pr, False))
            api.assert_not_called()

    def test_closed_unmerged_pr_stops(self):
        with patch.object(farmer, "api") as api:
            with self.assertRaises(farmer.FarmerError):
                farmer.step(CONFIG, 1, {"farmer/test/0001": {"state": "closed", "number": 1}})
            api.assert_not_called()

    def test_interrupted_open_pr_uses_existing_head(self):
        pr = {"state": "open", "number": 7, "html_url": "https://github.com/example/pull/7"}
        with patch.object(farmer, "api", side_effect=[
            {"login": "muxu9"}, {"head": {"sha": "abc"}}, {"merged": True}
        ]) as api:
            self.assertEqual(farmer.step(CONFIG, 1, {"farmer/test/0001": pr}), (pr, True))
            self.assertEqual(api.call_args.args, ("repos/muxu9/achievment-farmer/pulls/7/merge", "PUT",
                                                 {"merge_method": "merge", "sha": "abc"}))

    def test_failed_merge_is_not_reported_as_success(self):
        with patch.object(farmer, "api", side_effect=[
            {"login": "muxu9"}, {"head": {"sha": "abc"}}, {"merged": False, "message": "blocked"}
        ]):
            with self.assertRaisesRegex(farmer.FarmerError, "blocked"):
                farmer.step(CONFIG, 1, {"farmer/test/0001": {"state": "open", "number": 7}})


if __name__ == "__main__":
    unittest.main()
