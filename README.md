# 파이썬 타이핑 땅따먹기 (프로토타입)

## 실행
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
브라우저에서 `http://localhost:8000` 접속. 같은 네트워크의 다른 PC는 `http://<서버PC IP>:8000`.

## 테스트
```bash
pip install -r requirements-dev.txt
pytest
```
