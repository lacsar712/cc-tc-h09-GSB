import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, request
from jose import JWTError, jwt
from passlib.context import CryptContext

from claimer import start as start_claimer
from models import Base, ConvergenceLog, SessionLocal, engine, ensure_columns, row_dict

SECRET = os.environ.get("JWT_SECRET", "tunnelconv-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "surveyor": {"role": "writer", "password_hash": pwd.hash("surv123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

app = Flask(__name__)


def seed():
    Base.metadata.create_all(engine)
    ensure_columns()
    db = SessionLocal()
    try:
        if db.query(ConvergenceLog).count() > 0:
            return
        now = datetime.now(timezone.utc)
        for chainage, delta, expect in (("K12+180", 1.2, "合格"), ("K18+040", 5.6, "超限")):
            from rules import judge

            verdict, reason = judge(delta)
            assert verdict == expect
            db.add(
                ConvergenceLog(
                    chainage=chainage,
                    delta_mm=delta,
                    sidewall_mm=delta,
                    status="done",
                    verdict=verdict,
                    reason=reason,
                    created_by="surveyor",
                    created_at=now,
                    processed_at=now,
                )
            )
        db.commit()
    finally:
        db.close()


seed()
start_claimer()


def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(auth[7:].strip(), SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"detail": "未登录"}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def require_writer(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"detail": "未登录"}), 401
        if user["role"] != "writer":
            return jsonify({"detail": "仅测量员可提交收敛读数"}), 403
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "tunnel-convergence-desk"})


@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        return jsonify({"detail": "用户名或密码错误"}), 401
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return jsonify({"access_token": token, "username": username, "role": user["role"]})


@app.get("/api/logs")
@require_login
def list_logs():
    db = SessionLocal()
    try:
        rows = db.query(ConvergenceLog).order_by(ConvergenceLog.id.desc()).all()
        return jsonify([row_dict(r) for r in rows])
    finally:
        db.close()


def _parse_mm(body: dict, key: str, label: str):
    """读取毫米数值；空串、纯空格、None、布尔、非数字一律拒绝。"""
    raw = body.get(key)
    if isinstance(raw, bool) or raw is None:
        raise ValueError(label)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(label)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(label)
    return value


@app.post("/api/logs")
@require_writer
def create_log():
    body = request.get_json(silent=True) or {}

    # 落库前校验：桩号不填或只打空格一律拒收，绝不补"未命名断面"。
    raw_chainage = body.get("chainage")
    if not isinstance(raw_chainage, str) or not raw_chainage.strip():
        return jsonify({"detail": "桩号不能为空"}), 400
    chainage = raw_chainage.strip()

    try:
        delta_mm = _parse_mm(body, "delta_mm", "收敛值")
        sidewall_mm = _parse_mm(body, "sidewall_mm", "边墙值")
    except ValueError as exc:
        return jsonify({"detail": f"{exc.args[0]}必须是数字"}), 400

    # 全部字段通过校验后才打开会话写库，失败不留任何半截行。
    db = SessionLocal()
    try:
        row = ConvergenceLog(
            chainage=chainage,
            delta_mm=delta_mm,
            sidewall_mm=sidewall_mm,
            status="pending",
            created_by=g.user["username"],
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return jsonify(row_dict(row)), 201
    finally:
        db.close()
