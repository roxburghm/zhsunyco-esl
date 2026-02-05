# Zhsunyco BLE E-Ink Label Library

A Python library and CLI tools to control Zhsunyco BLE e-ink displays (2.9" 296x128). This library allows you to send images, test patterns, and barcodes to the device over Bluetooth Low Energy (BLE).

## Original Tag

| | |
|---|---|
| Original !["Original"](/images/Z_ORIG.jpg) | Rewritten Display !["Alternate Barcode"](/images/Z_MY_BAR.jpg) |
| Test Pattern !["Test Patterm"](/images/Z_TEST.jpg) | Rewritten!["Dithering"](/images/Z_CAT.jpg) |


## Dev Possibilities

!["Cat"](/images/Z_DEV.jpg)

## Features

- **Protocol Implementation**: Full implementation of the communication protocol (CRC16, RLE compression).
- **Image Processing**: Automatic resizing and optional dithering of images to fit the e-ink display (Black/White/Red).
- **CLI Tools**: Ready-to-use scripts for common tasks.
- **Async Client**: Built on top of `bleak` for modern async Bluetooth support.

## Installation

Clone the repository and install in editable mode:

```bash
git clone https://github.com/roxburghm/zhsunyco-esl.git
cd zhsunyco
pip install -e .
```

Dependencies: `bleak`, `Pillow`, `click`, `python-barcode`.

## CLI Usage

The package includes several scripts in the `scripts/` directory.

### 1. Send Custom Image

Send any image file. It will be automatically resized and dithered.

```bash
python scripts/send_image.py --mac "3D:00:00:E5:7D:76" --image "photo.jpg" --color BWR
```

**Options:**
- `--mac` (Required): MAC address of the label.
- `--image` (Required): Path to the image file.
- `--color`: `BWR` (Black/White/Red - default) or `BW` (Black/White only).
- `--width`: Width of the label (default: 296).
- `--height`: Height of the label (default: 128).
- `--no-dither`: Don't use dithering.

### 2. Send Barcode

Generates a Code128 barcode of the MAC address, formats it with text, and adds a footer URL.

```bash
python scripts/send_barcode.py --mac "3D:00:00:E5:7D:76"
```

**Options:**
- `--mac` (Required): MAC address of the label.
- `--color`: `BWR` (Black/White/Red - default) or `BW` (Black/White only).
- `--width`: Width of the label (default: 296).
- `--height`: Height of the label (default: 128).


### 3. Send Test Pattern

Sends a built-in test pattern (Stripes + Box) to verify screen functionality.

```bash
python scripts/send_pattern.py --mac "3D:00:00:E5:7D:76"
```

**Options:**
- `--mac` (Required): MAC address of the label.
- `--color`: `BWR` (Black/White/Red - default) or `BW` (Black/White only).
- `--width`: Width of the label (default: 296).
- `--height`: Height of the label (default: 128).

### 4. Send Weather

Fetches current weather for London and displays it on the label.

```bash
python scripts/send_weather.py --mac "3D:00:00:E5:7D:76"
```

**Options:**
- `--mac` (Required): MAC address of the label.
- `--color`: `BWR` (Black/White/Red - default) or `BW` (Black/White only).

### 5. Reset Label

Fetches temp and voltage information and resets the label to factory state.


```bash
python scripts/send_query.py --mac "3D:00:00:E5:7D:76"
```

**Options:**
- `--mac` (Required): MAC address of the label.


## Library Usage

You can use the `ZhsunycoClient` in your own Python scripts:

```python
import asyncio
from zhsunyco_esl import ZhsunycoClient, LabelConfig

async def update_label():
    client = ZhsunycoClient("3D:00:00:E5:7D:76")
    
    # Send an image file
    await client.send_image_file("my_label.png", color_mode="BWR")

if __name__ == "__main__":
    asyncio.run(update_label())
```

## Protocol Details

The device uses a custom BLE protocol involving:
- **GATT Write**: `00001525-1212-efde-1523-785feabcd123`
- **GATT Notify**: `00001526-1212-efde-1523-785feabcd123`
- **Data Format**: RLE compressed bitmaps (Black plane + Red plane) wrapped in a custom packet structure with XOR encryption (key derived from MAC) and CRC16-CCITT checksums.

## License

MIT
