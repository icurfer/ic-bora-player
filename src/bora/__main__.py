"""진입점. `bora [--debug] [영상] [자막]`"""

from __future__ import annotations

import sys

from .app import BoraApplication
from .log import debug_enabled, setup


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    debug = debug_enabled(argv)
    logger = setup(debug)
    if debug:
        logger.debug("디버그 로그 켜짐. BORA_LOG_FILE 을 주면 파일로도 남는다.")
    # --debug 는 우리 것이므로 GTK 에 넘기지 않는다(모르는 인자로 취급돼 경고가 난다).
    argv = [a for a in argv if a != "--debug"]
    return BoraApplication().run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
