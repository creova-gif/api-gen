#!/usr/bin/env python3
"""Compatibility wrapper for datapi."""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root))

from datapi.cli import main

if __name__ == "__main__":
    main()
