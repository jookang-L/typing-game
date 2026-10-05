import random

import pytest

import game
from game import (COLORS, GameError, RoomManager, SELECT_TIME, QUIZ_TIME, WRONG_COOLDOWN,
                  POINTS_PER_STAR, ITEMS, ITEM_CAP, load_questions)


def mkq(tag="t", diff="square", n=12):
    return [{"id": f"{tag}{diff}{i}", "tag": tag, "difficulty": diff, "command": f"cmd_{tag}_{diff}_{i}()",
             "quiz": {"type": "출력 결과", "question": "q?", "choices": ["a", "b", "c", "d"],
                      "answer": 1, "explanation": "해설"}} for i in range(n)]


QS = mkq("출력", "square") + mkq("출력", "pyramid") + mkq("출력", "circle") + mkq("변수", "square")


def make(mode="solo", map_="square", n=2, duration=300, item_start=None, hide=False, seed=1):
    m = RoomManager(QS)
    room = m.create_room(0, {"mode": mode, "map": map_, "tags": ["출력"], "duration": duration,
                             "item_start": item_start, "hide_last_minute": hide,
                             "max_players": 9 if mode == "solo" else 36})
    room.rng = random.Random(seed)
    ps = [room.join(f"user{i}", "cat", COLORS[i % 9], 0) for i in range(n)]
    return m, room, ps


def started(**kw):
    m, room, ps = make(**kw)
    if room.settings.mode == "team":
        room.assign_teams()
    room.start(0)
    return m, room, ps


def point_at(room, p, idx):
    p.cursor = idx


def capture(room, p, idx, now):
    point_at(room, p, idx)
    cmd = room.select(p.token, now)
    return room.submit(p.token, cmd, now)


def steal(room, p, idx, now, correct=True):
    point_at(room, p, idx)
    cmd = room.select(p.token, now)
    assert room.submit(p.token, cmd, now)["result"] == "quiz"
    # 화면 보기 번호 중 정답 위치
    ans = p.qdata["quiz"]["answer"]
    pos = p.quiz_order.index(ans) + 1
    if not correct:
        pos = next(i for i in range(1, 5) if i != pos and (i - 1) not in p.quiz_hidden)
    return room.answer(p.token, pos, now)


# ---------- 설정/방 ----------
def test_room_code_format():
    m = RoomManager(QS)
    for _ in range(200):
        code = m.create_room(0, {"tags": ["출력"]}).code
        assert len(code) == 6 and not set(code) & set("0O1I")


def test_settings_validation():
    m = RoomManager(QS)
    bad = [{"tags": []}, {"tags": ["변수"], "map": "pyramid"},   # 문제 10개 미만
           {"tags": ["출력"], "duration": 120}, {"tags": ["출력"], "mode": "x"},
           {"tags": ["출력"], "duration": 180, "hide_last_minute": True},
           {"tags": ["출력"], "duration": 180, "item_start": 150},   # 종료 1분 전 초과
           {"tags": ["출력"], "item_start": 60}, {"tags": ["출력"], "max_players": 1},
           {"tags": ["출력"], "mode": "team", "max_players": 40}, {"tags": ["없는태그"]}]
    for raw in bad:
        with pytest.raises(GameError):
            m.validate_settings(raw)
    ok = m.validate_settings({"tags": ["출력"], "duration": 180, "item_start": 120})
    assert ok.item_start == 120
    assert m.item_start_options(180) == [90, 120]
    assert m.validate_settings({"tags": ["출력"], "duration": 240, "hide_last_minute": True}).hide_last_minute


def test_real_bank_integrity():
    qs = load_questions()
    assert len(qs) == 285
    cmds = [q["command"] for q in qs]
    assert len(set(cmds)) == len(cmds)
    assert not set(cmds) & set(ITEMS)
    from collections import Counter
    c = Counter((q["tag"], q["difficulty"]) for q in qs)
    for tag in game.TAGS:
        for d in ("square", "pyramid", "circle"):
            assert c[(tag, d)] == (15 if tag == "컨테이너" else 10), (tag, d)
    for q in qs:
        assert q["command"].isascii() and "\n" not in q["command"]
        assert len(q["quiz"]["choices"]) == 4 and 0 <= q["quiz"]["answer"] < 4
        assert q["quiz"]["type"] in ("출력 결과", "빈칸 채우기", "오류 찾기")


def test_join_rules_and_late_join():
    m, room, ps = make(n=1)
    with pytest.raises(GameError):
        room.join("user0", "cat", COLORS[5], 0)
    with pytest.raises(GameError):
        room.join("other", "cat", COLORS[0], 0)   # 개인전 색 중복
    room.join("two", "cat", COLORS[1], 0)
    room.start(0)
    with pytest.raises(GameError):
        room.join("late", "cat", COLORS[4], 1)


def test_solo_requires_two_players():
    m, room, ps = make(n=1)
    with pytest.raises(GameError):
        room.start(0)


def test_dev_mode_allows_single(monkeypatch):
    monkeypatch.setenv("TYPING_DEV", "1")
    m, room, ps = make(n=1)
    room.start(0)


# ---------- 맵 ----------
@pytest.mark.parametrize("map_", ["square", "pyramid", "circle"])
def test_maps_have_64_cells_and_movement_stays_inside(map_):
    _, room, (a, b) = started(map_=map_)
    assert len(room.cells) == 64
    rng = random.Random(3)
    for _ in range(300):
        room.move(a.token, rng.choice([-1, 0, 1]), rng.choice([-1, 0, 1]), 1)
        assert 0 <= a.cursor < 64


def test_pyramid_vertical_move_follows_center():
    _, room, (a, _) = started(map_="pyramid")
    a.cursor = 0
    room.move(a.token, 0, 1, 1)
    r, c, x = room.layout.cells[a.cursor]
    assert (r, x) == (1, 0.0)


# ---------- 점령 ----------
def test_capture_gives_star_points_and_exact_match():
    _, room, (a, _) = started()
    point_at(room, a, 10)
    cmd = room.select(a.token, 1)
    assert room.submit(a.token, cmd.upper(), 2)["result"] == "wrong"
    assert room.submit(a.token, "  " + cmd + "  ", 2)["result"] == "captured"
    st = room.cells[10].stars
    assert room.standings(2)[0]["score"] == st * POINTS_PER_STAR


def test_lock_blocks_other_player_cancel_unlocks_and_one_at_a_time():
    _, room, (a, b) = started()
    point_at(room, a, 5); point_at(room, b, 5)
    room.select(a.token, 1)
    with pytest.raises(GameError):
        room.select(b.token, 1)
    with pytest.raises(GameError):
        room.select(a.token, 1)
    room.cancel(a.token, 2)
    room.select(b.token, 2)


def test_typing_timeout_unlocks_without_penalty():
    _, room, (a, b) = started()
    point_at(room, a, 5)
    room.select(a.token, 1)
    assert room.tick(1 + SELECT_TIME) == [(a.pid, "typing")]
    assert room.cells[5].locked_by is None
    assert room.submit(a.token, "x", 30)["result"] == "timeout"
    assert a.cooldowns == {}


def test_same_cell_gets_different_question():
    _, room, (a, _) = started()
    point_at(room, a, 7)
    first = room.select(a.token, 1)
    room.cancel(a.token, 2)
    for i in range(30):
        again = room.select(a.token, 3 + i)
        assert again != first
        room.cancel(a.token, 3 + i)
        first = again


def test_question_bag_no_repeat_until_exhausted():
    _, room, (a, _) = started()
    seen = []
    for i in range(12):
        point_at(room, a, i)
        seen.append(room.select(a.token, i))
        room.cancel(a.token, i)
    assert len(set(seen)) == 12   # 풀(12개)을 한 번씩 다 쓰기 전에는 반복 없음


# ---------- 뺏기·퀴즈 ----------
def test_steal_flow_moves_territory_and_sets_revenge():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    stars = room.cells[3].stars * POINTS_PER_STAR
    res = steal(room, b, 3, 2)
    assert res["result"] == "stolen" and res["explanation"] == "해설"
    assert room.cells[3].owner == b.pid
    scores = {s["id"]: s["score"] for s in room.standings(3)}
    assert scores[a.pid] == 0 and scores[b.pid] == stars
    assert room.sides[a.pid].revenge[0] == b.pid
    assert b.quiz_correct == 1 and b.captures == 1


def test_wrong_quiz_cooldown_blocks_same_cell_only():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    assert steal(room, b, 3, 2, correct=False)["result"] == "wrong"
    assert room.cells[3].owner == a.pid and room.cells[3].locked_by is None
    point_at(room, b, 3)
    with pytest.raises(GameError):
        room.select(b.token, 3)
    capture(room, b, 4, 3)               # 다른 칸은 선택 가능
    point_at(room, b, 3)
    room.select(b.token, 2 + WRONG_COOLDOWN + 0.1)   # 쿨타임 뒤 같은 칸 재도전


def test_quiz_timeout_counts_as_wrong():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    point_at(room, b, 3)
    cmd = room.select(b.token, 2)
    room.submit(b.token, cmd, 2)
    room.tick(2 + QUIZ_TIME + 0.1)
    assert b.phase is None and room.cells[3].owner == a.pid
    assert any(n["type"] == "quiz_timeout" and n["to"] == b.pid for n in room.notices)
    assert b.cooldowns[3] > 2


def test_cannot_steal_own_cell_and_lock_held_during_quiz():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    point_at(room, a, 3)
    with pytest.raises(GameError):
        room.select(a.token, 2)
    point_at(room, b, 3)
    cmd = room.select(b.token, 2)
    room.submit(b.token, cmd, 2)
    assert b.phase == "quiz" and room.cells[3].locked_by == b.pid


def test_quiz_choices_hidden_answer_and_shuffled():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    point_at(room, b, 3)
    room.select(b.token, 2)
    room.submit(b.token, b.command, 2)
    me = room.me_state(b, 2)
    assert "answer" not in str(me) and len(me["quiz"]["choices"]) == 4


def test_cannot_cancel_during_quiz():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    point_at(room, b, 3)
    room.select(b.token, 2)
    room.submit(b.token, b.command, 2)
    room.cancel(b.token, 3)
    assert b.phase == "quiz"


# ---------- 팀전 ----------
def test_team_assignment_balanced_and_start_rules():
    for n in (4, 5, 7, 9, 13, 36):
        m, room, ps = make("team", n=n)
        room.assign_teams()
        sizes = {}
        for p in room.players.values():
            sizes[p.team] = sizes.get(p.team, 0) + 1
        import math
        assert len(sizes) == min(9, math.ceil(n / 4))
        assert max(sizes.values()) - min(sizes.values()) <= 1
        assert max(sizes.values()) <= 4
        if len(sizes) >= 2 and min(sizes.values()) >= 2:
            room.start(0)
        else:
            with pytest.raises(GameError):
                room.start(0)


def test_team_move_limits():
    m, room, ps = make("team", n=6)
    for i in range(4):
        room.set_team(ps[i].pid, 0)
    with pytest.raises(GameError):
        room.set_team(ps[4].pid, 0)   # 팀당 최대 4명


def test_team_shared_land_and_no_steal_from_teammate():
    m, room, ps = make("team", n=4)
    for i, p in enumerate(ps):
        room.set_team(p.pid, i // 2)
    room.start(0)
    a, a2, b, b2 = ps
    capture(room, a, 3, 1)
    assert room.cells[3].owner == "t1"
    point_at(room, a2, 3)
    with pytest.raises(GameError):
        room.select(a2.token, 2)
    steal(room, b, 3, 2)
    assert room.cells[3].owner == "t2"


def test_team_ranking_by_average():
    m, room, ps = make("team", n=6)
    for i, p in enumerate(ps):
        room.set_team(p.pid, 0 if i < 4 else 1)   # 4명 vs 2명
    room.start(0)
    for c in room.cells:
        c.stars = 1
    for i in range(4):
        room.cells[i].owner = "t1"      # 40점 / 4명 = 10
    for i in range(4, 7):
        room.cells[i].owner = "t2"      # 30점 / 2명 = 15
    s = room.standings(1)
    assert [x["id"] for x in s] == ["t2", "t1"] and s[0]["avg"] == 15 and s[1]["avg"] == 10


def test_team_contribution_tracking():
    m, room, ps = make("team", n=4)
    for i, p in enumerate(ps):
        room.set_team(p.pid, i // 2)
    room.start(0)
    capture(room, ps[0], 3, 1)
    mem = {m["pid"]: m for s in room.standings(2) for m in s["members"]}
    assert mem[ps[0].pid]["captures"] == 1 and mem[ps[1].pid]["captures"] == 0
    assert mem[ps[0].pid]["score"] == room.cells[3].stars * POINTS_PER_STAR


# ---------- 점수 ----------
def test_tiebreak_cells_then_earlier_time():
    _, room, (a, b) = started()
    for c in room.cells:
        c.stars = 1
    room.cells[0].owner = a.pid
    room.cells[1].owner = b.pid
    room.sides[a.pid].last_score_time, room.sides[b.pid].last_score_time = 10, 5
    s = room.standings(1)
    assert [r["id"] for r in s] == [b.pid, a.pid]
    room.sides[a.pid].last_score_time = room.sides[b.pid].last_score_time = 5
    assert [r["rank"] for r in room.standings(1)] == [1, 1]
    room.cells[2].owner = a.pid
    assert room.standings(1)[0]["id"] == a.pid


def test_bonus_not_lost_when_land_stolen():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    a.items = ["bonus()"]
    room.use_item(a.token, "bonus()", 2)
    steal(room, b, 3, 3)
    s = {r["id"]: r for r in room.standings(4)}
    assert s[a.pid]["score"] == 30 and s[a.pid]["territory"] == 0


# ---------- 시간 ----------
def test_game_end_invalidates_in_progress_and_blocks_actions():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    point_at(room, b, 3)
    cmd = room.select(b.token, 2)
    room.submit(b.token, cmd, 2)           # 퀴즈 중
    room.tick(301)
    assert room.state == "ended" and room.cells[3].owner == a.pid and room.cells[3].locked_by is None
    with pytest.raises(GameError):
        room.answer(b.token, 1, 302)
    with pytest.raises(GameError):
        room.move(a.token, 1, 0, 302)


def test_force_end():
    _, room, _ = started()
    room.force_end(10)
    assert room.state == "ended"


def test_disconnect_keeps_score_releases_lock_rejoin():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    point_at(room, a, 4)
    room.select(a.token, 2)
    room.disconnect(a.token, 3)
    assert room.cells[4].locked_by is None and room.cells[3].owner == a.pid
    room.reconnect(a.token, "s", 4)
    assert a.connected


# ---------- 아이템 ----------
def test_item_spawn_schedule_and_rules():
    _, room, (a, b) = started(duration=300, item_start=90)
    room.tick(89)
    assert not any(c.item for c in room.cells)
    room.tick(90)
    assert sum(1 for c in room.cells if c.item) == 2
    assert any(n["type"] == "item_spawn" for n in room.notices)
    room.tick(120)   # 초반 30초 간격
    assert sum(1 for c in room.cells if c.item) == 3
    room.tick(200)
    room.tick(240)
    room.tick(260)
    assert sum(1 for c in room.cells if c.item) == ITEM_CAP   # 상한 4개
    room.tick(280)
    assert sum(1 for c in room.cells if c.item) == ITEM_CAP


def test_items_never_on_owned_locked_or_ever_owned_cells():
    _, room, (a, b) = started(item_start=90, duration=600)
    for i in range(64):
        room.cells[i].owner = a.pid if i < 40 else None
    room.cells[40].locked_by = b.pid
    room.cells[41].ever_owned = True
    for _ in range(50):
        for c in room.cells:
            c.item = None
        room.spawn_item(100)
        idx = [i for i, c in enumerate(room.cells) if c.item]
        assert idx and all(i >= 42 for i in idx)


def test_no_items_when_disabled():
    _, room, _ = started(item_start=None)
    room.tick(250)
    assert not any(c.item for c in room.cells)


def test_item_pickup_only_on_first_capture_and_visible_only_as_marker():
    _, room, (a, b) = started()
    room.cells[3].item = "x2"
    st = room.public_state(0)
    assert st["cells"][3]["item"] is True and "x2" not in str(st)
    res = capture(room, a, 3, 1)
    assert res["item"] == "x2" and a.items == ["x2"]
    steal(room, b, 3, 2)
    assert b.items == []            # 뺏기로는 아이템을 얻지 못한다


def test_inventory_replaces_oldest():
    _, room, (a, b) = started()
    a.items = ["x2", "hint()"]
    room.cells[3].item = "private"
    res = capture(room, a, 3, 1)
    assert a.items == ["hint()", "private"] and res["replaced"] == "x2"


def test_use_item_typo_missing_and_penalty_free():
    _, room, (a, b) = started()
    assert room.use_item(a.token, "bnus()", 1)["result"] == "typo"
    assert room.use_item(a.token, "bonus()", 1)["result"] == "missing"


def test_bonus_and_x2():
    _, room, (a, b) = started()
    a.items = ["bonus()", "x2"]
    assert room.use_item(a.token, "bonus()", 1)["gained"] == 30
    room.use_item(a.token, "x2", 2)
    res = capture(room, a, 3, 3)
    gain = room.cells[3].stars * POINTS_PER_STAR
    assert res["extra"] == gain
    assert room.standings(3)[0]["score"] == 30 + 2 * gain
    res2 = capture(room, a, 4, 2 + 16)   # 15초 지남
    assert res2["extra"] == 0


def test_hint_removes_two_wrong_choices():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    b.items = ["hint()"]
    room.use_item(b.token, "hint()", 2)
    point_at(room, b, 3)
    room.select(b.token, 3)
    room.submit(b.token, b.command, 3)
    off = [c for c in room.me_state(b, 3)["quiz"]["choices"] if c["off"]]
    assert len(off) == 2 and not b.hint_pending
    ans_pos = b.quiz_order.index(1)
    assert ans_pos not in b.quiz_hidden


def test_try_except_protects_last_captured_cell():
    _, room, (a, b) = started()
    capture(room, a, 3, 1)
    a.items = ["try/except"]
    room.use_item(a.token, "try/except", 2)
    point_at(room, b, 3)
    with pytest.raises(GameError):
        room.select(b.token, 3)
    room.select(b.token, 23)   # 20초 뒤 가능
    b.items = []


def test_sleep_blocks_input_for_5s_and_targets_leader():
    _, room, (a, b) = started()
    capture(room, b, 3, 1)        # b가 1위
    a.items = ["sleep(5)"]
    res = room.use_item(a.token, "sleep(5)", 2)
    assert res["target"] == b.nickname and not res["blocked"]
    point_at(room, b, 9)
    with pytest.raises(GameError):
        room.select(b.token, 4)
    room.select(b.token, 7.1)     # 5초 뒤 입력 가능


def test_leader_targets_second_place_and_no_self_target():
    m, room, ps = make(n=3)
    room.start(0)
    a, b, c = ps
    capture(room, a, 1, 1)
    capture(room, b, 2, 1)
    room.cells[1].stars = 3; room.cells[2].stars = 2     # a 1위, b 2위
    a.items = ["blur()"]
    assert room.use_item(a.token, "blur()", 2)["target"] == b.nickname


def test_revenge_target_takes_priority():
    m, room, ps = make(n=3)
    room.start(0)
    a, b, c = ps
    for i in range(5):
        capture(room, b, 10 + i, 1 + i * 0.1)    # b가 1위
    capture(room, a, 3, 2)
    steal(room, c, 3, 3)                          # c가 a의 땅을 뺏음 → a의 복수 대상은 c
    a.items = ["blur()"]
    assert room.use_item(a.token, "blur()", 4)["target"] == c.nickname


def test_private_blocks_attack_consumes_item_notifies_both():
    _, room, (a, b) = started()
    capture(room, b, 3, 1)
    b.items = ["private"]
    room.use_item(b.token, "private", 2)
    a.items = ["sleep(5)"]
    res = room.use_item(a.token, "sleep(5)", 3)
    assert res["blocked"] and a.items == []
    kinds = {(n["type"], n["to"]) for n in room.notices}
    assert ("blocked", a.pid) in kinds and ("defended", b.pid) in kinds
    # private는 퀴즈 뺏기를 막지 않는다
    capture(room, a, 4, 4)
    assert steal(room, b, 4, 5)["result"] == "stolen"


def test_post_hit_immunity_prevents_chain_attacks():
    _, room, (a, b) = started()
    capture(room, b, 3, 1)
    a.items = ["blur()", "sleep(5)"]
    assert not room.use_item(a.token, "blur()", 2)["blocked"]
    r = room.use_item(a.token, "sleep(5)", 3)
    assert r["blocked"] and r["reason"] == "recent"


def test_attack_without_target_does_not_consume():
    m, room, ps = make(n=2)
    room.start(0)
    room.kick(ps[1].pid)
    ps[0].items = ["blur()"]
    with pytest.raises(GameError):
        room.use_item(ps[0].token, "blur()", 1)
    assert ps[0].items == ["blur()"]


def test_team_attack_hits_single_member_of_target_team():
    m, room, ps = make("team", n=4)
    for i, p in enumerate(ps):
        room.set_team(p.pid, i // 2)
    room.start(0)
    capture(room, ps[2], 3, 1)
    ps[0].items = ["blur()"]
    res = room.use_item(ps[0].token, "blur()", 2)
    hit = [p for p in ps if p.blur_until > 2]
    assert len(hit) == 1 and hit[0].team == 1


def test_private_has_cooldown():
    _, room, (a, b) = started()
    a.items = ["private", "private"]
    room.use_item(a.token, "private", 1)
    with pytest.raises(GameError):
        room.use_item(a.token, "private", 5)
    room.use_item(a.token, "private", 100)


# ---------- 마지막 1분 비공개 ----------
def test_hide_last_minute_hides_others_not_self():
    _, room, (a, b) = started(duration=300, hide=True)
    capture(room, a, 3, 10)
    capture(room, b, 4, 11)
    visible = room.public_state(100, a.token)
    assert all(s["score"] is not None for s in visible["sides"]) and not visible["scoresHidden"]
    hidden = room.public_state(250, a.token)
    mine = next(s for s in hidden["sides"] if s["id"] == a.pid)
    other = next(s for s in hidden["sides"] if s["id"] == b.pid)
    assert hidden["scoresHidden"] and mine["score"] is not None and mine["rank"] is not None
    assert other["score"] is None and other["rank"] is None
    # 내부 판정은 계속됨
    assert room.standings(250)[0]["score"] is not None


def test_public_state_leaks_no_secrets():
    _, room, (a, b) = started()
    cmd = room.select(a.token, 1)
    blob = str(room.public_state(1, a.token))
    assert cmd not in blob and a.token not in blob and room.host_token not in blob
    assert "answer" not in blob and "explanation" not in blob


# ---------- 방 관리 ----------
def test_wrong_code_rate_limit():
    m = RoomManager(QS)
    for _ in range(5):
        with pytest.raises(GameError):
            m.find("ZZZZZZ", "c1", 0)
    with pytest.raises(GameError) as e:
        m.find("ZZZZZZ", "c1", 1)
    assert "잠시" in str(e.value)
    with pytest.raises(GameError) as e2:
        m.find("ZZZZZZ", "c1", 31)
    assert "찾을 수" in str(e2.value)


def test_cleanup_old_ended_room():
    m, room, _ = started()
    room.tick(301)
    assert m.cleanup(400) == []
    assert m.cleanup(301 + 31 * 60) == [room.code]
