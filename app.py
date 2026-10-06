import io
import json
import os
import random
import secrets
import sqlite3
import time
from pathlib import Path

import qrcode
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
)
from werkzeug.middleware.proxy_fix import ProxyFix


# ============================================================
# APP SETUP
# ============================================================

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1
)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    secrets.token_hex(32)
)


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).parent

DB = Path(
    os.environ.get(
        "DATABASE_PATH",
        str(BASE_DIR / "game.db")
    )
)

ADMIN_KEY = os.environ.get(
    "ADMIN_KEY",
    "change-me-1234"
)

PORT = int(
    os.environ.get(
        "PORT",
        "5000"
    )
)


# ============================================================
# GAME ROUNDS
# ============================================================

ROUNDS = [
    {
        "id": 1,
        "name": "REACTION",
        "kind": "reaction",
        "duration": 12
    },
    {
        "id": 2,
        "name": "MEMORY",
        "kind": "memory",
        "duration": 15
    },
    {
        "id": 3,
        "name": "SPOT IT",
        "kind": "spot",
        "duration": 20
    },
    {
        "id": 4,
        "name": "FASTEST FINGER",
        "kind": "sequence",
        "duration": 20
    },
    {
        "id": 5,
        "name": "CHAOS",
        "kind": "chaos",
        "duration": 15
    },
    {
        "id": 6,
        "name": "FINAL CLIMB",
        "kind": "final",
        "duration": 30
    },
]


# ============================================================
# DATABASE
# ============================================================

def con():
    """
    Open a SQLite database connection.
    """
    c = sqlite3.connect(
        DB,
        timeout=10
    )

    c.row_factory = sqlite3.Row

    return c


def init():
    """
    Create database tables if they don't already exist.
    """

    c = con()

    # Players table
    c.execute("""
        CREATE TABLE IF NOT EXISTS players(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            joined REAL,
            last_seen REAL,
            connected INTEGER DEFAULT 1
        )
    """)

    # Game table
    c.execute("""
        CREATE TABLE IF NOT EXISTS game(
            id INTEGER PRIMARY KEY CHECK(id=1),
            status TEXT DEFAULT 'lobby',
            round_no INTEGER DEFAULT 0,
            started REAL DEFAULT 0,
            round_started REAL DEFAULT 0
        )
    """)

    # Make sure the single game row exists
    c.execute("""
        INSERT OR IGNORE INTO game(
            id,
            status,
            round_no,
            started,
            round_started
        )
        VALUES(
            1,
            'lobby',
            0,
            0,
            0
        )
    """)

    c.commit()
    c.close()


# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

def is_admin():
    """
    Check whether the current browser session is an admin.
    """
    return session.get("admin") is True


def require_admin():
    """
    Protect admin API routes.
    """

    if not is_admin():
        return jsonify(
            ok=False,
            error="Admin login required."
        ), 403

    return None


# ============================================================
# URL / QR
# ============================================================

def public_join_url():
    """
    Generate the public URL players should open.
    """

    return request.url_root.rstrip("/") + "/"


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return render_template("home.html")


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route("/admin/<key>")
def admin(key):

    # Check admin key
    if not secrets.compare_digest(
        str(key),
        str(ADMIN_KEY)
    ):
        return "Not found", 404

    # Save admin authentication in session
    session["admin"] = True

    return render_template(
        "admin.html",
        join_url=public_join_url()
    )


@app.route("/admin")
def admin_redirect():
    return redirect("/")


# ============================================================
# QR CODE
# ============================================================

@app.route("/join-qr.png")
def join_qr():

    img = qrcode.make(
        public_join_url()
    )

    buf = io.BytesIO()

    img.save(
        buf,
        format="PNG"
    )

    buf.seek(0)

    return send_file(
        buf,
        mimetype="image/png",
        max_age=0
    )


# ============================================================
# PLAYER JOIN
# ============================================================

@app.route("/join", methods=["POST"])
def join():

    data = request.get_json(
        silent=True
    ) or {}

    name = (
        data.get("name") or ""
    ).strip()[:24]

    if not name:
        return jsonify(
            ok=False,
            error="Enter your name."
        )

    now = time.time()

    c = con()

    c.execute(
        """
        INSERT INTO players(
            name,
            joined,
            last_seen,
            connected
        )
        VALUES(?,?,?,1)
        """,
        (
            name,
            now,
            now
        )
    )

    pid = c.execute(
        "SELECT last_insert_rowid() AS id"
    ).fetchone()["id"]

    c.commit()
    c.close()

    session["pid"] = pid

    return jsonify(
        ok=True,
        player_id=pid
    )


# ============================================================
# PLAYER PAGE
# ============================================================

@app.route("/player")
def player():

    if not session.get("pid"):
        return redirect("/")

    return render_template(
        "player.html"
    )


# ============================================================
# PLAYER HEARTBEAT
# ============================================================

@app.route("/heartbeat", methods=["POST"])
def heartbeat():

    pid = session.get("pid")

    if pid:

        c = con()

        c.execute(
            """
            UPDATE players
            SET last_seen=?,
                connected=1
            WHERE id=?
            """,
            (
                time.time(),
                pid
            )
        )

        c.commit()
        c.close()

    return jsonify(
        ok=True
    )


# ============================================================
# GAME STATE
# ============================================================

@app.route("/state")
def state():

    c = con()

    game = c.execute(
        """
        SELECT *
        FROM game
        WHERE id=1
        """
    ).fetchone()

    player = None

    pid = session.get("pid")

    if pid:

        player = c.execute(
            """
            SELECT *
            FROM players
            WHERE id=?
            """,
            (pid,)
        ).fetchone()

    c.close()

    return jsonify(
        game=dict(game),
        player=dict(player) if player else None,
        rounds=ROUNDS
    )


# ============================================================
# LEADERBOARD
# ============================================================

@app.route("/leaderboard")
def leaderboard():

    c = con()

    rows = c.execute(
        """
        SELECT
            id,
            name,
            score,
            connected
        FROM players
        ORDER BY score DESC, id
        """
    ).fetchall()

    c.close()

    return jsonify(
        [dict(row) for row in rows]
    )


# ============================================================
# ADMIN - PLAYERS
# ============================================================

@app.route("/players")
def players():

    c = con()

    rows = c.execute(
        """
        SELECT
            id,
            name,
            score,
            connected,
            last_seen
        FROM players
        ORDER BY joined
        """
    ).fetchall()

    c.close()

    return jsonify(
        [dict(row) for row in rows]
    )


# ============================================================
# ADMIN - START GAME
# ============================================================

@app.post("/admin/start")
def start():

    # Check admin session
    error = require_admin()

    if error:
        return error

    now = time.time()

    c = con()

    try:

        c.execute(
            """
            UPDATE game
            SET
                status='live',
                round_no=1,
                started=?,
                round_started=?
            WHERE id=1
            """,
            (
                now,
                now
            )
        )

        c.commit()

        # Verify that the update actually happened
        game = c.execute(
            """
            SELECT *
            FROM game
            WHERE id=1
            """
        ).fetchone()

        return jsonify(
            ok=True,
            game=dict(game)
        )

    except Exception as e:

        c.rollback()

        return jsonify(
            ok=False,
            error=str(e)
        ), 500

    finally:

        c.close()


# ============================================================
# ADMIN - PAUSE
# ============================================================

@app.post("/admin/pause")
def pause():

    error = require_admin()

    if error:
        return error

    c = con()

    try:

        c.execute(
            """
            UPDATE game
            SET status='paused'
            WHERE id=1
            """
        )

        c.commit()

        game = c.execute(
            """
            SELECT *
            FROM game
            WHERE id=1
            """
        ).fetchone()

        return jsonify(
            ok=True,
            game=dict(game)
        )

    except Exception as e:

        c.rollback()

        return jsonify(
            ok=False,
            error=str(e)
        ), 500

    finally:

        c.close()


# ============================================================
# ADMIN - RESUME
# ============================================================

@app.post("/admin/resume")
def resume():

    error = require_admin()

    if error:
        return error

    now = time.time()

    c = con()

    try:

        c.execute(
            """
            UPDATE game
            SET
                status='live',
                round_started=?
            WHERE id=1
            """,
            (now,)
        )

        c.commit()

        game = c.execute(
            """
            SELECT *
            FROM game
            WHERE id=1
            """
        ).fetchone()

        return jsonify(
            ok=True,
            game=dict(game)
        )

    except Exception as e:

        c.rollback()

        return jsonify(
            ok=False,
            error=str(e)
        ), 500

    finally:

        c.close()


# ============================================================
# ADMIN - NEXT ROUND
# ============================================================

@app.post("/admin/next")
def next_round():

    error = require_admin()

    if error:
        return error

    c = con()

    try:

        game = c.execute(
            """
            SELECT round_no
            FROM game
            WHERE id=1
            """
        ).fetchone()

        current_round = game["round_no"]

        next_number = current_round + 1

        if next_number > len(ROUNDS):

            c.execute(
                """
                UPDATE game
                SET
                    status='finished',
                    round_no=?
                WHERE id=1
                """,
                (next_number,)
            )

        else:

            c.execute(
                """
                UPDATE game
                SET
                    status='live',
                    round_no=?,
                    round_started=?
                WHERE id=1
                """,
                (
                    next_number,
                    time.time()
                )
            )

        c.commit()

        updated_game = c.execute(
            """
            SELECT *
            FROM game
            WHERE id=1
            """
        ).fetchone()

        return jsonify(
            ok=True,
            game=dict(updated_game)
        )

    except Exception as e:

        c.rollback()

        return jsonify(
            ok=False,
            error=str(e)
        ), 500

    finally:

        c.close()


# ============================================================
# ADMIN - RESET
# ============================================================

@app.post("/admin/reset")
def reset():

    error = require_admin()

    if error:
        return error

    c = con()

    try:

        c.execute(
            "DELETE FROM players"
        )

        c.execute(
            """
            UPDATE game
            SET
                status='lobby',
                round_no=0,
                started=0,
                round_started=0
            WHERE id=1
            """
        )

        c.commit()

        game = c.execute(
            """
            SELECT *
            FROM game
            WHERE id=1
            """
        ).fetchone()

        return jsonify(
            ok=True,
            game=dict(game)
        )

    except Exception as e:

        c.rollback()

        return jsonify(
            ok=False,
            error=str(e)
        ), 500

    finally:

        c.close()


# ============================================================
# PLAYER SCORE
# ============================================================

@app.post("/score")
def score():

    pid = session.get("pid")

    if not pid:
        return jsonify(
            ok=False,
            error="Not joined."
        ), 403

    data = request.get_json(
        silent=True
    ) or {}

    try:

        points = int(
            data.get(
                "points",
                0
            )
        )

    except Exception:

        points = 0

    # Prevent ridiculous scores
    points = max(
        -500,
        min(
            1500,
            points
        )
    )

    c = con()

    c.execute(
        """
        UPDATE players
        SET score=score+?
        WHERE id=?
        """,
        (
            points,
            pid
        )
    )

    c.commit()

    row = c.execute(
        """
        SELECT score
        FROM players
        WHERE id=?
        """,
        (pid,)
    ).fetchone()

    c.close()

    return jsonify(
        ok=True,
        score=row["score"],
        points=points
    )


# ============================================================
# CHALLENGE GENERATOR
# ============================================================

@app.route("/challenge")
def challenge():

    # Same challenge for everyone
    # during the same 30-second window.

    seed = int(
        time.time() // 30
    )

    rng = random.Random(seed)

    nums = rng.sample(
        range(1, 10),
        5
    )

    target = rng.choice(
        [
            "red",
            "blue",
            "green",
            "yellow"
        ]
    )

    word = rng.choice(
        [
            "CHAOS",
            "PIXEL",
            "ROCKET",
            "BANANA",
            "TIGER"
        ]
    )

    sequence = rng.sample(
        range(1, 10),
        5
    )

    return jsonify(
        nums=nums,
        target=target,
        word=word,
        sequence=sequence
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return jsonify(
        ok=True,
        status="running"
    )


# ============================================================
# STARTUP
# ============================================================

init()


# ============================================================
# LOCAL SERVER
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
init()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
