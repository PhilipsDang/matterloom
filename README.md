# MatterLoom | 律脉

**Trace the facts. Build lasting legal knowledge.**

MatterLoom is a local workspace for organizing Chinese legal matter documents. This first-stage prototype supports matter creation, multiple-file uploads, original-file storage, parsing status, page-by-page PDF viewing, and paragraph or table-cell references for DOCX files.

## Project status

Version: **0.1.0**. This is a single-user development prototype.

- Implemented: browser interface, upload endpoints, SQLite persistence, document parsing, and PDF page rendering.
- Included: **16 fictional sample documents** across two matters: 11 PDFs, including two image-only scans, and five DOCX files.
- Verification: **22 automated data and HTTP-handler tests passed** during implementation. Real browser end-to-end operation has not yet been verified.
- Sample ingestion: 14 documents completed text extraction; two scans retained their original pages and reported that OCR needed attention. These counts are parsing outcomes, not extraction-accuracy scores.
- OCR: the optional Apple Vision helper compiled, but actual recognition failed in the implementation environment. Chinese OCR is not yet verified.
- The initial implementation environment blocked local server startup. A local Git repository has since been initialized in the original workspace; the downloadable archive does not include Git metadata.

Structured fact review, cross-document question answering, timelines, calendar export, and fact-summary drafting remain planned features.

## Quick start from the download

Use **Python 3.12**. The commands below target macOS or a Unix-like shell. Install dependencies with network access, then run the application locally:

```sh
cd MatterLoom
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
sh run.sh
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Use the sample collection button, labeled **查看模拟案卷**, to import either fictional matter.

Press **Control-C** in the server terminal to stop the application. If port 8501 is already in use:

```sh
sh run.sh --port 8502
```

To initialize version control in an extracted copy, optionally run `git init -b main`. This is not required to start the application.

### Using the existing development workspace

The original workspace already contains a `.venv` that uses the bundled Codex Python packages. From that project directory, run `sh run.sh` without reinstalling dependencies. This environment is machine-specific and is not included in the download.

After dependencies are installed, macOS users can also double-click `启动律脉.command` to start the server. This launcher does not initialize Git.

## What the prototype does

1. Create a matter or import a sample matter.
2. Select multiple PDF/DOCX files or drag them into the upload area. Each file is limited to 20 MB; each PDF is limited to 100 pages.
3. Check each document's parsing status: complete, needs review, failed, or pending.
4. Select a PDF and compare the original page image with the extracted text. Page references use the PDF file's page order, which may differ from printed page numbers.
5. Select a DOCX file to view text by body paragraph or table-cell location. Download the original to inspect its layout; the application does not invent fixed page numbers for Word documents.
6. Review the reason for partial or failed parsing and retry when appropriate.

Original files and SQLite records are stored in `data/` by default. Closing the page or restarting the application does not delete them. To use another data directory:

```sh
sh run.sh --data-dir /path/to/local/workspace
```

Identical file contents are deduplicated within a matter, even if the filenames differ. Changed contents are stored as a separate document; automatic version replacement is not implemented. Separate matters can each retain a copy of the same original.

## Optional OCR on macOS

An Apple Vision adapter is provided for local recognition without an external model API. It requires the macOS Swift compiler:

```sh
sh scripts/setup_ocr.sh
```

Compilation only prepares the helper; it does not establish that recognition works. Enable the scan-recognition option, labeled **识别扫描件**, and test sample A03 or B08. If recognition fails, the document is marked as needing review and its original page remains available.

Without a working OCR engine, disable scan recognition and begin with text-based PDFs and DOCX files. Native OCR for other platforms is not included. A tested Docling or other OCR backend can later be integrated through `matterloom/parsing.py`.

## Implementation

| Component | Current implementation |
| --- | --- |
| Interface | HTML, CSS, and JavaScript with no external frontend assets |
| Local service | Python standard-library HTTP server |
| PDF text extraction | pypdf |
| PDF page rendering | pypdfium2 |
| DOCX text extraction | python-docx |
| Optional scan recognition | Apple Vision via a Swift helper |
| Persistence | SQLite metadata and local original files |
| Sample generation | ReportLab and python-docx |

The initial plan proposed Streamlit and Docling. Those dependencies could not be installed in the implementation environment, so this prototype uses the available components above. It has not established that this stack outperforms the original proposal. See [implementation decisions](docs/decisions.md) for the rationale and boundaries; that document is currently in Chinese.

The application does not call an external LLM or upload documents to an external service. Package installation requires network access, but document processing uses local components.

## Tests and sample checks

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_samples.py
```

Tests use temporary directories rather than personal workspace data. HTTP-handler tests exercise actual request and multipart-upload parsing without opening a listening port; they do not replace browser end-to-end testing.

The [verification record](docs/verification.md), currently in Chinese, documents the implementation checks and remaining manual checks. The OCR adapter contract test uses a simulated recognition response and is not a measurement of real OCR quality.

[evaluation/reference.json](evaluation/reference.json) contains reference facts for future question-answering tests. It is deliberately kept separate from uploaded matter documents and is not included in the application's sample import.

## Repository layout

```text
matterloom/             Persistence, parsing, and local server
web/                    Browser interface
samples/                Two fictional matter bundles and their manifest
evaluation/             Reference answers, excluded from sample imports
scripts/                Sample generation, validation, and OCR build tools
tests/                  Data and HTTP-handler tests
docs/                   Implementation decisions and verification record
requirements.txt        Dependency version ranges
requirements-lock.txt   Direct dependency versions used during verification
run.sh                  Local application launcher
启动律脉.command         macOS double-click launcher
data/                   Personal matters and originals, ignored by Git
work/                   Generated QA files and OCR executable, ignored by Git
outputs/                Distribution archives, ignored by Git
```

The version file pins the direct dependencies used during verification; it is not a complete transitive dependency lock.

## Download contents

The archive includes all project source files, both English README files, the complete set of 16 sample documents, reference answers, tests, scripts, dependency files, and project documentation. `PACKAGE_CONTENTS.txt` inside the archive lists the packaged files and their SHA-256 checksums.

Machine-specific virtual environments, Git metadata, personal matter data, secrets, caches, compiled OCR binaries, and generated QA intermediates are excluded. Recreate the environment and compile the optional OCR helper using the commands above.

## Known limitations

- No lawyer usability study has been completed; efficiency and legal accuracy have not been established.
- PDF tables are currently extracted as text. Complex columns and table structure may not retain their original reading order.
- Mixed text-and-image PDF pages require review of image regions. Failed OCR does not remove the original file.
- DOCX extraction covers body paragraphs and ordinary tables. The parser flags supported detections of revisions, images, headers or footers, text boxes, footnotes, and nested tables for manual review. It does not provide Word's original paginated layout.
- The service binds only to `127.0.0.1`. It has no login, team permissions, or production deployment safeguards and should not be exposed to the public internet.
- The interface and sample documents are intentionally in Chinese. Both README files are in English; the remaining project notes are in Chinese.
