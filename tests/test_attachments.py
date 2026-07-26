"""
Attachments and local text extraction.

The PDF cases use a real PDF built in the test rather than a fixture blob, so
the extractor is exercised against an actual file format. The failure that
matters most is a *silent* one: a scanned PDF has no text layer, and returning
an empty string that looks like success would send an empty document into a
prompt and produce confidently baseless output.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_att_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import attachment_service as svc  # noqa: E402

PROJECT = "attachment-test-project"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Keep every test out of the user's real workspace."""
    from src.services import terminal_service

    monkeypatch.setattr(terminal_service, "project_root",
                        lambda pid: Path(tmp_path) / pid)
    (Path(tmp_path) / PROJECT).mkdir(parents=True, exist_ok=True)
    yield


def make_pdf(text: str) -> bytes:
    """A genuine one-page PDF containing `text`."""
    from pypdf import PdfWriter
    import io

    # pypdf cannot author content streams, so build the minimal PDF by hand.
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


class TestStorage:
    def test_saving_records_size_and_hash(self):
        row = svc.save(PROJECT, "notes.txt", b"hello world")
        assert row["size"] == 11 and len(row["sha256"]) == 64
        assert Path(row["path"]).exists()

    def test_an_empty_file_is_refused(self):
        with pytest.raises(svc.AttachmentError, match="empty"):
            svc.save(PROJECT, "nothing.txt", b"")

    def test_an_oversized_file_is_refused_with_the_limit(self):
        with pytest.raises(svc.AttachmentError, match="limit is"):
            svc.save(PROJECT, "huge.bin", b"x" * (svc.MAX_BYTES + 1))

    @pytest.mark.parametrize("evil", [
        "../../../etc/passwd", "/etc/passwd", "..\\..\\windows\\system32",
    ])
    def test_a_path_traversing_filename_cannot_escape(self, evil):
        row = svc.save(PROJECT, evil, b"data")
        stored = Path(row["path"]).resolve()
        assert stored.parent == svc.attachments_dir(PROJECT).resolve()
        assert "/etc/passwd" not in str(stored)

    def test_same_named_files_do_not_collide(self):
        a = svc.save(PROJECT, "same.txt", b"first")
        b = svc.save(PROJECT, "same.txt", b"second")
        assert a["path"] != b["path"]
        assert Path(a["path"]).read_bytes() == b"first"

    def test_list_and_delete(self):
        row = svc.save(PROJECT, "temp.txt", b"bye")
        assert any(r["id"] == row["id"] for r in svc.list_attachments(PROJECT))
        assert svc.delete(PROJECT, row["id"]) is True
        assert svc.delete(PROJECT, row["id"]) is False
        assert not Path(row["path"]).exists()


class TestExtraction:
    def test_plain_text(self):
        row = svc.save(PROJECT, "readme.md", b"# Title\n\nSome content here.")
        assert row["extract_mode"] == "text"
        assert "Some content here" in svc.text_of(PROJECT, row["id"])

    def test_invalid_utf8_does_not_crash(self):
        row = svc.save(PROJECT, "mixed.txt", b"ok \xff\xfe bytes")
        assert row["extract_mode"] == "text"
        assert "ok" in svc.text_of(PROJECT, row["id"])

    def test_a_real_pdf_yields_its_text(self):
        row = svc.save(PROJECT, "doc.pdf", make_pdf("Extractable content"))
        assert row["extract_mode"] == "pypdf"
        assert row["pages"] == 1
        assert "Extractable content" in svc.text_of(PROJECT, row["id"])

    def test_a_pdf_with_no_text_layer_says_so(self):
        """The silent failure that matters: empty is not the same as success."""
        empty = make_pdf("").replace(b"BT /F1 12 Tf 72 720 Td () Tj ET", b" " * 34)
        row = svc.save(PROJECT, "scan.pdf", empty)
        assert row["extract_mode"] in ("needs_ocr", "failed")
        assert row["note"]                      # never silently empty

    def test_a_corrupt_pdf_degrades_rather_than_raising(self):
        """pypdf failing must hand off to the next mode, not blow up.

        On macOS `textutil` often salvages something, which is the fallback
        working. What matters is that the recorded mode names whichever
        extractor actually answered, so a caller can judge the result.
        """
        row = svc.save(PROJECT, "broken.pdf", b"%PDF-1.4\nthis is not a pdf")
        assert row["extract_mode"] in ("failed", "unavailable", "needs_ocr",
                                       "textutil")
        assert row["extract_mode"] != "pypdf"      # never claim a clean parse

    def test_an_unsupported_type_is_stored_but_flagged(self):
        row = svc.save(PROJECT, "photo.png", b"\x89PNG\r\n\x1a\n" + b"x" * 50)
        assert row["extract_mode"] == "unsupported"
        assert "stored" in row["note"]

    def test_long_text_is_truncated_and_marked(self):
        row = svc.save(PROJECT, "big.txt", b"a" * (svc.MAX_TEXT + 500))
        assert row["truncated"] is True
        assert row["chars"] <= svc.MAX_TEXT


class TestContextBlock:
    def test_selected_documents_are_rendered_for_a_prompt(self):
        a = svc.save(PROJECT, "one.txt", b"first document body")
        b = svc.save(PROJECT, "two.txt", b"second document body")
        block = svc.context_block(PROJECT, [a["id"], b["id"]])
        assert 'name="one.txt"' in block and "second document body" in block

    def test_no_selection_yields_nothing(self):
        assert svc.context_block(PROJECT, []) == ""

    def test_budget_is_shared_between_documents(self):
        """Three files must not each claim the whole window."""
        ids = [svc.save(PROJECT, f"f{i}.txt", b"x" * 20_000)["id"] for i in range(3)]
        block = svc.context_block(PROJECT, ids, budget=9_000)
        assert len(block) < 15_000
        assert block.count("<document") == 3     # all three still represented

    def test_a_missing_attachment_is_skipped_not_fatal(self):
        good = svc.save(PROJECT, "real.txt", b"present")
        block = svc.context_block(PROJECT, [good["id"], "does-not-exist"])
        assert "present" in block


class TestApi:
    def test_upload_list_and_delete(self, client):
        r = client.post(f"/api/v1/attachments/project/{PROJECT}",
                        files={"file": ("api.txt", b"uploaded body", "text/plain")})
        assert r.status_code == 200, r.text
        aid = r.json()["id"]

        listing = client.get(f"/api/v1/attachments/project/{PROJECT}").json()
        assert any(a["id"] == aid for a in listing["attachments"])

        text = client.get(f"/api/v1/attachments/project/{PROJECT}/{aid}/text").json()
        assert "uploaded body" in text["text"]

        assert client.delete(f"/api/v1/attachments/project/{PROJECT}/{aid}").status_code == 200

    def test_uploading_an_empty_file_is_a_400(self, client):
        r = client.post(f"/api/v1/attachments/project/{PROJECT}",
                        files={"file": ("empty.txt", b"", "text/plain")})
        assert r.status_code == 400

    def test_text_of_a_missing_attachment_is_404(self, client):
        r = client.get(f"/api/v1/attachments/project/{PROJECT}/nope/text")
        assert r.status_code == 404
