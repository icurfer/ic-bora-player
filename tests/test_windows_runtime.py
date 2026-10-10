"""Windows runtime regressions without requiring GTK or a display."""
import base64
import ctypes
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1] / "src/bora/platform"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gl = load("windows_gl_test", ROOT / "windows/gl.py")
base = load("bora_platform.base", ROOT / "base.py")
with patch.dict(sys.modules, {"bora_platform.base": base}):
    integration = load("bora_platform.windows.integration", ROOT / "windows/integration.py")


class WindowsGLTests(unittest.TestCase):
    def setUp(self):
        self.wgl = Mock(_handle=10)
        self.egl = Mock(_handle=20)
        self.wgl.wglGetCurrentContext.return_value = 1
        self.egl.eglGetCurrentContext.return_value = 0
        self.kernel = Mock()
        self.kernel.GetProcAddress.return_value = 1234
        for key, value in (("_gl", self.wgl), ("_egl", self.egl), ("_kernel32", self.kernel)):
            replacement = patch.object(gl, key, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_wgl_failure_addresses_use_dll_export(self):
        for address in (None, 0, 1, 2, 3, -1, ctypes.c_void_p(-1).value):
            self.wgl.wglGetProcAddress.return_value = address
            self.assertEqual(gl.get_proc_address(None, b"glGetString"), 1234)

    def test_wgl_extension(self):
        self.wgl.wglGetProcAddress.return_value = 5678
        self.assertEqual(gl.get_proc_address(None, b"glBindFramebuffer"), 5678)
        self.kernel.GetProcAddress.assert_not_called()

    def test_egl_context_never_uses_wgl(self):
        self.egl.eglGetCurrentContext.return_value = 1
        self.egl.eglGetProcAddress.return_value = 4321
        self.assertEqual(gl.get_proc_address(None, b"glGetIntegerv"), 4321)
        self.wgl.wglGetProcAddress.assert_not_called()

    def test_egl_core_export_fallback(self):
        self.egl.eglGetCurrentContext.return_value = 1
        self.egl.eglGetProcAddress.return_value = 0
        with patch.object(gl, "_gles", Mock(_handle=30)):
            self.assertEqual(gl.get_proc_address(None, b"glGetIntegerv"), 1234)
        self.assertEqual(self.kernel.GetProcAddress.call_args.args[0].value, 30)

    def test_no_context_returns_zero_without_calling_gl(self):
        self.wgl.wglGetCurrentContext.return_value = 0
        self.assertEqual(gl.current_fbo(), 0)
        self.wgl.wglGetProcAddress.assert_not_called()

    def test_current_fbo_uses_resolved_backend_function(self):
        factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)

        @factory(None, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))
        def query(enum, result):
            self.assertEqual(enum, gl.GL_DRAW_FRAMEBUFFER_BINDING)
            result[0] = 42

        with patch.object(gl, "get_proc_address", return_value=ctypes.cast(query, ctypes.c_void_p).value):
            self.assertEqual(gl.current_fbo(), 42)


class WindowsTerminalTests(unittest.TestCase):
    @patch("shutil.which", return_value="powershell.exe")
    @patch("subprocess.Popen")
    def test_encoded_arguments_and_new_console(self, popen, which):
        argv = ["C:/한글 폴더/codex.exe", "a'; & echo bad\n새 질문"]
        popen.return_value.wait.side_effect = subprocess.TimeoutExpired("test", 1)
        env = {"PATH": "tools"}
        with patch.object(subprocess, "CREATE_NEW_CONSOLE", 16, create=True):
            integration.launch_terminal(argv, Path("C:/notes"), env)
        command = popen.call_args.args[0]
        script = base64.b64decode(command[-1]).decode("utf-16le")
        payload = script.split("FromBase64String('")[1].split("'")[0]
        self.assertEqual(json.loads(base64.b64decode(payload)),
                         {"file": argv[0], "arguments": subprocess.list2cmdline(argv[1:])})
        self.assertNotIn(argv[1], script)
        self.assertEqual(popen.call_args.kwargs["env"], env)
        self.assertEqual(popen.call_args.kwargs["creationflags"], 16)
        which.assert_called_once_with("powershell.exe", path="tools")

    def test_batch_launcher_is_explicitly_rejected(self):
        for name in ("codex.cmd", "claude.BAT"):
            with self.assertRaisesRegex(OSError, "exe 또는 ps1"):
                integration.launch_terminal([name], Path("."), {})

    @patch("shutil.which", return_value=None)
    def test_missing_powershell(self, which):
        with self.assertRaisesRegex(OSError, "PowerShell"):
            integration.launch_terminal(["codex.exe"], Path("."), {})

    @patch("shutil.which", return_value="powershell.exe")
    @patch("subprocess.Popen")
    def test_early_failure(self, popen, which):
        popen.return_value.wait.return_value = 1
        with patch.object(subprocess, "CREATE_NEW_CONSOLE", 16, create=True):
            with self.assertRaisesRegex(OSError, "종료 코드 1"):
                integration.launch_terminal(["codex.exe"], Path("."), {})

    @unittest.skipUnless(sys.platform == "win32", "Windows native process test")
    def test_real_powershell_preserves_native_arguments(self):
        import tempfile

        actual_popen = subprocess.Popen
        # 같은 실행 스크립트를 격리 실행하되 검증 콘솔은 즉시 닫는다.
        def isolated_popen(command, **kwargs):
            command = [arg for arg in command if arg != "-NoExit"]
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            return actual_popen(command, **kwargs)

        with tempfile.TemporaryDirectory(prefix="bora-terminal-") as folder:
            target = Path(folder) / "인자 기록.json"
            args = ['한글 공백', 'quote"inside', "a'; & echo bad", "줄\n바꿈", "끝\\", ""]
            script = "import json,sys; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]),encoding='utf-8')"
            import os
            with patch("subprocess.Popen", side_effect=isolated_popen):
                integration.launch_terminal([sys.executable, "-c", script, str(target), *args],
                                            Path(folder), dict(os.environ))
            import time
            deadline = time.monotonic() + 10
            while not target.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), args)


if __name__ == "__main__":
    unittest.main()
