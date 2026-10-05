"""integration through the public fixture CLI."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import jsonschema
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[2]


class FixtureIntegration(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "backend.fixture", *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True)

    def test_generate_and_adapt(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli("generate", "--output-root", directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((Path(directory) / "invoice.pdf").is_file())
            adapted = self.cli("adapt", "invoice.pdf", "--input-root", directory)
            self.assertEqual(adapted.returncode, 0, adapted.stdout + adapted.stderr)
            self.assertEqual(json.loads(adapted.stdout)["source_kind"], "synthetic")

    def test_repeatability_pdf_text_and_provenance_schemas(self):
        """inspect actual generated PDF and linked raw/normalized data."""
        fixture = ROOT / "fixtures" / "invoice"
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for directory in (first, second):
                result = self.cli("generate", "--output-root", directory)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in ("invoice.pdf", "normalized.json", "textract-shaped.json", "provenance.json"):
                content = (Path(first) / name).read_bytes()
                self.assertEqual(content, (Path(second) / name).read_bytes())
                self.assertEqual(content, (fixture / name).read_bytes(), name)
            pdf = PdfReader(Path(first) / "invoice.pdf", strict=True)
            self.assertEqual(len(pdf.pages), 1)
            text = pdf.pages[0].extract_text()
            self.assertIn("SYNTHETIC DEMO DATA", text)
            digest = hashlib.sha256((Path(first) / "invoice.pdf").read_bytes()).hexdigest()
            normalized = json.loads((Path(first) / "normalized.json").read_text())
            raw = json.loads((Path(first) / "textract-shaped.json").read_text())
            for name, value in (("normalized", normalized), ("textract-shaped", raw)):
                schema = json.loads((fixture / f"{name}.schema.json").read_text())
                jsonschema.Draft202012Validator.check_schema(schema)
                jsonschema.validate(value, schema)
                self.assertEqual(value["document_sha256"], digest)
            expected = {"invoice_number": "SYN-2026-001", "vendor": "Juniper Example Supplies",
                        "date": "2026-10-01", "currency": "USD", "total": "125.00"}
            self.assertEqual({f["name"]: f["value"] for f in normalized["fields"]}, expected)
            blocks = {block["Id"]: block for block in raw["Blocks"]}
            for field in normalized["fields"]:
                self.assertIn(field["value"], text)
                self.assertEqual(field["document_sha256"], digest)
                self.assertEqual(field["confidence_kind"], "invented_not_calibrated")
                block = blocks[field["evidence"]["block_id"]]
                self.assertIn(block["Text"], text)
                self.assertEqual(field["evidence"]["bounding_box"], block["Geometry"]["BoundingBox"])
                self.assertEqual(field["confidence"], block["Confidence"] / 100)
                self.assertEqual(field["page"], block["Page"])
            adapted = self.cli("adapt", "invoice.pdf", "--input-root", first)
            self.assertEqual(adapted.returncode, 0, adapted.stderr)
            self.assertEqual(json.loads(adapted.stdout), normalized)

    def test_rejection_contract(self):
        """parser-backed input limits, exact hash and stable CLI failures."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unsupported.txt").write_bytes(b"%PDF-1.4")
            (root / "malformed.pdf").write_bytes(b"%PDF-1.4\nnot a PDF")
            (root / "large.pdf").write_bytes(b"x" * (5 * 1024 * 1024 + 1))
            (root / "limit.pdf").write_bytes(b"x" * (5 * 1024 * 1024))
            for name, pages, password in (("unknown.pdf", 1, None), ("ten.pdf", 10, None),
                                          ("eleven.pdf", 11, None), ("encrypted.pdf", 1, "secret"),
                                          ("empty.pdf", 0, None)):
                writer = PdfWriter()
                for _ in range(pages):
                    writer.add_blank_page(612, 792)
                if password:
                    writer.encrypt(password)
                writer.write(root / name)
            expected = {"unsupported.txt": "UNSUPPORTED_TYPE", "malformed.pdf": "INVALID_PDF",
                        "large.pdf": "FILE_TOO_LARGE", "limit.pdf": "INVALID_PDF",
                        "unknown.pdf": "UNKNOWN_FIXTURE_DOCUMENT", "ten.pdf": "UNKNOWN_FIXTURE_DOCUMENT",
                        "eleven.pdf": "TOO_MANY_PAGES", "encrypted.pdf": "ENCRYPTED_PDF",
                        "empty.pdf": "INVALID_PDF", "missing.pdf": "INPUT_UNREADABLE",
                        "../outside.pdf": "PATH_OUTSIDE_ROOT", str(root / "unknown.pdf"): "PATH_OUTSIDE_ROOT"}
            for name, code in expected.items():
                with self.subTest(name=name):
                    result = self.cli("adapt", name, "--input-root", directory)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout), {"error": {"code": code}})
            result = self.cli("generate", "--output-root", directory, "--directory", "../escape")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "PATH_OUTSIDE_ROOT")
            result = self.cli("generate", "--output-root", directory, "--directory", "nested")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = self.cli("adapt", "nested/invoice.pdf", "--input-root", directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
