#!/usr/bin/env bash
#
# .deb 패키지를 만든다. debhelper 없이 dpkg-deb 로 직접 조립한다 —
# 순수 파이썬 + 데이터 파일뿐이라 빌드 단계가 필요 없다(Architecture: all).
#
#   bash scripts/build-deb.sh          -> dist/bora_<버전>_all.deb
#   sudo apt install ./dist/bora_*.deb
#
# ⚠ 선택 기능(AI 질의·텍스트 추출)은 deb 에 넣지 않는다.
#   anthropic·faster-whisper 는 데비안 패키지가 없고, 모델까지 수백 MB 다.
#   설치 후 scripts/install-ai.sh · install-stt.sh 로 각자 넣는다.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

VERSION="$(cat version)"
PKG="bora"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/${PKG}_${VERSION}_all"

mkdir -p "$ROOT/DEBIAN" \
         "$ROOT/usr/lib/python3/dist-packages" \
         "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/scalable/apps" \
         "$ROOT/usr/share/doc/$PKG"

cp -r src/bora "$ROOT/usr/lib/python3/dist-packages/"
find "$ROOT/usr/lib/python3/dist-packages/bora" -name '__pycache__' -type d -exec rm -rf {} +

# 설치본에는 저장소의 `version` 파일이 없다. 버전을 코드에 심어 둔다
# (안 하면 앱이 0.0.0 으로 뜬다 — 실제로 겪었다).
sed -i "s/^_BUILD_VERSION = .*/_BUILD_VERSION = \"$VERSION\"/" \
    "$ROOT/usr/lib/python3/dist-packages/bora/__init__.py"
grep -q "_BUILD_VERSION = \"$VERSION\"" \
    "$ROOT/usr/lib/python3/dist-packages/bora/__init__.py" \
    || { echo "✗ 버전을 심지 못했다" >&2; exit 1; }

install -m 644 data/com.icurfer.Bora.desktop "$ROOT/usr/share/applications/"
sed -i 's|^Exec=.*|Exec=/usr/bin/bora %U|' "$ROOT/usr/share/applications/com.icurfer.Bora.desktop"
grep -q '^Exec=' "$ROOT/usr/share/applications/com.icurfer.Bora.desktop" || \
  echo 'Exec=/usr/bin/bora %U' >> "$ROOT/usr/share/applications/com.icurfer.Bora.desktop"
install -m 644 data/icons/com.icurfer.Bora.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"

cat > "$ROOT/usr/bin/bora" <<'EOF'
#!/usr/bin/env python3
import sys
from bora.__main__ import main
sys.exit(main())
EOF
chmod 755 "$ROOT/usr/bin/bora"

install -m 644 README.md "$ROOT/usr/share/doc/$PKG/"
install -m 644 CHANGELOG.md "$ROOT/usr/share/doc/$PKG/"

INSTALLED_KB="$(du -sk "$ROOT" | cut -f1)"

cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: video
Priority: optional
Architecture: all
Maintainer: icurfer <noreply@icurfer.com>
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-mpv
Recommends: ffmpeg, fonts-noto-cjk
Suggests: python3-venv
Description: 국내 자막을 제대로 다루는 리눅스 미디어 플레이어
 libmpv 를 엔진으로 쓰는 GTK4 플레이어. CP949 인코딩 자동 판정, 한·영 통합 SAMI
 트랙 분리, 자막 편집·저장을 내장한다.
 .
 강의 학습 도구이기도 하다 — 타임스탬프가 붙는 마크다운 메모, 구간 반복(A-B), 핀,
 음성 텍스트 추출, AI 질의를 제공한다.
 .
 텍스트 추출(faster-whisper)과 AI 질의(anthropic)는 선택 기능이며 별도 설치가 필요하다:
 /usr/share/doc/bora/README.md 참고.
EOF

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -q -f /usr/share/icons/hicolor 2>/dev/null || true
fi
EOF
chmod 755 "$ROOT/DEBIAN/postinst"

cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -q -f /usr/share/icons/hicolor 2>/dev/null || true
fi
EOF
chmod 755 "$ROOT/DEBIAN/postrm"

mkdir -p dist
fakeroot dpkg-deb --build "$ROOT" "dist/${PKG}_${VERSION}_all.deb" >/dev/null
echo "만들었다: dist/${PKG}_${VERSION}_all.deb  ($(du -h "dist/${PKG}_${VERSION}_all.deb" | cut -f1))"
echo
dpkg-deb --info "dist/${PKG}_${VERSION}_all.deb" | grep -E "Package|Version|Depends|Installed-Size"
echo
echo "설치:   sudo apt install ./dist/${PKG}_${VERSION}_all.deb"
echo "제거:   sudo apt remove bora"
