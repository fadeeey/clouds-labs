import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/lab-03/summarize_scan.py"


class ScanSummaryTests(unittest.TestCase):
    def test_summary_reports_only_severities_in_scan_scope(self):
        report = {
            "Metadata": {"ImageID": "sha256:fixture"},
            "Results": [
                {
                    "Vulnerabilities": [
                        {"Severity": "HIGH"},
                        {"Severity": "MEDIUM"},
                    ]
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.json"
            path.write_text(json.dumps(report))
            env = os.environ.copy()
            env["TRIVY_CACHE_DIR"] = str(Path(directory) / "empty-cache")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "fixture:image"],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

        self.assertIn("| HIGH | 1 |", result.stdout)
        self.assertIn("| CRITICAL | 0 |", result.stdout)
        self.assertIn("lower severities are excluded", result.stdout)
        self.assertNotIn("MEDIUM |", result.stdout)
        self.assertNotIn("LOW |", result.stdout)


if __name__ == "__main__":
    unittest.main()
