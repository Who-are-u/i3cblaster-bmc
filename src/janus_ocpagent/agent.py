"""
OCP Recovery (streaming boot) agent over I3C, using the I3CBlaster firmware.

This implements a BMC-side agent that pushes a firmware image into a device
(e.g. a Caliptra recovery interface) using the OCP "Secure Firmware Recovery"
register interface, transported over I3C via the i3cblaster module.

How it works
------------
The OCP Recovery interface exposes a set of standardized registers, each
addressed by a fixed "Command Code" (defined by the OCP Recovery spec, NOT
returned by the device). Registers are accessed as I3C private transfers:

    read_reg :  i3c_sdr_writeread(addr, [command_code], length)
    write_reg:  i3c_sdr_write(addr, [command_code, data...])

Firmware is streamed by repeatedly writing chunks into INDIRECT_FIFO_DATA,
observing INDIRECT_FIFO_STATUS for flow control.

IMPORTANT
---------
- The Command Code values below follow the common OCP Recovery register map.
  VERIFY them against the exact OCP Recovery spec revision / Caliptra register
  definition you are targeting, and adjust the constants if needed.
- The device I3C address is discovered at runtime (i3c_scan / i3c_entdaa),
  since that is bus/config specific, unlike the fixed register command codes.
"""

import argparse
import os
import sys
import time


# Load the i3cblaster module from the I3CBlaster git submodule.
# This module lives in src/janus_ocpagent/, so the repo root is three levels up.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SUBMODULE_PY = os.path.join(_REPO_ROOT, "I3CBlaster", "python")
if _SUBMODULE_PY not in sys.path:
    sys.path.insert(0, _SUBMODULE_PY)

import i3cblaster


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# I3C Blaster COM port. Loaded from the I3C_BLASTER_PORT environment variable.
# Leave unset (or empty) to auto-detect by USB VID/PID (0x2E8A:0x000A).
FORCED_PORT = os.environ.get("I3C_BLASTER_PORT") or None
I3C_CLK_KHZ = 12500           # I3C clock (kHz)

# If you already know the recovery device's dynamic address, set it here to
# skip discovery. Otherwise leave None to scan / assign via ENTDAA.
RECOVERY_ADDR = None
ENTDAA_ASSIGN_ADDR = 0x08     # dynamic address to assign if we run ENTDAA

# Firmware image to stream. Replace with your Caliptra recovery image path.
FIRMWARE_PATH = "firmware.bin"

# Streaming chunk size (bytes) written per INDIRECT_FIFO_DATA transfer.
# Keep modest to stay within a single I3C private write; tune to the device.
CHUNK_SIZE = 64


# ----------------------------------------------------------------------------
# OCP Recovery register Command Codes  (VERIFY against your spec revision!)
# ----------------------------------------------------------------------------

class Reg:
    PROT_CAP             = 0x22  # Protocol capabilities
    DEVICE_ID            = 0x23  # Device identification
    DEVICE_STATUS        = 0x24  # Device status
    DEVICE_RESET         = 0x25  # Device reset control
    RECOVERY_CTRL        = 0x26  # Recovery control (activate/select component)
    RECOVERY_STATUS      = 0x27  # Recovery status / progress
    HW_STATUS            = 0x28  # Hardware status
    INDIRECT_FIFO_CTRL   = 0x29  # Indirect FIFO control (image size, reset)
    INDIRECT_FIFO_STATUS = 0x2A  # Indirect FIFO status (space / empty / full)
    INDIRECT_FIFO_DATA   = 0x2B  # Indirect FIFO data window (stream fw here)


# DEVICE_STATUS device-state field values (example encoding; verify with spec)
DEV_STATUS_RECOVERY_MODE = 0x03   # "Recovery mode - awaiting recovery image"

# RECOVERY_CTRL / RECOVERY_STATUS bit fields (example; verify with spec)
RECOVERY_CTRL_ACTIVATE = 0x0F     # value that triggers activate/boot of image
RECOVERY_STATUS_MASK   = 0x0F
RECOVERY_STATUS_AWAIT  = 0x01     # awaiting recovery image
RECOVERY_STATUS_BOOTING = 0x02    # booting recovery image
RECOVERY_STATUS_SUCCESS = 0x03    # recovery successful


# ----------------------------------------------------------------------------
# I3C wrapper with a forced COM port and a corrected i3c_clk command
# ----------------------------------------------------------------------------

class Blaster(i3cblaster.i3cblaster):
    def _findcomport(self, serialnumber=None):
        if FORCED_PORT is not None:
            return FORCED_PORT
        return super()._findcomport(serialnumber)

    # The shipped module sends 'i3c_clock' but firmware expects 'i3c_clk'.
    def i3c_clk(self, clockrate_khz):
        resp = self._parse_response(self._exec('i3c_clk %d' % clockrate_khz))
        if resp[0] != self.OKTEXT:
            raise Exception('I3C Blaster exception: ' + resp[0])


# ----------------------------------------------------------------------------
# OCP Recovery agent
# ----------------------------------------------------------------------------

class OcpRecoveryAgent:
    def __init__(self, i3c, addr):
        self.i3c = i3c
        self.addr = addr

    # --- low level register access -----------------------------------------

    def read_reg(self, command_code, length):
        """Read `length` bytes from a recovery register."""
        return self.i3c.i3c_sdr_writeread(self.addr, [command_code], length)

    def write_reg(self, command_code, data_bytes):
        """Write data bytes to a recovery register."""
        self.i3c.i3c_sdr_write(self.addr, [command_code] + list(data_bytes))

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _u32_le(data):
        """Interpret up to 4 little-endian bytes as an unsigned int."""
        val = 0
        for i, b in enumerate(data[:4]):
            val |= (b & 0xFF) << (8 * i)
        return val

    @staticmethod
    def _to_le_bytes(value, n):
        return [(value >> (8 * i)) & 0xFF for i in range(n)]

    # --- protocol steps -----------------------------------------------------

    def read_prot_cap(self):
        data = self.read_reg(Reg.PROT_CAP, 15)
        print("PROT_CAP:", [hex(b) for b in data])
        return data

    def read_device_id(self):
        data = self.read_reg(Reg.DEVICE_ID, 24)
        print("DEVICE_ID:", [hex(b) for b in data])
        return data

    def read_device_status(self):
        data = self.read_reg(Reg.DEVICE_STATUS, 4)
        state = data[0] if data else None
        print("DEVICE_STATUS:", [hex(b) for b in data], "state=", hex(state) if state is not None else None)
        return data

    def read_recovery_status(self):
        data = self.read_reg(Reg.RECOVERY_STATUS, 2)
        st = (data[0] & RECOVERY_STATUS_MASK) if data else None
        print("RECOVERY_STATUS:", [hex(b) for b in data], "->", hex(st) if st is not None else None)
        return st

    def wait_recovery_mode(self, timeout_s=5.0):
        """Wait until the device reports it is awaiting a recovery image."""
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            data = self.read_device_status()
            if data and data[0] == DEV_STATUS_RECOVERY_MODE:
                print("Device is in recovery mode (awaiting image).")
                return True
            time.sleep(0.1)
        print("WARNING: device did not enter recovery mode within timeout.")
        return False

    def configure_fifo(self, image_size_bytes):
        """
        Program INDIRECT_FIFO_CTRL with the image size and reset the FIFO.
        Layout is device specific; a common layout is:
          [0]      = reset/flags
          [1]      = component/CMS index
          [2..5]   = image size in 4-byte units (or bytes), little-endian
        Adjust to match your spec.
        """
        # Example: reset FIFO + set image size (in bytes, LE, 4 bytes).
        size_le = self._to_le_bytes(image_size_bytes, 4)
        payload = [0x01, 0x00] + size_le  # [reset=1, cms=0, size...]
        self.write_reg(Reg.INDIRECT_FIFO_CTRL, payload)
        print(f"INDIRECT_FIFO_CTRL programmed, image_size={image_size_bytes} bytes")

    def fifo_free_space(self):
        """
        Read INDIRECT_FIFO_STATUS and return an approximate free-space / status.
        Common layout:
          [0]     = flags (bit0 empty, bit1 full, ...)
          [1..4]  = write index / free space (device specific)
        Returns a tuple (flags, free_space_estimate).
        """
        data = self.read_reg(Reg.INDIRECT_FIFO_STATUS, 8)
        flags = data[0] if data else 0
        free = self._u32_le(data[1:5]) if len(data) >= 5 else None
        return flags, free, data

    def start_recovery(self):
        """Tell the device to begin recovery (select image via INDIRECT FIFO)."""
        # Common RECOVERY_CTRL layout: [component, image_source, activate]
        # Here: component 0, use indirect FIFO (source=1), do not activate yet.
        self.write_reg(Reg.RECOVERY_CTRL, [0x00, 0x01, 0x00])
        print("RECOVERY_CTRL: recovery started (indirect FIFO source).")

    def activate_image(self):
        """Tell the device the full image was delivered; activate/boot it."""
        self.write_reg(Reg.RECOVERY_CTRL, [0x00, 0x01, RECOVERY_CTRL_ACTIVATE])
        print("RECOVERY_CTRL: activate requested.")

    def stream_firmware(self, image, chunk_size=CHUNK_SIZE):
        """Stream the firmware image into INDIRECT_FIFO_DATA in chunks."""
        total = len(image)
        sent = 0
        print(f"Streaming {total} bytes in chunks of {chunk_size} ...")
        while sent < total:
            # Simple flow control: check FIFO status before writing.
            flags, free, raw = self.fifo_free_space()
            # If we can read a meaningful free-space value, respect it.
            if free is not None and free == 0:
                # FIFO full; wait a moment and retry.
                time.sleep(0.001)
                continue

            chunk = image[sent:sent + chunk_size]
            self.write_reg(Reg.INDIRECT_FIFO_DATA, chunk)
            sent += len(chunk)
            if (sent // chunk_size) % 16 == 0 or sent == total:
                print(f"  {sent}/{total} bytes sent")
        print("Firmware streaming complete.")

    def wait_recovery_complete(self, timeout_s=30.0):
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            st = self.read_recovery_status()
            if st == RECOVERY_STATUS_SUCCESS:
                print("Recovery SUCCESS.")
                return True
            time.sleep(0.2)
        print("WARNING: recovery did not report success within timeout.")
        return False


# ----------------------------------------------------------------------------
# Device discovery
# ----------------------------------------------------------------------------

def discover_device(i3c):
    """Return the I3C address of the recovery device.

    Order of preference:
      1. RECOVERY_ADDR if configured
      2. an address found via i3c_scan
      3. assign one via ENTDAA
    """
    if RECOVERY_ADDR is not None:
        print(f"Using configured recovery address 0x{RECOVERY_ADDR:02x}")
        return RECOVERY_ADDR

    # Clear stale dynamic addresses first.
    try:
        i3c.i3c_rstdaa()
    except Exception as e:
        print("i3c_rstdaa warning:", e)

    # Try assigning a dynamic address via ENTDAA.
    try:
        info = i3c.i3c_entdaa(ENTDAA_ASSIGN_ADDR)
        if info is not None:
            print(f"ENTDAA assigned 0x{ENTDAA_ASSIGN_ADDR:02x}, "
                  f"device info: {[hex(x) for x in info]}")
            return ENTDAA_ASSIGN_ADDR
        else:
            print("ENTDAA: no device responded (0x7E NAKed).")
    except Exception as e:
        print("i3c_entdaa warning:", e)

    # Fall back to scanning.
    try:
        targets = i3c.i3c_scan()
        targets = [t for t in targets if t != 0x7E]
        print("i3c_scan found:", [hex(t) for t in targets])
        if targets:
            return targets[0]
    except Exception as e:
        print("i3c_scan warning:", e)

    return None


# ----------------------------------------------------------------------------
# Command-line interface
# ----------------------------------------------------------------------------

def _auto_int(value):
    """Parse an int accepting decimal or 0x-prefixed hex on the command line."""
    return int(value, 0)


def build_arg_parser():
    """Build the argparse parser for the OCP Recovery agent CLI."""
    parser = argparse.ArgumentParser(
        prog="janus-ocpagent",
        description=(
            "Stream a firmware binary blob into an OCP Recovery device "
            "(e.g. Caliptra) over I3C using the I3CBlaster USB-to-I3C converter."
        ),
    )

    parser.add_argument(
        "firmware",
        nargs="?",
        default=FIRMWARE_PATH,
        help=(
            "Path to the firmware binary blob to stream into the device. "
            "If omitted, the register-access flow is exercised but no image "
            "is sent (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--port",
        default=FORCED_PORT,
        help=(
            "I3CBlaster serial/COM port (e.g. COM5 or /dev/ttyACM0). "
            "Defaults to the I3C_BLASTER_PORT environment variable, else "
            "auto-detect by USB VID:PID."
        ),
    )
    parser.add_argument(
        "--clk-khz",
        type=int,
        default=I3C_CLK_KHZ,
        help="I3C clock rate in kHz (default: %(default)s).",
    )
    parser.add_argument(
        "--addr",
        type=_auto_int,
        default=RECOVERY_ADDR,
        help=(
            "Known recovery device I3C dynamic address (e.g. 0x08). "
            "If omitted, the device is discovered via ENTDAA / scan."
        ),
    )
    parser.add_argument(
        "--entdaa-addr",
        type=_auto_int,
        default=ENTDAA_ASSIGN_ADDR,
        help="Dynamic address to assign during ENTDAA (default: 0x%(default)02x).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help="Bytes per INDIRECT_FIFO_DATA write (default: %(default)s).",
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Stream the image but skip the final activate/boot step.",
    )
    return parser


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    # Apply CLI selections to the runtime configuration used by the wrapper
    # and discovery helpers (which reference the module-level globals).
    global FORCED_PORT, RECOVERY_ADDR, ENTDAA_ASSIGN_ADDR
    FORCED_PORT = args.port
    RECOVERY_ADDR = args.addr
    ENTDAA_ASSIGN_ADDR = args.entdaa_addr

    i3c = Blaster()
    i3c.init()

    if not i3c._connect():
        print("ERROR: could not connect to I3CBlaster. "
              "Check COM port / firmware / that no terminal holds the port.")
        return 1

    print("Connected to I3CBlaster.")

    try:
        i3c.i3c_clk(args.clk_khz)
        print(f"I3C clock set to {args.clk_khz} kHz")
    except Exception as e:
        print("i3c_clk warning:", e)

    addr = discover_device(i3c)
    if addr is None:
        print("ERROR: no recovery device found on the I3C bus.")
        return 1
    print(f"Recovery device I3C address: 0x{addr:02x}")

    agent = OcpRecoveryAgent(i3c, addr)

    # --- OCP Recovery streaming boot sequence ---
    print("\n=== Reading capabilities / identity ===")
    try:
        agent.read_prot_cap()
        agent.read_device_id()
        agent.read_device_status()
    except Exception as e:
        print("Register read failed (check command codes / device):", e)
        return 1

    print("\n=== Ensure device is in recovery mode ===")
    agent.wait_recovery_mode(timeout_s=5.0)

    # Load firmware image.
    try:
        with open(args.firmware, "rb") as f:
            image = list(f.read())
    except FileNotFoundError:
        print(f"NOTE: firmware file '{args.firmware}' not found. "
              "Skipping streaming; register access flow was exercised.")
        return 0
    print(f"Loaded firmware '{args.firmware}': {len(image)} bytes")

    print("\n=== Start recovery / configure FIFO ===")
    agent.start_recovery()
    agent.configure_fifo(len(image))

    print("\n=== Stream firmware ===")
    agent.stream_firmware(image, chunk_size=args.chunk_size)

    if args.no_activate:
        print("\n=== Skipping activate (--no-activate) ===")
    else:
        print("\n=== Activate image ===")
        agent.activate_image()

        print("\n=== Wait for recovery to complete ===")
        agent.wait_recovery_complete(timeout_s=30.0)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


