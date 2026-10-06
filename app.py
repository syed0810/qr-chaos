import io
import json
import os
import random
import secrets
import sqlite3
import time
from pathlib import Path

import qrcode
from flask import Flask, jsonify, redirect, render_template, request, send_file, session
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

DB = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).parent / "game.db")))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "change-me-1234")
PORT = int(os.environ.get("PORT", "5000"))

ROUNDS = [
    {"id": 1, "name": "REACTION", "kind": "reaction", "duration": 12},
    {"id": 2, "name": "MEMORY", "kind": "memory", "duration": 15},
    {"id": 3, "name": "SPOT IT", "kind": "spot", "duration": 20},
    {"id": 4, "name": "FASTEST FINGER", "kind": "sequence", "duration": 20},
    {"id": 5, "name": "CHAOS", "kind": "chaos", "duration": 15},
    {"id": 6, "name": "FINAL CLIMB", "kind": "final", "duration": 30},
]


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = con()
    c.execute("""CREATE TABLE IF NOT EXISTS players(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        score INTEGER DEFAULT 0,
        joined REAL,
        last_seen REAL,
        connected INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS game(
        id INTEGER PRIMARY KEY CHECK(id=1),
        status TEXT DEFAULT 'lobby',
        round_no INTEGER DEFAULT 0,
        started REAL DEFAULT 0,
        round_started REAL DEFAULT 0
    )""")
    c.execute("INSERT OR IGNORE INTO game(id) VALUES(1)")
    c.commit()
    c.close()


def is_admin():
    return session.get("admin") is True


def require_admin():
    if not is_admin():
        return jsonify(ok=False, error="Admin login required."), 403
    return None


def public_join_url():
    # On Render this becomes https://your-app.onrender.com/ . Locally it is localhost.
    return request.url_root.rstrip("/") + "/"


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/admin/<key>")
def admin(key):
    if not secrets.compare_digest(str(key), str(ADMIN_KEY)):
        return "Not found", 404
    session["admin"] = True
    return render_template("admin.html", join_url=public_join_url())


@app.route("/admin")
def admin_redirect():
    return redirect("/")


@app.route("/join-qr.png")
def join_qr():
    img = qrcode.make(public_join_url())
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=0)


@app.route("/join", methods=["POST"])
def join():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:24]
    if not name:
        return jsonify(ok=False, error="Enter your name.")

    now = time.time()
    c = con()
    c.execute(
        "INSERT INTO players(name, joined, last_seen, connected) VALUES(?,?,?,1)",
        (name, now, now),
    )
    pid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    c.commit()
    c.close()
    session["pid"] = pid
    return jsonify(ok=True)


@app.route("/player")
def player():
    if not session.get("pid"):
        return redirect("/")
    return render_template("player.html")


@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    pid = session.get("pid")
    if pid:
        c = con()
        c.execute("UPDATE players SET last_seen=?, connected=1 WHERE id=?", (time.time(), pid))
        c.commit()
        c.close()
    return jsonify(ok=True)


@app.route("/state")
def state():
    c = con()
    g = c.execute("SELECT * FROM game WHERE id=1").fetchone()
    p = None
    if session.get("pid"):
        p = c.execute("SELECT * FROM players WHERE id=?", (session["pid"],)).fetchone()
    c.close()
    return jsonify(game=dict(g), player=dict(p) if p else None, rounds=ROUNDS)


@app.route("/leaderboard")
def leaderboard():
    c = con()
    rows = c.execute("SELECT id,name,score,connected FROM players ORDER BY score DESC, id").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.route("/players")
def players():
    c = con()
    rows = c.execute("SELECT id,name,score,connected,last_seen FROM players ORDER BY joined").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.post("/admin/start")
def start():
    if (e := require_admin()): return e
    c = con()
    c.execute("UPDATE game SET status='live',round_no=1,started=?,round_started=? WHERE id=1", (time.time(), time.time()))
    c.commit(); c.close()
    return jsonify(ok=True)


@app.post("/admin/pause")
def pause():
    if (e := require_admin()): return e
    c = con(); c.execute("UPDATE game SET status='paused' WHERE id=1"); c.commit(); c.close()
    return jsonify(ok=True)


@app.post("/admin/resume")
def resume():
    if (e := require_admin()): return e
    c = con(); c.execute("UPDATE game SET status='live',round_started=? WHERE id=1", (time.time(),)); c.commit(); c.close()
    return jsonify(ok=True)


@app.post("/admin/next")
def next_round():
    if (e := require_admin()): return e
    c = con()
    g = c.execute("SELECT round_no FROM game WHERE id=1").fetchone()
    n = g["round_no"] + 1
    if n > len(ROUNDS):
        c.execute("UPDATE game SET status='finished',round_no=? WHERE id=1", (n,))
    else:
        c.execute("UPDATE game SET status='live',round_no=?,round_started=? WHERE id=1", (n, time.time()))
    c.commit(); c.close()
    return jsonify(ok=True)


@app.post("/admin/reset")
def reset():
    if (e := require_admin()): return e
    c = con(); c.execute("DELETE FROM players"); c.execute("UPDATE game SET status='lobby',round_no=0,started=0,round_started=0 WHERE id=1"); c.commit(); c.close()
    return jsonify(ok=True)


@app.post("/score")
def score():
    pid = session.get("pid")
    if not pid:
        return jsonify(ok=False, error="Not joined."), 403
    data = request.get_json(silent=True) or {}
    try:
        points = int(data.get("points", 0))
    except Exception:
        points = 0
    points = max(-500, min(1500, points))
    c = con()
    c.execute("UPDATE players SET score=score+? WHERE id=?", (points, pid))
    c.commit()
    row = c.execute("SELECT score FROM players WHERE id=?", (pid,)).fetchone()
    c.close()
    return jsonify(ok=True, score=row["score"], points=points)


@app.route("/challenge")
def challenge():
    # Same challenge for everyone during the same 30-second window.
    seed = int(time.time() // 30)
    rng = random.Random(seed)
    nums = rng.sample(range(1, 10), 5)
    target = rng.choice(["red", "blue", "green", "yellow"])
    word = rng.choice(["CHAOS", "PIXEL", "ROCKET", "BANANA", "TIGER"])
    seq = rng.sample(range(1, 10), 5)
    return jsonify(nums=nums, target=target, word=word, sequence=seq)


@app.get("/health")
def health():
    return jsonify(ok=True)


init()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
