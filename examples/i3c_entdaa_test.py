"""Assign dynamic address 0x30 to one unaddressed I3C target using ENTDAA."""

from i3c_bus_test import CLK_KHZ, FORCED_PORT, ForcedPortBlaster


DYNAMIC_ADDR = 0x30


def main():
    i3c = ForcedPortBlaster()
    i3c.init()
    try:
        print(f"Connecting to {FORCED_PORT} ...")
        if not i3c._connect():
            print(f"ERROR: could not connect to {FORCED_PORT}.")
            return 1

        i3c.i3c_clk(CLK_KHZ)
        print(f"i3c_clk set to {CLK_KHZ} kHz")
        print(f"Sending ENTDAA once, assigning 0x{DYNAMIC_ADDR:02X}. "
              "No RSTDAA is sent; ensure this address is unused on the bus.")
        data = i3c.i3c_entdaa(DYNAMIC_ADDR)
        if data is None:
            print("ENTDAA was NACKed during addressing. No assignment confirmed; "
                  "the target may already have a dynamic address.")
            return 1
        if len(data) != 8:
            print(f"ERROR: expected 8 identity bytes (PID/BCR/DCR), got {data!r}.")
            return 1

        pid = "".join(f"{byte:02X}" for byte in data[:6])
        print(f"Assigned dynamic address: 0x{DYNAMIC_ADDR:02X}")
        print(f"PID: 0x{pid}, BCR: 0x{data[6]:02X}, DCR: 0x{data[7]:02X}")
        return 0
    except Exception as exc:
        # The bundled API reports firmware errors as generic Exception.
        print(f"ERROR: {exc}")
        return 1
    finally:
        if i3c._ser is not None:
            i3c._ser.close()
            i3c._ser = None


if __name__ == "__main__":
    raise SystemExit(main())
