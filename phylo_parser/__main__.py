# SPDX-FileCopyrightText: 2026 Thiago S. R. Silva, Diego S. Porto
# SPDX-License-Identifier: MIT

"""
Package entry point.

Allows execution via:
    python -m phylo_parser
"""

from .main import main


def run() -> None:
    main()


if __name__ == "__main__":
    run()
