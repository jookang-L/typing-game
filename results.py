"""게임 결과 내보내기 (게임 로직과 분리). 1차에는 저장하지 않고 종료 화면에서만 보여 준다.
나중에 SQLite 저장 등을 붙일 때 이 모듈에 함수를 추가하면 된다."""
from __future__ import annotations


def export_results(room, now: float) -> dict:
    s = room.settings
    return {
        "code": room.code,
        "mode": s.mode, "map": s.map, "tags": list(s.tags), "duration": s.duration,
        "standings": room.standings(now),
    }
