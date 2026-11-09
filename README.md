# MatterLoom | 律脉

**Trace the facts. Build lasting legal knowledge.**

MatterLoom is a local workspace for organizing Chinese legal matter documents. It supports matter creation, multiple-file uploads, original-file storage, page-by-page PDF viewing, and structured information review with traceable quotations. The interface and sample materials are in Chinese.

## Project status

Version: **0.2.0**. This is a single-user development prototype.

- Implemented: document ingestion and viewing; seven information categories; local candidate extraction; an optional GLM adapter; editing, confirmation, uncertainty, reversible removal, and revision history.
- Included: **16 fictional sample documents** across two matters: 11 PDFs, including two image-only scans, and five DOCX files.
- Verification: **48 automated data, extraction, review, and HTTP-handler tests passed**. JavaScript syntax checks passed. Real browser end-to-end operation has not yet been verified.
- Local extraction: **129 pending candidates** from 14 readable sample documents; every stored quotation was found in its referenced source. Eleven predefined literal amount/date probes were found. These are operational checks, not precision, recall, or semantic correctness scores.
- GLM: the adapter, response validation, and error paths were tested with simulated responses. No live GLM request or model-quality evaluation was performed.
- Sample ingestion: 14 documents completed text extraction; two scans retained their original pages and reported that OCR needed attention. These counts are parsing outcomes, not extraction-accuracy scores.
- OCR: the optional Apple Vision helper compiled, but actual recognition failed in the implementation environment. Chinese OCR is not yet verified.
- The initial implementation environment blocked local server startup. A local Git repository has since been initialized in the original workspace; the downloadable archive does not include Git metadata.

Cross-document question answering, entity resolution, conflict reconciliation, timelines, calendar export, and fact-summary drafting remain planned features. This release collects facts across a matter but does not automatically resolve disagreements between documents.

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

When upgrading an existing installation, stop the running service, install the updated dependencies, and restart it. Startup adds review tables to the existing database without replacing matters, documents, or original files. Keep the existing `data/` directory. Do not run different application versions against the same data directory simultaneously.

## What the prototype does

1. Create a matter or import a sample matter.
2. Select multiple PDF/DOCX files or drag them into the upload area. Each file is limited to 20 MB; each PDF is limited to 100 pages.
3. Check each document's parsing status: complete, needs review, failed, or pending.
4. Select a PDF and compare the original page image with the extracted text. Page references use the PDF file's page order, which may differ from printed page numbers.
5. Select a DOCX file to view text by body paragraph or table-cell location. Download the original to inspect its layout; the application does not invent fixed page numbers for Word documents.
6. Review the reason for partial or failed parsing and retry when appropriate.
7. Open **事实审核**, choose **本地规则**, and click **提取事项信息**. Every new candidate starts as pending.
8. Click a quotation to open its PDF page or DOCX paragraph/table cell. The matching text is highlighted; use the original-page tab to compare it with the PDF image.
9. Use **修改 / 审核** to edit the category, title, value, optional normalized value, uncertainty, and review note; select pending, confirmed, uncertain, or removed. Removal preserves history and can be reversed through the removed-items filter.
10. Use **手动补充** to add a missed fact from the currently selected document. Supply an exact continuous quotation; the new entry starts as pending. Use **修改记录** to inspect earlier versions.

Original files and SQLite records are stored in `data/` by default. Closing the page or restarting the application does not delete them. To use another data directory:

```sh
sh run.sh --data-dir /path/to/local/workspace
```

Identical file contents are deduplicated within a matter, even if the filenames differ. Changed contents are stored as a separate document; automatic version replacement is not implemented. Separate matters can each retain a copy of the same original.

## Structured information and review

The seven categories are **person, organization, amount, date, event, claim, and open question**. Each record stores a short label, a value or statement, an optional normalized value, an uncertainty explanation, source quotations, review status, and review history. PDF citations use file-page order; DOCX citations use body/table coordinates.

The local extractor is a conservative rule baseline. It identifies common role-labelled names, organizations, Arabic-numeral amounts in yuan, explicit dates, and sentence-level event/claim/missing-information cues. It preserves negation and proposal wording in quoted statements. It does not reliably resolve pronouns, party roles, Chinese written-out monetary amounts, cross-page sentences, table semantics, or conflicts. Long PDF line wrapping is handled heuristically and still needs review. Relative or yearless dates remain unnormalized; no deadline arithmetic is performed.

Candidate and edit payloads are validated with Pydantic. Date normalized values must be valid `YYYY-MM-DD` dates; monetary values use a currency code and number, such as `CNY 100000`. Unknown values stay null. Quotations must occur verbatim within an allowed source unit. This proves that a quotation exists, **not that it supports the associated interpretation**; the reviewer must check that relationship.

Exact repeated candidates are skipped without overwriting human edits or restoring removed records. Different wording or sources may produce separate candidates. Original extraction values and citation snapshots remain available after edits. Concurrent edits from an outdated editor return a conflict instead of overwriting a newer revision.

If reparsing changes a cited source unit, its location, or extraction method, affected confirmed records become uncertain and retain the old quotation. Unavailable citations cannot be confirmed. Re-extract and review a new record, then remove the superseded entry. Unchanged reparsing preserves confirmation. Only confirmed records with currently valid sources have `eligible: true`; a future drafting/calendar module must use that property rather than status alone.

### Optional GLM extraction

Local mode needs no API key and sends no documents to a model service. To enable GLM, set these environment variables before starting the app:

```sh
export GLM_API_KEY='your-api-key'
export MATTERLOOM_GLM_MODEL='your-exact-supported-text-model-id'
sh run.sh
```

The model ID above is a placeholder: replace it with the exact supported text model identifier for your account. Do not paste a key into chat, source files, or Git. The app reads process environment variables; it does not automatically load a `.env` file. Keys are never returned to the browser or included in history.

In **事实审核**, select **GLM 模型** and check the consent box before clicking **提取事项信息**. This sends each document's parsed text to the fixed official endpoint `https://open.bigmodel.cn/api/paas/v4/chat/completions` and may incur API charges. Original PDF/DOCX binaries, other matters, evaluation labels, and reviewer history are not sent. Selecting GLM alone or uploading a file does not trigger external processing. Consent resets on matter or mode changes.

The adapter uses JSON-object output, validates each candidate and exact quotation, and records requested/returned model IDs and the extraction schema/prompt version. It sends text in batches of up to roughly 6,000 characters, allows at most 20 batches per file, and sets a 90-second timeout per request. It does not silently truncate inputs or retry paid calls. If a later batch fails, that document's new candidates are not committed; earlier API requests may still have been billed. Earlier saved reviews remain intact. Invalid individual candidates are omitted and counted in the extraction log; incomplete source parsing is also reported.

The adapter follows the [official GLM chat-completion API](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8) and [Pydantic model validation](https://docs.pydantic.dev/latest/concepts/models/). Live compatibility depends on the configured model and still needs testing with fictional material.

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
| Fact extraction | Local rules; optional, explicitly enabled GLM JSON output |
| Validation and review | Pydantic; source hashes; SQLite revision history |
| Sample generation | ReportLab and python-docx |

The initial plan proposed Streamlit and Docling. Those dependencies could not be installed in the implementation environment, so this prototype uses the available components above. It has not established that this stack outperforms the original proposal. See [implementation decisions](docs/decisions.md) for the rationale and boundaries; that document is currently in Chinese.

The default workflow processes documents locally. External model processing occurs only when GLM is configured, selected, and explicitly enabled for the current matter through the consent checkbox. Package installation also requires network access.

## Tests and sample checks

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_samples.py
.venv/bin/python scripts/check_extraction.py
```

Tests use temporary directories rather than personal workspace data. HTTP-handler tests exercise actual request and multipart-upload parsing without opening a listening port; they do not replace browser end-to-end testing.

The [verification record](docs/verification.md), currently in Chinese, documents the implementation checks and remaining manual checks. The OCR adapter contract test uses a simulated recognition response and is not a measurement of real OCR quality.

[Stage-two design and acceptance notes](docs/stage2-review.md) explain the information schema, review transitions, known failure cases, and remaining browser/model checks. `scripts/check_extraction.py` uses temporary data and local mode only, and writes its report under `work/stage2/`.

[evaluation/reference.json](evaluation/reference.json) contains reference facts for future question-answering tests. It is deliberately kept separate from uploaded matter documents and is not included in the application's sample import.

## Repository layout

```text
matterloom/             Persistence, parsing, extraction, review, and local server
web/                    Browser interface
samples/                Two fictional matter bundles and their manifest
evaluation/             Reference answers, excluded from sample imports
scripts/                Sample generation, validation, and OCR build tools
tests/                  Data, extraction, review, and HTTP-handler tests
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
- The local baseline produces review candidates, not verified legal facts. Quotation matching is not semantic entailment; live GLM accuracy has not been evaluated.
- Scans without readable OCR text do not generate candidates. This does not mean that those documents contain no relevant information.
- PDF tables are currently extracted as text. Complex columns and table structure may not retain their original reading order.
- Mixed text-and-image PDF pages require review of image regions. Failed OCR does not remove the original file.
- DOCX extraction covers body paragraphs and ordinary tables. The parser flags supported detections of revisions, images, headers or footers, text boxes, footnotes, and nested tables for manual review. It does not provide Word's original paginated layout.
- The service binds only to `127.0.0.1`. It has no login, team permissions, or production deployment safeguards and should not be exposed to the public internet.
- The interface and sample documents are intentionally in Chinese. Both README files are in English; the remaining project notes are in Chinese.
