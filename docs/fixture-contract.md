# Synthetic invoice contract v1

This is a local deterministic
adapter contract for subsequent ingestion work. It makes no cloud calls.
The names, invoice values and confidence scores are invented; this is not a
Textract response or a measurement of extraction accuracy.

With the locked backend dependencies installed, run from the repository root:

```text
python -m backend.fixture generate
python -m backend.fixture adapt invoice.pdf
python -m pytest tests/integration/test_fixture.py -q
```

Generation reproduces `fixtures/invoice/invoice.pdf`, `textract-shaped.json`,
`normalized.json` and `provenance.json` byte for byte. The PDF uses fixed text,
object order and offsets with no clock, random identifier or machine metadata.
The two committed `*.schema.json` files validate the version 1.0 raw and
normalized contracts and are maintained separately from generated data.

Use `generate --output-root DIRECTORY [--directory RELATIVE_SUBDIRECTORY]`
for a different explicit output root. Use `adapt RELATIVE_PDF --input-root DIRECTORY`
for an explicit input root. Roots are caller-selected trusted directories;
document/subdirectory names must be relative and resolve within their root,
including existing symlink targets. Generation replaces its four fixed output
files. Do not let untrusted callers select roots. Concurrent filesystem changes
by another local writer are outside this local CLI's security boundary.

Inputs must have a `.pdf` suffix (case insensitive), be valid unencrypted PDFs,
contain 1–10 pages, and be at most 5 MiB (5,242,880 bytes). Size is checked before
parsing, reads are bounded, and pypdf validates structure and page count. The
adapter accepts only the exact SHA-256 of the generated invoice; even a valid
edited or re-saved PDF is unknown. It never returns sample fields for other
documents. The Python `adapt(document, input_root)` function is the future
adapter boundary; alternative extractors require separate implementation.

CLI success emits one JSON object to stdout and exits 0. Rejected documents
emit `{"error":{"code":"CODE"}}` to stdout and exit 2; parser diagnostics may
also appear on stderr. Argument syntax errors use argparse's stderr/exit 2.
The Python interface raises `FixtureError` with a `.code` for rejected inputs.

| Code | Condition |
| --- | --- |
| `PATH_OUTSIDE_ROOT` | Absolute input name or resolved path outside the explicit root |
| `UNSUPPORTED_TYPE` | Filename extension is not `.pdf` |
| `INPUT_UNREADABLE` | Missing, inaccessible or non-file input |
| `FILE_TOO_LARGE` | More than 5 MiB, checked before parser use |
| `INVALID_PDF` | Malformed structure or no pages |
| `ENCRYPTED_PDF` | Encryption present, even if an empty password could open it |
| `TOO_MANY_PAGES` | More than 10 pages |
| `UNKNOWN_FIXTURE_DOCUMENT` | Valid PDF within limits but unsupported document hash |
| `OUTPUT_UNWRITABLE` | Generator cannot create/write its selected output |

The normalized envelope carries `schema_version`, `source_kind=synthetic`,
`document_sha256` and five `fields`: invoice number, vendor, date, currency and
total. Each field repeats the document hash and carries its value, one-based
page, source block ID, bounding box, method `synthetic_fixture_v1`, confidence
in [0,1], and `confidence_kind=invented_not_calibrated`. Raw Textract-shaped
LINE blocks preserve text, page, ID, geometry and confidence in [0,100].
Boxes enclose the corresponding complete label/value line, with normalized
top-left origin coordinates. Totals are decimal strings and dates ISO dates.

The integration suite executes real CLI subprocesses, parses the PDF and its
text, validates schemas, compares every field with the text/raw provenance,
checks committed bytes against two generations, and exercises invalid inputs
and both size/page boundaries. No upload endpoint, persisted ingestion or live
AWS integration is delivered here.
