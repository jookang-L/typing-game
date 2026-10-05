"""맵 모양. 세 맵 모두 64칸. 줄마다 가운데 정렬로 그린다."""
from __future__ import annotations

MAP_ROWS = {
    "square": [8, 8, 8, 8, 8, 8, 8, 8],
    "pyramid": [1, 3, 5, 7, 9, 11, 13, 15],
    "circle": [4, 8, 10, 10, 10, 10, 8, 4],
}
MAP_LABELS = {"square": "정사각형 (쉬움)", "pyramid": "피라미드 (보통)", "circle": "원 (어려움)"}
for _name, _rows in MAP_ROWS.items():
    assert sum(_rows) == 64, _name


class Layout:
    def __init__(self, rows: list[int]):
        self.rows = rows
        self.cells: list[tuple[int, int, float]] = []   # (row, col, x)
        self.index: dict[tuple[int, int], int] = {}
        for r, n in enumerate(rows):
            for c in range(n):
                self.index[(r, c)] = len(self.cells)
                self.cells.append((r, c, c - (n - 1) / 2))

    def __len__(self) -> int:
        return len(self.cells)

    def center(self) -> int:
        r = len(self.rows) // 2
        return self.index[(r, self.rows[r] // 2)]

    def move(self, idx: int, dx: int, dy: int) -> int:
        r, c, x = self.cells[idx]
        if dx:
            c2 = c + (1 if dx > 0 else -1)
            return self.index.get((r, c2), idx)
        if dy:
            r2 = r + (1 if dy > 0 else -1)
            if not 0 <= r2 < len(self.rows):
                return idx
            n = self.rows[r2]
            best = min(range(n), key=lambda cc: (abs(cc - (n - 1) / 2 - x), cc))
            return self.index[(r2, best)]
        return idx
