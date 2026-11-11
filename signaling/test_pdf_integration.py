"""REAL LibreOffice tests. Simulated converters are forbidden in this module."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import importlib.util
import os
import unittest

from signaling.pdf_conversion import ConversionOptions, PDFConversionError, convert_docx_to_pdf, find_libreoffice

try:
    EXECUTABLE = find_libreoffice(os.environ.get("LIBREOFFICE_EXECUTABLE"))
except PDFConversionError:
    EXECUTABLE = None
DEPENDENCY = importlib.util.find_spec("pypdf") is not None


@unittest.skipUnless(EXECUTABLE and DEPENDENCY, "Real integration requires LibreOffice and requirements-pdf-poc.txt")
class LibreOfficeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.pdf_poc import build_sample_docx
        cls.original = build_sample_docx()
        cls.options = ConversionOptions(executable=EXECUTABLE)

    def check_content(self, converted):
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(converted),strict=True)
        self.assertGreater(len(reader.pages),0)
        text=" ".join((page.extract_text() or "") for page in reader.pages)
        normalized=" ".join(text.split())
        for expected in ("Relatório Técnico de Segurança Viária", "Análise técnica e considerações finais",
                         "Autor sintético", "Data de emissão", "SINTETICO-01", "PoC"):
            self.assertIn(expected,normalized)
        resources=[page.get("/Resources") for page in reader.pages]
        self.assertTrue(any(resource and resource.get_object().get("/XObject") for resource in resources))

    def test_representative_docx_converts_to_readable_pdf(self):
        before=bytes(self.original)
        self.check_content(convert_docx_to_pdf(self.original,options=self.options))
        self.assertEqual(self.original,before)

    def test_two_real_conversions_do_not_collide(self):
        with ThreadPoolExecutor(2) as executor:
            futures=[executor.submit(convert_docx_to_pdf,self.original,options=self.options) for _ in range(2)]
            for future in futures:
                self.check_content(future.result(timeout=75))
