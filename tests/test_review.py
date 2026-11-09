import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from matterloom import extraction as ex
from matterloom.parsing import parse_pdf
from matterloom.review import ConflictError, Review
from matterloom.store import Store
import test_core as core

PDF, DOCX, SCAN = core.PDF, core.DOCX, core.SCAN


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name); self.review = Review(self.store)
        self.matter = self.store.create_matter("审核测试")
        self.doc = self.store.ingest(self.matter, PDF.name, PDF.read_bytes(), False)["document"]

    def extract(self):
        return self.review.extract(self.matter, self.doc["id"])

    def facts(self):
        return self.review.facts(self.matter)["facts"]

    def edit(self, fact, **changes):
        data = {**fact["current"], "version": fact["version"], "status": fact["status"], "reviewer_note": fact["reviewer_note"]}
        data.update(changes)
        return self.review.edit(self.matter, fact["id"], data)

    def candidate(self):
        unit = self.store.units(self.matter, self.doc["id"])[0]
        return {"kind":"amount", "label":"合同总价", "value":"合同写明总价为人民币100,000元。", "normalized_value":"CNY 100000",
                "uncertainty":"", "evidence":[{"unit_id":unit["id"], "quote":"合同总价人民币100,000元"}]}

    def test_local_facts_have_sources_and_never_confirm_themselves(self):
        self.extract(); facts = self.facts()
        self.assertTrue(facts)
        self.assertTrue(all(f["status"] == "pending" and not f["eligible"] and f["source_valid"] for f in facts))
        total = next(f for f in facts if f["current"]["normalized_value"] == "CNY 100000")
        self.assertEqual(total["evidence"][0]["page_number"], 1)
        self.assertEqual(total["evidence"][0]["document_name"], PDF.name)
        self.assertTrue(any(f["current"]["normalized_value"] == "2026-10-20" for f in facts))
        self.assertTrue(any(f["current"]["value"] == "陈砚" for f in facts))

    def test_edit_confirm_history_persist_and_repeat_extraction_preserves_edits(self):
        self.extract(); original = self.facts()[0]
        edited = self.edit(original, value="经核对后的记录", status="confirmed", reviewer_note="已核对原文")
        result = self.extract()
        saved = next(f for f in Review(Store(self.temp.name)).facts(self.matter)["facts"] if f["id"] == original["id"])
        self.assertEqual(result["added"], 0)
        self.assertTrue(saved["eligible"])
        self.assertEqual(saved["current"]["value"], "经核对后的记录")
        self.assertEqual(saved["original"], original["original"])
        self.assertEqual(saved["version"], edited["version"])
        history = self.review.history(self.matter, saved["id"])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["before"]["current"], original["current"])

    def test_uncertainty_exclusion_and_restoration_are_audited(self):
        self.extract(); fact = self.facts()[0]
        fact = self.edit(fact, status="uncertain", reviewer_note="归属需补证")
        fact = self.edit(fact, status="excluded")
        self.assertFalse(fact["eligible"])
        self.extract()
        fact = next(f for f in self.facts() if f["id"] == fact["id"])
        self.assertEqual(fact["status"], "excluded")
        restored = self.edit(fact, status="pending")
        self.assertEqual(restored["status"], "pending")
        self.assertEqual(len(self.review.history(self.matter, fact["id"])), 4)

    def test_stale_editor_cannot_overwrite_newer_review(self):
        self.extract(); fact = self.facts()[0]
        self.edit(fact, value="第一次编辑")
        with self.assertRaises(ConflictError): self.edit(fact, value="过期编辑")
        self.assertEqual(next(f for f in self.facts() if f["id"] == fact["id"])["current"]["value"], "第一次编辑")

    def test_manual_add_rejects_foreign_sources_and_fabricated_quotes(self):
        data = self.candidate()
        fact = self.review.add(self.matter, data)["fact"]
        self.assertEqual(fact["status"], "pending")
        self.assertFalse(self.review.add(self.matter, data)["added"])
        other = self.store.create_matter("无权引用")
        with self.assertRaises(ValueError): self.review.add(other, data)
        data["evidence"][0]["quote"] = "双方已确认最终责任"
        with self.assertRaises(ValueError): self.review.add(self.matter, data)

    def test_schema_rejects_extra_fields_invalid_date_and_empty_evidence(self):
        for changes in [{"status":"confirmed"}, {"evidence":[]}, {"kind":"legal_conclusion"}, {"value":42},
                        {"kind":"date","normalized_value":"2026-02-30"}, {"label":"  "}, {"normalized_value":"10,000"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.review.add(self.matter, {**self.candidate(), **changes})

    def test_docx_fact_keeps_table_cell_and_no_fake_page(self):
        doc = self.store.ingest(self.matter, DOCX.name, DOCX.read_bytes(), False)["document"]
        self.review.extract(self.matter, doc["id"])
        fact = next(f for f in self.facts() if f["current"]["normalized_value"] == "CNY 60000")
        self.assertIsNone(fact["evidence"][0]["page_number"])
        self.assertIn("第 4 行第 2 列", fact["evidence"][0]["locator"])

    def test_unreadable_scan_never_succeeds_with_empty_facts(self):
        scan = self.store.ingest(self.matter, SCAN.name, SCAN.read_bytes(), False)["document"]
        with self.assertRaisesRegex(ValueError, "OCR"): self.review.extract(self.matter, scan["id"])
        self.assertFalse(self.facts())
        self.assertEqual(self.review.facts(self.matter)["runs"][0]["status"], "failed")

    def test_stage_one_database_upgrade_keeps_existing_documents_and_originals(self):
        # Remove only the new empty tables to reproduce a v0.1 database.
        with self.store.db() as db:
            db.execute("DROP TABLE fact_history")
            db.execute("DROP TABLE facts")
            db.execute("DROP TABLE extraction_runs")
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.original(self.doc).read_bytes(), PDF.read_bytes())
        self.assertEqual(len(reopened.units(self.matter, self.doc["id"])), 2)
        self.assertGreater(Review(reopened).extract(self.matter, self.doc["id"])["added"], 0)

    def test_partial_document_only_extracts_available_units_and_records_warning(self):
        result = parse_pdf(self.store.original(self.doc), False)
        result["status"] = "partial"
        result["units"][1]["text"] = ""
        result["units"][1]["status"] = "needs_review"
        with patch("matterloom.parsing.parse", return_value=result): self.store.reparse(self.matter, self.doc["id"], False)
        extracted = self.extract()
        self.assertEqual(extracted["status"], "partial")
        self.assertEqual(extracted["details"]["empty_units"], 1)
        self.assertTrue(all(e["page_number"] == 1 for f in self.facts() for e in f["evidence"]))

    def test_reparse_identical_text_retains_confirmation(self):
        self.extract(); fact = self.edit(self.facts()[0], status="confirmed")
        self.store.reparse(self.matter, self.doc["id"], False)
        saved = next(f for f in self.facts() if f["id"] == fact["id"])
        self.assertTrue(saved["eligible"])
        self.assertEqual(saved["version"], fact["version"])

    def test_reparse_changed_text_invalidates_confirmation_and_keeps_snapshot(self):
        self.extract()
        fact = next(f for f in self.facts() if f["current"]["normalized_value"] == "CNY 100000")
        fact = self.edit(fact, status="confirmed")
        result = parse_pdf(self.store.original(self.doc), False)
        result["units"][0]["text"] = result["units"][0]["text"].replace("100,000", "110,000")
        with patch("matterloom.parsing.parse", return_value=result): self.store.reparse(self.matter, self.doc["id"], False)
        saved = next(f for f in self.facts() if f["id"] == fact["id"])
        self.assertEqual(saved["status"], "uncertain")
        self.assertFalse(saved["source_valid"])
        self.assertEqual(saved["evidence"], fact["evidence"])
        self.assertEqual(self.review.history(self.matter, saved["id"])[0]["action"], "source_changed")
        with self.assertRaises(ValueError): self.edit(saved, status="confirmed")
        self.extract()
        self.assertTrue(any(f["current"]["normalized_value"] == "CNY 110000" for f in self.facts()))

    def test_failed_reparse_removes_confirmed_eligibility(self):
        self.extract(); fact = self.edit(self.facts()[0], status="confirmed")
        with patch("matterloom.parsing.parse", side_effect=ValueError("无法解析")):
            self.store.reparse(self.matter, self.doc["id"], False)
        saved = next(f for f in self.facts() if f["id"] == fact["id"])
        self.assertEqual(saved["status"], "uncertain"); self.assertFalse(saved["eligible"])

    def test_cross_matter_list_edit_history_and_extraction_are_isolated(self):
        self.extract(); fact = self.facts()[0]; other = self.store.create_matter("其他事项")
        self.assertFalse(self.review.facts(other)["facts"])
        with self.assertRaises(LookupError): self.review.history(other, fact["id"])
        with self.assertRaises(LookupError): self.review.extract(other, self.doc["id"])
        with self.assertRaises(LookupError): self.review.edit(other, fact["id"], {**fact["current"],"version":1,"status":"confirmed"})

    def test_local_mode_never_calls_model_and_glm_requires_explicit_consent(self):
        with patch("matterloom.extraction.call_glm") as call:
            self.extract()
            with self.assertRaises(ValueError): self.review.extract(self.matter, self.doc["id"], "glm")
            call.assert_not_called()

    @patch.dict("os.environ", {"GLM_API_KEY":"test-only-key", "MATTERLOOM_GLM_MODEL":"test-model"})
    def test_model_validation_rejects_bad_quotes_and_status_injection(self):
        valid = self.candidate(); invalid = copy.deepcopy(valid); invalid["evidence"][0]["quote"] = "凭空出现的句子"
        with patch("matterloom.extraction.call_glm", return_value=(json.dumps({"facts":[valid,invalid,{**valid,"status":"confirmed"}]}), "returned-model")):
            result = self.review.extract(self.matter, self.doc["id"], "glm", True)
        self.assertEqual(result["status"], "partial"); self.assertEqual(result["details"]["rejected"], 2)
        self.assertEqual(result["details"]["models"], ["returned-model"])
        self.assertEqual(len(self.facts()), 1); self.assertEqual(self.facts()[0]["status"], "pending")

    @patch.dict("os.environ", {"GLM_API_KEY":"test-only-key", "MATTERLOOM_GLM_MODEL":"test-model"})
    def test_malformed_model_response_records_failure_and_preserves_reviews(self):
        self.extract(); before = self.edit(self.facts()[0], status="confirmed")
        with patch("matterloom.extraction.call_glm", return_value=("not JSON", "test-model")):
            with self.assertRaises(ValueError): self.review.extract(self.matter, self.doc["id"], "glm", True)
        self.assertEqual(self.review.facts(self.matter)["runs"][0]["status"], "failed")
        self.assertTrue(next(f for f in self.facts() if f["id"] == before["id"])["eligible"])

    def test_source_change_while_extracting_aborts_transaction(self):
        original = ex.local_candidates
        def change(units):
            with self.store.db() as db:
                db.execute("UPDATE units SET text=text || '更新' WHERE document_id=?", (self.doc["id"],))
            return original(units)
        with patch("matterloom.extraction.local_candidates", side_effect=change):
            with self.assertRaisesRegex(ValueError, "原文发生变化"): self.extract()
        self.assertFalse(self.facts())
        self.assertEqual(self.review.facts(self.matter)["runs"][0]["status"], "failed")

    def test_overlapping_extraction_is_blocked_and_interrupted_run_recoverable(self):
        def overlap(units):
            with self.assertRaises(ConflictError): self.extract()
            return []
        with patch("matterloom.extraction.local_candidates", side_effect=overlap): self.extract()
        with self.store.db() as db: db.execute("UPDATE extraction_runs SET status='running'")
        self.store.recover_interrupted()
        self.assertEqual(self.review.facts(self.matter)["runs"][0]["status"], "failed")
        self.assertGreater(self.extract()["added"], 0)


class ExtractionUnitTests(unittest.TestCase):
    def test_relative_dates_invalid_dates_and_requests_are_not_invented_facts(self):
        units = [{"id":"unit", "text":"约定收到通知后十日付款。拟于10月18日交接。日期记为2026年2月30日。买方提出减价人民币1万元，卖方尚未同意。"}]
        facts = ex.local_candidates(units)
        dates = [f for f in facts if f.kind == "date"]
        self.assertEqual(len(dates), 3)
        self.assertTrue(all(f.normalized_value is None for f in dates))
        self.assertTrue(any(f.kind == "amount" and f.normalized_value == "CNY 10000" for f in facts))
        claims = [f for f in facts if f.kind == "claim"]
        self.assertIn("尚未同意", claims[0].value)

    def test_pdf_line_wrap_keeps_amount_and_negation_with_exact_quote(self):
        source = "2026年10月12日，买方代表提出：其中10件设备运行不稳定，希望减少价款人民币10,000\n元，但卖方未确认减价。"
        facts = ex.local_candidates([{"id":"source", "text":source}])
        amount = next(f for f in facts if f.kind == "amount")
        self.assertEqual(amount.normalized_value, "CNY 10000")
        self.assertIn(amount.evidence[0].quote, source)
        self.assertIn("未确认", next(f.value for f in facts if f.kind == "claim"))

    def test_chunking_covers_long_sources_and_rejects_budget_overflow(self):
        text = "甲"*5001 + "结束日期2026年10月20日。"
        chunks = ex.chunks([{"id":"a", "text":text}])
        self.assertTrue(any("2026年10月20日" in unit["text"] for batch in chunks for unit in batch))
        self.assertTrue(all(unit["text"] in text for batch in chunks for unit in batch))
        with self.assertRaises(ValueError): ex.chunks([{"id":"a","text":"长"*150000}])

    @patch.dict("os.environ", {"GLM_API_KEY":"test-only-key", "MATTERLOOM_GLM_MODEL":"configured-model"})
    def test_glm_transport_has_fixed_endpoint_timeout_and_rejects_truncation(self):
        with patch("matterloom.extraction.build_opener") as build:
            opener = build.return_value
            raw = {"model":"provider-model", "choices":[{"finish_reason":"stop", "message":{"content":'{"facts":[]}'}}]}
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(raw).encode()
            content, model = ex.call_glm([{"unit_id":"a", "text":"模拟内容"}])
            self.assertEqual(model, "provider-model")
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, ex.ENDPOINT)
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 90)
            payload = json.loads(request.data)
            self.assertEqual(payload["response_format"], {"type":"json_object"})
            self.assertNotIn("tools", payload)
            raw["choices"][0]["finish_reason"] = "length"
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(raw).encode()
            with self.assertRaisesRegex(ValueError, "未完整"): ex.call_glm([])

    @patch.dict("os.environ", {"GLM_API_KEY":"never-echo-this", "MATTERLOOM_GLM_MODEL":"test-model"})
    def test_transport_error_does_not_expose_key_or_provider_response(self):
        for error in [HTTPError(ex.ENDPOINT, 401, "never-echo-this", {}, io.BytesIO(b"sensitive")), URLError("never-echo-this")]:
            with patch("matterloom.extraction.build_opener") as build:
                build.return_value.open.side_effect = error
                with self.assertRaises(ValueError) as caught: ex.call_glm([])
                self.assertNotIn("never-echo-this", str(caught.exception))
                self.assertNotIn("sensitive", str(caught.exception))


# Reuse the raw-HTTP helper without re-running the stage-one test methods.
class ReviewHTTPTests(unittest.TestCase):
    setUp = core.HTTPContractTests.setUp
    request = core.HTTPContractTests.request

    def test_extract_review_conflict_and_history_routes(self):
        doc = self.store.ingest(self.matter, PDF.name, PDF.read_bytes(), False)["document"]
        status, body = self.request("POST", f"/api/matters/{self.matter}/documents/{doc['id']}/extract", b'{"mode":"local"}')
        self.assertEqual(status, 200)
        base = f"/api/matters/{self.matter}/facts"
        status, body = self.request("GET", base)
        fact = json.loads(body)["facts"][0]
        edit = json.dumps({**fact["current"],"version":fact["version"],"status":"confirmed"}).encode()
        self.assertEqual(self.request("POST", base+"/"+fact["id"], edit)[0], 200)
        self.assertEqual(self.request("POST", base+"/"+fact["id"], edit)[0], 409)
        status, body = self.request("GET", base+"/"+fact["id"]+"/history")
        self.assertEqual(status, 200); self.assertEqual(len(json.loads(body)["history"]), 2)
        other = self.store.create_matter("other")
        self.assertEqual(self.request("GET",f"/api/matters/{other}/facts/{fact['id']}/history")[0], 404)

    def test_model_no_consent_and_invalid_schema_return_actionable_errors(self):
        doc = self.store.ingest(self.matter, PDF.name, PDF.read_bytes(), False)["document"]
        with patch("matterloom.extraction.call_glm") as call:
            status, body = self.request("POST", f"/api/matters/{self.matter}/documents/{doc['id']}/extract", b'{"mode":"glm"}')
            self.assertEqual(status, 400); self.assertIn("同意", json.loads(body)["error"]); call.assert_not_called()
        self.assertEqual(self.request("POST",f"/api/matters/{self.matter}/facts", b'{}')[0], 400)
        self.assertEqual(self.request("GET", "/review.js")[0], 200)


if __name__ == "__main__":
    unittest.main()
