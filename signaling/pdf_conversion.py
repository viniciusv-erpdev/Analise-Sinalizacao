"""Isolated DOCX -> PDF PoC. Input is bytes, never a client-controlled path."""
from dataclasses import dataclass
from io import BytesIO
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import threading
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from signaling.pdf_process import ProcessError, run_process

MiB = 1024 * 1024
_SLOTS = threading.BoundedSemaphore(2)  # per Python process, NOT a cluster-wide quota
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class PDFConversionError(Exception):
    """Only code/status are safe for ordinary logs. diagnostics must stay private."""
    def __init__(self, code, *, returncode=None, diagnostics=None):
        self.code, self.returncode = code, returncode
        self.diagnostics = diagnostics
        super().__init__(code)


@dataclass(frozen=True)
class ConversionOptions:
    # Administrative configuration, never fields from an HTTP request.
    executable: str | None = None
    temp_root: Path | None = None
    timeout_seconds: float = 60
    max_docx_bytes: int = 32 * MiB
    max_uncompressed_bytes: int = 128 * MiB
    max_xml_bytes: int = 8 * MiB
    max_pdf_bytes: int = 64 * MiB
    max_workspace_bytes: int = 256 * MiB
    memory_bytes: int = 1024 * MiB
    max_pages: int = 200

    def __post_init__(self):
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (float,int))
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError("Invalid conversion timeout")
        for name in ("max_docx_bytes", "max_uncompressed_bytes", "max_xml_bytes",
                     "max_pdf_bytes", "max_workspace_bytes", "memory_bytes", "max_pages"):
            if type(getattr(self,name)) is not int or getattr(self,name) <= 0:
                raise ValueError("Invalid conversion limit")


def find_libreoffice(configured=None):
    if configured:
        path = Path(configured)
        if not path.is_absolute() or not path.is_file():
            raise PDFConversionError("converter_unavailable")
        return str(path.resolve())
    candidates = [shutil.which(name) for name in ("soffice.com", "soffice", "libreoffice")]
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(variable):
                candidates.extend(str(Path(os.environ[variable]) / "LibreOffice/program" / name)
                                  for name in ("soffice.com", "soffice.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise PDFConversionError("converter_unavailable")


def _xml(data):
    if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise PDFConversionError("invalid_docx")
    return ET.fromstring(data)


def _validate_docx(data, options):
    if not isinstance(data, bytes) or not data or len(data) > options.max_docx_bytes:
        raise PDFConversionError("docx_size_or_type_invalid")
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (len(entries) > 2048 or len(set(names)) != len(names)
                    or sum(entry.file_size for entry in entries) > options.max_uncompressed_bytes):
                raise PDFConversionError("docx_expansion_limit")
            for entry in entries:
                name = entry.filename
                if (entry.flag_bits & 1 or PurePosixPath(name).is_absolute()
                        or ".." in PurePosixPath(name).parts or "\\" in name
                        or name.lower().endswith(("vbaproject.bin", ".ole"))
                        or name.startswith("word/embeddings/")):
                    raise PDFConversionError("unsupported_docx_content")
                if name.endswith((".xml", ".rels")):
                    if entry.file_size > options.max_xml_bytes:
                        raise PDFConversionError("docx_xml_limit")
                    root = _xml(archive.read(entry))
                    if name.endswith(".rels") and any(
                        node.attrib.get("TargetMode", "").lower() == "external" for node in root):
                        raise PDFConversionError("external_docx_relationship")
                    for node in root.iter():
                        if node.tag == "{"+_WORD_NS+"}altChunk":
                            raise PDFConversionError("unsupported_docx_content")
                        instruction = ((node.text or "") if node.tag == "{"+_WORD_NS+"}instrText"
                                       else node.get("{"+_WORD_NS+"}instr", ""))
                        if instruction.strip() and instruction.strip().split()[0].upper() not in {"PAGE", "NUMPAGES"}:
                            raise PDFConversionError("unsupported_docx_content")
            if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}.issubset(names):
                raise PDFConversionError("invalid_docx")
            if _xml(archive.read("word/document.xml")).tag != "{"+_WORD_NS+"}document":
                raise PDFConversionError("invalid_docx")
            if archive.testzip() is not None:
                raise PDFConversionError("invalid_docx")
    except (BadZipFile, ET.ParseError, KeyError, RuntimeError, OSError, ValueError):
        raise PDFConversionError("invalid_docx") from None


def validate_pdf(data, *, max_pages=200):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise PDFConversionError("pdf_validator_unavailable") from None
    if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        raise PDFConversionError("invalid_pdf")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or not 0 < len(reader.pages) <= max_pages:
            raise PDFConversionError("invalid_pdf")
        for page in reader.pages:
            if page.mediabox.width <= 0 or page.mediabox.height <= 0:
                raise PDFConversionError("invalid_pdf")
    except PDFConversionError:
        raise
    except Exception:
        raise PDFConversionError("invalid_pdf") from None


def _convert(data, options):
    _validate_docx(data, options)
    executable = find_libreoffice(options.executable)
    try:
        with tempfile.TemporaryDirectory(prefix="signaling-pdf-", dir=options.temp_root) as directory:
            work = Path(directory).resolve()
            profile, output, scratch = work / "profile", work / "output", work / "scratch"
            for path in (profile,output,scratch):
                path.mkdir(mode=0o700)
            (work / "input.docx").write_bytes(data)
            # Disable macros/links in this private profile as defense in depth.
            (profile / "user").mkdir()
            (profile / "user/registrymodifications.xcu").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
                '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
                '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
                '</item></oor:items>', encoding="utf-8")
            # No database passwords, Django secret keys or session settings in children.
            allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL",
                       "LC_CTYPE", "TZ", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES"}
            env = {key:value for key,value in os.environ.items() if key.upper() in allowed}
            env["HOME"] = str(scratch)
            env["XDG_CACHE_HOME"] = str(scratch / "cache")
            env["XDG_CONFIG_HOME"] = str(scratch / "config")
            for key in ("TMPDIR", "TMP", "TEMP"):
                env[key] = str(scratch)
            env["SAL_USE_VCLPLUGIN"] = "svp"
            command = [executable, "-env:UserInstallation="+profile.as_uri(),
                "--headless", "--nologo", "--nodefault", "--nofirststartwizard", "--norestore",
                "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(output), str(work / "input.docx")]
            result = run_process(command, cwd=work, env=env, timeout=options.timeout_seconds,
                memory_bytes=options.memory_bytes, file_bytes=options.max_pdf_bytes,
                workspace_bytes=options.max_workspace_bytes)
            if result.returncode:
                raise PDFConversionError("converter_failed", returncode=result.returncode,
                                         diagnostics=result)
            pdf = output / "input.pdf"
            if not pdf.is_file() or pdf.is_symlink():
                raise PDFConversionError("pdf_not_produced", diagnostics=result)
            if not 0 < pdf.stat().st_size <= options.max_pdf_bytes:
                raise PDFConversionError("pdf_size_invalid")
            converted = pdf.read_bytes()
            validate_pdf(converted, max_pages=options.max_pages)
            return converted
    except ProcessError as error:
        raise PDFConversionError(error.code) from None
    except OSError:
        raise PDFConversionError("temporary_storage_error") from None


def convert_docx_to_pdf(data, *, options=None):
    """Return validated PDF bytes; never retain an original DOCX, path, or PDF."""
    if not _SLOTS.acquire(blocking=False):
        raise PDFConversionError("conversion_busy")
    try:
        return _convert(data, options or ConversionOptions())
    finally:
        _SLOTS.release()
