"""PyInstaller entry point: start PDF Studio exactly as ``python -m app`` does."""

import sys

from app.launcher import main

sys.exit(main())
