# run_scale.py
import asyncio
from aiobookoo.bookooscale import BookooScale

SCALE_MAC = "DD:DF:D0:70:6C:FE" # replace with your scale's MAC

def on_scale_data():
    print(f"Weight: {scale.weight}g | Flow Rate: {scale.flow_rate} g/s | Timer: {scale.timer} s")

scale = BookooScale(address_or_ble_device=SCALE_MAC, notify_callback=on_scale_data)

async def main():
    print("Connecting...")
    await scale.connect()
    print("Listening for 10 seconds...")
    await asyncio.sleep(10)
    await scale.disconnect()

asyncio.run(main())