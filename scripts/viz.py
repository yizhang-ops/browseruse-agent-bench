#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browseruse_bench.cli import main as cli_main


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    return cli_main(["viz", *args])


if __name__ == "__main__":
    sys.exit(main())
