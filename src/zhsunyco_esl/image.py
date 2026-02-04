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

    if color_mode == "BW":
        if dist_black < dist_white:
            return (0, 0, 0, 1, 0) # Black
        else:
            return (255, 255, 255, 0, 0) # White
            
    # BWR Mode
    min_dist = min(dist_black, dist_white, dist_red)
    if min_dist == dist_black:
        return (0, 0, 0, 1, 0) # Black
    elif min_dist == dist_white:
        return (255, 255, 255, 0, 0) # White
    else:
        return (255, 0, 0, 0, 1) # Red

def dither_image(img: Image.Image, width: int, height: int, color_mode: str = "BWR") -> Tuple[List[int], List[int]]:
    """
    Dither image to Black, White, Red using Floyd-Steinberg error diffusion.
    Returns (plane_bw, plane_red) lists.
    """
    img = img.convert("RGB")
    pixels = img.load() # This provides read/write access
    
    plane_bw = []
    plane_red = []
    
    # Pre-calculate bit planes to avoid storing another full image if possible,
    # but FS requires modifying future pixels, so we modify 'img' in place and build lists at the end.
    # However, to build lists sequentially we might as well do it in one pass if we are careful.
    # Actually, simpler to run FS on the image first, then extract bits.
    
    for y in range(height):
        for x in range(width):
            old_r, old_g, old_b = pixels[x, y]
            
            # Find nearest palette color
            new_r, new_g, new_b, _, _ = _get_palette_color(old_r, old_g, old_b, color_mode)
            
            # Set pixel to new color
            pixels[x, y] = (new_r, new_g, new_b)
            
            # Calculate quantization error
            err_r = old_r - new_r
            err_g = old_g - new_g
            err_b = old_b - new_b
            
            # Distribute error to neighbors
            # Right, Down-Left, Down, Down-Right
            # coeffs: 7/16, 3/16, 5/16, 1/16
            
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

    # Second pass: generate bit planes from the now-dithered image
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            # Since pixels are now exactly palette colors, we can just map them
            # But rely on the helper for consistency (distance 0)
            _, _, _, bw_bit, red_bit = _get_palette_color(r, g, b, color_mode)
            plane_bw.append(bw_bit)
            plane_red.append(red_bit)
                
    return plane_bw, plane_red

def process_image(image_path: str, config: LabelConfig, color_mode: str = "BWR") -> Tuple[List[int], List[int]]:
    """Load, resize, and process an image from path."""
    img = Image.open(image_path)
    img = resize_image(img, config.width, config.height)
    return dither_image(img, config.width, config.height, color_mode)
