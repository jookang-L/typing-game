"""검수·수정한 엑셀을 문제 은행(data/questions.json)에 반영한다.
사용: python tools/import_xlsx.py review/문제검수.xlsx
- 타이핑 문제 시트의 명령어와 퀴즈_* 시트의 질문·보기·정답번호·해설을 읽는다.
- 검수 열이 '삭제'인 문제는 제외한다. ID는 기존 문제와 일치해야 한다.
- 반영 전에 형식을 검사한다(보기 4개·중복 없음, 정답번호 1~4, 명령어 한 줄·ASCII, 아이템 이름과 중복 금지)."""
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).parent.parent
ITEMS = {"bonus()", "x2", "sleep(5)", "blur()", "try/except", "private", "hint()"}


def main(path: str) -> None:
    wb = load_workbook(path, data_only=True)
    bank = {q["id"]: q for q in json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))}
    delete, errors = set(), []
    for row in wb["타이핑 문제"].iter_rows(min_row=2, values_only=True):
        qid, _, _, _, cmd, _, review, _ = row[:8]
        if not qid:
            continue
        if qid not in bank:
            errors.append(f"{qid}: 알 수 없는 ID")
            continue
        if review == "삭제":
            delete.add(qid)
        bank[qid]["command"] = str(cmd).strip()
    for ws in wb.worksheets:
        if not ws.title.startswith("퀴즈_"):
            continue
        for row in ws.iter_rows(min_row=2, values_only=True):
            qid, _, _, qtype, _, question, c1, c2, c3, c4, ans, _, expl, review, _ = row[:15]
            if not qid or qid not in bank:
                continue
            if review == "삭제":
                delete.add(qid)
            bank[qid]["quiz"] = {"type": qtype, "question": str(question), "choices": [str(c) for c in (c1, c2, c3, c4)],
                                 "answer": int(ans) - 1, "explanation": str(expl)}
    seen = set()
    for qid, q in bank.items():
        if qid in delete:
            continue
        z, c = q["quiz"], q["command"]
        if len(set(z["choices"])) != 4 or not 0 <= z["answer"] < 4:
            errors.append(f"{qid}: 보기 4개가 서로 달라야 하고 정답번호는 1~4")
        if not c or not c.isascii() or "\n" in c:
            errors.append(f"{qid}: 명령어는 한 줄, 영문/숫자/기호만 ({c!r})")
        if c in ITEMS:
            errors.append(f"{qid}: 아이템 이름과 같은 명령어 ({c})")
        if c in seen:
            errors.append(f"{qid}: 명령어 중복 ({c})")
        seen.add(c)
    if errors:
        print("반영하지 않았습니다. 아래를 고쳐 주세요:\n" + "\n".join(errors))
        sys.exit(1)
    out = [q for qid, q in bank.items() if qid not in delete]
    (ROOT / "data" / "questions.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)}세트 반영 (삭제 {len(delete)}개)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "review" / "문제검수.xlsx"))
