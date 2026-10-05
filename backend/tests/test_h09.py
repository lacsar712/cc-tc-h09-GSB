"""H09：空格子绝不进队、绝不落库；合法读数正常进队；巡检员禁写。

用临时文件 SQLite 驱动整条接口（api 导入即建表、放种子、起认领线程），
每一条拒收都直接核对库里的行数，杜绝"提示报错却偷偷补了行"。
"""
import os
import tempfile
import time

_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db_path}?timeout=30")

import pytest

from api import app
from models import ConvergenceLog, SessionLocal


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _token(client, username, password):
    res = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert res.status_code == 200, res.data
    return res.get_json()["access_token"]


@pytest.fixture()
def surveyor_token(client):
    return _token(client, "surveyor", "surv123456")


@pytest.fixture()
def inspector_token(client):
    return _token(client, "inspector", "insp123456")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _row_count():
    db = SessionLocal()
    try:
        return db.query(ConvergenceLog).count()
    finally:
        db.close()


def _post_logs(client, token, payload):
    return client.post("/api/logs", json=payload, headers=_auth(token))


VALID_BODY = {"chainage": "K20+050", "delta_mm": 1.2, "sidewall_mm": 0.8}


def test_blank_chainage_never_enters_queue_twice(client, surveyor_token):
    """空桩号连点两次：两次 400，库行数一次都不许涨，也没有未命名断面。"""
    before = _row_count()
    for body in (
        {"chainage": "", "delta_mm": 1.2, "sidewall_mm": 0.8},
        {"chainage": "   ", "delta_mm": 1.2, "sidewall_mm": 0.8},
    ):
        res = _post_logs(client, surveyor_token, body)
        assert res.status_code == 400, res.data
        assert "桩号" in res.get_json()["detail"]

    assert _row_count() == before

    db = SessionLocal()
    try:
        assert (
            db.query(ConvergenceLog)
            .filter(ConvergenceLog.chainage == "未命名断面")
            .count()
            == 0
        )
    finally:
        db.close()


def test_blank_sidewall_never_enters_queue(client, surveyor_token):
    """边墙空格子同样不许进队，库行数不涨。"""
    before = _row_count()
    for sidewall in ("", "   "):
        res = _post_logs(
            client,
            surveyor_token,
            {"chainage": "K20+051", "delta_mm": 1.2, "sidewall_mm": sidewall},
        )
        assert res.status_code == 400, res.data
    assert _row_count() == before


def test_blank_delta_never_enters_queue(client, surveyor_token):
    before = _row_count()
    res = _post_logs(
        client,
        surveyor_token,
        {"chainage": "K20+051", "delta_mm": "  ", "sidewall_mm": 0.8},
    )
    assert res.status_code == 400
    assert _row_count() == before


def test_inspector_cannot_write_and_no_row(client, inspector_token):
    """巡检员禁写：403，且库行数不涨。"""
    before = _row_count()
    res = _post_logs(client, inspector_token, dict(VALID_BODY))
    assert res.status_code == 403, res.data
    assert _row_count() == before


def test_valid_reading_enters_queue_and_gets_claimed(client, surveyor_token):
    """合法桩号 + 收敛毫米 + 边墙毫米：201 进队，随后被认领判合格，只涨一行。"""
    before = _row_count()
    res = _post_logs(client, surveyor_token, dict(VALID_BODY))
    assert res.status_code == 201, res.data
    created = res.get_json()
    assert created["chainage"] == "K20+050"
    assert created["sidewall_mm"] == 0.8
    assert created["status"] == "pending"
    assert _row_count() == before + 1

    # 等后台认领线程判完（进程内 claimer，约每秒一轮）。
    deadline = time.time() + 10
    final = None
    while time.time() < deadline:
        listing = client.get("/api/logs", headers=_auth(surveyor_token)).get_json()
        final = next(r for r in listing if r["id"] == created["id"])
        if final["status"] == "done":
            break
        time.sleep(0.2)
    assert final is not None and final["status"] == "done", final
    assert final["verdict"] == "合格"
    assert _row_count() == before + 1
