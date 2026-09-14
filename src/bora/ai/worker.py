#!/usr/bin/env python3
"""AI 질의 작업자 — `.venv` 의 파이썬으로 **독립 실행**된다.

앱 본체는 시스템 파이썬으로 도는데 anthropic 은 PEP 668 때문에 거기 넣을 수 없다.
그래서 텍스트 추출과 같은 방식으로 별도 프로세스에 맡긴다(`bora` 패키지를 import 하지 않는다).

    echo '<요청 JSON>' | .venv/bin/python src/bora/ai/worker.py

요청:  {"model": "...", "system": [...], "user": "..."}
응답:  stdout 에 JSON 한 줄씩
    {"type": "delta", "text": "..."}
    {"type": "done", "usage": {...}, "cost": 0.0123}
    {"type": "error", "message": "..."}
"""

import json
import sys

# 1M 토큰당 달러. 비용을 보여 주려고 둔다 — 자기 돈이 나가는 것을 알아야 한다.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def emit(**payload) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def estimate_cost(model: str, usage) -> float:
    price_in, price_out = PRICES.get(model, PRICES["claude-opus-5"])
    read = getattr(usage, "input_tokens", 0) or 0
    cached_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cached_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    # 캐시 쓰기는 약 1.25배, 캐시 읽기는 약 0.1배로 친다.
    total_in = read + cached_write * 1.25 + cached_read * 0.1
    return (total_in * price_in + out * price_out) / 1_000_000


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
    except ValueError as exc:
        emit(type="error", message=f"요청을 읽지 못했다: {exc}")
        return 2

    try:
        import anthropic
    except ImportError as exc:
        emit(type="error", message=f"anthropic 을 불러오지 못했다: {exc}")
        return 3

    try:
        client = anthropic.Anthropic()      # 키는 SDK 가 환경에서 찾는다(앱은 저장하지 않는다)
    except Exception as exc:
        emit(type="error", message=f"API 자격 증명을 찾지 못했다: {exc}")
        return 4

    model = request.get("model") or "claude-opus-5"
    try:
        # 스트리밍 — 답이 길 수 있고, 기다리는 동안 뭔가 보여야 한다.
        with client.messages.stream(
            model=model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=request.get("system") or [],
            messages=[{"role": "user", "content": request.get("user") or ""}],
        ) as stream:
            for text in stream.text_stream:
                emit(type="delta", text=text)
            final = stream.get_final_message()
    except Exception as exc:
        name = type(exc).__name__
        emit(type="error", message=f"{name}: {exc}")
        return 5

    usage = getattr(final, "usage", None)
    emit(
        type="done",
        model=getattr(final, "model", model),
        cost=round(estimate_cost(model, usage), 6) if usage else 0.0,
        usage={
            "input": getattr(usage, "input_tokens", 0) if usage else 0,
            "output": getattr(usage, "output_tokens", 0) if usage else 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) if usage else 0,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
