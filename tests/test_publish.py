"""Exercise the actual shell guard with a fake git; never commit or push in tests."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "publish.sh"


class PublishGuardTests(unittest.TestCase):
    def run_script(self, mode, *, site=False, **statuses):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            git = binary / "git"
            git.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "args = sys.argv[1:]\n"
                "with open(os.environ['MOCK_GIT_LOG'], 'a') as log:\n"
                "    log.write(json.dumps(args) + '\\n')\n"
                "command = args[2] if args[:1] == ['-C'] else args[0]\n"
                "status = json.loads(os.environ['MOCK_GIT_STATUSES']).get(command, 0)\n"
                "sys.exit(status)\n",
                encoding="utf-8",
            )
            git.chmod(0o755)
            if site:
                (root / "site").mkdir()
                (root / "site" / ".git").write_text("fake worktree marker\n")
            log = root / "git.jsonl"
            env = {
                **os.environ,
                "PATH": str(binary) + os.pathsep + os.environ.get("PATH", ""),
                "MOCK_GIT_LOG": str(log),
                "MOCK_GIT_STATUSES": json.dumps(statuses),
            }
            result = subprocess.run(
                ["bash", str(SCRIPT), mode], cwd=root, env=env,
                capture_output=True, text=True, check=False,
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    @staticmethod
    def commands(calls):
        return [args[2] if args[:1] == ["-C"] else args[0] for args in calls]

    def test_weekend_or_retry_without_changes_never_commits_or_pushes(self):
        result, calls = self.run_script("publish", site=True, diff=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(calls), ["add", "diff"])
        self.assertIn("no commit or push", result.stdout)

    def test_changed_observations_publish_once_without_force(self):
        result, calls = self.run_script("publish", site=True, diff=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(calls).count("commit"), 1)
        self.assertEqual(calls[-1], ["-C", "site", "push", "origin", "HEAD:refs/heads/gh-pages"])

    def test_diff_error_never_commits_or_pushes(self):
        result, calls = self.run_script("publish", site=True, diff=128)
        self.assertEqual(result.returncode, 128)
        self.assertEqual(self.commands(calls), ["add", "diff"])

    def test_stage_failure_stops_before_diff(self):
        result, calls = self.run_script("publish", site=True, add=128)
        self.assertEqual(result.returncode, 128)
        self.assertEqual(self.commands(calls), ["add"])

    def test_commit_failure_never_pushes(self):
        result, calls = self.run_script("publish", site=True, diff=1, commit=1)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("push", self.commands(calls))

    def test_push_failure_is_not_reported_as_success(self):
        result, _ = self.run_script("publish", site=True, diff=1, push=1)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Updated gh-pages", result.stdout)

    def test_missing_worktree_never_stages_source_checkout(self):
        result, calls = self.run_script("publish")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [])

    def test_existing_branch_restores_persisted_history(self):
        result, calls = self.run_script("restore")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(calls), ["ls-remote", "fetch", "worktree"])
        self.assertEqual(calls[-1][-1], "refs/remotes/origin/gh-pages")

    def test_missing_branch_bootstraps_orphan_site(self):
        result, calls = self.run_script("restore", **{"ls-remote": 2})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(calls), ["ls-remote", "worktree", "switch"])
        self.assertEqual(calls[-1], ["-C", "site", "switch", "--orphan", "gh-pages"])

    def test_auth_or_network_error_does_not_bootstrap(self):
        result, calls = self.run_script("restore", **{"ls-remote": 128})
        self.assertEqual(result.returncode, 128)
        self.assertEqual(self.commands(calls), ["ls-remote"])

    def test_fetch_failure_does_not_create_worktree(self):
        result, calls = self.run_script("restore", fetch=128)
        self.assertEqual(result.returncode, 128)
        self.assertEqual(self.commands(calls), ["ls-remote", "fetch"])

    def test_restore_refuses_existing_site(self):
        result, calls = self.run_script("restore", site=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
