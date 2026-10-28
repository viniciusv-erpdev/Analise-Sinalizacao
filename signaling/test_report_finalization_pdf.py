"""Real LibreOffice conversion of an official snapshot; no database."""
from io import BytesIO
from unittest import TestCase, skipUnless
from signaling import test_pdf_integration as integration
from signaling.report_snapshots import render_snapshot
from signaling.test_report_finalization import sample_snapshot
from signaling.pdf_conversion import convert_docx_to_pdf, ConversionOptions


@skipUnless(integration.EXECUTABLE and integration.DEPENDENCY, "Requires LibreOffice and pypdf")
class OfficialSnapshotPDFTests(TestCase):
    def test_real_pdf_preserves_official_identity_frozen_author_and_sao_paulo_date(self):
        from pypdf import PdfReader
        snapshot = sample_snapshot()
        original = render_snapshot(snapshot, [])
        converted = convert_docx_to_pdf(original, options=ConversionOptions(executable=integration.EXECUTABLE))
        reader = PdfReader(BytesIO(converted), strict=True)
        text = " ".join(" ".join(page.extract_text().split()) for page in reader.pages)
        for expected in ("RTSV-2026-0001", "Frozen Author (frozen-user)", "31/12/2026", "22:30:00", "Final analysis"):
            self.assertIn(expected, text)
