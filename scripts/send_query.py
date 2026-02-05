import asyncio
import click
from zhsunyco_esl import ZhsunycoClient

@click.command()
@click.version_option()
@click.option('--mac', required=True, help='MAC address of the label')
def main(mac):
    """Sends a Query/Ping command to get device status (battery voltage and temperature).

    WARNING: The 0xF0 query command causes the device to reset its display
    to the factory/shipping screen. You will need to re-send an image afterward.
    """

    print(f"Querying device {mac}...")
    print("Note: Query will reset the display to shipping screen.")
    client = ZhsunycoClient(mac)

    try:
        result = asyncio.run(client.send_query())
        if result:
            print(f"Battery:     {result['battery_voltage']}V")
            print(f"Temperature: {result['temperature']}C")
            print(f"Raw bytes:   {result['raw'].hex(' ')}")
        else:
            print("No response received from device.")
    except Exception as e:
        print(f"Error: {e}")
        ctx = click.get_current_context()
        ctx.exit(1)

if __name__ == "__main__":
    main()
