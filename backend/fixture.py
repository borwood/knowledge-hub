"""Deterministic synthetic invoice adapter; no cloud services or extraction claims."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

from pypdf import PdfReader

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "invoice"
MAX_BYTES = 5 * 1024 * 1024
VALUES = [("invoice_number", "SYN-2026-001"), ("vendor", "Juniper Example Supplies"),
          ("date", "2026-10-01"), ("currency", "USD"), ("total", "125.00")]
LABELS = ["Invoice number", "Vendor", "Date", "Currency", "Total"]


class FixtureError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def contained(root, name):
    """The explicit root is trusted; relative names must remain inside it."""
    root = Path(root).resolve()
    path = Path(name)
    if path.is_absolute():
        raise FixtureError("PATH_OUTSIDE_ROOT")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise FixtureError("PATH_OUTSIDE_ROOT")
    return resolved


def invoice_pdf():
    lines = ["SYNTHETIC DEMO DATA - NOT A REAL INVOICE", "All names and values are invented."]
    lines.extend(f"{label}: {value}" for label, (_, value) in zip(LABELS, VALUES))
    content = "BT /F1 12 Tf 50 750 Td 24 TL\n" + "\n".join(
        f"({line}) Tj T*" for line in lines) + "\nET\n"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Length {len(content)} >>\nstream\n{content}endstream".encode("ascii")]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


def artifacts():
    pdf = invoice_pdf()
    digest = hashlib.sha256(pdf).hexdigest()
    raw = {"schema_version": "1.0", "source_kind": "synthetic", "document_sha256": digest,
           "confidence_kind": "invented_not_calibrated", "method": "synthetic_fixture_v1",
           "notice": "Invented Textract-shaped blocks; no AWS Textract call was made.",
           "DocumentMetadata": {"Pages": 1}, "Blocks": []}
    fields = []
    for index, (name, value) in enumerate(VALUES):
        # Bounding boxes enclose the corresponding full text line in PDF coordinates,
        # normalized from the top-left; use generous widths for Helvetica text.
        box = {"Left": 50 / 612, "Top": (792 - (702 - index * 24) - 12) / 792,
               "Width": 400 / 612, "Height": 18 / 792}
        block = {"Id": f"line-{index + 1}", "BlockType": "LINE", "Page": 1,
                 "Text": f"{LABELS[index]}: {value}", "Confidence": 99.0,
                 "Geometry": {"BoundingBox": box}}
        raw["Blocks"].append(block)
        fields.append({"name": name, "value": value, "page": 1,
                       "document_sha256": digest, "method": raw["method"],
                       "confidence": block["Confidence"] / 100,
                       "confidence_kind": raw["confidence_kind"],
                       "evidence": {"block_id": block["Id"], "bounding_box": box}})
    normalized = {key: raw[key] for key in ("schema_version", "source_kind", "document_sha256")}
    normalized["fields"] = fields
    provenance = {"schema_version": "1.0", "source_kind": "synthetic", "document_sha256": digest,
                  "generator": "python -m backend.fixture generate", "cloud_calls": False,
                  "confidence_kind": raw["confidence_kind"], "notice": raw["notice"]}
    return {"invoice.pdf": pdf, "textract-shaped.json": json_bytes(raw),
            "normalized.json": json_bytes(normalized), "provenance.json": json_bytes(provenance)}


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def generate(output_root=FIXTURE_ROOT, directory="."):
    target = contained(output_root, directory)
    files = artifacts()
    # Resolve every target first, including preexisting symlinks, before writing.
    paths = {name: contained(output_root, str(Path(directory) / name)) for name in files}
    target.mkdir(parents=True, exist_ok=True)
    for name, path in paths.items():
        path.write_bytes(files[name])
    return {"generated": sorted(files)}


def adapt(document, input_root=FIXTURE_ROOT):
    path = contained(input_root, document)
    if path.suffix.lower() != ".pdf":
        raise FixtureError("UNSUPPORTED_TYPE")
    try:
        # Bound the read as well as the stat so growing inputs cannot evade the cap.
        if path.stat().st_size > MAX_BYTES:
            raise FixtureError("FILE_TOO_LARGE")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise FixtureError("INPUT_UNREADABLE") from exc
    if len(data) > MAX_BYTES:
        raise FixtureError("FILE_TOO_LARGE")
    return adapt_bytes(data)


def validate_pdf(data):
    if len(data) > MAX_BYTES:
        raise FixtureError("FILE_TOO_LARGE")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise FixtureError("ENCRYPTED_PDF")
        pages = len(reader.pages)
        if pages > 10:
            raise FixtureError("TOO_MANY_PAGES")
        if pages < 1:
            raise FixtureError("INVALID_PDF")
    except FixtureError:
        raise
    except Exception as exc:
        raise FixtureError("INVALID_PDF") from exc


def adapt_bytes(data):
    validate_pdf(data)
    if hashlib.sha256(data).hexdigest() != hashlib.sha256(invoice_pdf()).hexdigest():
        raise FixtureError("UNKNOWN_FIXTURE_DOCUMENT")
    return json.loads(artifacts()["normalized.json"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generation = commands.add_parser("generate")
    generation.add_argument("--output-root", default=str(FIXTURE_ROOT))
    generation.add_argument("--directory", default=".")
    adaptation = commands.add_parser("adapt")
    adaptation.add_argument("document")
    adaptation.add_argument("--input-root", default=str(FIXTURE_ROOT))
    args = parser.parse_args()
    try:
        result = generate(args.output_root, args.directory) if args.command == "generate" else adapt(args.document, args.input_root)
    except FixtureError as exc:
        print(json.dumps({"error": {"code": exc.code}}))
        return 2
    except OSError:
        print(json.dumps({"error": {"code": "OUTPUT_UNWRITABLE"}}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
