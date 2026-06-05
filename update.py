from __future__ import annotations

import sys

from lifecycle import update


if __name__ == "__main__":
    raise SystemExit(update(sys.argv[1:]))
