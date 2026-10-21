"""PyInstaller entry point (a package's __main__ cannot be the target directly)."""

import sys

from tracker_agent.app import main

sys.exit(main())
