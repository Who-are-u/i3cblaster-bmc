"""
I3C bus test / waveform generator using the i3cblaster module.

Repeatedly issues an I3C SDR write so the controller drives SCL/SDA, which is
handy for capturing and identifying the SDR timing on a scope / logic analyzer.

The i3cblaster module normally auto-detects the COM port by USB VID/PID.
Here we force it to a fixed port (from I3C_BLASTER_PORT, default COM5) by
overriding the internal _findcomport method.
"""

import os
import sys
import time

# Load the i3cblaster module from the I3CBlaster git submodule.
# This file lives in examples/, so the repo root is one level up.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SUBMODULE_PY = os.path.join(_REPO_ROOT, "I3CBlaster", "python")
if _SUBMODULE_PY not in sys.path:
    sys.path.insert(0, _SUBMODULE_PY)

import i3cblaster


# I3C Blaster COM port, loaded from the I3C_BLASTER_PORT environment variable
# (falls back to COM5 if unset).
FORCED_PORT = os.environ.get("I3C_BLASTER_PORT", "COM5")

# I3C clock frequency (in kHz) to send in the loop, and the loop interval.
CLK_KHZ = 12500        # 12.5 MHz
LOOP_INTERVAL_S = 2.0  # seconds between each transfer

# Target address and data bytes to write in the loop. The Blaster first sends
# the I3C arbitration header; if that is NACKed, firmware stops before sending
# the target address or payload.
TARGET_ADDR = 0x30
WRITE_DATA = [0xAB, 0xCD]


class ForcedPortBlaster(i3cblaster.i3cblaster):
    """i3cblaster variant that always connects to a fixed COM port."""

    def _findcomport(self, serialnumber=None):
        return FORCED_PORT

    def _connect(self, forcereconnect=False):
        if forcereconnect and self._ser is not None:
            self._ser.close()
            self._ser = None

        if self._ser is None:
            comport = self._findcomport(self._serialnumber)
            if comport is None:
                return False

            self.close_serialport(comport)
            try:
                self._ser = i3cblaster.serial.Serial(
                    comport, 115200, timeout=1
                )
            except i3cblaster.serial.SerialException as exc:
                raise RuntimeError(
                    f"Could not open {comport}: {exc}. Close any terminal "
                    "or other program using the port, then try again."
                ) from exc

            startup_deadline = time.monotonic() + 2
            while time.monotonic() < startup_deadline:
                if self._ser.read_all():
                    time.sleep(0.5)
                    self._ser.read_all()
                    break
                time.sleep(0.05)

        return self._ser is not None

    # The shipped module sends 'i3c_clock', but the firmware command is
    # actually 'i3c_clk' (see README command table). Override to fix it.
    def i3c_clk(self, clockrate_khz):
        resp = self._parse_response(self._exec('i3c_clk %d' % clockrate_khz))
        if resp[0] != self.OKTEXT:
            raise Exception('I3C Blaster exception: ' + resp[0])


def main():
    print("Detected i3cblaster devices (by VID/PID):", i3cblaster.listdevices())

    i3c = ForcedPortBlaster()
    i3c.init()  # no serialnumber needed, port is forced

    print(f"Connecting to {FORCED_PORT} ...")
    try:
        connected = i3c._connect()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return
    if not connected:
        print(f"ERROR: could not open {FORCED_PORT}. "
              "Check the cable and that the firmware is flashed.")
        return

    print(f"Connected to {FORCED_PORT}.")

    # Set the clock rate ONCE. i3c_clk() only configures the frequency;
    # it does NOT toggle SCL by itself. On I3C (like I2C) the clock is
    # generated only during an actual bus transfer, so to see any signal
    # on SCL/SDA we must repeatedly trigger real bus traffic below.
    try:
        i3c.i3c_clk(CLK_KHZ)
        print(f"i3c_clk set to {CLK_KHZ} kHz")
    except Exception as e:
        print("i3c_clk failed:", e)

    # Continuously attempt an I3C SDR write. An arbitration-header NACK aborts
    # the transfer before the private address and payload, so a responding
    # target (and appropriate bus wiring) is required to capture the full
    # write waveform. Press Ctrl+C to stop.
    data_str = ",".join(hex(d) for d in WRITE_DATA)
    print(f"Looping i3c_sdr_write(0x{TARGET_ADDR:02x}, [{data_str}]) "
          f"every {LOOP_INTERVAL_S}s. Press Ctrl+C to stop.")
    count = 0
    try:
        if True:
            count += 1
            try:
                i3c.i3c_sdr_write(TARGET_ADDR, WRITE_DATA)
            except Exception as e:
                if "ERR_NAKED_DURING_ARBHDR" in str(e):
                    print(f"[{count}] arbitration header NACK; "
                          f"address/data not sent: {e}")
                else:
                    raise
            else:
                print(f"[{count}] write completed")
            time.sleep(LOOP_INTERVAL_S)
    except KeyboardInterrupt:
        print(f"\nStopped after {count} transfers.")


if __name__ == "__main__":
    main()
