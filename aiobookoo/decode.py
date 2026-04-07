"""Message decoding functions, taken from pybookoo."""

from dataclasses import dataclass
import logging

from .const import MONITOR_BYTE1, MONITOR_BYTE2, WEIGHT_BYTE1, WEIGHT_BYTE2
from .exceptions import BookooMessageError, BookooMessageTooLong, BookooMessageTooShort

_LOGGER = logging.getLogger(__name__)


@dataclass
class BookooMessage:
    """Representation of the contents of a Datapacket from the weight Characteristic of a Bookoo Scale."""

    def __init__(self, payload: bytearray) -> None:
        """Initialize a Settings instance.

        :param payload: The payload containing the settings data.
        decode as described in https://github.com/BooKooCode/OpenSource/blob/main/bookoo_mini_scale/protocols.md
        """

        self.timer: float | None = (
            int.from_bytes(
                payload[2:5],
                byteorder="big",  # time in milliseconds
            )
            / 1000.0  # time in seconds
        )
        self.unit: bytes = payload[5]
        self.weight_symbol = -1 if payload[6] == 45 else 1 if payload[6] == 43 else 0
        self.weight: float | None = (
            int.from_bytes(payload[7:10], byteorder="big") / 100.0 * self.weight_symbol
        )  # Convert to grams

        self.flowSymbol = -1 if payload[10] == 45 else 1 if payload[10] == 43 else 0
        self.flow_rate = (
            int.from_bytes(payload[11:13], byteorder="big") / 100.0 * self.flowSymbol
        )  # Convert to ml
        self.battery = payload[13]  # battery level in percent
        self.standby_time = int.from_bytes(payload[14:16], byteorder="big")  # minutes
        self.buzzer_gear = payload[16]
        self.flow_rate_smoothing = payload[17]  # 0 = off, 1 = on

        # Verify checksum
        checksum = 0
        for byte in payload[:-1]:
            checksum ^= byte
        if checksum != payload[-1]:
            raise BookooMessageError(payload, "Checksum mismatch")

        # _LOGGER.debug(
        #     "Bookoo Message: unit=%s, weight=%s, time=%s, battery=%s, flowRate=%s, standbyTime=%s, buzzerGear=%s, flowRateSmoothing=%s",
        #     self.unit,
        #     self.weight,
        #     self.timer,
        #     self.battery,
        #     self.flow_rate,
        #     self.standby_time,
        #     self.buzzer_gear,
        #     self.flow_rate_smoothing,
        # )


def decode(byte_msg: bytearray):
    """Return a tuple - first element is the message, or None.

    The second element is the remaining bytes of the message.

    """

    if len(byte_msg) < 20:
        raise BookooMessageTooShort(byte_msg)

    if len(byte_msg) > 20:
        raise BookooMessageTooLong(byte_msg)

    if byte_msg[0] == WEIGHT_BYTE1 and byte_msg[1] == WEIGHT_BYTE2:
        # _LOGGER.debug("Found valid weight Message")
        return (BookooMessage(byte_msg), bytearray())

    _LOGGER.debug("Full message: %s", byte_msg)
    return (None, byte_msg)


@dataclass
class BookooMonitorMessage:
    """Representation of a data packet from the Extraction Data Characteristic of a Bookoo Espresso Monitor.

    Packet layout (10 bytes), decoded as described in
    https://github.com/BooKooCode/OpenSource/blob/main/espresso_monitor/protocols.md

    BYTE1-2 : header (02 1B)
    BYTE3-4 : reserved (00 00)
    BYTE5-6 : pressure * 100 bar, big-endian unsigned short
    BYTE7   : battery remaining (%)
    BYTE8-9 : reserved (00 00)
    BYTE10  : XOR checksum
    """

    def __init__(self, payload: bytearray) -> None:
        """Initialize a BookooMonitorMessage from a raw 10-byte payload."""

        self.pressure: float = (
            int.from_bytes(payload[4:6], byteorder="big") / 100.0
        )  # Convert to bar
        self.battery: int = payload[6]  # battery level in percent

        # Verify checksum
        checksum = 0
        for byte in payload[:-1]:
            checksum ^= byte
        if checksum != payload[-1]:
            raise BookooMessageError(payload, "Checksum mismatch")


def decode_monitor(byte_msg: bytearray):
    """Return a tuple - first element is the monitor message, or None.

    The second element is the remaining bytes of the message.

    """

    if len(byte_msg) < 10:
        raise BookooMessageTooShort(byte_msg)

    if len(byte_msg) > 10:
        raise BookooMessageTooLong(byte_msg)

    if byte_msg[0] == MONITOR_BYTE1 and byte_msg[1] == MONITOR_BYTE2:
        return (BookooMonitorMessage(byte_msg), bytearray())

    _LOGGER.debug("Full monitor message: %s", byte_msg)
    return (None, byte_msg)
