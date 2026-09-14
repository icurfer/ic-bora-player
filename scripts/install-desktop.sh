#!/usr/bin/env bash
#
# Bora 를 앱 목록에 등록한다(사용자 영역, sudo 불필요).
#
# 배포용 패키징(deb/Flatpak)은 아직 미정이라(deferred §1), 개발 중 편의로 쓰는 설치기다.
# 저장소를 지우거나 옮기면 실행이 깨지므로 그때는 다시 실행해야 한다.
#
#   bash scripts/install-desktop.sh          설치
#   bash scripts/install-desktop.sh --remove 제거
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
ROOT="$(pwd)"

APP_ID="com.icurfer.Bora"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin"

if [ "${1:-}" = "--remove" ]; then
  rm -f "$APPS/$APP_ID.desktop" "$ICONS/$APP_ID.svg" "$BIN/bora"
  update-desktop-database "$APPS" 2>/dev/null || true
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
  echo "제거했다."
  exit 0
fi

mkdir -p "$APPS" "$ICONS" "$BIN"

# 실행기 — 저장소 위치를 박아 둔다(PYTHONPATH 를 매번 치지 않아도 되게)
cat > "$BIN/bora" <<EOF
#!/usr/bin/env bash
exec env PYTHONPATH="$ROOT/src" python3 -m bora "\$@"
EOF
chmod +x "$BIN/bora"

install -m 644 "$ROOT/data/icons/$APP_ID.svg" "$ICONS/$APP_ID.svg"
sed "s|^Exec=.*||" "$ROOT/data/$APP_ID.desktop" > "$APPS/$APP_ID.desktop"
# Exec 은 설치 시점의 실제 경로로 박는다
printf 'Exec=%s %%U\n' "$BIN/bora" >> "$APPS/$APP_ID.desktop"
chmod 644 "$APPS/$APP_ID.desktop"

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "등록했다:"
echo "  앱 목록 : $APPS/$APP_ID.desktop"
echo "  아이콘  : $ICONS/$APP_ID.svg"
echo "  실행기  : $BIN/bora   (PATH 에 있으면 'bora <파일>' 로 실행된다)"
echo
echo "⚠ 데스크톱이 이 앱을 영상 기본 프로그램으로 잡아갈 수 있다"
echo "   (MimeType 이 등록되고 기존 기본값이 비어 있으면 그렇게 된다 — 실제로 겪었다)."
echo "   확인·변경은 Bora 안에서: 헤더바 ☰ → '기본 영상 플레이어' 스위치"
echo "   현재 값: $(xdg-mime query default video/mp4 2>/dev/null || echo '(알 수 없음)')"
