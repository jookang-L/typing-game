"""문제 은행 작성 도우미. 문제 세트 = 태그 + 난이도 + 명령어 + 객관식 퀴즈.

작성 규칙: 첫 번째 보기는 항상 정답으로 쓰고, 빌더가 고정 시드로 섞는다(서버도 출제 때마다 섞는다).
출력 결과(O)는 실제로 실행해서 정답과 일치하는지 검증하고, 오류 찾기(E)는 정답 코드만 오류가 나는지 검증한다.
"""
from __future__ import annotations

import contextlib
import io
import random
import re

TYPE_O, TYPE_F, TYPE_E = "출력 결과", "빈칸 채우기", "오류 찾기"


def O(cmd, code, correct, wrongs, expl, stdin=None, sub=None):
    note = f" (입력: {stdin.replace(chr(10), ' ⏎ ')})" if stdin else ""
    return dict(cmd=cmd, type=TYPE_O, q=f"다음 코드의 출력 결과는?{note}\n{code}", correct=correct,
                wrongs=wrongs, expl=expl, run=code, stdin=stdin, sub=sub)


def F(cmd, q, correct, wrongs, expl, sub=None):
    return dict(cmd=cmd, type=TYPE_F, q=q, correct=correct, wrongs=wrongs, expl=expl, sub=sub)


def E(cmd, bad, oks, expl, sub=None):
    return dict(cmd=cmd, type=TYPE_E, q="다음 중 실행하면 오류가 나는 코드는?", correct=bad,
                wrongs=oks, expl=expl, bad=bad, oks=oks, sub=sub)


def _norm(s: str) -> str:
    return " ".join(str(s).split())


def _run(code: str, stdin: str | None = None) -> str:
    out = io.StringIO()
    old_input = __builtins__["input"] if isinstance(__builtins__, dict) else __builtins__.input
    lines = iter((stdin or "").split("\n"))
    env = {"input": lambda prompt="": next(lines)}
    with contextlib.redirect_stdout(out):
        exec(compile(code, "<q>", "exec"), env)
    return _norm(out.getvalue())


def _raises(code: str) -> bool:
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(code, "<q>", "exec"), {"input": lambda prompt="": "1"})
    except Exception:
        return True
    return False


def check(item: dict, where: str) -> None:
    c = item
    assert len(c["wrongs"]) == 3, where
    f = (lambda x: x) if c["type"] == TYPE_E else _norm
    texts = [f(c["correct"])] + [f(w) for w in c["wrongs"]]
    assert len(set(texts)) == 4, f"{where}: 보기 중복 {texts}"
    assert "\n" not in c["cmd"] and c["cmd"] == c["cmd"].strip(), where
    assert c["cmd"].isascii(), f"{where}: 명령어에 한글/특수문자 {c['cmd']!r}"
    if c.get("run"):
        got = _run(c["run"], c.get("stdin"))
        assert got == _norm(c["correct"]), f"{where}: 실행 결과 {got!r} != 정답 {c['correct']!r}"
    if c["type"] == TYPE_E:
        assert _raises(c["bad"]), f"{where}: 정답 코드가 오류를 내지 않음 {c['bad']!r}"
        for ok in c["oks"]:
            assert not _raises(ok), f"{where}: 오류 없어야 할 코드가 오류 {ok!r}"


def build(banks: dict[str, dict[str, list[dict]]], per_level: dict[str, int]) -> list[dict]:
    """banks[태그][난이도] = [문제...]. 난이도는 square/pyramid/circle."""
    out, seen = [], set()
    rng = random.Random(20260705)
    for tag, levels in banks.items():
        for diff in ("square", "pyramid", "circle"):
            items = levels.get(diff, [])
            want = per_level.get(tag, 10)
            assert len(items) == want, f"{tag}/{diff}: {len(items)}개 (필요 {want}개)"
            for n, it in enumerate(items, 1):
                where = f"{tag}/{diff}#{n} {it['cmd']}"
                check(it, where)
                assert it["cmd"] not in seen, f"명령어 중복: {it['cmd']}"
                seen.add(it["cmd"])
                choices = [it["correct"]] + list(it["wrongs"])
                order = list(range(4))
                rng.shuffle(order)
                shuffled = [choices[i] for i in order]
                answer = order.index(0)
                q = {"id": f"{tag}-{diff}-{n:02d}", "tag": tag, "difficulty": diff,
                     "command": it["cmd"],
                     "quiz": {"type": it["type"], "question": it["q"], "choices": shuffled,
                              "answer": answer, "explanation": it["expl"]}}
                if it.get("sub"):
                    q["sub"] = it["sub"]
                out.append(q)
    return out
