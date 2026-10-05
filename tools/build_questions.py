"""문제 은행 빌드: python tools/build_questions.py  → data/questions.json
출력 결과 문제는 실제로 실행해 정답을 검증하고, 오류 찾기 문제는 정답 코드만 오류가 나는지 검증한다."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qbuild import build   # noqa: E402
import bank_a, bank_b, bank_c   # noqa: E402,E401

BANKS = {"출력": bank_a.출력, "변수": bank_a.변수, "입력": bank_a.입력,
         "연산자": bank_b.연산자, "자료형": bank_b.자료형, "컨테이너": bank_b.컨테이너,
         "조건문": bank_c.조건문, "반복문": bank_c.반복문, "함수": bank_c.함수}

if __name__ == "__main__":
    qs = build(BANKS, {"컨테이너": 15})
    out = Path(__file__).parent.parent / "data" / "questions.json"
    out.write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(qs)}세트 → {out}")
