import asyncio
import click
from PIL import Image, ImageDraw
from zhsunyco_esl import ZhsunycoClient, LabelConfig, ColorMode

@click.command()
@click.version_option()
@click.option('--mac', required=True, help='MAC address of the label')
@click.option('--width', default=296, help='Width of the label')
@click.option('--height', default=128, help='Height of the label')
@click.option('--color', default='BWR', type=click.Choice(['BW', 'BWR']), help='Color mode')
def main(mac, width, height, color):
    """Sends a generated test pattern to the Zhsunyco label."""
    
    print(f"Generating test pattern ({width}x{height}, {color})...")
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    # Stripes: Black, Red, Black
    draw.rectangle([20, 0, 60, height], fill="black")
    if color == 'BWR':
        draw.rectangle([80, 0, 120, height], fill="red")
    draw.rectangle([140, 0, 180, height], fill="black")
    
    # Square in bottom right
    draw.rectangle([width-20, height-20, width, height], fill="black")
    
    config = LabelConfig(width=width, height=height)
    client = ZhsunycoClient(mac, config=config)
    
    # We can use the library's internal dither function or just save and load
    # For cleanliness, let's use the low-level processing from image module 
    # but we need to import it. Or just rely on client.
    
    # To use client.send_image_planes via helper we would need to manually separate planes
    # But client has send_image_file. 
    # Let's add send_image_object to client? 
    # Or just save to temp file?
    # Or manually process here.
    
    from zhsunyco_esl.image import dither_image
    plane_bw, plane_red = dither_image(img, width, height)
    
    try:
        asyncio.run(client.send_image_planes(plane_bw, plane_red))
    except Exception as e:
        print(f"Error: {e}")
        ctx = click.get_current_context()
        ctx.exit(1)

if __name__ == "__main__":
    main()
