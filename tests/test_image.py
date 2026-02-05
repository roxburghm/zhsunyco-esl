"""
Test suite for zhsunyco_esl.image module.

Tests bitplane color mapping (Section 7.1):
  - BW plane: Value 0 = White (no ink), Value 1 = Black (ink)
  - Red plane: Value 0 = No red ink, Value 1 = Red ink
"""

import sys
import os
import tempfile
from unittest.mock import patch

import pytest
from PIL import Image

# Ensure the src directory is importable even without an editable install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zhsunyco_esl.image import _get_palette_color, dither_image, resize_image, process_image
from zhsunyco_esl.models import LabelConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_solid_image(width, height, color):
    """Create a solid-color RGB image."""
    img = Image.new("RGB", (width, height), color)
    return img


def _make_single_pixel_image(color):
    """Create a 1x1 RGB image with the given color."""
    return _make_solid_image(1, 1, color)


# ===========================================================================
# 1. Polarity Tests (V2 compliance)
# ===========================================================================

class TestPolarityV2:
    """Verify that _get_palette_color returns correct V2 bitplane values."""

    def test_pure_black_pixel(self):
        """Pure black (0,0,0) -> bw_bit=1 (ink), red_bit=0 (no red)."""
        r, g, b, bw_bit, red_bit = _get_palette_color(0, 0, 0, "BWR")
        assert bw_bit == 1, "Black pixel BW bit must be 1 (ink present)"
        assert red_bit == 0, "Black pixel red bit must be 0 (no red ink)"
        assert (r, g, b) == (0, 0, 0)

    def test_pure_black_pixel_bw_mode(self):
        """Pure black in BW mode -> bw_bit=1, red_bit=0."""
        r, g, b, bw_bit, red_bit = _get_palette_color(0, 0, 0, "BW")
        assert bw_bit == 1
        assert red_bit == 0

    def test_pure_white_pixel(self):
        """Pure white (255,255,255) -> bw_bit=0 (no ink), red_bit=0."""
        r, g, b, bw_bit, red_bit = _get_palette_color(255, 255, 255, "BWR")
        assert bw_bit == 0, "White pixel BW bit must be 0 (no ink)"
        assert red_bit == 0, "White pixel red bit must be 0 (no red ink)"
        assert (r, g, b) == (255, 255, 255)

    def test_pure_white_pixel_bw_mode(self):
        """Pure white in BW mode -> bw_bit=0, red_bit=0."""
        r, g, b, bw_bit, red_bit = _get_palette_color(255, 255, 255, "BW")
        assert bw_bit == 0
        assert red_bit == 0

    def test_pure_red_pixel_bwr(self):
        """Pure red (255,0,0) in BWR mode -> bw_bit=0, red_bit=1."""
        r, g, b, bw_bit, red_bit = _get_palette_color(255, 0, 0, "BWR")
        assert bw_bit == 0, "Red pixel BW bit must be 0 (no black ink at red pixel)"
        assert red_bit == 1, "Red pixel red bit must be 1 (red ink present)"
        assert (r, g, b) == (255, 0, 0)

    def test_red_pixel_bw_bit_must_be_zero(self):
        """Red pixel's BW bit must be 0 -- no black ink under red."""
        _, _, _, bw_bit, red_bit = _get_palette_color(255, 0, 0, "BWR")
        assert bw_bit == 0, (
            "Red pixel must have bw_bit=0 so no black ink is laid "
            "under the red ink"
        )
        assert red_bit == 1

    def test_bw_mode_never_produces_red(self):
        """In BW mode, no input can produce red_bit=1."""
        # Exhaustively check a set of colors including red itself
        test_colors = [
            (0, 0, 0),
            (255, 255, 255),
            (255, 0, 0),
            (128, 0, 0),
            (200, 50, 50),
            (0, 255, 0),
            (0, 0, 255),
            (128, 128, 128),
        ]
        for color in test_colors:
            _, _, _, _bw, red_bit = _get_palette_color(*color, "BW")
            assert red_bit == 0, (
                f"BW mode must never produce red_bit=1, but got it for {color}"
            )

    def test_bw_mode_only_black_and_white(self):
        """BW mode only returns (0,0,0) or (255,255,255)."""
        test_colors = [
            (0, 0, 0),
            (255, 255, 255),
            (255, 0, 0),
            (100, 200, 50),
            (128, 128, 128),
        ]
        for color in test_colors:
            r, g, b, _, _ = _get_palette_color(*color, "BW")
            assert (r, g, b) in [(0, 0, 0), (255, 255, 255)], (
                f"BW mode returned unexpected color ({r},{g},{b}) for input {color}"
            )


# ===========================================================================
# 2. Color Quantization Tests
# ===========================================================================

class TestColorQuantization:
    """Verify nearest-color mapping for various inputs."""

    def test_dark_gray_maps_to_black(self):
        """Dark gray (50,50,50) should map to black."""
        r, g, b, bw_bit, red_bit = _get_palette_color(50, 50, 50, "BWR")
        assert (r, g, b) == (0, 0, 0), "Dark gray should quantize to black"
        assert bw_bit == 1
        assert red_bit == 0

    def test_light_gray_maps_to_white(self):
        """Light gray (200,200,200) should map to white."""
        r, g, b, bw_bit, red_bit = _get_palette_color(200, 200, 200, "BWR")
        assert (r, g, b) == (255, 255, 255), "Light gray should quantize to white"
        assert bw_bit == 0
        assert red_bit == 0

    def test_pinkish_maps_to_red_in_bwr(self):
        """Pinkish color (200,50,50) should map to red in BWR mode."""
        r, g, b, bw_bit, red_bit = _get_palette_color(200, 50, 50, "BWR")
        assert (r, g, b) == (255, 0, 0), "Pinkish should quantize to red in BWR"
        assert bw_bit == 0
        assert red_bit == 1

    def test_pinkish_maps_to_black_in_bw(self):
        """Pinkish color (200,50,50) should map to black in BW mode (closer to
        black than white in Euclidean distance)."""
        # dist_black = 200^2 + 50^2 + 50^2 = 40000 + 2500 + 2500 = 45000
        # dist_white = 55^2 + 205^2 + 205^2 = 3025 + 42025 + 42025 = 87075
        r, g, b, bw_bit, red_bit = _get_palette_color(200, 50, 50, "BW")
        assert (r, g, b) == (0, 0, 0), "Pinkish should quantize to black in BW mode"
        assert bw_bit == 1
        assert red_bit == 0

    def test_green_maps_to_nearest_in_bwr(self):
        """Green (0,255,0) in BWR mode -> should map to one of {black, white, red}.

        dist_black = 0 + 255^2 + 0    = 65025
        dist_white = 255^2 + 0 + 255^2 = 130050
        dist_red   = 255^2 + 255^2 + 0 = 130050
        => nearest is black.
        """
        r, g, b, bw_bit, red_bit = _get_palette_color(0, 255, 0, "BWR")
        assert (r, g, b) == (0, 0, 0), "Green should quantize to black in BWR"
        assert bw_bit == 1
        assert red_bit == 0

    def test_midtone_red(self):
        """A moderately red color (180, 30, 30) should map to red in BWR.

        dist_black = 180^2 + 30^2 + 30^2 = 32400 + 900 + 900 = 34200
        dist_white = 75^2 + 225^2 + 225^2 = 5625 + 50625 + 50625 = 106875
        dist_red   = 75^2 + 30^2 + 30^2   = 5625 + 900 + 900 = 7425
        => nearest is red.
        """
        r, g, b, bw_bit, red_bit = _get_palette_color(180, 30, 30, "BWR")
        assert (r, g, b) == (255, 0, 0)
        assert bw_bit == 0
        assert red_bit == 1

    def test_exact_palette_colors_pass_through(self):
        """Exact palette colors should map to themselves."""
        for color, expected_bw, expected_red in [
            ((0, 0, 0), 1, 0),
            ((255, 255, 255), 0, 0),
            ((255, 0, 0), 0, 1),
        ]:
            r, g, b, bw, red = _get_palette_color(*color, "BWR")
            assert (r, g, b) == color
            assert bw == expected_bw
            assert red == expected_red


# ===========================================================================
# 3. Dither Tests
# ===========================================================================

class TestDither:
    """Test the Floyd-Steinberg dithering and bitplane extraction."""

    def test_all_white_image(self):
        """All-white image -> every bw_bit=0, every red_bit=0."""
        w, h = 16, 16
        img = _make_solid_image(w, h, (255, 255, 255))
        plane_bw, plane_red = dither_image(img, w, h, "BWR")

        assert all(b == 0 for b in plane_bw), "All-white image: every BW bit should be 0"
        assert all(r == 0 for r in plane_red), "All-white image: every red bit should be 0"

    def test_all_black_image(self):
        """All-black image -> every bw_bit=1, every red_bit=0."""
        w, h = 16, 16
        img = _make_solid_image(w, h, (0, 0, 0))
        plane_bw, plane_red = dither_image(img, w, h, "BWR")

        assert all(b == 1 for b in plane_bw), "All-black image: every BW bit should be 1"
        assert all(r == 0 for r in plane_red), "All-black image: every red bit should be 0"

    def test_all_red_image_bwr(self):
        """All-red image in BWR -> every bw_bit=0, every red_bit=1."""
        w, h = 16, 16
        img = _make_solid_image(w, h, (255, 0, 0))
        plane_bw, plane_red = dither_image(img, w, h, "BWR")

        assert all(b == 0 for b in plane_bw), "All-red image: every BW bit should be 0"
        assert all(r == 1 for r in plane_red), "All-red image: every red bit should be 1"

    def test_plane_sizes_match_dimensions(self):
        """Both planes must have exactly width * height elements."""
        w, h = 20, 10
        img = _make_solid_image(w, h, (128, 128, 128))
        plane_bw, plane_red = dither_image(img, w, h, "BWR")

        assert len(plane_bw) == w * h, f"BW plane size should be {w*h}, got {len(plane_bw)}"
        assert len(plane_red) == w * h, f"Red plane size should be {w*h}, got {len(plane_red)}"

    def test_plane_sizes_various_dimensions(self):
        """Plane sizes for several non-trivial dimensions."""
        for w, h in [(1, 1), (7, 3), (100, 50), (296, 128)]:
            img = _make_solid_image(w, h, (100, 100, 100))
            plane_bw, plane_red = dither_image(img, w, h, "BWR")
            assert len(plane_bw) == w * h
            assert len(plane_red) == w * h

    def test_bw_mode_red_plane_all_zeros(self):
        """In BW mode, the red plane must be all zeros regardless of input."""
        w, h = 16, 16
        # Use a red-ish image to tempt the code into setting red bits
        img = _make_solid_image(w, h, (255, 0, 0))
        plane_bw, plane_red = dither_image(img, w, h, "BW")

        assert all(r == 0 for r in plane_red), (
            "BW mode: red plane must be all zeros even for red input"
        )

    def test_bw_mode_planes_only_zero_and_one(self):
        """BW plane values must only be 0 or 1."""
        w, h = 32, 32
        img = _make_solid_image(w, h, (100, 150, 200))
        plane_bw, plane_red = dither_image(img, w, h, "BWR")

        assert all(v in (0, 1) for v in plane_bw), "BW plane must contain only 0 or 1"
        assert all(v in (0, 1) for v in plane_red), "Red plane must contain only 0 or 1"

    def test_dither_mixed_image_produces_both_bw_values(self):
        """A 50% gray image should dither to a mix of black and white pixels."""
        w, h = 64, 64
        img = _make_solid_image(w, h, (128, 128, 128))
        plane_bw, plane_red = dither_image(img, w, h, "BW")

        count_0 = plane_bw.count(0)
        count_1 = plane_bw.count(1)
        total = w * h
        # A 50% gray should produce a roughly even split (allow wide margin for
        # dithering patterns); just verify both values appear.
        assert count_0 > 0, "50% gray should produce some black pixels"
        assert count_1 > 0, "50% gray should produce some white pixels"
        # Rough check: each should be at least 20% of total
        assert count_0 > total * 0.2, "Expected substantial black pixel count"
        assert count_1 > total * 0.2, "Expected substantial white pixel count"

    def test_no_dither_gray_maps_to_single_color(self):
        """With dither=False, 50% gray maps to one color (no error diffusion)."""
        w, h = 64, 64
        img = _make_solid_image(w, h, (128, 128, 128))
        plane_bw, plane_red = dither_image(img, w, h, "BW", dither=False)

        # Without dithering, all pixels snap to nearest color (all same)
        unique_vals = set(plane_bw)
        assert len(unique_vals) == 1, (
            f"No-dither gray should map uniformly, got {unique_vals}"
        )

    def test_no_dither_preserves_sharp_edges(self):
        """With dither=False, a black/white image stays crisp."""
        w, h = 16, 16
        img = Image.new("RGB", (w, h), "white")
        pixels = img.load()
        # Left half black, right half white
        for y in range(h):
            for x in range(w // 2):
                pixels[x, y] = (0, 0, 0)
        plane_bw, _ = dither_image(img, w, h, "BW", dither=False)

        # Left half should be all 1 (black ink), right half all 0 (white)
        for y in range(h):
            for x in range(w):
                idx = y * w + x
                if x < w // 2:
                    assert plane_bw[idx] == 1, f"Left pixel ({x},{y}) should be black"
                else:
                    assert plane_bw[idx] == 0, f"Right pixel ({x},{y}) should be white"

    def test_dither_flag_default_is_true(self):
        """dither_image without dither kwarg uses dithering (default=True)."""
        w, h = 32, 32
        img = _make_solid_image(w, h, (128, 128, 128))
        plane_dithered, _ = dither_image(img, w, h, "BW")
        # Dithered gray should have both 0 and 1 values
        assert 0 in plane_dithered and 1 in plane_dithered


# ===========================================================================
# 4. Resize Tests
# ===========================================================================

class TestResize:
    """Test image resizing behavior."""

    def test_resize_to_exact_dimensions(self):
        """Image is resized to exact target dimensions."""
        img = Image.new("RGB", (500, 400), (0, 0, 0))
        resized = resize_image(img, 296, 128)
        assert resized.size == (296, 128)

    def test_resize_upscale(self):
        """Small image is upscaled to target dimensions."""
        img = Image.new("RGB", (10, 5), (255, 255, 255))
        resized = resize_image(img, 296, 128)
        assert resized.size == (296, 128)

    def test_resize_same_size(self):
        """Image already at target size remains the same size."""
        img = Image.new("RGB", (296, 128), (128, 128, 128))
        resized = resize_image(img, 296, 128)
        assert resized.size == (296, 128)

    def test_resize_uses_lanczos(self):
        """Verify that LANCZOS resampling is used by checking the code calls
        img.resize with Image.Resampling.LANCZOS."""
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        with patch.object(img, "resize", wraps=img.resize) as mock_resize:
            resize_image(img, 50, 50)
            mock_resize.assert_called_once_with((50, 50), Image.Resampling.LANCZOS)

    def test_resize_preserves_mode(self):
        """Resized image retains RGB mode."""
        img = Image.new("RGB", (200, 200), (50, 100, 150))
        resized = resize_image(img, 296, 128)
        assert resized.mode == "RGB"

    def test_resize_non_standard_dimensions(self):
        """Resize works for arbitrary non-standard target dimensions."""
        img = Image.new("RGB", (300, 300), (0, 0, 0))
        for target_w, target_h in [(1, 1), (7, 3), (1000, 500)]:
            resized = resize_image(img, target_w, target_h)
            assert resized.size == (target_w, target_h)


# ===========================================================================
# 5. Process Image Integration Tests
# ===========================================================================

class TestProcessImage:
    """End-to-end tests: create a temp image, call process_image, verify output."""

    def test_process_image_plane_dimensions(self):
        """process_image returns planes with correct dimensions."""
        config = LabelConfig(width=296, height=128)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img = _make_solid_image(400, 300, (100, 100, 100))
            img.save(tmp.name)
            tmp_path = tmp.name

        try:
            plane_bw, plane_red = process_image(tmp_path, config, "BWR")
            expected = config.width * config.height
            assert len(plane_bw) == expected, (
                f"BW plane length {len(plane_bw)} != expected {expected}"
            )
            assert len(plane_red) == expected, (
                f"Red plane length {len(plane_red)} != expected {expected}"
            )
        finally:
            os.unlink(tmp_path)

    def test_process_image_white_png(self):
        """White PNG -> all bw_bit=0, all red_bit=0."""
        config = LabelConfig(width=50, height=50)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img = _make_solid_image(50, 50, (255, 255, 255))
            img.save(tmp.name)
            tmp_path = tmp.name

        try:
            plane_bw, plane_red = process_image(tmp_path, config, "BWR")
            assert all(b == 0 for b in plane_bw)
            assert all(r == 0 for r in plane_red)
        finally:
            os.unlink(tmp_path)

    def test_process_image_black_png(self):
        """Black PNG -> all bw_bit=1, all red_bit=0."""
        config = LabelConfig(width=50, height=50)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img = _make_solid_image(50, 50, (0, 0, 0))
            img.save(tmp.name)
            tmp_path = tmp.name

        try:
            plane_bw, plane_red = process_image(tmp_path, config, "BWR")
            assert all(b == 1 for b in plane_bw)
            assert all(r == 0 for r in plane_red)
        finally:
            os.unlink(tmp_path)

    def test_process_image_red_png_bwr(self):
        """Red PNG in BWR mode -> all bw_bit=0, all red_bit=1."""
        config = LabelConfig(width=50, height=50)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img = _make_solid_image(50, 50, (255, 0, 0))
            img.save(tmp.name)
            tmp_path = tmp.name

        try:
            plane_bw, plane_red = process_image(tmp_path, config, "BWR")
            assert all(b == 0 for b in plane_bw)
            assert all(r == 1 for r in plane_red)
        finally:
            os.unlink(tmp_path)

    def test_process_image_bw_mode(self):
        """BW mode: red plane should always be zeros even with red input."""
        config = LabelConfig(width=50, height=50)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img = _make_solid_image(50, 50, (255, 0, 0))
            img.save(tmp.name)
            tmp_path = tmp.name

        try:
            plane_bw, plane_red = process_image(tmp_path, config, "BW")
            assert all(r == 0 for r in plane_red), "BW mode red plane must be all zeros"
        finally:
            os.unlink(tmp_path)

    def test_process_image_resizes_before_dither(self):
        """An oversized image is resized to config dimensions before dithering,
        so output planes match config.width * config.height."""
        config = LabelConfig(width=100, height=80)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            # Source image is much larger than target
            img = _make_solid_image(800, 600, (128, 64, 64))
            img.save(tmp.name)
            tmp_path = tmp.name

        try:
            plane_bw, plane_red = process_image(tmp_path, config, "BWR")
            expected = config.width * config.height
            assert len(plane_bw) == expected
            assert len(plane_red) == expected
        finally:
            os.unlink(tmp_path)

    def test_process_image_values_are_binary(self):
        """All plane values must be 0 or 1."""
        config = LabelConfig(width=64, height=64)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            # Use a gradient-ish image with varied colors
            img = Image.new("RGB", (64, 64))
            pixels = img.load()
            for y in range(64):
                for x in range(64):
                    pixels[x, y] = (x * 4, y * 4, (x + y) * 2)
            img.save(tmp.name)
            tmp_path = tmp.name

        try:
            plane_bw, plane_red = process_image(tmp_path, config, "BWR")
            assert all(v in (0, 1) for v in plane_bw), "BW plane must be binary"
            assert all(v in (0, 1) for v in plane_red), "Red plane must be binary"
        finally:
            os.unlink(tmp_path)
