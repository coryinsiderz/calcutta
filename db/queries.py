import json
import random
from datetime import datetime, timezone
from psycopg.rows import dict_row

from db.connection import get_conn

_ALLOWED_STATE_COLS = {
    "status", "current_team_id", "high_bid", "high_bidder_user_id",
    "high_bidder_username", "bid_message_id", "silence_phase",
    "last_bid_at", "chat_id", "updated_at",
}


# ── Config ──────────────────────────────────────────────────────────────────

def get_auction_config() -> dict:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM auction_config WHERE id = 1")
            return cur.fetchone()


def update_auction_config(updates: dict):
    if not updates:
        return
    cols = list(updates.keys())
    vals = list(updates.values()) + [1]
    sql = f"UPDATE auction_config SET {', '.join(f'{c} = %s' for c in cols)} WHERE id = %s"
    with get_conn() as conn:
        conn.execute(sql, vals)


def get_increment_bands() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM increment_bands ORDER BY min_price")
            return cur.fetchall()


def replace_increment_bands(bands: list[dict]):
    with get_conn() as conn:
        conn.execute("DELETE FROM increment_bands")
        if bands:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO increment_bands (min_price, increment) VALUES (%s, %s)",
                    [(b["min_price"], b["increment"]) for b in bands],
                )


# ── Auction state ────────────────────────────────────────────────────────────

def get_auction_state() -> dict | None:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM auction_state WHERE id = 1")
            return cur.fetchone()


def update_auction_state(**kwargs):
    invalid = set(kwargs) - _ALLOWED_STATE_COLS
    if invalid:
        raise ValueError(f"Invalid auction_state columns: {invalid}")
    kwargs["updated_at"] = datetime.now(timezone.utc)
    cols = list(kwargs.keys())
    vals = list(kwargs.values())
    sql = f"UPDATE auction_state SET {', '.join(f'{c} = %s' for c in cols)} WHERE id = 1"
    with get_conn() as conn:
        conn.execute(sql, vals)


def set_auction_running(chat_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE auction_state SET status = 'running', chat_id = %s, updated_at = now() WHERE id = 1",
            (chat_id,),
        )


def set_auction_status(status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE auction_state SET status = %s, updated_at = now() WHERE id = 1",
            (status,),
        )


def reset_auction_state_for_team(team_id: int):
    with get_conn() as conn:
        conn.execute(
            """UPDATE auction_state SET
               current_team_id = %s, high_bid = NULL, high_bidder_user_id = NULL,
               high_bidder_username = NULL, bid_message_id = NULL,
               silence_phase = 'none', last_bid_at = NULL, updated_at = now()
               WHERE id = 1""",
            (team_id,),
        )


def accept_bid_state(team_id: int, user_id: int, username: str, amount: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bids (team_id, user_id, username, amount, accepted) VALUES (%s, %s, %s, %s, true)",
            (team_id, user_id, username, amount),
        )
        conn.execute(
            """UPDATE auction_state SET
               high_bid = %s, high_bidder_user_id = %s, high_bidder_username = %s,
               silence_phase = 'none', last_bid_at = now(), updated_at = now()
               WHERE id = 1""",
            (amount, user_id, username),
        )


def reject_bid_log(team_id: int | None, user_id: int, username: str, amount: int, reason: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bids (team_id, user_id, username, amount, accepted, reason) VALUES (%s, %s, %s, %s, false, %s)",
            (team_id, user_id, username, amount, reason),
        )


def set_bid_message_id(message_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE auction_state SET bid_message_id = %s, updated_at = now() WHERE id = 1",
            (message_id,),
        )


def set_silence_phase(phase: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE auction_state SET silence_phase = %s, updated_at = now() WHERE id = 1",
            (phase,),
        )


# ── Teams ────────────────────────────────────────────────────────────────────

def get_all_teams() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM teams ORDER BY draw_position")
            return cur.fetchall()


def get_team_by_id(team_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM teams WHERE id = %s", (team_id,))
            return cur.fetchone()


def get_next_pending_team() -> dict | None:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM teams WHERE status = 'pending' ORDER BY draw_position LIMIT 1"
            )
            return cur.fetchone()


def count_pending_teams() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM teams WHERE status = 'pending'").fetchone()[0]


def count_sold_teams() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM teams WHERE status = 'sold'").fetchone()[0]


def set_team_active(team_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE teams SET status = 'active' WHERE id = %s", (team_id,))


def mark_team_sold(team_id: int, user_id: int, username: str, price: int):
    with get_conn() as conn:
        conn.execute(
            """UPDATE teams SET status = 'sold', sold_to_user_id = %s,
               sold_to_username = %s, sold_price = %s, sold_at = now()
               WHERE id = %s""",
            (user_id, username, price, team_id),
        )


def unmark_team_sold(team_id: int):
    with get_conn() as conn:
        conn.execute(
            """UPDATE teams SET status = 'pending', sold_to_user_id = NULL,
               sold_to_username = NULL, sold_price = NULL, sold_at = NULL
               WHERE id = %s""",
            (team_id,),
        )


def get_last_sold_team() -> dict | None:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM teams WHERE status = 'sold' ORDER BY sold_at DESC LIMIT 1"
            )
            return cur.fetchone()


def shuffle_pending_teams():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM teams WHERE status IN ('pending', 'active')")
            ids = [r[0] for r in cur.fetchall()]
        positions = list(range(1, len(ids) + 1))
        random.shuffle(positions)
        with conn.cursor() as cur:
            for tid, pos in zip(ids, positions):
                cur.execute(
                    "UPDATE teams SET draw_position = %s WHERE id = %s", (pos, tid)
                )


def correct_sold_price(team_id: int, new_price: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE teams SET sold_price = %s WHERE id = %s", (new_price, team_id)
        )


# ── Overrides ────────────────────────────────────────────────────────────────

def get_pending_overrides() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM pending_overrides WHERE applied = false ORDER BY created_at"
            )
            return cur.fetchall()


def mark_override_applied(override_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_overrides SET applied = true, applied_at = now() WHERE id = %s",
            (override_id,),
        )


def queue_override(action: str, params: dict | None = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pending_overrides (action, params) VALUES (%s, %s)",
            (action, json.dumps(params) if params else None),
        )


# ── Results & live state ─────────────────────────────────────────────────────

def get_results() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM teams WHERE status = 'sold' ORDER BY sold_at"
            )
            return cur.fetchall()


def get_live_state() -> dict:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM auction_state WHERE id = 1")
            state = cur.fetchone()

            current_team = None
            recent_bids: list[dict] = []

            if state and state["current_team_id"]:
                cur.execute("SELECT * FROM teams WHERE id = %s", (state["current_team_id"],))
                current_team = cur.fetchone()

                cur.execute(
                    """SELECT * FROM bids WHERE team_id = %s AND accepted = true
                       ORDER BY created_at DESC LIMIT 8""",
                    (state["current_team_id"],),
                )
                recent_bids = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM teams WHERE status = 'pending'")
            remaining = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM teams WHERE status = 'sold'")
            sold = cur.fetchone()[0]

            cur.execute(
                "SELECT * FROM teams WHERE status = 'sold' ORDER BY sold_at DESC LIMIT 6"
            )
            recent_sold = cur.fetchall()

        return {
            "status": state["status"] if state else "idle",
            "current_team": (
                {"id": current_team["id"], "name": current_team["name"], "flag": current_team["flag"]}
                if current_team
                else None
            ),
            "high_bid": state["high_bid"] if state else None,
            "high_bidder": state["high_bidder_username"] if state else None,
            "silence_phase": (state["silence_phase"] if state else "none"),
            "remaining_teams": remaining,
            "teams_sold": sold,
            "recent_bids": [
                {
                    "username": b["username"],
                    "amount": b["amount"],
                    "ts": b["created_at"].isoformat() if b["created_at"] else None,
                }
                for b in recent_bids
            ],
            "recent_sold": [
                {
                    "name": t["name"],
                    "flag": t["flag"],
                    "buyer": t["sold_to_username"],
                    "price": t["sold_price"],
                }
                for t in recent_sold
            ],
        }
