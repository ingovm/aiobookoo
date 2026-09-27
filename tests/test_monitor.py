"""Tests for Espresso Monitor start/stop sequencing."""

import asyncio

from aiobookoo.bookoomonitor import BookooEspressoMonitor


class _FakeClient:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.disconnected = False

    async def write_gatt_char(self, char_id, payload) -> None:
        self.writes.append(bytes(payload))

    async def disconnect(self) -> None:
        self.disconnected = True


def _monitor_with_slow_connect(delay: float) -> tuple[BookooEspressoMonitor, _FakeClient]:
    monitor = BookooEspressoMonitor("AA:BB:CC:DD:EE:FF")
    client = _FakeClient()

    async def fake_connect(*_args, **_kwargs) -> None:
        await asyncio.sleep(delay)
        monitor._client = client
        monitor.connected = True
        monitor._setup_tasks()

    monitor.connect = fake_connect
    return monitor, client


async def _stop_while_connecting():
    monitor, client = _monitor_with_slow_connect(0.2)
    start = asyncio.create_task(monitor.start_extraction())
    await asyncio.sleep(0.05)  # stop pressed while still connecting
    await monitor.stop_extraction()
    await start

    assert client.disconnected
    assert not monitor.connected
    start_msg = bytes(monitor._msg_types["startExtraction"])
    stop_msg = bytes(monitor._msg_types["stopExtraction"])
    assert client.writes == [start_msg, stop_msg]


async def _stop_when_idle():
    monitor, client = _monitor_with_slow_connect(0)
    await monitor.stop_extraction()
    assert client.writes == []


def test_stop_while_connecting_is_not_dropped():
    asyncio.run(_stop_while_connecting())


def test_stop_when_idle_is_noop():
    asyncio.run(_stop_when_idle())


def test_pressure_notify_throttling(monkeypatch):
    import aiobookoo.bookoomonitor as mod

    now = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    monitor = BookooEspressoMonitor("AA:BB:CC:DD:EE:FF")

    def reading(pressure, battery=50):
        monitor._pressure, monitor._battery = pressure, battery
        notify = monitor._should_notify()
        if notify:
            monitor._notified_pressure, monitor._notified_battery = pressure, battery
            monitor._last_notify_time = now[0]
        return notify

    assert reading(0.02)  # first reading always notifies
    now[0] += 1
    assert not reading(0.05)  # idle noise below delta
    assert reading(3.0)  # real change, interval elapsed
    now[0] += 0.1
    assert not reading(5.0)  # real change, but too soon
    now[0] += 0.5
    assert reading(5.0)  # published once interval elapsed
    now[0] += 0.1
    assert reading(5.0, battery=49)  # battery change bypasses throttle
