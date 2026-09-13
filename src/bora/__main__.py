"""진입점. `bora [영상] [자막]`"""

from __future__ import annotations

import sys

from .app import BoraApplication


def main(argv: list[str] | None = None) -> int:
    return BoraApplication().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
