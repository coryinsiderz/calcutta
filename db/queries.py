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


def admin_update_team(team_id: int, name: str, status: str, owner: str | None, price: int | None):
    """Full manual edit of a team row from the admin panel."""
    with get_conn() as conn:
        if status == "sold":
            conn.execute(
                """UPDATE teams SET name = %s, status = 'sold',
                   sold_to_username = %s, sold_price = %s,
                   sold_at = COALESCE(sold_at, now())
                   WHERE id = %s""",
                (name, owner, price if price is not None else 0, team_id),
            )
        elif status == "pending":
            conn.execute(
                """UPDATE teams SET name = %s, status = 'pending',
                   sold_to_user_id = NULL, sold_to_username = NULL,
                   sold_price = NULL, sold_at = NULL
                   WHERE id = %s""",
                (name, team_id),
            )
        else:  # active
            conn.execute(
                "UPDATE teams SET name = %s, status = %s WHERE id = %s",
                (name, status, team_id),
            )


def set_team_progress(team_id: int, ko_stage: int, won_group: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE teams SET ko_stage = %s, won_group = %s WHERE id = %s",
            (ko_stage, won_group, team_id),
        )


def get_side_awards() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM side_awards ORDER BY sort")
            return cur.fetchall()


def set_side_award_team(key: str, team_id: int | None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE side_awards SET team_id = %s WHERE key = %s", (team_id, key)
        )


def get_payout_rules() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM payout_rules ORDER BY sort")
            return cur.fetchall()


def register_participant(name: str, user_id: int | None = None) -> tuple[bool, str]:
    """Returns (created, canonical_name). created=False if the name already existed."""
    name = name.strip()
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT name FROM participants WHERE name_lower = %s", (name.lower(),))
            existing = cur.fetchone()
            if existing:
                return False, existing["name"]
            cur.execute(
                "INSERT INTO participants (name, name_lower, telegram_user_id) VALUES (%s, %s, %s)",
                (name, name.lower(), user_id),
            )
            return True, name


def get_participants() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM participants ORDER BY name")
            return cur.fetchall()


def find_participant(name: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM participants WHERE name_lower = %s", (name.strip().lower(),)
            )
            return cur.fetchone()


def find_participant_by_user_id(user_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM participants WHERE telegram_user_id = %s LIMIT 1", (user_id,)
            )
            return cur.fetchone()


def unregister_participant(name: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM participants WHERE name_lower = %s", (name.strip().lower(),)
        )
        return cur.rowcount > 0


def get_frozen() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT frozen FROM auction_state WHERE id = 1").fetchone()
        return bool(row[0]) if row else False


def set_frozen(frozen: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE auction_state SET frozen = %s, updated_at = now() WHERE id = 1",
            (frozen,),
        )


def save_snapshot(label: str) -> int:
    """Save a restore point of all teams + side awards. Returns snapshot id."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT id, name, status, sold_to_user_id, sold_to_username,
                          sold_price, ko_stage, won_group
                   FROM teams ORDER BY id"""
            )
            teams = cur.fetchall()
            cur.execute("SELECT key, team_id FROM side_awards")
            sides = cur.fetchall()
            payload = json.dumps({"teams": teams, "side_awards": sides}, default=str)
            cur.execute(
                "INSERT INTO snapshots (label, payload) VALUES (%s, %s) RETURNING id",
                (label, payload),
            )
            return cur.fetchone()["id"]


def list_snapshots() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, label, created_at FROM snapshots ORDER BY created_at DESC"
            )
            return cur.fetchall()


def restore_snapshot(snap_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT payload FROM snapshots WHERE id = %s", (snap_id,))
            row = cur.fetchone()
            if not row:
                return False
            payload = row["payload"]  # JSONB -> dict
            for t in payload.get("teams", []):
                cur.execute(
                    """UPDATE teams SET status = %s, sold_to_user_id = %s,
                       sold_to_username = %s, sold_price = %s, ko_stage = %s, won_group = %s
                       WHERE id = %s""",
                    (
                        t["status"], t["sold_to_user_id"], t["sold_to_username"],
                        t["sold_price"], t["ko_stage"], t["won_group"], t["id"],
                    ),
                )
            for s in payload.get("side_awards", []):
                cur.execute(
                    "UPDATE side_awards SET team_id = %s WHERE key = %s",
                    (s["team_id"], s["key"]),
                )
    return True


def reset_auction():
    """Wipe all bids and sales, reset state to idle, reshuffle the draw order."""
    with get_conn() as conn:
        conn.execute("DELETE FROM bids")
        conn.execute(
            """UPDATE teams SET status = 'pending', sold_to_user_id = NULL,
               sold_to_username = NULL, sold_price = NULL, sold_at = NULL,
               ko_stage = 0, won_group = false"""
        )
        conn.execute("UPDATE side_awards SET team_id = NULL")
        conn.execute(
            """UPDATE auction_state SET status = 'idle', current_team_id = NULL,
               high_bid = NULL, high_bidder_user_id = NULL, high_bidder_username = NULL,
               bid_message_id = NULL, silence_phase = 'none', last_bid_at = NULL,
               updated_at = now() WHERE id = 1"""
        )
        conn.execute(
            "UPDATE pending_overrides SET applied = true, applied_at = now() WHERE applied = false"
        )
    shuffle_pending_teams()


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

            cur.execute("SELECT COUNT(*) AS n FROM teams WHERE status = 'pending'")
            remaining = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM teams WHERE status = 'sold'")
            sold = cur.fetchone()["n"]

            cur.execute("SELECT COALESCE(SUM(sold_price), 0) AS pot FROM teams WHERE status = 'sold'")
            pot = cur.fetchone()["pot"]

            cur.execute(
                "SELECT * FROM teams WHERE status = 'sold' ORDER BY sold_at DESC"
            )
            recent_sold = cur.fetchall()

        return {
            "status": state["status"] if state else "idle",
            "frozen": bool(state["frozen"]) if state else False,
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
            "pot": pot,
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
