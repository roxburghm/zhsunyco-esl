import asyncio
import click
import io
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter
from zhsunyco_esl import ZhsunycoClient, LabelConfig

RED = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def _load_font(name, size, fallback_name=None):
    """Try to load a TrueType font, fall back to default."""
    for n in [name, fallback_name]:
        if n:
            try:
                return ImageFont.truetype(n, size)
            except IOError:
                continue
    return ImageFont.load_default()


def _center_text(draw, y, text, font, fill, width):
    """Draw text horizontally centered."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) // 2, y), text, fill=fill, font=font)


@click.command()
@click.version_option()
@click.option('--mac', required=True, help='MAC address of the label')
@click.option('--width', default=296, help='Width of the label')
@click.option('--height', default=128, help='Height of the label')
@click.option('--color', default='BWR', type=click.Choice(['BW', 'BWR']), help='Color mode')
def main(mac, width, height, color):
    """Generates a styled barcode label and sends it to the display."""

    print(f"Generating barcode for {mac}...")

    # --- Fonts (monospace for MAC, bold sans for title) ---
    font_title = _load_font("arialbd.ttf", 14, "arial.ttf")
    font_mac = _load_font("consolab.ttf", 20, "consola.ttf")
    font_url = _load_font("consola.ttf", 12, "arial.ttf")

    # --- Generate barcode ---
    mac_digits = mac.replace(":", "")
    code128 = barcode.get_barcode_class('code128')
    writer = ImageWriter()
    generated_barcode = code128(mac_digits, writer=writer)

    buffer = io.BytesIO()
    generated_barcode.write(buffer, options={
        'write_text': False, 'module_height': 10.0,
        'module_width': 0.4, 'quiet_zone': 1.0,
    })
    buffer.seek(0)
    barcode_img = Image.open(buffer)

    # --- Canvas (fontmode '1' disables antialiasing for crisp e-ink rendering) ---
    canvas = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(canvas)
    draw.fontmode = "1"

    # --- Layout constants ---
    pad = 4  # Safe margin for e-ink edges
    banner_h = 22
    margin = 12
    barcode_area_top = banner_h + 6
    barcode_max_w = width - margin * 2
    barcode_max_h = 44
    footer_h = 16

    # --- Red top banner ---
    draw.rectangle([pad, pad, width - 1 - pad, pad + banner_h - 1], fill=RED)
    _center_text(draw, pad + 3, "DEVICE IDENTIFIER", font_title, WHITE, width)

    # --- Red bottom accent line ---
    draw.rectangle([pad, height - 1 - pad - 1, width - 1 - pad, height - 1 - pad], fill=RED)

    # --- Barcode ---
    bc_w, bc_h = barcode_img.size
    aspect = bc_w / bc_h
    new_h = int(barcode_max_w / aspect)
    new_w = barcode_max_w
    if new_h > barcode_max_h:
        new_h = barcode_max_h
        new_w = int(new_h * aspect)

    barcode_resized = barcode_img.resize((new_w, new_h), Image.Resampling.NEAREST)
    bc_x = (width - new_w) // 2
    bc_y = pad + barcode_area_top
    canvas.paste(barcode_resized, (bc_x, bc_y))

    # --- MAC address ---
    mac_y = bc_y + new_h + 4
    _center_text(draw, mac_y, mac.upper(), font_mac, BLACK, width)

    # --- Red separator dots ---
    sep_y = mac_y + 26
    dot_spacing = 4
    for x in range(margin, width - margin, dot_spacing):
        draw.point((x, sep_y), fill=RED)

    # --- Footer URL (centered) ---
    url_text = "github.com/roxburghm/zhsunyco-esl"
    _center_text(draw, height - pad - footer_h, url_text, font_url, BLACK, width)

    # Debug save
    canvas.save("last_barcode.png")

    # --- Send ---
    from zhsunyco_esl.image import dither_image
    plane_bw, plane_red = dither_image(canvas, width, height, color_mode=color, dither=False)

    config = LabelConfig(width=width, height=height)
    client = ZhsunycoClient(mac, config=config)

    try:
        asyncio.run(client.send_image_planes(plane_bw, plane_red))
    except Exception as e:
        print(f"Error: {e}")
        ctx = click.get_current_context()
        ctx.exit(1)

if __name__ == "__main__":
    main()
