"""Download small public legal-dataset samples on a GitHub-hosted runner.

No files are downloaded to the user's computer. Output is JSONL plus provenance
metadata and is intended as a reproducible development/evaluation starter pack.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from datasets import load_dataset

MANIFEST = Path("datasets/manifest.json")
OUT_DIR = Path("datasets/generated")
ROWS = max(1, int(os.getenv("ROWS_PER_DATASET", "10")))
SPLIT = os.getenv("DATASET_SPLIT", "train")
MAX_CHARS = max(200, int(os.getenv("MAX_FIELD_CHARS", "3000")))


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._") or "dataset"


def clean(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_CHARS]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in list(value.items())[:80]}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value[:80]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_CHARS]


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, Any]] = []
    failures = 0

    for item in manifest["datasets"]:
        name = item["name"]
        output = OUT_DIR / f"{safe_name(name)}.jsonl"
        print(f"Loading {name} ({item['id']})", flush=True)
        result: dict[str, Any] = {
            "name": name,
            "dataset_id": item["id"],
            "config": item.get("config"),
            "source": item["source"],
            "license_note": item["license_note"],
            "requested_rows": ROWS,
            "split": SPLIT,
            "status": "failed",
            "rows_written": 0,
            "output_file": output.name,
        }
        try:
            kwargs: dict[str, Any] = {"split": SPLIT, "streaming": True}
            if item.get("config"):
                ds = load_dataset(item["id"], item["config"], **kwargs)
            else:
                ds = load_dataset(item["id"], **kwargs)
            with output.open("w", encoding="utf-8") as stream:
                for index, row in enumerate(ds):
                    if index >= ROWS:
                        break
                    record = {
                        "dataset_name": name,
                        "dataset_id": item["id"],
                        "source": item["source"],
                        "license_note": item["license_note"],
                        "sample_index": index,
                        "data": clean(dict(row)),
                    }
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    result["rows_written"] += 1
            if result["rows_written"] == 0:
                raise RuntimeError(f"No rows returned for split {SPLIT!r}")
            result["status"] = "ok"
            print(f"  wrote {result['rows_written']} rows", flush=True)
        except Exception as exc:
            failures += 1
            result["error"] = f"{type(exc).__name__}: {str(exc)[:700]}"
            output.unlink(missing_ok=True)
            print(f"  FAILED: {result['error']}", file=sys.stderr, flush=True)
        report.append(result)

    report_path = OUT_DIR / "download_report.json"
    report_path.write_text(json.dumps({
        "note": "Samples are not a substitute for checking each dataset's current license and source terms.",
        "requested_rows_per_dataset": ROWS,
        "successful_datasets": sum(r["status"] == "ok" for r in report),
        "failed_datasets": failures,
        "results": report,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Report saved to {report_path}")
    print(f"Completed: {len(report) - failures}/{len(report)} datasets")
    # Keep the report/artifact even if one source is temporarily unavailable.
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
