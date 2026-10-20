#!/usr/bin/env python3
"""Print a concise severity summary from Trivy JSON without hiding findings."""

import json
import os
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1])
    image = sys.argv[2]
    report = json.loads(path.read_text())
    counts: Counter[str] = Counter()
    for result in report.get("Results", []):
        for vulnerability in result.get("Vulnerabilities", []):
            counts[vulnerability.get("Severity", "UNKNOWN")] += 1
    cache_dir = Path(os.environ.get("TRIVY_CACHE_DIR", path.parent.parent / "trivy-cache"))
    metadata_path = cache_dir / "db" / "metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    print(f"### Trivy scan: `{image}`")
    print(f"\nLocal image config digest: `{report.get('Metadata', {}).get('ImageID', 'not found')}`.")
    print("\n| Severity | Findings |\n|---|---:|")
    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        print(f"| {severity} | {counts[severity]} |")
    print(f"\nDatabase updated: `{metadata.get('UpdatedAt', 'not found')}`; Trivy schema: `{metadata.get('Version', 'not found')}`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
