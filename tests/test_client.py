"""Run the shipped client script using Node's built-in test runner, without packages."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ClientTests(unittest.TestCase):
    def test_calculator_and_observation_chart(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js 20+ is required for the offline client proof")
        script = Path(__file__).with_name("client_logic.cjs")
        result = subprocess.run([node, "--test", "--test-reporter=tap", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# fail 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
