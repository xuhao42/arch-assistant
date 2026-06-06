#!/usr/bin/env python3
"""Batch-test architecture recommendations against data/test_scenarios.json.

The local services must be running before this script is executed.
Progress is written to test_progress.json, and final results are written to
test_results.json.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API = "http://localhost:8001/api/v1/analyze"
TEST_FILE = ROOT / "data" / "test_scenarios.json"
PROGRESS_FILE = ROOT / "test_progress.json"
RESULT_FILE = ROOT / "test_results.json"


with TEST_FILE.open(encoding="utf-8") as f:
    scenarios = json.load(f)

results = []
passed = 0
failed = 0


def save_progress() -> None:
    PROGRESS_FILE.write_text(
        json.dumps(
            {
                "current": len(results),
                "total": len(scenarios),
                "passed": passed,
                "failed": failed,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


save_progress()

for scenario in scenarios:
    sid = scenario["id"]
    desc = scenario["description"]
    expected = scenario.get("primary_recommendation", "")

    t0 = time.perf_counter()
    payload = json.dumps({"prompt": desc, "session_id": f"batch_{sid}"}, ensure_ascii=False)
    proc = subprocess.run(
        [
            "curl",
            "-s",
            "--max-time",
            "180",
            "-X",
            "POST",
            API,
            "-H",
            "Content-Type: application/json",
            "-d",
            payload,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=200,
    )
    elapsed = round((time.perf_counter() - t0) * 1000)

    if proc.returncode != 0:
        results.append(
            {
                "id": sid,
                "desc": desc[:60],
                "expected": expected,
                "top": "ERROR",
                "hit": False,
                "elapsed": elapsed,
                "error": proc.stderr[:200],
            }
        )
        failed += 1
        print(f"[{sid}/{len(scenarios)}] ERROR ({elapsed}ms)")
        save_progress()
        continue

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        results.append(
            {
                "id": sid,
                "desc": desc[:60],
                "expected": expected,
                "top": "PARSE_ERR",
                "hit": False,
                "elapsed": elapsed,
                "response": proc.stdout[:200],
            }
        )
        failed += 1
        print(f"[{sid}/{len(scenarios)}] PARSE_ERR ({elapsed}ms)")
        save_progress()
        continue

    candidates = data.get("candidates") or []
    top_name = candidates[0]["name"] if candidates else "N/A"
    names = [candidate["name"] for candidate in candidates[:3]]
    hit = any(expected in name for name in names)

    if not hit:
        alias_map = {
            "CQRS": ["CQRS"],
            "SOA": ["SOA"],
            "MVC": ["MVC", "Model-View-Controller"],
            "P2P": ["P2P", "对等", "Peer"],
            "Serverless": ["Serverless", "无服务器"],
            "Space-Based": ["Space-Based", "空间架构", "SBA"],
        }
        for key, aliases in alias_map.items():
            if key in expected:
                hit = any(any(alias.lower() in name.lower() for alias in aliases) for name in names)
                break

    if hit:
        passed += 1
        marker = "PASS"
    else:
        failed += 1
        marker = "FAIL"

    results.append(
        {
            "id": sid,
            "desc": desc[:60],
            "expected": expected,
            "top": top_name,
            "candidates": names,
            "hit": hit,
            "elapsed": elapsed,
        }
    )
    print(f"[{sid}/{len(scenarios)}] {marker}: {top_name} ({elapsed}ms)")
    save_progress()

summary = {
    "passed": passed,
    "failed": failed,
    "total": len(scenarios),
    "accuracy": f"{passed}/{len(scenarios)} ({100 * passed / len(scenarios):.1f}%)",
}
RESULT_FILE.write_text(
    json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"DONE: {summary['accuracy']}")
