import random

import pytest

from game import (CODE_ALPHABET, COLORS, GameError, Room, RoomManager,
                  SELECT_TIME, POINTS_PER_STAR)

QS = [{"id": f"q{i}", "tag": "t", "difficulty": "square", "command": f"cmd{i}()"} for i in range(5)]


def make_room(n=2, duration=300):
    m = RoomManager(QS)
    room = m.create_room(0, duration)
    room.rng = random.Random(1)
    ps = [room.join(f"user{i}", "cat", COLORS[i], 0) for i in range(n)]
    return m, room, ps


def started(n=2):
    m, room, ps = make_room(n)
    room.start(0)
    return m, room, ps


def test_room_code_format():
    m = RoomManager(QS)
    for _ in range(200):
        code = m.create_room(0).code
        assert len(code) == 6 and all(c in CODE_ALPHABET for c in code)
        assert not set(code) & set("0O1I")


def test_join_rules():
    m, room, ps = make_room(1)
    with pytest.raises(GameError):
        room.join("user0", "cat", COLORS[5], 0)   # 중복 닉네임
    with pytest.raises(GameError):
        room.join("other", "cat", COLORS[0], 0)   # 중복 색
    room.start(0)
    with pytest.raises(GameError):
        room.join("late", "cat", COLORS[4], 1)    # 시작 후 입장 불가


def test_map_is_64_cells_with_star_values():
    _, room, _ = started()
    assert len(room.cells) == 64
    assert {c.stars for c in room.cells} <= {1, 2, 3}


def test_cursor_clamped_and_no_move_while_selecting():
    _, room, (a, _) = started()
    for _ in range(20):
        room.move(a.token, -1, -1, 1)
    assert a.cursor == 0
    for _ in range(20):
        room.move(a.token, 1, 1, 1)
    assert a.cursor == 63
    room.move(a.token, -1, 0, 1)
    room.select(a.token, 1)
    pos = a.cursor
    room.move(a.token, -1, 0, 1)
    assert a.cursor == pos


def test_capture_gives_star_points():
    _, room, (a, _) = started()
    cmd = room.select(a.token, 1)
    stars = room.cells[a.cursor].stars
    res = room.submit(a.token, f"  {cmd}  ", 2)   # 앞뒤 공백은 무시
    assert res["result"] == "captured" and res["gained"] == stars * POINTS_PER_STAR
    assert room.cells[a.cursor].owner == a.pid
    assert room.territory(a.pid) == stars * POINTS_PER_STAR


def test_exact_match_case_and_inner_space():
    _, room, (a, _) = started()
    cmd = room.select(a.token, 1)
    assert room.submit(a.token, cmd.upper(), 2)["result"] == "wrong"
    assert room.submit(a.token, cmd.replace("(", " ("), 2)["result"] == "wrong"
    assert room.cells[a.cursor].owner is None
    assert room.submit(a.token, cmd, 3)["result"] == "captured"


def test_lock_blocks_other_player_and_one_cell_at_a_time():
    _, room, (a, b) = started()
    b.cursor = a.cursor
    room.select(a.token, 1)
    with pytest.raises(GameError):
        room.select(b.token, 1)          # 잠긴 칸
    with pytest.raises(GameError):
        room.select(a.token, 1)          # 동시에 한 칸만


def test_cancel_unlocks():
    _, room, (a, b) = started()
    b.cursor = a.cursor
    room.select(a.token, 1)
    room.cancel(a.token, 2)
    assert room.cells[a.cursor].locked_by is None
    room.select(b.token, 2)


def test_select_timeout_unlocks_without_penalty():
    _, room, (a, b) = started()
    b.cursor = a.cursor
    cmd = room.select(a.token, 1)
    expired = room.tick(1 + SELECT_TIME)
    assert expired == [a.pid]
    assert room.cells[a.cursor].locked_by is None
    assert room.submit(a.token, cmd, 1 + SELECT_TIME + 1)["result"] == "timeout"
    assert room.territory(a.pid) == 0
    room.select(b.token, 1 + SELECT_TIME + 1)  # 다른 사람이 잡을 수 있음


def test_no_double_capture_of_owned_cell():
    _, room, (a, b) = started()
    b.cursor = a.cursor
    cmd = room.select(a.token, 1)
    room.submit(a.token, cmd, 2)
    with pytest.raises(GameError):
        room.select(b.token, 3)   # 상대 땅 (뺏기는 1단계)
    with pytest.raises(GameError):
        room.select(a.token, 3)   # 내 땅


def test_same_question_not_repeated_until_bag_empty():
    _, room, (a, _) = started()
    seen = []
    for i in range(5):
        room.cells[a.cursor].owner = None
        seen.append(room.select(a.token, i))
        room.cancel(a.token, i)
    assert sorted(seen) == sorted(q["command"] for q in QS)


def test_game_end_invalidates_in_progress_and_blocks_actions():
    _, room, (a, _) = started()
    cmd = room.select(a.token, 1)
    room.tick(301)
    assert room.state == "ended"
    assert room.cells[a.cursor].locked_by is None
    with pytest.raises(GameError):
        room.submit(a.token, cmd, 302)
    with pytest.raises(GameError):
        room.move(a.token, 1, 0, 302)


def test_submit_after_deadline_is_not_captured():
    _, room, (a, _) = started()
    cmd = room.select(a.token, 1)
    assert room.submit(a.token, cmd, 1 + SELECT_TIME + 0.1)["result"] == "timeout"
    assert room.territory(a.pid) == 0


def test_disconnect_keeps_score_releases_lock_and_rejoin():
    _, room, (a, _) = started()
    cmd = room.select(a.token, 1)
    room.submit(a.token, cmd, 2)
    score = room.territory(a.pid)
    a.cursor = 0
    room.cells[0].owner = None
    room.select(a.token, 3)
    room.disconnect(a.token, 4)
    assert room.cells[0].locked_by is None and room.territory(a.pid) == score
    room.reconnect(a.token, "sid2", 5)
    assert a.connected


def test_standings_tiebreak_cells_then_earlier_time():
    _, room, (a, b) = started()
    for c in room.cells:
        c.stars = 1
    room.cells[0].owner = a.pid
    room.cells[1].owner = b.pid
    a.last_score_time, b.last_score_time = 10, 5
    s = room.standings()
    assert [r["pid"] for r in s] == [b.pid, a.pid] and [r["rank"] for r in s] == [1, 2]
    a.last_score_time = b.last_score_time = 5
    assert [r["rank"] for r in room.standings()] == [1, 1]   # 공동 우승
    room.cells[2].owner = a.pid
    assert room.standings()[0]["pid"] == a.pid


def test_public_state_leaks_no_secrets():
    _, room, (a, _) = started()
    cmd = room.select(a.token, 1)
    blob = str(room.public_state(1))
    assert cmd not in blob and a.token not in blob and room.host_token not in blob
    assert "answer" not in blob


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
