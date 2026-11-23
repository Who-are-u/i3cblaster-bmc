# i3cblaster-bmc

BMC-side **OCP Recovery (streaming boot)** agent that pushes a firmware image
into a device (e.g. a Caliptra recovery interface) over **I3C**, using the
[I3CBlaster](https://github.com/xyphro/I3CBlaster) USB-to-I3C converter.

## Layout

- `src/i3cblaster_bmc.py` - the OCP Recovery streaming-boot agent (entry point `main`).
- `examples/` - runnable examples (e.g. `i3c_bus_test.py`, an I3C bus test /
  waveform generator).
- `docs/` - project documentation.
- `tools/` - helper scripts and utilities, including the
  `XyphroLabs-I3C-Saleae-Protocol-Analyzer` git submodule (Saleae Logic 2 I3C
  decoder).
- `tests/` - pytest test suite (hardware-free smoke tests).
- `I3CBlaster/` - **git submodule** of `xyphro/I3CBlaster`. The
  `i3cblaster` Python module (`I3CBlaster/python/i3cblaster.py`) is loaded at
  runtime via `sys.path`, so the submodule stays pristine.

## Setup (uv + git)

Clone with submodules:

```
git clone --recurse-submodules <this-repo-url>
```

If already cloned without submodules:

```
git submodule update --init --recursive
```

Create the environment and install dependencies with [uv](https://docs.astral.sh/uv/):

```
uv sync
```

## Configure the serial port

The I3C Blaster COM port is read from the `I3C_BLASTER_UART` environment
variable (see `.env.example`):

- Windows: `set I3C_BLASTER_UART=COM5`
- Linux/macOS: `export I3C_BLASTER_UART=/dev/ttyACM0`

In the agent, if the variable is unset the port is auto-detected by
USB VID:PID (0x2E8A:0x000A). The example falls back to `COM5`.

## Run

The agent's main job is to stream a firmware **binary blob** into the recovery
device. Pass the file to send as a positional argument:

```
uv run i3cblaster-bmc path/to/firmware.bin
```

or equivalently:

```
uv run python -m i3cblaster_bmc path/to/firmware.bin
```

If no firmware file is given, the agent still connects, discovers the device
and exercises the register-access flow, but does not stream an image.

### Options

```
firmware              Path to the firmware binary blob to stream (positional).
--uart UART           I3CBlaster serial/COM port (e.g. COM5 or /dev/ttyACM0).
                      Defaults to $I3C_BLASTER_UART, else auto-detect by USB VID:PID.
--clk-khz CLK_KHZ     I3C clock rate in kHz (default: 12500).
--addr ADDR           Known recovery device I3C dynamic address (e.g. 0x08).
                      If omitted, the device is discovered via ENTDAA / scan.
--entdaa-addr ADDR    Dynamic address to assign during ENTDAA (default: 0x08).
--chunk-size N        Bytes per INDIRECT_FIFO_DATA write (default: 64).
--no-activate         Stream the image but skip the final activate/boot step.
```

Example specifying an explicit port and address:

```
uv run i3cblaster-bmc fw.bin --uart COM5 --addr 0x08 --chunk-size 128
```

Run `uv run i3cblaster-bmc --help` for the full, current list.


The I3C bus test example:

```
uv run python examples/i3c_bus_test.py
```

The one-shot dynamic address assignment example:

```
uv run python examples/i3c_entdaa_test.py
```

This reuses the bus example's connection settings (`I3C_BLASTER_UART`, default
`COM5`, and a 12500 kHz clock). It runs ENTDAA once to assign `0x30` to one
unaddressed target and prints its PID, BCR, and DCR. Ensure `0x30` is unused
on the bus before running. It does not send RSTDAA, reset targets, or send
private write data. Already-addressed targets do not participate in ENTDAA.

For a successful capture, expect START, `0x7E+W`, the ENTDAA CCC `0x07`,
repeated START, `0x7E+R`, the target's 48-bit PID / 8-bit BCR / 8-bit DCR,
and the assigned 7-bit address plus odd parity (`0x30` encodes as `0x61`),
followed by STOP. Without a responding target, the transfer can terminate
early with a NACK; a complete assignment waveform is not guaranteed.

## Test

```
uv run pytest
```

## Notes

- The OCP Recovery Command Codes (0x22-0x2B) and register bit-field layouts in
  `src/i3cblaster_bmc.py` are placeholders from the common OCP map and MUST be verified
  against the exact OCP Recovery spec revision / Caliptra register definitions
  before real use.
