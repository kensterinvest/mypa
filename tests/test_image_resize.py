"""Image resize at ingest — keeps phone photos manageable + strips EXIF
(which carries GPS by default). Skipped gracefully if Pillow not installed."""
import io
import os
import tempfile
from pathlib import Path

os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-resize")
os.environ.setdefault("NTFY_USER_MGMT_ENABLED", "false")

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

from mypa import attachments as att_lib
from mypa import users as users_lib
from mypa.db import Base, engine, session_factory
from mypa.schemas import ItemCreate
from mypa import service, settings as settings_mod
from tests.conftest import _apply_oauth_schema


@pytest.fixture
def tmp_blob_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("BLOB_DIR", td)
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "10485760")
        monkeypatch.setenv("MAX_USER_BYTES", "10485760")
        # Re-enable resize for THIS test module — test_attachment_limits.py
        # may have set IMAGE_RESIZE_ENABLED=false at process scope. monkeypatch
        # restores it after each test.
        monkeypatch.setenv("IMAGE_RESIZE_ENABLED", "true")
        settings_mod._settings = None
        yield Path(td)


def _setup(tmp_blob_dir):
    Base.metadata.create_all(engine())
    _apply_oauth_schema()
    S = session_factory()
    with S() as db:
        u = users_lib.create_user(db, "a@e.com", "alice-pw-1234567", name="A", is_admin=True)
        it = service.create_item(db, ItemCreate(kind="note", title="x"), user_id=u.id)
    return u.id, it.id


def _make_jpeg(w: int, h: int) -> bytes:
    """Generate a JPEG of given dimensions in-memory."""
    img = Image.new("RGB", (w, h), color=(200, 150, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _make_png(w: int, h: int) -> bytes:
    img = Image.new("RGBA", (w, h), color=(50, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_resize_kicks_in_above_max_dimension(tmp_blob_dir, monkeypatch):
    """A 3000×2000 JPEG with max_dim=2048 → resized to 2048×~1365."""
    monkeypatch.setenv("IMAGE_MAX_DIMENSION", "2048")
    settings_mod._settings = None
    big = _make_jpeg(3000, 2000)
    resized = att_lib.resize_image_if_large(big, "image/jpeg")
    # Output is a different (smaller) image
    assert resized != big
    out = Image.open(io.BytesIO(resized))
    assert max(out.size) == 2048
    # Aspect ratio preserved within rounding tolerance
    assert abs(out.size[0] / out.size[1] - 3000 / 2000) < 0.01


def test_resize_skipped_when_image_already_small(tmp_blob_dir, monkeypatch):
    """A 100×100 JPEG with max_dim=2048 → still resized to strip EXIF, but
    only if the rewrite is actually smaller. For tiny clean JPEGs the
    rewrite is often LARGER (re-encoding overhead) and original is kept."""
    monkeypatch.setenv("IMAGE_MAX_DIMENSION", "2048")
    settings_mod._settings = None
    small = _make_jpeg(100, 100)
    out = att_lib.resize_image_if_large(small, "image/jpeg")
    # Dimensions unchanged either way
    out_img = Image.open(io.BytesIO(out))
    assert out_img.size == (100, 100)


def test_resize_disabled_via_env(tmp_blob_dir, monkeypatch):
    """IMAGE_RESIZE_ENABLED=false → original bytes returned untouched."""
    monkeypatch.setenv("IMAGE_RESIZE_ENABLED", "false")
    settings_mod._settings = None
    big = _make_jpeg(3000, 2000)
    out = att_lib.resize_image_if_large(big, "image/jpeg")
    assert out == big


def test_resize_strips_exif(tmp_blob_dir, monkeypatch):
    """A JPEG with embedded EXIF must come out with no EXIF after resize."""
    monkeypatch.setenv("IMAGE_MAX_DIMENSION", "200")
    settings_mod._settings = None
    img = Image.new("RGB", (1000, 1000), color="red")
    # Embed an EXIF blob containing a distinctive marker we can grep for.
    # The save(exif=...) parameter takes a bytes object — minimum valid
    # EXIF header is 'Exif\x00\x00' followed by TIFF header. Pillow
    # accepts anything starting with this prefix even if the rest is
    # garbage for our marker purposes.
    marker = b"MYPA_EXIF_MARKER_DO_NOT_LEAK"
    fake_exif = b"Exif\x00\x00" + b"\x00" * 16 + marker + b"\x00" * 64
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=fake_exif, quality=92)
    src = buf.getvalue()
    assert marker in src   # confirm EXIF was embedded

    resized = att_lib.resize_image_if_large(src, "image/jpeg")
    assert marker not in resized   # EXIF stripped after our re-save


def test_resize_skipped_for_gif(tmp_blob_dir):
    """GIF might be animated — never resize. Original returned untouched."""
    img = Image.new("RGB", (3000, 2000), color="white")
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    gif_bytes = buf.getvalue()
    out = att_lib.resize_image_if_large(gif_bytes, "image/gif")
    assert out == gif_bytes


def test_resize_skipped_for_pdf():
    """Non-image MIME — never resize."""
    pdf = b"%PDF-1.4\n%fake pdf content"
    out = att_lib.resize_image_if_large(pdf, "application/pdf")
    assert out == pdf


def test_create_attachment_stores_resized_image(tmp_blob_dir, monkeypatch):
    """End-to-end: a big JPEG goes through create_attachment, ends up stored
    at the post-resize size (smaller), with the post-resize sha256."""
    monkeypatch.setenv("IMAGE_MAX_DIMENSION", "256")
    settings_mod._settings = None
    aid, item_id = _setup(tmp_blob_dir)
    big = _make_jpeg(1000, 800)
    big_size = len(big)

    S = session_factory()
    with S() as db:
        att = att_lib.create_attachment(
            db, user_id=aid, data=big, mime="image/jpeg", item_id=item_id,
        )
    # Stored size MUCH smaller than upload
    assert att.bytes < big_size
    # Disk file contents have the resized dimensions
    disk_data = (tmp_blob_dir / att.path).read_bytes()
    out_img = Image.open(io.BytesIO(disk_data))
    assert max(out_img.size) == 256


def test_resize_jpeg_with_alpha_via_png_path(tmp_blob_dir, monkeypatch):
    """PNG with alpha channel resized: stays PNG (no flatten-to-JPEG)."""
    monkeypatch.setenv("IMAGE_MAX_DIMENSION", "256")
    settings_mod._settings = None
    rgba = _make_png(1000, 800)
    resized = att_lib.resize_image_if_large(rgba, "image/png")
    out = Image.open(io.BytesIO(resized))
    assert out.mode in ("RGBA", "P")   # alpha preserved
    assert max(out.size) == 256
