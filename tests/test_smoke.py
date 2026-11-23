"""
Smoke tests for i3cblaster-bmc.

These do NOT require hardware; they only verify that the modules import and
that basic pure-Python helpers behave as expected.

The `src` layout is put on the path via pyproject's
[tool.pytest.ini_options] pythonpath = ["src"].
"""

import importlib
import sys


def test_import_agent():
    mod = importlib.import_module("i3cblaster_bmc")
    assert hasattr(mod, "OcpRecoveryAgent")
    assert hasattr(mod, "Reg")


def test_env_port(monkeypatch):
    monkeypatch.setenv("I3C_BLASTER_UART", "COM42")
    sys.modules.pop("i3cblaster_bmc", None)
    mod = importlib.import_module("i3cblaster_bmc")
    args = mod.build_arg_parser().parse_args([])
    assert args.uart == "COM42"


def test_le_helpers():
    mod = importlib.import_module("i3cblaster_bmc")
    agent_cls = mod.OcpRecoveryAgent
    assert agent_cls._to_le_bytes(0x11223344, 4) == [0x44, 0x33, 0x22, 0x11]
    assert agent_cls._u32_le([0x44, 0x33, 0x22, 0x11]) == 0x11223344
