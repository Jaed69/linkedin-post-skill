"""Photo privacy helpers built on ImageMagick 7 (`magick`)."""

import os
import shutil
import subprocess
import tempfile

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class PhotoError(Exception):
    """An ImageMagick failure (exit code 1)."""


def image_type(path):
    """Return 'image/jpeg', 'image/png' or None, judged by file content."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return None
    if head.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if head.startswith(PNG_MAGIC):
        return "image/png"
    return None


def _magick(*args):
    if shutil.which("magick") is None:
        raise PhotoError("ImageMagick 7 (`magick`) is not installed or not on PATH")
    proc = subprocess.run(["magick", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise PhotoError(f"magick {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def has_gps(path):
    # identify prints an "unknown image property" warning and nothing on
    # stdout when the tag is absent.
    return bool(_magick("identify", "-format", "%[EXIF:GPSLatitude]", path).strip())


def size_of(path):
    """Width and height after auto-orientation, as the user sees the image."""
    w, h = _magick(path + "[0]", "-auto-orient", "-format", "%w %h", "info:").split()
    return int(w), int(h)


def process_dir(src_dir, out_dir):
    """Write stripped, auto-oriented copies; return (written, had_gps, skipped)."""
    written, had_gps, skipped = [], [], []
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        src = os.path.join(src_dir, name)
        if not os.path.isfile(src):
            continue
        if image_type(src) is None:
            skipped.append(name)
            continue
        if has_gps(src):
            had_gps.append(name)
        dst = os.path.join(out_dir, name)
        _magick(src, "-auto-orient", "-strip", "-quality", "92", dst)
        if has_gps(dst):
            raise PhotoError(f"GPS metadata still present in {dst}")
        written.append(dst)
    return written, had_gps, skipped


def contact_sheet(images, sheet_path):
    _magick("montage", "-label", "%f", *images, "-tile", "4x", "-geometry", "320x320+8+8",
            "-background", "white", "-strip", sheet_path)


def blur_polygon(src, dst, points):
    """Blur the polygon `points` [(x, y), ...] of `src` into a new file `dst`.

    A three-image `-composite` mask blurred the whole frame in ImageMagick 7, so
    this builds a blurred copy, gives it the polygon mask as alpha
    (CopyOpacity), then lays it over the original.
    """
    w, h = size_of(src)
    polygon = "polygon " + " ".join(f"{x},{y}" for x, y in points)
    work = tempfile.mkdtemp(prefix="lipost-blur-")
    try:
        blurred = os.path.join(work, "blurred.png")
        mask = os.path.join(work, "mask.png")
        masked = os.path.join(work, "masked.png")
        _magick(src + "[0]", "-auto-orient", "-resize", "10%", "-blur", "0x6",
                "-resize", f"{w}x{h}!", blurred)
        _magick("-size", f"{w}x{h}", "xc:black", "-fill", "white", "-draw", polygon,
                "-blur", "0x4", mask)
        _magick(blurred, mask, "-alpha", "off", "-compose", "CopyOpacity", "-composite", masked)
        tmp_out = os.path.join(work, "out" + os.path.splitext(dst)[1])
        _magick(src + "[0]", "-auto-orient", masked, "-compose", "over", "-composite",
                "-strip", tmp_out)
        shutil.move(tmp_out, dst)
    finally:
        shutil.rmtree(work, ignore_errors=True)
