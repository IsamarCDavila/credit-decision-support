"""Bounded extraction of a deliberately constrained synthetic statement format."""

import csv
import io
import json
import re
import subprocess
import sys
import unicodedata
from datetime import date
from typing import Any

FIELDS = (
    "annual_revenue",
    "ebitda",
    "total_debt",
    "debt_service",
    "available_cash_flow",
    "obligations",
)
META = ("synthetic", "currency", "period_start", "period_end", "basis")
CSV_COLUMNS = ("key", "value", "currency", "period_start", "period_end", "basis", "synthetic")
PARSER_VERSION = "synthetic-statement-v1"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000


class IngestionError(ValueError):
    pass


def metadata(values: dict[str, str]) -> dict[str, str]:
    if any(key not in values for key in META):
        raise IngestionError("Statement metadata is incomplete")
    if (values["synthetic"], values["currency"], values["basis"]) != ("true", "USD", "individual"):
        raise IngestionError("Only synthetic USD standalone statements are supported")
    try:
        start, end = (
            date.fromisoformat(values["period_start"]),
            date.fromisoformat(values["period_end"]),
        )
    except ValueError as exc:
        raise IngestionError("Invalid statement dates") from exc
    if start != date(start.year, 1, 1) or end != date(start.year, 12, 31):
        raise IngestionError("A complete calendar-year statement is required")
    return {key: values[key] for key in META}


def parse_csv(data: bytes) -> dict[str, Any]:
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError("CSV must use UTF-8") from exc
    if "\x00" in decoded:
        raise IngestionError("CSV contains unsupported control characters")
    csv.field_size_limit(256_000)
    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    try:
        header = next(reader)
        if tuple(header) != CSV_COLUMNS:
            raise IngestionError("CSV columns must match the synthetic statement schema")
        candidates, rows = [], []
        period: dict[str, str] | None = None
        for row_number, row in enumerate(reader, 2):
            if row_number > 2001 or len(row) != len(header):
                raise IngestionError("Invalid CSV row count or column count")
            if any("\n" in value or "\r" in value for value in row):
                raise IngestionError("Multiline CSV cells are not supported")
            fields = dict(zip(header, row, strict=True))
            current = metadata(fields)
            if period is not None and current != period:
                raise IngestionError("Statement rows must share one period and scope")
            period = current
            rows.append(fields)
            if fields["key"] in FIELDS:
                candidates.append(
                    {
                        "key": fields["key"],
                        "raw": fields["value"],
                        "locator": {"row": row_number, "column": "value"},
                    }
                )
        if not rows or not candidates or period is None:
            raise IngestionError("CSV contains no supported financial fields")
    except (csv.Error, StopIteration) as exc:
        raise IngestionError("Malformed CSV") from exc
    return {
        "metadata": period,
        "candidates": candidates,
        "rows": rows,
        "pages": [],
        "parser_version": PARSER_VERSION,
    }


def parse_pdf(data: bytes) -> dict[str, Any]:
    from pypdf import PdfReader

    if not data.startswith(b"%PDF-"):
        raise IngestionError("Invalid PDF signature")
    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise IngestionError("Encrypted PDFs are not supported")
    if not 1 <= len(reader.pages) <= 100:
        raise IngestionError("PDF must contain between 1 and 100 pages")
    pages: list[str] = []
    candidates: list[dict[str, Any]] = []
    values: dict[str, str] = {}
    total = 0
    for page_number, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > 20_000_000:
            raise IngestionError("PDF page content exceeds the extraction limit")
        normalized = unicodedata.normalize(
            "NFC", (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
        )
        total += len(normalized)
        if total > MAX_TEXT_CHARS:
            raise IngestionError("PDF extracted text exceeds the limit")
        pages.append(normalized)
        for match in re.finditer(r"(?m)^([a-z_]+):[ \t]*([^\n]*)", normalized):
            key, raw = match.group(1), match.group(2)
            if key in META:
                if key in values and values[key] != raw:
                    raise IngestionError("Conflicting statement metadata")
                values[key] = raw
            elif key in FIELDS:
                candidates.append(
                    {
                        "key": key,
                        "raw": raw,
                        "locator": {
                            "page": page_number,
                            "start": match.start(2),
                            "end": match.end(2),
                        },
                    }
                )
    if not any(page.strip() for page in pages) or not candidates:
        raise IngestionError("PDF contains no supported text fields; OCR is not available")
    return {
        "metadata": metadata(values),
        "candidates": candidates,
        "pages": pages,
        "rows": [],
        "parser_version": PARSER_VERSION,
    }


def parse_document(data: bytes, media_type: str, timeout: float = 15) -> dict[str, Any]:
    if not data or len(data) > MAX_FILE_BYTES:
        raise IngestionError("Document is empty or exceeds 10 MiB")
    try:
        process = subprocess.run(
            [sys.executable, "-m", "credit_support.parsers", media_type],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise IngestionError("Document parsing exceeded the time limit") from exc
    if process.returncode != 0:
        raise IngestionError("Document parser could not read the file")
    try:
        result: dict[str, Any] = json.loads(process.stdout)
    except (ValueError, UnicodeDecodeError) as exc:
        raise IngestionError("Document parser returned invalid output") from exc
    if "error" in result:
        raise IngestionError(result["error"])
    return result


def main() -> None:
    # Linux containers impose a hard process memory ceiling; Windows uses timeout/text limits.
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    try:
        data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if not data or len(data) > MAX_FILE_BYTES:
            raise IngestionError("Document is empty or exceeds 10 MiB")
        if sys.argv[1] == "text/csv":
            result = parse_csv(data)
        elif sys.argv[1] == "application/pdf":
            result = parse_pdf(data)
        else:
            raise IngestionError("Unsupported document media type")
    except IngestionError as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "Malformed or unreadable document"}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
