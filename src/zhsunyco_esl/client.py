import asyncio
from bleak import BleakClient, BleakScanner
from .models import LabelConfig, DEFAULT_CONFIG
from .protocol import build_packets
from .image import process_image

class ZhsunycoClient:
    def __init__(self, mac_address: str, config: LabelConfig = DEFAULT_CONFIG):
        self.mac_address = mac_address
        self.config = config
        self.client = None

    async def connect(self):
        print(f"Scanning for {self.mac_address}...")
        device = await BleakScanner.find_device_by_address(self.mac_address, timeout=120.0)
        if not device:
            raise Exception(f"Device {self.mac_address} not found")
        
        print(f"Connecting to {device.address}...")
        self.client = BleakClient(device, timeout=30.0)
        await self.client.connect()
        print("Connected.")
        await asyncio.sleep(1.0)

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            print("Disconnected.")

    async def send_image_planes(self, plane_bw, plane_red):
        if not self.client or not self.client.is_connected:
            await self.connect()

        mac_bytes = bytes.fromhex(self.mac_address.replace(":", ""))
        packets, key = build_packets(plane_bw, plane_red, mac_bytes, self.config)
        
        def handle_notify(s, d):
            dec = bytes([b ^ key for b in d])
            try:
                print(f"Notify: {dec.decode('utf-8', errors='ignore')}")
            except: pass

        await self.client.start_notify(self.config.notify_char_uuid, handle_notify)
        print("Notifications enabled.")
        await asyncio.sleep(0.5)

        print("Sending Header...")
        await self.client.write_gatt_char(self.config.write_char_uuid, packets[0], response=True)
        await asyncio.sleep(0.5)

        print("Sending Data...")
        total = len(packets) - 1
        for i, pkt in enumerate(packets[1:]):
            for attempt in range(3):
                try:
                    await self.client.write_gatt_char(self.config.write_char_uuid, pkt, response=True)
                    break
                except Exception as e:
                    print(f"Retry {attempt+1}: {e}")
                    await asyncio.sleep(0.5)
            await asyncio.sleep(0.05)
            if (i+1) % 5 == 0: await asyncio.sleep(0.02)
            if (i+1) % 10 == 0: print(f"Sent {i+1}/{total} packets")

        print("Done. Waiting for update...")
        await asyncio.sleep(20) # Wait for e-ink refresh
        try:
            if self.client.is_connected:
                await self.client.stop_notify(self.config.notify_char_uuid)
        except Exception as e:
            print(f"Note: Could not stop notify (device likely disconnected): {e}")

    async def send_image_file(self, image_path: str, color_mode: str = "BWR"):
        plane_bw, plane_red = process_image(image_path, self.config, color_mode)
        await self.send_image_planes(plane_bw, plane_red)
