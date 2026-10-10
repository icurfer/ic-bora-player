"""윈도우 데스크톱 연동 — 기본 앱 변경은 미지원, 외부 터미널은 PowerShell.

기본 재생기 설정은 윈도우에서 레지스트리(`HKCU\\Software\\Classes`)와
`SetUserFTA` 수준의 해시 검증까지 걸려 있어, 리눅스의 `xdg-mime` 처럼 간단하지 않다.
윈도우 10 부터는 **기본 앱을 프로그램이 임의로 바꾸는 것을 막는다** — 설정 앱에서
사용자가 직접 고르게 하는 것이 정석이다.

기획 v0.6 범위 밖이다(§2-2). 메뉴는 끄고 아래 이유를 화면에 적는다.
"""

from __future__ import annotations

from ..base import can_set_default, is_default, set_default, snapshot_defaults  # noqa: F401


def unsupported_reason() -> str:
    return ("윈도우는 기본 앱을 설정 앱에서 직접 고르게 한다 — "
            "설정 → 앱 → 기본 앱에서 Bora 를 고르면 된다")


def launch_terminal(argv, cwd, env):
    """새 PowerShell 콘솔에서 실행한다. 질문은 셸 코드로 합치지 않는다."""
    import base64
    import json
    from pathlib import Path
    import shutil
    import subprocess

    if not argv:
        raise OSError("터미널에서 실행할 명령이 없습니다.")
    if Path(argv[0]).suffix.lower() in (".cmd", ".bat"):
        raise OSError("배치 파일 대신 CLI의 exe 또는 ps1 실행 파일을 지정하세요.")
    shell = shutil.which("powershell.exe", path=env.get("PATH", ""))
    if shell is None:
        raise OSError("PowerShell을 찾지 못했습니다. Windows 실행 환경을 확인하세요.")
    arguments = list(argv)
    if Path(arguments[0]).suffix.lower() == ".ps1":
        arguments = [shell, "-NoLogo", "-NoProfile", "-File", *arguments]
    payload = base64.b64encode(json.dumps(
        {"file": arguments[0], "arguments": subprocess.list2cmdline(arguments[1:])},
        ensure_ascii=False,
    ).encode("utf-8")).decode("ascii")
    script = (
        "$ErrorActionPreference='Stop'; "
        "$a=ConvertFrom-Json ([Text.Encoding]::UTF8.GetString("
        f"[Convert]::FromBase64String('{payload}'))); "
        "$info=New-Object Diagnostics.ProcessStartInfo; "
        "$info.FileName=$a.file; $info.Arguments=$a.arguments; "
        "$info.UseShellExecute=$false; $info.WorkingDirectory=(Get-Location).Path; "
        "$child=[Diagnostics.Process]::Start($info); $child.WaitForExit(); "
        "if ($child.ExitCode) { Write-Error ('CLI 종료 코드: '+$child.ExitCode) }"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    process = subprocess.Popen(
        [shell, "-NoLogo", "-NoProfile", "-NoExit", "-EncodedCommand", encoded],
        cwd=cwd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    try:
        code = process.wait(timeout=1)
        if code:
            raise OSError(f"PowerShell을 열지 못했습니다 (종료 코드 {code}).")
    except subprocess.TimeoutExpired:
        return
