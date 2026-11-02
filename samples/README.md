# Fictional Matter Bundles

All documents were created as fictional fixtures for MatterLoom. They do not describe real clients, organizations, accounts, or transactions. Each document is clearly labeled for testing; no real client records were used to create these samples.

The documents remain in Chinese so that they exercise the application's intended language and document workflows.

## Matter A: Equipment Purchase and Payment Reconciliation

Eight documents cover a contract for CNY 100,000, payments of CNY 40,000 and CNY 20,000, and the buyer's requested price reduction of CNY 10,000. The materials do not establish that the seller accepted that reduction. An older reconciliation statement and a collection letter show CNY 60,000, which must be considered alongside the later payment.

| ID | Document | Format |
| --- | --- | --- |
| A01 | Equipment purchase contract | PDF, two pages |
| A02 | Purchase confirmation | DOCX |
| A03 | Delivery receipt | Image-only PDF |
| A04 | Quality-issue correspondence | PDF |
| A05 | Interim reconciliation statement | DOCX |
| A06 | Two payment records | PDF, two pages |
| A07 | Collection letter | PDF |
| A08 | Telephone discussion notes | DOCX |

## Matter B: Departure, Payroll, and Handover Reconciliation

Eight documents distinguish a monthly salary standard of CNY 8,000, listed gross pay of CNY 7,600, and net pay or money received of CNY 6,900. They also contain an unresolved attendance question and different dates for a proposed departure and the actual handover. The materials do not establish an agreed employment termination date.

| ID | Document | Format |
| --- | --- | --- |
| B01 | Employment contract | PDF, two pages |
| B02 | Offer letter | DOCX |
| B03 | Monthly attendance record | PDF |
| B04 | Payroll breakdown | PDF |
| B05 | Salary receipt record | PDF |
| B06 | Departure notice | DOCX |
| B07 | HR and supervisor correspondence | PDF |
| B08 | Work handover confirmation | Image-only PDF |

## Coverage and use

The collection contains **11 PDFs and five DOCX files**. The PDFs contain **14 pages** in total. A03 and B08 are image-only documents with no embedded text layer; they are intended to test scan detection, OCR attempts, and graceful handling of incomplete extraction.

Import either bundle with the application's sample collection button, labeled **查看模拟案卷**, or upload individual files manually. Each filename begins with its document ID. [manifest.json](manifest.json) contains the exact filenames and matter assignments.

To regenerate the documents, run this command from the project root after installing the dependencies:

```sh
.venv/bin/python scripts/build_samples.py
```

Reference answers live in `evaluation/`, outside the imported sample collection. They must not be included as retrieval material. The DOCX fixtures use Songti SC; install an appropriate Chinese font when reviewing their layout on another machine.
