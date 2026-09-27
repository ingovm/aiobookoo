"""Regression tests for the weight-frame decoder.

Focus: flow rate is a 2-byte big-endian value per the BooKoo protocol spec
(https://github.com/BooKooCode/OpenSource/blob/main/bookoo_mini_scale/protocols.md),
just like weight. Reading only the low byte wraps any flow >= 2.56 g/s down to
a small value (e.g. 3.00 g/s -> 0.44), which silently breaks fast shots.
"""

from aiobookoo.decode import decode


def _frame(body: list[int]) -> bytearray:
    """Build a 20-byte weight frame from 19 body bytes + XOR checksum."""
    assert len(body) == 19
    chk = 0
    for b in body:
        chk ^= b
    return bytearray(body + [chk])


def _weight_frame(flow_hi: int, flow_lo: int) -> bytearray:
    return _frame([
        0x03, 0x0B,        # header (weight message)
        0x00,              # message type / reserved
        0x00, 0x00,        # timer (ms)
        0x00,              # unit
        0x2B,              # weight sign '+'
        0x00,              # weight high byte
        0x03, 0xE8,        # weight 1000 -> 10.00 g
        0x2B,              # flow sign '+'
        flow_hi, flow_lo,  # flow rate, 2-byte big-endian, /100 = g/s
        0x64,              # battery 100%
        0x00,              # standby
        0x00,              # reserved
        0x00,              # buzzer gear
        0x00,              # flow smoothing
        0x00,              # reserved
    ])


def test_flow_under_ceiling_decodes():
    msg, _ = decode(_weight_frame(0x00, 0xC8))  # 200 -> 2.00 g/s
    assert msg is not None
    assert round(msg.flow_rate, 2) == 2.00


def test_flow_above_2_55_does_not_wrap():
    # 3.00 g/s = 300 = 0x012C. Low byte alone (0x2C = 44) would read 0.44 g/s.
    msg, _ = decode(_weight_frame(0x01, 0x2C))
    assert msg is not None
    assert round(msg.flow_rate, 2) == 3.00


def test_negative_flow_sign():
    body = list(_weight_frame(0x00, 0xC8))
    body[10] = 0x2D  # '-'
    chk = 0
    for b in body[:-1]:
        chk ^= b
    body[-1] = chk
    msg, _ = decode(bytearray(body))
    assert msg is not None
    assert round(msg.flow_rate, 2) == -2.00


def test_weight_decodes():
    msg, _ = decode(_weight_frame(0x00, 0x00))
    assert msg is not None
    assert round(msg.weight, 2) == 10.00
