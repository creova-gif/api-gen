#!/usr/bin/env python3
import sys
from pathlib import Path

# Add internal package path to sys.path
repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root / "apigen"))

from apigen.cli import main

if __name__ == "__main__":
    main()
