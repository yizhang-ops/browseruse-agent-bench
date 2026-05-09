#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import List, Optional

from browseruse_bench.cli import main as cli_main


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    return cli_main(["skills", *args])


if __name__ == "__main__":
    sys.exit(main())
