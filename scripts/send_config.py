import asyncio
import click
from zhsunyco_esl import ZhsunycoClient

def validate_hex_key(ctx, param, value):
    """Validate that the key is exactly 256 hex characters."""
    if len(value) != 256:
        raise click.BadParameter(f"Key must be exactly 256 hex characters, got {len(value)}.")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise click.BadParameter("Key must contain only valid hex characters (0-9, a-f, A-F).")
    return value

@click.command()
@click.version_option()
@click.option('--mac', required=True, help='MAC address of the label')
@click.option('--key', required=True, callback=validate_hex_key, help='256-character hex key string')
def main(mac, key):
    """Sends a Text/Config key to the Zhsunyco label."""

    print(f"Sending config key to {mac}...")
    client = ZhsunycoClient(mac)

    try:
        result = asyncio.run(client.send_config(key))
        if result:
            print(f"Config sent successfully. Response: {result}")
        else:
            print("Config sent. No response received from device.")
    except Exception as e:
        print(f"Error: {e}")
        ctx = click.get_current_context()
        ctx.exit(1)

if __name__ == "__main__":
    main()
