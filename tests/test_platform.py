# -*- coding: utf-8 -*-
"""플랫폼 분기 회귀 테스트 — 기획 v0.6 §3-1.

폴더가 넷(linux·windows·macos·android)으로 갈렸다. **지금 돌고 있는 플랫폼이 아닌 것도
import 는 되어야** 한다 — 안 되면 다른 플랫폼에서 손볼 때 바로 터진다.

그리고 각 폴더가 같은 이름을 같은 뜻으로 제공하는지 본다(`platform/base.py` 의 명세).
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bora import platform as P  # noqa: E402

PLATFORMS = ("linux", "windows", "macos", "android")
GL_NAMES = ("available", "get_proc_address", "current_fbo")
PATH_NAMES = ("config_dir", "cache_dir", "data_dir", "venv_python", "venv_pip")
INTEGRATION_NAMES = ("can_set_default", "is_default", "snapshot_defaults",
                     "set_default", "unsupported_reason", "launch_terminal")


@pytest.mark.parametrize("plat", PLATFORMS)
@pytest.mark.parametrize("module,names", [
    ("gl", GL_NAMES), ("paths", PATH_NAMES), ("integration", INTEGRATION_NAMES),
])
def test_every_platform_provides_the_same_names(plat, module, names) -> None:
    """빠진 이름이 있으면 그 플랫폼에서 AttributeError 로 터진다."""
    mod = importlib.import_module(f"bora.platform.{plat}.{module}")
    missing = [n for n in names if not hasattr(mod, n)]
    assert not missing, f"{plat}.{module} 에 없다: {missing}"


@pytest.mark.parametrize("plat", PLATFORMS)
def test_other_platforms_import_cleanly(plat) -> None:
    """지금 플랫폼이 아니어도 import 자체는 되어야 한다 — 로드 실패는 available() 로 알린다."""
    gl = importlib.import_module(f"bora.platform.{plat}.gl")
    assert isinstance(gl.available(), bool)
    assert isinstance(gl.current_fbo(), int)
    assert isinstance(gl.get_proc_address(None, b"glGetString"), int)


def test_exactly_one_platform_is_selected() -> None:
    flags = [P.IS_LINUX, P.IS_WINDOWS, P.IS_MAC, P.IS_ANDROID]
    assert sum(1 for f in flags if f) == 1, f"플랫폼 판정이 겹치거나 비었다: {flags}"


def test_android_is_not_mistaken_for_linux() -> None:
    """안드로이드는 sys.platform 이 'linux' 다 — 따로 가려야 한다."""
    if P.IS_ANDROID:
        assert not P.IS_LINUX
    else:
        assert not P.IS_ANDROID


def test_selected_modules_match_the_platform() -> None:
    assert P.name() in P.gl.__name__
    assert P.name() in P.paths.__name__
    assert P.name() in P.integration.__name__


def test_paths_are_absolute_and_under_one_root() -> None:
    for getter in (P.paths.config_dir, P.paths.cache_dir, P.paths.data_dir):
        path = getter()
        assert path.is_absolute(), f"{getter.__name__} 이 상대경로다: {path}"
        assert path.name == "bora" or "bora" in str(path), path


def test_windows_venv_layout_differs() -> None:
    """윈도우만 Scripts/ 다. 이걸 틀리면 선택 기능이 조용히 안 뜬다."""
    from bora.platform.linux import paths as lin
    from bora.platform.windows import paths as win
    venv = Path("/x/.venv")
    assert lin.venv_python(venv).name == "python"
    assert win.venv_python(venv).name == "python.exe"
    assert "Scripts" in str(win.venv_python(venv))
    assert "bin" in str(lin.venv_python(venv))


@pytest.mark.parametrize("plat", ("windows", "macos", "android"))
def test_unsupported_platforms_explain_themselves(plat) -> None:
    """못 하는 기능은 **왜 못 하는지**를 남긴다 — 조용한 실패를 만들지 않는다."""
    integration = importlib.import_module(f"bora.platform.{plat}.integration")
    assert not integration.can_set_default()
    reason = integration.unsupported_reason()
    assert reason and len(reason) > 10, f"{plat}: 이유가 비었다"


def test_linux_can_set_default() -> None:
    from bora.platform.linux import integration as lin
    assert callable(lin.can_set_default)
    assert isinstance(lin.can_set_default(), bool)
