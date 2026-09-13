# 실측 기록 4 — Flatpak 샌드박스에서 동명 자막 자동 로드 (2026-09-13)

기획서 [`../spec/plan-v0.1.0.md`](../spec/plan-v0.1.0.md) **§8-2** 검증.
§7 이 "Flatpak 샌드박스에서 동명 자막 자동 로드가 막힘"으로 적어 둔 위험을 실제로 확인한다.

환경: lab · Ubuntu 26.04 · Flatpak **1.16.6** · Celluloid **0.30**(Flathub) · GNOME Platform 50
테스트 세트: `~/bora-test/{movie.mp4, movie.smi}` 와 `/data/bora-test/{movie.mp4, movie.smi}`
(자막은 CP949 SAMI 587 B — research 2 의 `sample_cp949.smi`)

## 0. 결론 요약

**포털만으로는 동명 자막 자동 로드가 구조적으로 불가능하다.** 파일 선택 포털은 **고른 파일 하나만**
`/run/user/<uid>/doc/<id>/` 에 노출하고, 그 디렉터리에는 그 파일밖에 없다. 옆의 `.smi` 는 존재 자체가 보이지 않는다.

| 방식 | 동명 자막 자동 로드 | 비고 |
|---|---|---|
| 포털 전달, 추가 권한 없음 (= **Celluloid 의 현재 상태**) | ❌ **불가능** | doc 디렉터리에 영상 하나뿐 |
| `--filesystem=home` | ✅ 된다 | **홈 밖(`/data` 등)은 파일을 아예 못 연다** |
| `--filesystem=host:ro` | ✅ 된다 | `/data` 포함 전부. 권한이 넓다 |
| 영상 + 자막을 **함께** 선택 | ◐ `sub-auto` 로는 실패 | 둘이 **서로 다른** doc 디렉터리에 들어간다. 앱이 인자를 보고 `sub-add` 하면 된다 |

→ **Flatpak(B안)을 택하면 `--filesystem=host:ro` 가 사실상 필수다.** "자막이 그냥 나온다"(기획서 §3-2)를
포기하지 않으려면 다른 길이 없다. 이 사실은 **8-1 결정에서 A안 쪽에 유리하게 작용한다.**

## 1. Celluloid 가 실제로 선언한 권한

```
$ flatpak info --show-permissions io.github.celluloid_player.Celluloid
[Context]
shared=network;ipc;
sockets=wayland;pulseaudio;fallback-x11;
devices=all;
filesystems=xdg-run/pipewire-0:ro;xdg-pictures;xdg-run/gvfsd;xdg-run/gvfs;
```

**`home` 도 `host` 도 없다.** 홈에서 보이는 것은 `Pictures` 하나뿐이다:

```
$ flatpak run --command=sh io.github.celluloid_player.Celluloid -c 'ls ~; ls ~/bora-test'
Pictures
ls: '/home/ubuntu/bora-test'에 접근할 수 없음: 그런 파일이나 디렉터리가 없습니다
```

→ **Celluloid 사용자는 `/data` 같은 별도 디스크의 영상을 직접 경로로 열 수 없고**(포털로만 가능),
포털로 열면 **자막이 붙지 않는다.** 기획서 §1 이 말한 "Celluloid 는 자막 문제를 사용자가 스스로
해결해야 한다"의 구체적 증거다.

## 2. 포털이 노출하는 것은 파일 하나뿐

```
$ flatpak run --file-forwarding --command=sh io.github.celluloid_player.Celluloid -c '
    f="${1:-$0}"; echo "$f"; ls -la "$(dirname "$f")"' @@ /home/ubuntu/bora-test/movie.mp4 @@

/run/user/1000/doc/63df4d90/movie.mp4
drwx------ 2 ubuntu ubuntu        0  .
dr-x------ 2 ubuntu ubuntu        0  ..
-rw-rw-r-- 1 ubuntu ubuntu 19410904  movie.mp4        ← 영상 하나뿐. movie.smi 는 없다
```

mpv 를 그 상태로 돌리면 자막 탐색은 **수행되지만 아무것도 찾지 못한다**:

```
$ flatpak run --file-forwarding --command=mpv io.github.celluloid_player.Celluloid \
    --vo=null --ao=null --length=0.2 --sub-auto=fuzzy -v @@ .../movie.mp4 @@
[find_files] Loading external files in /run/user/1000/doc/63df4d90/
(끝. 'Opening ... .smi' 가 없다)
```

비교 — 샌드박스 밖 네이티브 mpv 는 정상이다:
```
자막 트랙: [(1, True, '/home/ubuntu/bora-test/movie.smi')]
```

## 3. 권한을 주면 바로 해결된다

```
$ flatpak run --filesystem=home --command=mpv ... /home/ubuntu/bora-test/movie.mp4
[file] Opening /home/ubuntu/bora-test/movie.smi        ✅
[lavf] Using subtitle charset: UHC

$ flatpak run --filesystem=home --command=mpv ... /data/bora-test/movie.mp4
[file] Cannot open file '/data/bora-test/movie.mp4': No such file or directory    ❌ 홈 밖

$ flatpak run --filesystem=host:ro --command=mpv ... /data/bora-test/movie.mp4
[file] Opening /data/bora-test/movie.smi               ✅
[lavf] Using subtitle charset: UHC
```

**`home` 으로는 부족하다.** 국내 사용자가 영상을 두는 곳은 홈만이 아니다(이 머신도 `/data` 가 미디어 디스크다).

## 4. 곁가지로 확인한 것

- **영상과 자막을 함께 전달하면 서로 다른 doc 디렉터리에 들어간다.**
  ```
  인자1: /run/user/1000/doc/63df4d90/movie.mp4
  인자2: /run/user/1000/doc/91c4cadb/movie.smi
  ```
  → `sub-auto` 는 못 찾지만 **앱이 두 번째 인자를 자막으로 인식해 `sub-add` 하면 된다.**
  "영상과 자막을 함께 선택" UX 는 성립한다(자동은 아니다).
- **포털 디렉터리에는 새 파일을 쓸 수 있고, 그 파일은 다음 실행에도 남는다.**
  단 **호스트 원본 폴더에는 반영되지 않는다**(원본 `movie.smi` 587 B 그대로 확인).
  전처리 결과를 둘 자리로 쓸 수는 있으나, `sub-add` 로 아무 경로나 줄 수 있어 실익은 크지 않다.
  ⚠ 그 파일이 다음 세션의 `sub-auto` 에 잡힌다 — **실험 중 이것 때문에 한 번 오염됐다.** 재현할 때 주의.

## 5. 설계에 주는 결론

1. **B안(Flatpak)이면 매니페스트에 `--filesystem=host:ro` 를 넣는다.** 읽기 전용으로 충분하다 —
   전처리 결과는 원본 폴더가 아니라 앱 캐시(`~/.var/app/<id>/cache`)에 쓰고 `sub-add` 로 주입하면 된다.
   Flathub 심사에서 넓은 권한은 지적 대상이 될 수 있으니 근거(동명 자막 자동 로드)를 매니페스트 주석에 남긴다.
2. **A안(시스템 패키지)에는 이 문제가 없다.** 8-2 의 결과는 **A안에 유리한 재료**다.
3. 어느 쪽이든 **"자막 파일 직접 선택" UI 는 필요하다** — 권한이 없거나 자막 이름이 다를 때의 유일한 길이다.

## 5-1. 덤으로 확인 — Flatpak 안의 하드웨어 디코딩 (§8-1 절반)

같은 Flatpak 런타임에서 실제로 렌더(`--vo=gpu`)하며 1080p H.264 를 재생하면 **호스트와 결과가 같다**:

```
Flatpak:  [vd] Using hardware decoding (vulkan).
          [cplayer] VO: [gpu] 1920x1080 vulkan[nv12]
호스트:    [vd] Using hardware decoding (vulkan).
          [cplayer] VO: [gpu] 1920x1080 vulkan[nv12]
```

→ **Flatpak 런타임이 GPU 가속을 제대로 전달한다. 기획서 §4 가 "대체로 문제 없음"으로 적어 둔 것이 맞았다.**
(⚠ `--vo=null` 로 재면 hwdec 이 안 붙는다 — 인터롭 대상이 없기 때문이다. 하드웨어 디코딩을 측정할 때는
반드시 실제 VO 로 재야 한다. 처음에 `vo=null` 로 재다 빈손이 나왔다.)

## 6. 아직 검증하지 않은 것

- GUI 파일 선택기(실제 포털 대화상자)로 열었을 때의 동작. 이번 측정은 `--file-forwarding` 으로 대신했다.
  포털 API 에는 폴더를 여는 `OpenDirectory` 도 있는데, 파일 선택기에서 그 경로를 쓰는지는 확인하지 못했다.
- `--filesystem=host:ro` 로 Flathub 심사를 통과하는지(선례 조사 필요 — mpv 계열 다른 앱의 매니페스트).
- Flatpak 판에서의 하드웨어 디코딩(§8-1 의 나머지 절반).
