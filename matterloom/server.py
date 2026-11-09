"""Loopback-only development server. No cloud services or API keys required."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

from .parsing import ocr_available, render_page
from .store import MAX_FILE_BYTES, Store
from .review import ConflictError, Review

ROOT = Path(__file__).resolve().parents[1]


def make_handler(store):
    review = Review(store)
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data, kind="application/json; charset=utf-8", filename=None):
            payload = json.dumps(data, ensure_ascii=False).encode() if kind.startswith("application/json") else data
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
            self.end_headers()
            self.wfile.write(payload)

        def body(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_FILE_BYTES + 1024 * 1024:
                raise ValueError("请求为空或超过 20 MB 文件限制。")
            return self.rfile.read(length)

        def json_body(self):
            data = json.loads(self.body())
            if not isinstance(data, dict):
                raise ValueError("请求格式错误。")
            return data

        def dispatch(self, method):
            # No remote bind, no cross-origin writes, no arbitrary file serving.
            host = self.headers.get("Host", "").split(":")[0]
            if host not in {"127.0.0.1", "localhost"}:
                return self.reply(403, {"error": "仅允许本机访问。"})
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.reply(403, {"error": "请求来源不匹配。"})
            if method == "POST" and self.headers.get("X-MatterLoom") != "1":
                return self.reply(403, {"error": "请求校验失败。"})
            path = urlsplit(self.path).path
            if method == "GET" and path in {"/", "/app.js", "/review.js", "/style.css", "/mark.svg"}:
                asset = ROOT / "web" / ("index.html" if path == "/" else path[1:])
                return self.reply(200, asset.read_bytes(), mimetypes.guess_type(str(asset))[0] or "text/plain")
            if method == "GET" and path == "/api/matters":
                return self.reply(200, {"matters": store.matters(), "ocr_available": ocr_available()})
            if method == "POST" and path == "/api/matters":
                data = self.json_body()
                matter_id = store.create_matter(data.get("name", ""), data.get("description", ""))
                return self.reply(201, {"id": matter_id})
            if method == "GET" and path == "/api/samples":
                manifest = json.loads((ROOT / "samples/manifest.json").read_text())
                return self.reply(200, manifest)
            if method == "POST" and path == "/api/samples/import":
                data = self.json_body()
                manifest = json.loads((ROOT / "samples/manifest.json").read_text())
                case = next((c for c in manifest["matters"] if c["key"] == data.get("key")), None)
                if not case:
                    raise LookupError("模拟事项不存在。")
                matter_id = store.create_matter(case["name"], case["description"], case["key"])
                # Return the matter immediately; import each document separately for progress.
                return self.reply(200, {"id": matter_id, "files": case["files"]})
            sample_match = re.fullmatch(r"/api/matters/([a-f0-9]{32})/sample", path)
            if method == "POST" and sample_match:
                data = self.json_body()
                matter = store.matter(sample_match[1])
                manifest = json.loads((ROOT / "samples/manifest.json").read_text())
                case = next((c for c in manifest["matters"] if c["key"] == matter["sample_key"]), None)
                item = next((f for f in case["files"] if f["name"] == data.get("name")), None) if case else None
                if not item:
                    raise LookupError("模拟文件不存在。")
                sample = ROOT / "samples" / case["key"] / item["name"]
                return self.reply(200, store.ingest(matter["id"], item["name"], sample.read_bytes(), data.get("ocr", True) is True))
            fact_match = re.fullmatch(r"/api/matters/([a-f0-9]{32})/facts(?:/([a-f0-9]{32})(?:/(history))?)?", path)
            if fact_match:
                matter_id, fact_id, action = fact_match.groups()
                if not fact_id:
                    if method == "GET":
                        return self.reply(200, review.facts(matter_id))
                    return self.reply(201, review.add(matter_id, self.json_body()))
                if action == "history" and method == "GET":
                    return self.reply(200, {"history": review.history(matter_id, fact_id)})
                if not action and method == "POST":
                    return self.reply(200, {"fact": review.edit(matter_id, fact_id, self.json_body())})
                raise LookupError("页面不存在。")
            match = re.fullmatch(r"/api/matters/([a-f0-9]{32})/documents(?:/([a-f0-9]{32})(?:/(units|original|parse|extract|pages/[0-9]+))?)?", path)
            if not match:
                raise LookupError("页面不存在。")
            matter_id, doc_id, action = match.groups()
            if not doc_id:
                if method == "GET":
                    return self.reply(200, {"matter": store.matter(matter_id), "documents": store.documents(matter_id)})
                content_type = self.headers.get("Content-Type", "")
                if not content_type.startswith("multipart/form-data"):
                    raise ValueError("请使用文件上传。")
                message = BytesParser(policy=policy.default).parsebytes(
                    f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + self.body())
                file = None
                use_ocr = True
                for part in message.iter_parts():
                    if part.get_param("name", header="content-disposition") == "file":
                        file = part
                    if part.get_param("name", header="content-disposition") == "ocr":
                        use_ocr = part.get_payload(decode=True) == b"true"
                if file is None:
                    raise ValueError("没有收到文件。")
                return self.reply(201, store.ingest(matter_id, file.get_filename(), file.get_payload(decode=True), use_ocr))
            document = store.document(matter_id, doc_id)
            if method == "GET" and action == "units":
                return self.reply(200, {"document": document, "units": store.units(matter_id, doc_id)})
            if method == "GET" and action == "original":
                return self.reply(200, store.original(document).read_bytes(), "application/octet-stream", document["name"])
            if method == "GET" and action and action.startswith("pages/"):
                if document["kind"] != "pdf":
                    raise ValueError("Word 文档按段落定位，不提供虚构页码。")
                return self.reply(200, render_page(store.original(document), int(action.split("/")[1])), "image/png")
            if method == "POST" and action == "parse":
                return self.reply(200, store.reparse(matter_id, doc_id, self.json_body().get("ocr", True) is True))
            if method == "POST" and action == "extract":
                data = self.json_body()
                return self.reply(200, review.extract(matter_id, doc_id, data.get("mode", "local"), data.get("allow_external", False)))
            raise LookupError("页面不存在。")

        def handle_request(self, method):
            try:
                self.dispatch(method)
            except LookupError as exc:
                self.reply(404, {"error": str(exc)})
            except ConflictError as exc:
                self.reply(409, {"error": str(exc)})
            except (ValueError, json.JSONDecodeError) as exc:
                self.reply(400, {"error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.reply(500, {"error": "操作未完成。请刷新后重试；原始文件如已保存仍会保留。"})

        def do_GET(self):
            self.handle_request("GET")

        def do_POST(self):
            self.handle_request("POST")

        def log_message(self, format, *args):
            # Do not write filenames, documents or request bodies into logs.
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description="MatterLoom local workspace")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--data-dir", default=os.environ.get("MATTERLOOM_DATA_DIR", str(ROOT / "data")))
    args = parser.parse_args()
    store = Store(args.data_dir)
    store.recover_interrupted()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store))
    except PermissionError:
        raise SystemExit("当前运行环境不允许开启本地网页服务。请在自己的终端运行 sh run.sh。")
    except OSError as exc:
        raise SystemExit(f"无法启动本地服务（端口 {args.port}）。若端口已占用，请运行 sh run.sh --port 8502。\n{exc}")
    print(f"MatterLoom is running at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
