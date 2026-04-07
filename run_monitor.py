# run_monitor.py
import asyncio
from aiobookoo.bookoomonitor import BookooEspressoMonitor

MONITOR_MAC = "FE:D5:D9:06:92:EF"  # replace with your monitor's MAC

def on_monitor_data():
    print(f"Pressure: {monitor.pressure} bar  |  Battery: {monitor.battery}%")

monitor = BookooEspressoMonitor(address_or_ble_device=MONITOR_MAC, notify_callback=on_monitor_data)

async def main():
    print("Connecting...")
    await monitor.connect()
    print("Connected. Starting extraction monitoring...")
    await monitor.start_extraction()
    print("Listening for 10 seconds...")
    await asyncio.sleep(10)
    await monitor.stop_extraction()
    await monitor.disconnect()

asyncio.run(main())