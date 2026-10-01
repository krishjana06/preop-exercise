#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=2.0.0", "pydantic>=2.8.0"]
# ///
"""Score existing outputs with the supplied harness, without uploading records."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from run_evals import (
    PRIMARY_SCORE_NAME,
    _build_eval_items,
    _summarize_local_rows,
    load_baseline_outputs,
    load_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/patients_sample_50.jsonl")
    parser.add_argument("--outputs", default="data/baseline_outputs.jsonl")
    parser.add_argument("--report", default="data/eval_report.json")
    args = parser.parse_args()
    cases = load_cases(Path(args.input))
    outputs = load_baseline_outputs(Path(args.outputs))
    _, rows = _build_eval_items(cases, outputs)
    summary = _summarize_local_rows(rows)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "local_eval",
        "primary_score": {
            "name": PRIMARY_SCORE_NAME,
            "value_pct": summary["aggregate_local_score_pct"],
            "goal": "maximize",
        },
        "local_metrics_summary": summary,
        "records": rows,
        "output_items": [],
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Local report written to {path}")


if __name__ == "__main__":
    main()
