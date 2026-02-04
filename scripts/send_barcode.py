import asyncio
import click
import io
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter
from zhsunyco_esl import ZhsunycoClient, LabelConfig

@click.command()
@click.version_option()
@click.option('--mac', required=True, help='MAC address of the label')
@click.option('--width', default=296, help='Width of the label')
@click.option('--height', default=128, help='Height of the label')
@click.option('--color', default='BWR', type=click.Choice(['BW', 'BWR']), help='Color mode')
def main(mac, width, height, color):
    """Generates a barcode for the MAC address and sends it to the label."""
    
    print(f"Generating barcode for {mac}...")
    
    # 1. Generate Barcode (Code128)
    # The user wants digits only in the barcode
    mac_digits = mac.replace(":", "")
    code128 = barcode.get_barcode_class('code128')
    # writer_options for ImageWriter to remove text if we want to render it manually
    # or we can let barcode render it. User asked for "BT Address... underneath : separated".
    # Standard barcode text is usually the value. 
    # Let's generate barcode without text and render text manually to control formatting (: separated).
    writer = ImageWriter()
    generated_barcode = code128(mac_digits, writer=writer)
    
    # Save to buffer
    buffer = io.BytesIO()
    generated_barcode.write(buffer, options={'write_text': False, 'module_height': 10.0, 'module_width': 0.4, 'quiet_zone': 1.0})
    buffer.seek(0)
    barcode_img = Image.open(buffer)
    
    # 2. Composition
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    
    # Center the barcode near the top
    # Barcode image might be large, need to resize potentially? 
    # Usually barcode writers create hi-res images.
    # Let's resize barcode_img to fit comfortably horizontally
    bc_w, bc_h = barcode_img.size
    target_bc_w = int(width * 0.8)
    target_bc_h = int(height * 0.5) 
    
    # Resize keeping aspect ratio or just fit? 
    # Barcodes are sensitive to resizing strictly but usually okay if scaled nicely.
    # Let's verify aspect ratio.
    aspect = bc_w / bc_h
    new_h = int(target_bc_w / aspect)
    if new_h > target_bc_h:
        new_h = target_bc_h
        target_bc_w = int(new_h * aspect)
        
    barcode_resized = barcode_img.resize((target_bc_w, new_h), Image.Resampling.LANCZOS)
    
    # Position: Centered horizontally, slightly from top
    x_pos = (width - target_bc_w) // 2
    y_pos = 10
    canvas.paste(barcode_resized, (x_pos, y_pos))
    
    # 3. Text
    try:
        font = ImageFont.truetype("arial.ttf", 12)
        small_font = ImageFont.truetype("arial.ttf", 10)
    except IOError:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        
    # Text: MAC Address (formatted) under barcode
    text_mac = mac
    # Get text text bounds
    bbox = draw.textbbox((0, 0), text_mac, font=font)
    text_w = bbox[2] - bbox[0]
    text_x = (width - text_w) // 2
    text_y = y_pos + new_h + 5
    draw.text((text_x, text_y), text_mac, fill="black", font=font)
    
    # Text: URL bottom left
    text_url = "https://github.com/roxburghm/zhsunyco-esl"
    draw.text((5, height - 15), text_url, fill="black", font=small_font)
    
    # Save for debug
    # canvas.save("last_barcode.png")
    
    # 4. Send
    # We need to process it (dither)
    from zhsunyco_esl.image import dither_image
    plane_bw, plane_red = dither_image(canvas, width, height, color_mode=color)
    
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
