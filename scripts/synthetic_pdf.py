"""Generate small synthetic PDF input for examples and tests."""
from pathlib import Path


def make_pdf(path: Path, *, rotation: int = 0, text: bool = True, pages: int = 2, page_content: bytes | None = None) -> Path:
    """Build a tiny synthetic PDF; no customer documents or external fixture files."""
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for index in range(pages):
        page_id = len(objects) + 1
        page_ids.append(page_id)
        content_id = page_id + 1
        content = b"0.1 0.3 0.7 RG 2 w 15 15 210 290 re S\n"
        if text:
            content += f"BT /F1 18 Tf 30 250 Td (Hello HTML {index + 1}) Tj ET\n".encode()
        if page_content is not None:
            content=page_content
        objects.extend([
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 240 320] /Rotate {rotation} /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode(),
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream",
        ])
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {pages} >>".encode()
    payload = bytearray(b"%PDF-1.7\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(payload)
    return path
