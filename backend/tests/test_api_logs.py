"""落库层验收：空白桩号在写库前被截住，合法桩号正常进队，巡检员禁写。

用隔离的 sqlite 临时库跑 Flask 测试客户端；若环境已指定其他 DATABASE_URL
（例如在正式容器里连 PostgreSQL），为避免碰真实库，整模块跳过。
"""
import os
import tempfile

import pytest

_fd, _db_path = tempfile.mkstemp(suffix=".db", prefix="h09_api_")
os.close(_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db_path}")

import api  # noqa: E402
import claimer  # noqa: E402
from models import ConvergenceLog, SessionLocal, engine  # noqa: E402

if engine.url.get_backend_name() != "sqlite":
    pytest.skip("需要隔离的 sqlite 库才能跑落库测试", allow_module_level=True)

claimer._stop.set()  # 停掉认领线程，让 pending 状态可稳定断言


@pytest.fixture()
def client():
    api.app.config.update(TESTING=True)
    with api.app.test_client() as c:
        yield c


def _login(client, username, password):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    token = res.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _row_count():
    db = SessionLocal()
    try:
        return db.query(ConvergenceLog).count()
    finally:
        db.close()


def _fake_section_count():
    db = SessionLocal()
    try:
        return (
            db.query(ConvergenceLog)
            .filter(ConvergenceLog.chainage == "未命名断面")
            .count()
        )
    finally:
        db.close()


def test_blank_chainage_blocked_before_persist_even_on_double_click(client):
    headers = _login(client, "surveyor", "surv123456")
    before = _row_count()
    for raw in ("", "   ", "　　"):
        # 连点两次空格子
        for _ in range(2):
            res = client.post(
                "/api/logs",
                json={"chainage": raw, "delta_mm": 1.0},
                headers=headers,
            )
            assert res.status_code == 400
            assert res.get_json()["detail"] == "桩号不能为空"
    assert _row_count() == before  # 行数不许悄悄涨
    assert _fake_section_count() == 0  # 不许留下“未命名断面”假行


def test_valid_chainage_enqueues_normally(client):
    headers = _login(client, "surveyor", "surv123456")
    before = _row_count()
    res = client.post(
        "/api/logs",
        json={"chainage": "K20+050", "delta_mm": 2.4},
        headers=headers,
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["chainage"] == "K20+050"
    assert body["status"] == "pending"
    assert _row_count() == before + 1


def test_inspector_cannot_write(client):
    headers = _login(client, "inspector", "insp123456")
    before = _row_count()
    res = client.post(
        "/api/logs",
        json={"chainage": "K20+051", "delta_mm": 1.0},
        headers=headers,
    )
    assert res.status_code == 403
    assert _row_count() == before


def test_anonymous_cannot_write(client):
    before = _row_count()
    res = client.post("/api/logs", json={"chainage": "K20+052", "delta_mm": 1.0})
    assert res.status_code == 401
    assert _row_count() == before
