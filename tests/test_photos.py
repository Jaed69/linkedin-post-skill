"""CLI tests for `lipost photos` and `lipost blur` using generated images."""

import os
import subprocess
import unittest

from helpers import CliTestCase, gps_of, make_image, make_jpeg_with_exif, sha256_file


def size_of(path):
    out = subprocess.run(["magick", "identify", "-format", "%w %h", path],
                         capture_output=True, text=True, check=True)
    return tuple(int(v) for v in out.stdout.split())


def region_stddev(path, geometry):
    out = subprocess.run(["magick", path, "-crop", geometry, "+repage",
                          "-format", "%[fx:standard_deviation]", "info:"],
                         capture_output=True, text=True, check=True)
    return float(out.stdout)


def region_identical(a, b, geometry):
    # Compare pixel values, not encoded bytes (palette/bit depth may differ).
    crop = lambda p: f"( {p} -crop {geometry} +repage )".split()
    proc = subprocess.run(["magick", "compare", "-metric", "AE", *crop(a), *crop(b), "null:"],
                          capture_output=True, text=True)
    return proc.returncode == 0


class PhotosTest(CliTestCase):
    use_server = False

    def setUp(self):
        super().setUp()
        self.src = self.path("src")
        os.makedirs(self.src)
        self.gps = make_jpeg_with_exif(os.path.join(self.src, "gps.jpg"), size="40x20",
                                       gps=True, orientation=6)
        self.plain = make_image(os.path.join(self.src, "plain.png"))
        with open(os.path.join(self.src, "notes.txt"), "w") as fh:
            fh.write("not an image")
        self.assertTrue(gps_of(self.gps), "fixture must carry GPS")
        self.before = {p: sha256_file(p) for p in (self.gps, self.plain)}

    def test_photos_strips_gps_orients_and_keeps_originals(self):
        out = self.path("out")
        proc = self.run_cli("photos", self.src, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(os.listdir(out)), ["gps.jpg", "plain.png"])
        for name in ("gps.jpg", "plain.png"):
            self.assertEqual(gps_of(os.path.join(out, name)), "")
        # Orientation 6 (rotate 90 CW) means the stripped copy is upright: 20x40.
        self.assertEqual(size_of(os.path.join(out, "gps.jpg")), (20, 40))
        self.assertEqual({p: sha256_file(p) for p in self.before}, self.before)
        self.assertIn("GPS found in 1 original(s)", proc.stdout)
        self.assertIn("gps.jpg", proc.stdout.split("GPS found")[1])
        self.assertNotIn("plain.png", proc.stdout.split("GPS found")[1])
        self.assertIn("verified: no GPS", proc.stdout)
        self.assertIn("Skipped (not JPEG/PNG): notes.txt", proc.stdout)

    def test_photos_contact_sheet(self):
        out, sheet = self.path("out"), self.path("sheet.jpg")
        proc = self.run_cli("photos", self.src, "--out", out, "--sheet", sheet)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.getsize(sheet) > 0)
        self.assertEqual(gps_of(sheet), "")
        self.assertIn(sheet, proc.stdout)

    def test_photos_refuses_output_into_source_dir(self):
        proc = self.run_cli("photos", self.src, "--out", self.src)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must differ", proc.stderr)
        self.assertEqual({p: sha256_file(p) for p in self.before}, self.before)
        self.assertEqual(len(os.listdir(self.src)), 3)


class BlurTest(CliTestCase):
    use_server = False

    def setUp(self):
        super().setUp()
        self.src = self.path("in.png")
        subprocess.run(["magick", "-size", "200x100", "pattern:checkerboard", self.src],
                       check=True)
        self.src_hash = sha256_file(self.src)
        self.polygon = ["10,10", "90,10", "90,90", "10,90"]

    def test_blur_polygon_region_only(self):
        out = self.path("out.png")
        proc = self.run_cli("blur", self.src, out, "--polygon", *self.polygon)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sha256_file(self.src), self.src_hash)
        self.assertEqual(size_of(out), (200, 100))
        inside = "60x60+20+20"
        self.assertLess(region_stddev(out, inside), region_stddev(self.src, inside) / 5)
        self.assertTrue(region_identical(self.src, out, "80x80+110+10"))
        self.assertIn(out, proc.stdout)

    def test_blur_refuses_overwriting_input(self):
        same = os.path.join(self.tmp, ".", "in.png")
        for extra in ([], ["--force"]):
            with self.subTest(extra=extra):
                proc = self.run_cli("blur", self.src, same, "--polygon", *self.polygon, *extra)
                self.assertEqual(proc.returncode, 2)
                self.assertIn("input", proc.stderr)
                self.assertEqual(sha256_file(self.src), self.src_hash)

    def test_blur_refuses_existing_output_without_force(self):
        out = make_image(self.path("exists.png"))
        before = sha256_file(out)
        proc = self.run_cli("blur", self.src, out, "--polygon", *self.polygon)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--force", proc.stderr)
        self.assertEqual(sha256_file(out), before)
        proc = self.run_cli("blur", self.src, out, "--polygon", *self.polygon, "--force")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotEqual(sha256_file(out), before)

    def test_blur_rejects_bad_polygon(self):
        for pts in (["10,10", "20,20"], ["10,10", "20,x", "30,30"]):
            with self.subTest(pts=pts):
                proc = self.run_cli("blur", self.src, self.path("o.png"), "--polygon", *pts)
                self.assertEqual(proc.returncode, 2)
                self.assertFalse(os.path.exists(self.path("o.png")))


if __name__ == "__main__":
    unittest.main()
