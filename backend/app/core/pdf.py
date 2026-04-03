from __future__ import annotations

from textwrap import wrap


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(text: str, width: int = 92) -> list[str]:
    wrapped: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        expanded = raw_line.expandtabs(4)
        if not expanded:
            wrapped.append("")
            continue
        wrapped.extend(wrap(expanded, width=width, replace_whitespace=False, drop_whitespace=False) or [""])
    return wrapped


def render_pdf_document(title: str, body_text: str) -> bytes:
    lines = [title.strip() or "Document", "", *_wrap_lines(body_text)]
    page_width = 612
    page_height = 792
    margin_left = 50
    margin_top = 50
    margin_bottom = 50
    line_height = 14
    start_y = page_height - margin_top
    lines_per_page = max(int((start_y - margin_bottom) / line_height), 1)
    pages = [lines[index : index + lines_per_page] for index in range(0, len(lines), lines_per_page)] or [[title]]

    objects: list[bytes] = []

    def add_object(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    font_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    content_ids: list[int] = []
    page_ids: list[int] = []

    for page_lines in pages:
        stream_lines = [b"BT", b"/F1 11 Tf", f"{margin_left} {start_y} Td".encode("ascii"), f"{line_height} TL".encode("ascii")]
        for index, line in enumerate(page_lines):
            escaped = _escape_pdf_text(line)
            if index == 0:
                stream_lines.append(f"({escaped}) Tj".encode("utf-8"))
            else:
                stream_lines.append(f"T* ({escaped}) Tj".encode("utf-8"))
        stream_lines.append(b"ET")
        stream = b"\n".join(stream_lines)
        content_id = add_object(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")
        content_ids.append(content_id)
        page_id = add_object(b"")
        page_ids.append(page_id)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    pages_id = add_object(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii"))

    for page_id, content_id in zip(page_ids, content_ids, strict=True):
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")

    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)