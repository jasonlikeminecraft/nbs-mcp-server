from __future__ import annotations

import sys

from lifecycle import uninstall


if __name__ == "__main__":
    raise SystemExit(uninstall(sys.argv[1:]))
