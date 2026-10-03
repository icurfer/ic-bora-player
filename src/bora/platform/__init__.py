"""플랫폼이 갈리는 곳을 **여기 한 곳에** 모은다 (기획서 v0.6 §3-1).

본체 코드에 `if windows:` 를 흩으면 유지가 안 된다. 갈림길은 플랫폼 폴더 안에 두고,
바깥은 `from .platform import gl, paths, integration` 하나로 끝낸다.

```
platform/
  base.py        각 플랫폼이 지켜야 할 모양 + 공통 기본 구현
  linux/         ✅ 실기 검증됨 (Ubuntu 26.04)
  windows/       🚧 기획 v0.6 — 코드는 있으나 **미검증**
  macos/         📋 뼈대만 — 조사도 하지 않았다
  android/       📋 자리만 — 사실상 새 프로젝트다 (각 __init__ 참고)
```

어느 폴더가 쓰이는지는 **런타임에 한 번** 정해진다. 아래 import 가 명시적인 이유는
동적 로드보다 추적이 쉽고 린터가 볼 수 있어서다.
"""

from __future__ import annotations

import os
import sys


def _is_android() -> bool:
    """안드로이드는 `sys.platform` 이 'linux' 라 따로 가려야 한다."""
    if hasattr(sys, "getandroidapilevel"):
        return True
    return bool(os.environ.get("ANDROID_ROOT") and os.environ.get("ANDROID_DATA"))


IS_ANDROID = _is_android()
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux") and not IS_ANDROID


def name() -> str:
    """로그·진단에 적을 이름."""
    if IS_ANDROID:
        return "android"
    if IS_WINDOWS:
        return "windows"
    if IS_MAC:
        return "macos"
    if IS_LINUX:
        return "linux"
    return sys.platform


def verified() -> bool:
    """이 플랫폼에서 실기 검증을 마쳤나 — 경고를 띄울지 정하는 데 쓴다."""
    return IS_LINUX


if IS_ANDROID:                                      # pragma: no cover
    from .android import gl, integration, paths
elif IS_WINDOWS:                                    # pragma: no cover
    from .windows import gl, integration, paths
elif IS_MAC:                                        # pragma: no cover
    from .macos import gl, integration, paths
else:
    from .linux import gl, integration, paths

__all__ = [
    "IS_ANDROID", "IS_LINUX", "IS_MAC", "IS_WINDOWS",
    "gl", "integration", "name", "paths", "verified",
]
