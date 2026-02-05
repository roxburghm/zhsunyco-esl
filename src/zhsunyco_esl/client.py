import asyncio
import sys
from bleak import BleakClient, BleakScanner
from .models import LabelConfig, DEFAULT_CONFIG
from .protocol import (
    build_packets, build_query_packets, build_config_packets,
    decrypt_notification,
)
from .image import process_image


def _client_kwargs():
    """Platform-specific BleakClient kwargs."""
    if sys.platform == "win32":
        return {"winrt": {"use_cached_services": True}}
    return {}


class ZhsunycoClient:
    def __init__(self, mac_address: str, config: LabelConfig = DEFAULT_CONFIG):
        self.mac_address = mac_address
        self.config = config
        self.client = None
        self._notification_event = None
        self._notification_data = None

    async def connect(self):
        """Scan and connect (single attempt)."""
        print(f"Scanning for {self.mac_address}...")
        device = await BleakScanner.find_device_by_address(
            self.mac_address, timeout=20.0)
        if not device:
            raise Exception(f"Device {self.mac_address} not found")

        print(f"Connecting to {device.address}...")
        self.client = BleakClient(device, timeout=20.0, **_client_kwargs())
        await self.client.connect()
        print("Connected.")

    async def disconnect(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def _handle_notification(self, sender, data):
        mac_bytes = bytes.fromhex(self.mac_address.replace(":", ""))
        result = decrypt_notification(data, mac_bytes)
        self._notification_data = result
        if self._notification_event:
            self._notification_event.set()

    async def _send_packets(self, packets):
        """Send header + data packets with V2-compliant timing."""
        self._notification_event = asyncio.Event()
        self._notification_data = None

        await self.client.start_notify(
            self.config.notify_char_uuid, self._handle_notification)
        await asyncio.sleep(0.3)  # V2: 300ms post-CCCD write

        print("Sending header...")
        await self.client.write_gatt_char(
            self.config.write_char_uuid, packets[0], response=True)
        await asyncio.sleep(0.5)  # V2: 500ms before first data packet

        total = len(packets) - 1
        print(f"Sending {total} data packets...")
        for i, pkt in enumerate(packets[1:]):
            await self.client.write_gatt_char(
                self.config.write_char_uuid, pkt, response=True)
            await asyncio.sleep(0.02)  # V2: 20ms inter-packet
            if (i + 1) % 5 == 0:
                await asyncio.sleep(0.003)  # V2: 3ms every 5th packet
            if (i + 1) % 10 == 0:
                print(f"  Sent {i + 1}/{total}")

        print("Waiting for device response...")
        try:
            await asyncio.wait_for(
                self._notification_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            print("Warning: No notification response within 30s")

        try:
            if self.client.is_connected:
                await self.client.stop_notify(self.config.notify_char_uuid)
        except Exception:
            pass

        return self._notification_data

    async def _send_with_retry(self, packets):
        """Connect + send with V2 retry (3 total attempts).

        Disconnect between retries so the device goes back to advertising.
        """
        last_error = None
        for attempt in range(3):
            try:
                if not self.client or not self.client.is_connected:
                    await self.connect()
                return await self._send_packets(packets)
            except Exception as e:
                last_error = e
                print(f"Attempt {attempt + 1}/3 failed: {e}")
                if attempt < 2:
                    await self.disconnect()
                    await asyncio.sleep(2.0)
        raise last_error

    async def send_image_planes(self, plane_bw, plane_red):
        mac_bytes = bytes.fromhex(self.mac_address.replace(":", ""))
        packets, _key = build_packets(plane_bw, plane_red, mac_bytes, self.config)
        return await self._send_with_retry(packets)

    async def send_image_file(self, image_path: str, color_mode: str = "BWR",
                              dither: bool = True):
        plane_bw, plane_red = process_image(
            image_path, self.config, color_mode, dither=dither)
        return await self.send_image_planes(plane_bw, plane_red)

    async def send_query(self):
        """Send Query/Ping (0xF0) to get device status."""
        mac_bytes = bytes.fromhex(self.mac_address.replace(":", ""))
        packets, _key = build_query_packets(mac_bytes)
        return await self._send_with_retry(packets)

    async def send_config(self, hex_key: str):
        """Send Text/Config (0xF2) with a 256-char hex key string."""
        mac_bytes = bytes.fromhex(self.mac_address.replace(":", ""))
        packets, _key = build_config_packets(hex_key, mac_bytes)
        return await self._send_with_retry(packets)
