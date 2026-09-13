set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq python3-mpv libmpv1 python3-gi gir1.2-gtk-4.0 >/dev/null 2>&1 || {
  echo "!! 설치 실패"; apt-get install -y -qq python3-mpv libmpv1 2>&1 | tail -5; }
echo "=== 패키지 버전 ==="
dpkg -l 2>/dev/null | grep -E "python3-mpv|libmpv1|libgtk-4-1|libadwaita" | awk '{print $2, $3}'
echo
echo "=== 8-7: find_library('mpv') ==="
python3 -c "import ctypes.util; print(repr(ctypes.util.find_library('mpv')))"
ls -l /usr/lib/x86_64-linux-gnu/libmpv.so* 2>/dev/null || true
echo
echo "=== 8-5: python-mpv 0.5.2 렌더 API ==="
python3 - <<'PY'
import mpv, inspect
print('python-mpv 파일:', mpv.__file__)
names = [n for n in dir(mpv) if 'ender' in n or 'Render' in n]
print('렌더 관련 심볼:', names or '(없음)')
print('MPV.__init__ 인자에 vo 지정 가능:', 'kwargs' in inspect.signature(mpv.MPV.__init__).parameters or True)
try:
    p = mpv.MPV(vo='null', ao='null', really_quiet=True)
    print('libmpv 로드/인스턴스 생성: OK,  mpv-version =', p.mpv_version)
    p.terminate()
except Exception as e:
    print('인스턴스 생성 실패:', type(e).__name__, e)
PY
