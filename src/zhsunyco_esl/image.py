from PIL import Image
from typing import Tuple, List
from .models import LabelConfig

def resize_image(img: Image.Image, width: int, height: int) -> Image.Image:
    """Aggressively resize the image to fit the dimensions."""
    return img.resize((width, height), Image.Resampling.LANCZOS)

def _get_palette_color(r, g, b, color_mode):
    """Returns (r, g, b, bw_bit, red_bit) for the nearest color."""
    dist_black = r**2 + g**2 + b**2
    dist_white = (r-255)**2 + (g-255)**2 + (b-255)**2
    dist_red = (r-255)**2 + g**2 + b**2

    # Hardware polarity: BW plane 1=Black(ink), 0=White(no ink)
    #                   Red plane 0=No red, 1=Red ink
    if color_mode == "BW":
        if dist_black < dist_white:
            return (0, 0, 0, 1, 0)       # Black: bw=1 (ink)
        else:
            return (255, 255, 255, 0, 0)  # White: bw=0 (no ink)

    # BWR Mode
    min_dist = min(dist_black, dist_white, dist_red)
    if min_dist == dist_black:
        return (0, 0, 0, 1, 0)       # Black: bw=1 (ink), red=0
    elif min_dist == dist_white:
        return (255, 255, 255, 0, 0)  # White: bw=0 (no ink), red=0
    else:
        return (255, 0, 0, 0, 1)      # Red: bw=0 (no black ink), red=1

def dither_image(img: Image.Image, width: int, height: int,
                 color_mode: str = "BWR",
                 dither: bool = True) -> Tuple[List[int], List[int]]:
    """Quantize image to palette colors with optional Floyd-Steinberg dithering.

    Args:
        dither: If True, apply Floyd-Steinberg error diffusion. If False,
                use nearest-color quantization only (better for sharp
                graphics like barcodes and text).

    Returns (plane_bw, plane_red) lists.
    """
    img = img.convert("RGB")
    pixels = img.load()

    plane_bw = []
    plane_red = []

    for y in range(height):
        for x in range(width):
            old_r, old_g, old_b = pixels[x, y]
            new_r, new_g, new_b, _, _ = _get_palette_color(old_r, old_g, old_b, color_mode)
            pixels[x, y] = (new_r, new_g, new_b)

            if dither:
                err_r = old_r - new_r
                err_g = old_g - new_g
                err_b = old_b - new_b

                def add_error(nx, ny, factor):
                    if 0 <= nx < width and 0 <= ny < height:
                        nr, ng, nb = pixels[nx, ny]
                        pixels[nx, ny] = (
                            int(max(0, min(255, nr + err_r * factor))),
                            int(max(0, min(255, ng + err_g * factor))),
                            int(max(0, min(255, nb + err_b * factor)))
                        )

                add_error(x + 1, y, 7/16)
                add_error(x - 1, y + 1, 3/16)
                add_error(x, y + 1, 5/16)
                add_error(x + 1, y + 1, 1/16)

    # Extract bit planes from the quantized image
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            _, _, _, bw_bit, red_bit = _get_palette_color(r, g, b, color_mode)
            plane_bw.append(bw_bit)
            plane_red.append(red_bit)

    return plane_bw, plane_red


def process_image(image_path: str, config: LabelConfig,
                  color_mode: str = "BWR",
                  dither: bool = True) -> Tuple[List[int], List[int]]:
    """Load, resize, and process an image from path."""
    img = Image.open(image_path)
    img = resize_image(img, config.width, config.height)
    return dither_image(img, config.width, config.height, color_mode, dither=dither)
