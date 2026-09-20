#!/usr/bin/env python3
"""Entry point: `python3 kit.py <command>`. All logic lives in forensics.cli."""
import sys

from forensics.cli import main

if __name__ == "__main__":
    sys.exit(main())
