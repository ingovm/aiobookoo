"""Client to interact with the Bookoo Espresso Monitor."""

from __future__ import annotations

import asyncio
import logging
import time

from collections.abc import Awaitable, Callable

from bleak import BleakClient, BleakGATTCharacteristic, BLEDevice
from bleak.exc import BleakDeviceNotFoundError, BleakError

from .const import (
    CHARACTERISTIC_UUID_EXTRACTION,
    CHARACTERISTIC_UUID_MONITOR_COMMAND,
)
from .exceptions import (
    BookooDeviceNotFound,
    BookooError,
    BookooMessageError,
    BookooMessageTooLong,
    BookooMessageTooShort,
)
from .decode import BookooMonitorMessage, decode_monitor

_LOGGER = logging.getLogger(__name__)


class BookooEspressoMonitor:
    """Representation of a Bookoo Espresso Monitor."""

    model = "Espresso Monitor"

    _extraction_char_id = CHARACTERISTIC_UUID_EXTRACTION
    _command_char_id = CHARACTERISTIC_UUID_MONITOR_COMMAND

    _msg_types = {
        "startExtraction": bytearray([0x02, 0x0C, 0x01, 0x00, 0x00, 0x00, 0x0F]),
        "stopExtraction": bytearray([0x02, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x0E]),
    }

    def __init__(
        self,
        address_or_ble_device: str | BLEDevice,
        name: str | None = None,
        notify_callback: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the Espresso Monitor."""

        self._client: BleakClient | None = None

        self.address_or_ble_device = address_or_ble_device
        self.name = name

        # tasks
        self.process_queue_task: asyncio.Task | None = None

        # connection diagnostics
        self.connected = False
        self._timestamp_last_command: float | None = None
        self.last_disconnect_time: float | None = None

        self._pressure: float | None = None
        self._battery: int | None = None

        # queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._add_to_queue_lock = asyncio.Lock()

        self._notify_callback: Callable[[], None] | None = notify_callback

    @property
    def mac(self) -> str:
        """Return the MAC address of the monitor in upper case."""
        return (
            self.address_or_ble_device.upper()
            if isinstance(self.address_or_ble_device, str)
            else self.address_or_ble_device.address.upper()
        )

    @property
    def pressure(self) -> float | None:
        """Return the current pressure in bar."""
        return self._pressure

    @property
    def battery(self) -> int | None:
        """Return the battery level in percent."""
        return self._battery

    def device_disconnected_handler(
        self,
        client: BleakClient | None = None,  # pylint: disable=unused-argument
        notify: bool = True,
    ) -> None:
        """Handle device disconnection."""

        _LOGGER.debug(
            "Espresso Monitor with address %s disconnected through disconnect handler",
            self.mac,
        )

        self.connected = False
        self.last_disconnect_time = time.time()
        self.async_empty_queue_and_cancel_tasks()
        if notify and self._notify_callback:
            self._notify_callback()

    async def _write_msg(self, char_id: str, payload: bytearray) -> None:
        """Write to the device."""
        if self._client is None:
            raise BookooError("Client not initialized")
        try:
            await self._client.write_gatt_char(char_id, payload)
            self._timestamp_last_command = time.time()
        except BleakDeviceNotFoundError as ex:
            self.connected = False
            raise BookooDeviceNotFound("Device not found") from ex
        except BleakError as ex:
            self.connected = False
            raise BookooError("Error writing to device") from ex
        except TimeoutError as ex:
            self.connected = False
            raise BookooError("Timeout writing to device") from ex
        except Exception as ex:
            self.connected = False
            raise BookooError("Unknown error writing to device") from ex

    def async_empty_queue_and_cancel_tasks(self) -> None:
        """Empty the queue."""

        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

        if self.process_queue_task and not self.process_queue_task.done():
            self.process_queue_task.cancel()

    async def process_queue(self) -> None:
        """Task to process the queue in the background."""
        while True:
            try:
                if not self.connected:
                    self.async_empty_queue_and_cancel_tasks()
                    return

                char_id, payload = await self._queue.get()
                await self._write_msg(char_id, payload)
                self._queue.task_done()
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                self.connected = False
                return
            except (BookooDeviceNotFound, BookooError) as ex:
                self.connected = False
                _LOGGER.debug("Error writing to device: %s", ex)
                return

    async def connect(
        self,
        callback: (
            Callable[[BleakGATTCharacteristic, bytearray], Awaitable[None] | None]
            | None
        ) = None,
        setup_tasks: bool = True,
    ) -> None:
        """Connect the bluetooth client."""

        if self.connected:
            return

        if self.last_disconnect_time and self.last_disconnect_time > (time.time() - 5):
            _LOGGER.debug(
                "Espresso Monitor has recently been disconnected, waiting 5 seconds before reconnecting"
            )
            return

        self._client = BleakClient(
            address_or_ble_device=self.address_or_ble_device,
            disconnected_callback=self.device_disconnected_handler,
        )

        try:
            await self._client.connect()
        except BleakError as ex:
            msg = "Error during connecting to device"
            _LOGGER.debug("%s: %s", msg, ex)
            raise BookooError(msg) from ex
        except TimeoutError as ex:
            msg = "Timeout during connecting to device"
            _LOGGER.debug("%s: %s", msg, ex)
            raise BookooError(msg) from ex
        except Exception as ex:
            msg = "Unknown error during connecting to device"
            _LOGGER.debug("%s: %s", msg, ex)
            raise BookooError(msg) from ex

        self.connected = True
        _LOGGER.debug("Connected to Bookoo Espresso Monitor")

        if callback is None:
            callback = self.on_bluetooth_data_received
        try:
            await self._client.start_notify(
                char_specifier=self._extraction_char_id,
                callback=callback,
            )
            await asyncio.sleep(0.1)
        except BleakError as ex:
            msg = "Error subscribing to notifications"
            _LOGGER.debug("%s: %s", msg, ex)
            raise BookooError(msg) from ex

        if setup_tasks:
            self._setup_tasks()

    def _setup_tasks(self) -> None:
        """Set up background tasks."""
        if not self.process_queue_task or self.process_queue_task.done():
            self.process_queue_task = asyncio.create_task(self.process_queue())

    async def disconnect(self) -> None:
        """Clean disconnect from the monitor."""

        _LOGGER.debug("Disconnecting from Espresso Monitor")
        self.connected = False
        await self._queue.join()
        if not self._client:
            return
        try:
            await self._client.disconnect()
        except BleakError as ex:
            _LOGGER.debug("Error disconnecting from device: %s", ex)
        else:
            _LOGGER.debug("Disconnected from Espresso Monitor")

    async def start_extraction(self) -> None:
        """Send start extraction command."""
        if not self.connected:
            await self.connect()

        _LOGGER.debug('Sending "start extraction" message')

        async with self._add_to_queue_lock:
            await self._queue.put(
                (self._command_char_id, self._msg_types["startExtraction"])
            )

    async def stop_extraction(self) -> None:
        """Send stop extraction command."""
        if not self.connected:
            await self.connect()

        _LOGGER.debug('Sending "stop extraction" message')

        async with self._add_to_queue_lock:
            await self._queue.put(
                (self._command_char_id, self._msg_types["stopExtraction"])
            )

    async def on_bluetooth_data_received(
        self,
        characteristic: BleakGATTCharacteristic,  # pylint: disable=unused-argument
        data: bytearray,
    ) -> None:
        """Receive data from the Espresso Monitor."""

        try:
            msg, _ = decode_monitor(data)
        except BookooMessageTooShort as ex:
            _LOGGER.debug("Monitor message too short: %s", ex.bytes_recvd)
            return
        except BookooMessageTooLong as ex:
            _LOGGER.debug("%s: %s", ex.message, ex.bytes_recvd)
            return
        except BookooMessageError as ex:
            _LOGGER.warning("%s: %s", ex.message, ex.bytes_recvd)
            return

        if not isinstance(msg, BookooMonitorMessage):
            return

        self._pressure = msg.pressure
        self._battery = msg.battery

        if self._notify_callback is not None:
            self._notify_callback()
