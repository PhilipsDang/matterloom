import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from matterloom.parsing import parse_pdf, render_page
from matterloom.server import make_handler
from matterloom.store import MAX_FILE_BYTES, Store

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "samples/purchase/A01_设备买卖合同.pdf"
SCAN = ROOT / "samples/purchase/A03_送货签收单.pdf"
DOCX = ROOT / "samples/purchase/A05_阶段对账单.docx"


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.matter = self.store.create_matter("测试事项")

    def ingest(self, path=PDF, matter=None, name=None):
        return self.store.ingest(matter or self.matter, name or path.name, path.read_bytes(), use_ocr=False)

    def test_pdf_pages_and_text_have_exact_locations(self):
        doc = self.ingest()["document"]
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(doc["page_count"], 2)
        units = self.store.units(self.matter, doc["id"])
        self.assertIn("100,000", units[0]["text"])
        self.assertIn("2026年10月20日", units[1]["text"])
        self.assertEqual([u["page_number"] for u in units], [1,2])

    def test_duplicate_bytes_are_deduplicated_in_same_matter(self):
        first = self.ingest()
        again = self.ingest(name="重命名.pdf")
        self.assertTrue(again["duplicate"])
        self.assertEqual(first["document"]["id"], again["document"]["id"])
        self.assertEqual(len(self.store.documents(self.matter)), 1)

    def test_same_file_can_belong_to_separate_matters(self):
        one = self.ingest()["document"]
        other = self.store.create_matter("第二事项")
        two = self.ingest(matter=other)["document"]
        self.assertNotEqual(one["id"], two["id"])
        with self.assertRaises(LookupError):
            self.store.units(other, one["id"])

    def test_persistence_after_reopening(self):
        doc = self.ingest()["document"]
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.document(self.matter, doc["id"])["status"], "ready")
        self.assertEqual(reopened.original(doc).read_bytes(), PDF.read_bytes())
        self.assertEqual(len(reopened.units(self.matter, doc["id"])), 2)

    def test_corrupt_upload_is_saved_and_failure_is_visible(self):
        result = self.store.ingest(self.matter, "损坏.pdf", b"not a pdf")["document"]
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["error"])
        self.assertEqual(self.store.original(result).read_bytes(), b"not a pdf")
        self.assertEqual(self.ingest()["document"]["status"], "ready")

    def test_docx_keeps_table_coordinates_and_order_without_page_numbers(self):
        doc = self.ingest(DOCX)["document"]
        self.assertEqual(doc["status"], "ready")
        self.assertIsNone(doc["page_count"])
        units = self.store.units(self.matter, doc["id"])
        balance = next(u for u in units if u["text"] == "60,000元")
        self.assertEqual(balance["locator"], "表格 1 · 第 4 行第 2 列")
        self.assertTrue(all(u["page_number"] is None for u in units))
        self.assertGreater(units[-1]["sequence"], balance["sequence"])

    def test_scan_is_image_only_and_warns_without_ocr(self):
        self.assertFalse(PdfReader(SCAN).pages[0].extract_text().strip())
        doc = self.ingest(SCAN)["document"]
        self.assertEqual(doc["status"], "partial")
        self.assertEqual(doc["page_count"], 1)
        self.assertTrue(doc["warnings"])

    def test_ocr_failure_preserves_original_and_marks_page(self):
        with patch("matterloom.parsing.recognize", side_effect=RuntimeError("测试识别失败")):
            result = self.store.ingest(self.matter, SCAN.name, SCAN.read_bytes())["document"]
        self.assertEqual(result["status"], "partial")
        self.assertIn("测试识别失败", result["warnings"][0])
        self.assertTrue(self.store.original(result).is_file())

    def test_ocr_adapter_preserves_method_and_geometry(self):
        # Tests the OCR result contract, not native recognition accuracy.
        with patch("matterloom.parsing.recognize", return_value={"text": "模拟文字", "lines": [{"text": "模拟文字", "bbox": [0,0,1,1]}]}):
            doc = self.store.ingest(self.matter, SCAN.name, SCAN.read_bytes())["document"]
        unit = self.store.units(self.matter, doc["id"])[0]
        self.assertEqual(unit["method"], "ocr")
        self.assertEqual(unit["ocr_lines"][0]["bbox"], [0,0,1,1])

    def test_mixed_pdf_keeps_good_page_and_scanned_page(self):
        mixed = Path(self.temp.name) / "mixed.pdf"
        writer = PdfWriter()
        writer.add_page(PdfReader(PDF).pages[0]); writer.add_page(PdfReader(SCAN).pages[0])
        writer.write(mixed)
        result = parse_pdf(mixed, False)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["units"][0]["status"], "ready")
        self.assertEqual(result["units"][1]["status"], "needs_review")

    def test_encrypted_pdf_is_actionable_failure(self):
        writer = PdfWriter(); writer.add_blank_page(612,792); writer.encrypt("test")
        output = io.BytesIO(); writer.write(output)
        doc = self.store.ingest(self.matter, "加密.pdf", output.getvalue())["document"]
        self.assertEqual(doc["status"], "failed")
        self.assertIn("密码", doc["error"])

    def test_retry_does_not_duplicate_units(self):
        doc = self.ingest()["document"]
        ids = [u["id"] for u in self.store.units(self.matter, doc["id"])]
        self.store.reparse(self.matter, doc["id"], False)
        self.assertEqual([u["id"] for u in self.store.units(self.matter, doc["id"])], ids)

    def test_interrupted_parse_can_be_recovered(self):
        doc = self.ingest()["document"]
        with self.store.db() as db:
            db.execute("UPDATE documents SET status='parsing' WHERE id=?", (doc["id"],))
        self.store.recover_interrupted()
        self.assertEqual(self.store.document(self.matter, doc["id"])["status"], "pending")
        self.assertEqual(self.store.reparse(self.matter, doc["id"], False)["status"], "ready")

    def test_filename_cannot_escape_originals_directory(self):
        doc = self.ingest(name="../../outside.pdf")["document"]
        self.assertEqual(doc["name"], "outside.pdf")
        self.assertEqual(self.store.original(doc).parent, Path(self.temp.name).resolve() / "originals")

    def test_file_limits_and_types(self):
        for name, body in [("a.exe", b"x"), ("empty.pdf", b""), ("huge.pdf", b"x" * (MAX_FILE_BYTES + 1))]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.ingest(self.matter, name, body)

    def test_pdf_page_limit(self):
        writer = PdfWriter()
        for _ in range(101): writer.add_blank_page(612,792)
        output = io.BytesIO(); writer.write(output)
        result = self.store.ingest(self.matter, "过长.pdf", output.getvalue())["document"]
        self.assertEqual(result["status"], "failed")
        self.assertIn("100", result["error"])

    def test_rendered_original_is_png(self):
        self.assertTrue(render_page(PDF, 2).startswith(b"\x89PNG"))
        with self.assertRaises(ValueError): render_page(PDF, 3)


class HTTPContractTests(unittest.TestCase):
    """Exercise real request parsing without opening a listening port."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.handler_class = make_handler(self.store)
        self.matter = self.store.create_matter("接口验证")

    def request(self, method, path, body=b"", headers=None):
        header = {"Host": "127.0.0.1:8501", "X-MatterLoom": "1", "Content-Length": str(len(body))}
        header.update(headers or {})
        request = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k,v in header.items()) + "\r\n"
        handler = self.handler_class.__new__(self.handler_class)
        handler.rfile = io.BytesIO(request.encode() + body); handler.wfile = io.BytesIO()
        handler.server = SimpleNamespace(server_port=8501)
        handler.client_address = ("127.0.0.1", 9999)
        handler.handle_one_request()
        raw_headers, payload = handler.wfile.getvalue().split(b"\r\n\r\n",1)
        return int(raw_headers.split()[1]), payload

    def test_create_and_list_matter(self):
        status, body = self.request("POST", "/api/matters", json.dumps({"name":"新事项"}).encode())
        self.assertEqual(status, 201)
        status, body = self.request("GET", "/api/matters")
        self.assertEqual(len(json.loads(body)["matters"]), 2)

    def test_multipart_upload_and_page_route(self):
        boundary = "fixture-boundary"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="中文.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
                + PDF.read_bytes() + f"\r\n--{boundary}--\r\n".encode())
        status, payload = self.request("POST", f"/api/matters/{self.matter}/documents", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(status, 201)
        doc = json.loads(payload)["document"]
        self.assertEqual(doc["name"], "中文.pdf")
        status, payload = self.request("GET", f"/api/matters/{self.matter}/documents/{doc['id']}/pages/2")
        self.assertEqual(status, 200); self.assertTrue(payload.startswith(b"\x89PNG"))

    def test_cross_matter_route_is_rejected(self):
        doc = self.store.ingest(self.matter, PDF.name, PDF.read_bytes(), False)["document"]
        other = self.store.create_matter("其他事项")
        status, _ = self.request("GET", f"/api/matters/{other}/documents/{doc['id']}/original")
        self.assertEqual(status, 404)

    def test_cross_origin_and_missing_request_marker_are_rejected(self):
        for headers in [{"Origin":"https://example.org"}, {"X-MatterLoom":""}, {"Host":"example.org"}]:
            status, _ = self.request("POST", "/api/matters", b'{"name":"test"}', headers)
            self.assertEqual(status, 403)

    def test_static_assets_and_traversal(self):
        for path in ["/", "/style.css", "/app.js", "/mark.svg"]:
            self.assertEqual(self.request("GET", path)[0], 200)
        self.assertEqual(self.request("GET", "/../requirements.txt")[0], 404)


if __name__ == "__main__":
    unittest.main()
