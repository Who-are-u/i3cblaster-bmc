# Tools

Helper scripts and third-party utilities for Janus_OCPagent.

## XyphroLabs-I3C-Saleae-Protocol-Analyzer

A **git submodule** of
[xyphro/XyphroLabs-I3C-Saleae-Protocol-Analyzer](https://github.com/xyphro/XyphroLabs-I3C-Saleae-Protocol-Analyzer),
an I3C protocol decoder for the Saleae Logic 2 software. Use it to decode I3C
traffic captured from the I3CBlaster bus.

Install in Logic 2: Edit -> Preferences -> "Custom Low Level Analyzers" ->
point to this folder -> restart. Then Analyzers -> + -> I3C, and set
SCL = D0, SDA = D1 (adjust to your channels).

## Other tools (planned)

- Firmware image preparation / conversion helpers.
- I3C bus scan / diagnostic utilities.
- Logic-analyzer capture post-processing.
