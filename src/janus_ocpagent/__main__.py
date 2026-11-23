"""Allow `python -m janus_ocpagent` to run the recovery agent."""

import sys

from .agent import main

if __name__ == "__main__":
    sys.exit(main())
