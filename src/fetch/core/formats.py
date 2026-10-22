"""Declared format must match bytes. Mirrors the inresearch receiver's admission so a package never leaves here only to be rejected there."""
import json
from pathlib import Path
import zipfile

FORMATS = frozenset({
    "pdf", "doc", "docm", "docx", "dot", "dotm", "dotx", "xls", "xlsb", "xlsm", "xlsx", "xlt", "xltm", "xltx",
    "ppt", "pptm", "pptx", "pps", "ppsm", "ppsx", "pot", "potm", "potx", "csv", "rtf", "odt", "ods", "odp",
    "html", "json"})
READER_FORMATS = frozenset({"pdf", "html", "csv", "docx", "pptx", "xlsx", "xls", "ppt"})
OLE = bytes.fromhex("d0cf11e0a1b11ae1")
WORD = {"docx", "docm", "dot", "dotm", "dotx"}
SHEET = {"xlsx", "xlsb", "xlsm", "xlt", "xltx", "xltm"}
SLIDES = {"pptx", "pptm", "pps", "ppsx", "ppsm", "pot", "potx", "potm"}
OPEN_DOCUMENT = {"odt", "ods", "odp"}
JSON_LIMIT = 16 * 1024 * 1024


def matches(path, fmt):
    path = Path(path)
    with path.open("rb") as stream:
        head = stream.read(4096)
    if fmt == "pdf":
        return head.lstrip().startswith(b"%PDF-")
    if fmt == "rtf":
        return head.lstrip().startswith(b"{\\rtf")
    if fmt in {"doc", "xls", "ppt"}:
        return head.startswith(OLE)
    if fmt == "html":
        return b"<" in head and b"\x00" not in head
    if fmt == "csv":
        try:
            head.decode("utf-8-sig")
        except UnicodeError:
            return False
        return b"\x00" not in head
    if fmt == "json":
        try:
            return path.stat().st_size <= JSON_LIMIT and isinstance(json.loads(path.read_bytes().decode("utf-8")), dict)
        except (OSError, UnicodeError, ValueError):
            return False
    if fmt in WORD | SHEET | SLIDES | OPEN_DOCUMENT:
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except (OSError, zipfile.BadZipFile):
            return False
        if fmt in WORD:
            return "word/document.xml" in names
        if fmt in SHEET:
            return bool({"xl/workbook.xml", "xl/workbook.bin"} & names)
        if fmt in SLIDES:
            return "ppt/presentation.xml" in names
        return bool({"mimetype", "content.xml"} & names)
    return False
