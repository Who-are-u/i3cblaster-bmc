"""
Smoke tests for Janus_OCPagent.

These do NOT require hardware; they only verify that the modules import and
that basic pure-Python helpers behave as expected.

The `src` layout is put on the path via pyproject's
[tool.pytest.ini_options] pythonpath = ["src"].
"""

import importlib
import sys


def test_import_agent():
    mod = importlib.import_module("janus_ocpagent.agent")
    assert hasattr(mod, "OcpRecoveryAgent")
    assert hasattr(mod, "Reg")


def test_env_port(monkeypatch):
    monkeypatch.setenv("I3C_BLASTER_PORT", "COM42")
    sys.modules.pop("janus_ocpagent.agent", None)
    mod = importlib.import_module("janus_ocpagent.agent")
    assert mod.FORCED_PORT == "COM42"


def test_le_helpers():
    mod = importlib.import_module("janus_ocpagent.agent")
    agent_cls = mod.OcpRecoveryAgent
    assert agent_cls._to_le_bytes(0x11223344, 4) == [0x44, 0x33, 0x22, 0x11]
    assert agent_cls._u32_le([0x44, 0x33, 0x22, 0x11]) == 0x11223344
