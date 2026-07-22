from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: github_summary.py REPORT.json")
    path = Path(sys.argv[1])
    print("## QueryAssure SQL Agent gate\n")
    if not path.exists():
        print("Evaluation report was not produced. Inspect the preceding workflow step.")
        return
    report = json.loads(path.read_text())
    summary = report.get("summary", {})
    passed = int(summary.get("passed", 0))
    total = int(summary.get("total", 0))
    outcome = "✅ Safe to merge" if passed == total and total else "❌ Quality gate failed"
    print(f"**{outcome}** — {passed}/{total} contracts passed.\n")
    print("| Contract | Result | Latency | Failed checks |")
    print("|---|---:|---:|---|")
    for result in report.get("results", []):
        failed = [check["name"] for check in result.get("checks", []) if not check["passed"]]
        status = "PASS" if result.get("passed") else "FAIL"
        latency = float(result.get("trace", {}).get("latency_ms", 0.0))
        print(
            f"| `{result.get('case_id', 'unknown')}` | {status} | {latency:.1f} ms | "
            f"{', '.join(failed) or '—'} |"
        )


if __name__ == "__main__":
    main()

