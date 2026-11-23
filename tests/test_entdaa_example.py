import importlib
from pathlib import Path
from unittest.mock import Mock, call

import pytest


@pytest.fixture
def example(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "examples"))
    return importlib.import_module("i3c_entdaa_test")


@pytest.fixture
def blaster(example, monkeypatch):
    device = Mock()
    device._connect.return_value = True
    device.i3c_entdaa.return_value = [0x04, 0x6A, 0, 0, 0, 0, 0x27, 0xA0]
    monkeypatch.setattr(example, "ForcedPortBlaster", Mock(return_value=device))
    return device


def test_assigns_once_without_reset(example, blaster, capsys):
    port = blaster._ser
    assert example.main() == 0
    assert blaster.mock_calls == [
        call.init(),
        call._connect(),
        call.i3c_clk(example.CLK_KHZ),
        call.i3c_entdaa(0x30),
        call._ser.close(),
    ]
    port.close.assert_called_once()
    assert blaster._ser is None
    output = capsys.readouterr().out
    assert "Assigned dynamic address: 0x30" in output
    assert "PID: 0x046A00000000, BCR: 0x27, DCR: 0xA0" in output


@pytest.mark.parametrize("data", [None, [], [0x04, 0x6A]])
def test_unconfirmed_assignment(example, blaster, capsys, data):
    blaster.i3c_entdaa.return_value = data
    port = blaster._ser
    assert example.main() == 1
    assert "Assigned dynamic address:" not in capsys.readouterr().out
    port.close.assert_called_once()


def test_firmware_error(example, blaster, capsys):
    blaster.i3c_entdaa.side_effect = Exception("ERR_NAKED_DURING_ARBHDR(2)")
    port = blaster._ser
    assert example.main() == 1
    assert "ERROR: ERR_NAKED_DURING_ARBHDR(2)" in capsys.readouterr().out
    port.close.assert_called_once()


def test_connection_error(example, blaster, capsys):
    blaster._ser = None
    blaster._connect.side_effect = RuntimeError("Access is denied")
    assert example.main() == 1
    assert "Access is denied" in capsys.readouterr().out
    blaster.i3c_entdaa.assert_not_called()


def test_clock_error(example, blaster, capsys):
    blaster.i3c_clk.side_effect = Exception("clock failed")
    port = blaster._ser
    assert example.main() == 1
    assert "clock failed" in capsys.readouterr().out
    blaster.i3c_entdaa.assert_not_called()
    port.close.assert_called_once()
