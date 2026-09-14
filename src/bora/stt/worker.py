#!/usr/bin/env python3
"""텍스트 추출 작업자 — `.venv-stt` 의 파이썬으로 **독립 실행**된다.

앱 본체와 다른 환경에서 도므로 `bora` 패키지를 import 하지 않는다. 파일 경로로 직접 실행한다:

    .venv-stt/bin/python src/bora/stt/worker.py <영상> <출력.srt> --model small --lang ko

진행 상황을 stdout 에 **JSON 한 줄씩** 뱉는다. 부모가 그것을 읽어 진행률을 보여 준다.
    {"type": "start", "duration": 3600.0}
    {"type": "progress", "seconds": 120.5}
    {"type": "done", "path": "...", "cues": 842}
    {"type": "error", "message": "..."}
"""

import argparse
import json
import sys


def emit(**payload) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def to_srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("output")
    parser.add_argument("--model", default="small")
    parser.add_argument("--lang", default="")          # 빈 값이면 자동 감지
    parser.add_argument("--compute", default="int8")   # CPU 기본
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        emit(type="error", message=f"faster-whisper 를 불러오지 못했다: {exc}")
        return 2

    try:
        model = WhisperModel(args.model, device="cpu", compute_type=args.compute)
    except Exception as exc:
        emit(type="error", message=f"모델을 준비하지 못했다({args.model}): {exc}")
        return 3

    try:
        segments, info = model.transcribe(
            args.video,
            language=args.lang or None,
            vad_filter=True,            # 침묵 구간을 건너뛰어 빠르고 정확하다
            beam_size=5,
        )
    except Exception as exc:
        emit(type="error", message=f"추출을 시작하지 못했다: {exc}")
        return 4

    emit(type="start", duration=float(getattr(info, "duration", 0.0) or 0.0),
         language=getattr(info, "language", "") or "")

    lines = []
    count = 0
    try:
        for segment in segments:
            text = (segment.text or "").strip()
            if text:
                count += 1
                lines.append("%d\n%s --> %s\n%s\n" % (
                    count, to_srt_time(segment.start), to_srt_time(segment.end), text))
            emit(type="progress", seconds=float(segment.end), cues=count)
    except KeyboardInterrupt:
        emit(type="error", message="취소됨")
        return 130
    except Exception as exc:
        emit(type="error", message=f"추출 중 오류: {exc}")
        return 5

    try:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    except OSError as exc:
        emit(type="error", message=f"저장 실패: {exc}")
        return 6

    emit(type="done", path=args.output, cues=count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
