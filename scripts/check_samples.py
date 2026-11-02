"""Run the real ingestion path against all samples in a temporary workspace."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from matterloom.store import Store

manifest = json.loads((ROOT / "samples/manifest.json").read_text())
results = []
with tempfile.TemporaryDirectory(prefix="matterloom-check-") as folder:
    store = Store(folder)
    for case in manifest["matters"]:
        matter_id = store.create_matter(case["name"])
        for item in case["files"]:
            path = ROOT / "samples" / case["key"] / item["name"]
            doc = store.ingest(matter_id, item["name"], path.read_bytes())["document"]
            record = {"id": item["id"], "status": doc["status"], "pages": doc["page_count"],
                      "units": len(store.units(matter_id, doc["id"])), "warnings": doc["warnings"], "error": doc["error"]}
            results.append(record)
            print(f"{item['id']}: {record['status']}, {record['units']} source units")
report = {"total": len(results), "ready": sum(r["status"] == "ready" for r in results),
          "partial": sum(r["status"] == "partial" for r in results),
          "failed": sum(r["status"] == "failed" for r in results), "files": results}
destination = ROOT / "work/sample-check.json"
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(f"Result: {report['ready']} ready, {report['partial']} partial, {report['failed']} failed")
sys.exit(1 if report["failed"] else 0)
