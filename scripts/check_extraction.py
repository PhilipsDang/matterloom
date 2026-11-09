"""Check stage-two sample coverage without sending any data to a model service."""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from matterloom.review import Review
from matterloom.store import Store

# These are literal mention probes, not semantic accuracy labels or prompts.
# Both the rules and optional model adapter are independent of this evaluation.
PROBES = {
    "purchase": [("A01", "CNY 100000"), ("A01", "2026-10-20"), ("A04", "CNY 10000"),
                 ("A05", "CNY 60000"), ("A06", "CNY 40000"), ("A06", "CNY 20000")],
    "employment": [("B01", "CNY 8000"), ("B04", "CNY 7600"), ("B04", "CNY 700"),
                   ("B05", "CNY 6900"), ("B06", "2026-10-15")],
}


def main():
    manifest = json.loads((ROOT / "samples/manifest.json").read_text())
    report = {"mode":"local", "ocr":False, "meaning":"Operational checks and literal mention probes; not precision, recall, legal correctness, or lawyer feedback.", "matters":[]}
    with tempfile.TemporaryDirectory() as temporary:
        store = Store(temporary); review = Review(store)
        for case in manifest["matters"]:
            matter_id = store.create_matter(case["name"])
            rows = []
            for item in case["files"]:
                path = ROOT / "samples" / case["key"] / item["name"]
                doc = store.ingest(matter_id, path.name, path.read_bytes(), False)["document"]
                try:
                    result = review.extract(matter_id, doc["id"])
                    rows.append({"file":path.name,"status":result["status"],"candidates":result["added"]})
                    repeated = review.extract(matter_id, doc["id"])
                    assert repeated["added"] == 0, "Repeated extraction duplicated candidates"
                except ValueError as exc:
                    rows.append({"file":path.name,"status":"unavailable","reason":str(exc)})
            facts = review.facts(matter_id)["facts"]
            assert facts and all(f["source_valid"] and f["status"] == "pending" for f in facts)
            probes = [{"file_prefix":prefix,"normalized_value":value,"found":any(
                f["current"]["normalized_value"] == value and f["evidence"][0]["document_name"].startswith(prefix) for f in facts)}
                for prefix,value in PROBES[case["key"]]]
            report["matters"].append({"key":case["key"],"files":rows,"candidate_count":len(facts),
                "kinds":dict(Counter(f["current"]["kind"] for f in facts)),"all_quotes_located":True,
                "all_pending":True,"rerun_added_zero":True,"literal_probes":probes})
    output = ROOT / "work/stage2/extraction-check.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not all(probe["found"] for case in report["matters"] for probe in case["literal_probes"]):
        raise SystemExit("Some literal probes were missed; inspect the report.")


if __name__ == "__main__":
    main()
