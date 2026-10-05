# 파이썬 타이핑 땅따먹기

## 실행
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
브라우저에서 `http://localhost:8000` 접속. 같은 네트워크의 다른 PC는 `http://<서버PC IP>:8000`.

- 교사: **방 만들기** 탭에서 설정 후 방 열기 → 방 코드를 학생에게 알려 주고 로비에서 시작
- 학생: **학생 입장** 탭에서 방 코드 입력
- 혼자 테스트: `TYPING_DEV=1 uvicorn main:app` (Windows cmd: `set TYPING_DEV=1` 후 실행) → 최소 인원 제한 해제

## 조작
방향키 이동 · Enter 칸 선택 · Esc 취소 · 퀴즈는 숫자 1~4 · 이동 중 글자를 치면 아이템 이름 입력(Enter로 사용)

## 구조
- `main.py` 서버(FastAPI + Socket.IO), `game.py` 판정 로직, `maps.py` 맵, `results.py` 결과 내보내기
- `data/questions.json` 문제 은행(285세트, 공개되지 않음) — `tools/` 로 생성·검증: `python tools/build_questions.py`
- `static/` 화면(HTML/CSS/JS, Socket.IO·Lucide 포함)

## 테스트
```bash
pip install -r requirements-dev.txt
pytest
```
