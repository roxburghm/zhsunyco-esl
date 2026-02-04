import asyncio
import click
from zhsunyco_esl import ZhsunycoClient, LabelConfig

@click.command()
@click.version_option()
@click.option('--mac', required=True, help='MAC address of the label')
@click.option('--image', required=True, type=click.Path(exists=True), help='Path to image file')
@click.option('--width', default=296, help='Width of the label')
@click.option('--height', default=128, help='Height of the label')
@click.option('--color', default='BWR', type=click.Choice(['BW', 'BWR']), help='Color mode')
def main(mac, image, width, height, color):
    """Sends an image to the Zhsunyco label, resizing and dithering it."""
    
    config = LabelConfig(width=width, height=height)
    client = ZhsunycoClient(mac, config=config)
    
    print(f"Sending image {image} to {mac} (Color: {color})...")
    try:
        asyncio.run(client.send_image_file(image, color_mode=color))
    except Exception as e:
        print(f"Error: {e}")
        ctx = click.get_current_context()
        ctx.exit(1)

if __name__ == "__main__":
    main()
