#!/usr/bin/env python3
import sys
from pathlib import Path

# Make the in-repo `apigen` package importable regardless of the caller's cwd
repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root))

from apigen.cli import main

if __name__ == "__main__":
    main()
