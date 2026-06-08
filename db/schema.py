import logging
import random

from db.connection import get_conn

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS auction_config (
    id INT PRIMARY KEY DEFAULT 1,
    silence_once_sec  INT  NOT NULL DEFAULT 15,
    silence_twice_sec INT  NOT NULL DEFAULT 5,
    silence_sold_sec  INT  NOT NULL DEFAULT 5,
    opening_floor     INT  NOT NULL DEFAULT 1,
    msg_going_once    TEXT NOT NULL DEFAULT 'Going once... {team} to {bidder} for ${amount}',
    msg_going_twice   TEXT NOT NULL DEFAULT 'TWICE',
    msg_sold          TEXT NOT NULL DEFAULT 'SOLD! {team} to {bidder} for ${amount}',
    CONSTRAINT auction_config_one_row CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS increment_bands (
    id        SERIAL PRIMARY KEY,
    min_price INT NOT NULL,
    increment INT NOT NULL,
    CONSTRAINT increment_bands_unique_min UNIQUE (min_price)
);

CREATE TABLE IF NOT EXISTS teams (
    id                SERIAL PRIMARY KEY,
    name              TEXT NOT NULL,
    flag              TEXT NOT NULL DEFAULT '',
    draw_position     INT,
    status            TEXT NOT NULL DEFAULT 'pending',
    sold_to_user_id   BIGINT,
    sold_to_username  TEXT,
    sold_price        INT,
    sold_at           TIMESTAMPTZ,
    CONSTRAINT teams_valid_status CHECK (status IN ('pending', 'active', 'sold'))
);

CREATE TABLE IF NOT EXISTS auction_state (
    id                    INT PRIMARY KEY DEFAULT 1,
    status                TEXT NOT NULL DEFAULT 'idle',
    current_team_id       INT REFERENCES teams(id),
    high_bid              INT,
    high_bidder_user_id   BIGINT,
    high_bidder_username  TEXT,
    bid_message_id        BIGINT,
    silence_phase         TEXT NOT NULL DEFAULT 'none',
    last_bid_at           TIMESTAMPTZ,
    chat_id               BIGINT,
    updated_at            TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT auction_state_one_row CHECK (id = 1),
    CONSTRAINT auction_state_valid_status CHECK (status IN ('idle', 'running', 'paused', 'done')),
    CONSTRAINT auction_state_valid_phase CHECK (silence_phase IN ('none', 'once', 'twice'))
);

CREATE TABLE IF NOT EXISTS bids (
    id         SERIAL PRIMARY KEY,
    team_id    INT REFERENCES teams(id),
    user_id    BIGINT NOT NULL,
    username   TEXT NOT NULL,
    amount     INT NOT NULL,
    accepted   BOOLEAN NOT NULL DEFAULT true,
    reason     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pending_overrides (
    id         SERIAL PRIMARY KEY,
    action     TEXT NOT NULL,
    params     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at TIMESTAMPTZ,
    applied    BOOLEAN NOT NULL DEFAULT false
);

-- Tournament tracking (added to teams for existing DBs via ALTER below)
ALTER TABLE teams ADD COLUMN IF NOT EXISTS ko_stage  INT     NOT NULL DEFAULT 0;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS won_group BOOLEAN NOT NULL DEFAULT false;

-- Freeze lock: when true, /reset is refused (protects results during the tournament)
ALTER TABLE auction_state ADD COLUMN IF NOT EXISTS frozen BOOLEAN NOT NULL DEFAULT false;

-- Saved snapshots (restore points) of the full results + tournament progress
CREATE TABLE IF NOT EXISTS snapshots (
    id         SERIAL PRIMARY KEY,
    label      TEXT,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Registered participants (owners). name_lower enforces case-insensitive uniqueness.
CREATE TABLE IF NOT EXISTS participants (
    id               SERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    name_lower       TEXT NOT NULL UNIQUE,
    telegram_user_id BIGINT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payout_rules (
    key   TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    rate  NUMERIC NOT NULL,
    sort  INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS side_awards (
    key     TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    rate    NUMERIC NOT NULL,
    team_id INT REFERENCES teams(id),
    sort    INT NOT NULL DEFAULT 0
);
"""

# ko_stage scale:
#   0 = eliminated in group     1 = qualified (R32), lost in R32
#   2 = reached R16             3 = reached QF
#   4 = reached SF             5 = reached final (runner-up)
#   6 = champion

_PAYOUT_RULES = [
    ("qualify_other", "Qualified (2nd/3rd)",  0.005, 1),
    ("win_group",     "Won group",            0.01,  2),
    ("reach_r16",     "Reached R16",          0.005, 3),
    ("reach_qf",      "Reached QF",           0.015, 4),
    ("reach_sf",      "Reached SF",           0.03,  5),
    ("reach_final",   "Reached final",        0.07,  6),
    ("champion",      "Champion",             0.16,  7),
]

_SIDE_AWARDS = [
    ("third_place",       "3rd place (playoff winner)",                  0.02, 1),
    ("least_goals",       "Least goals scored (group)",                  0.03, 2),
    ("worst_gd",          "Worst goal differential (group)",             0.03, 3),
    ("most_goals",        "Most goals scored (group)",                   0.02, 4),
    ("top_fifa_ko",       "Highest FIFA rank to qualify for KO",         0.02, 5),
    ("least_conceded_ko", "Least conceded, KO qualifiers (excl. PKs)",   0.02, 6),
    ("most_conceded",     "Most conceded, full tournament",              0.01, 7),
    ("most_reds",         "Most red cards (tournament)",                 0.01, 8),
]


def apply_schema():
    with get_conn() as conn:
        conn.execute(_SCHEMA)
    logger.info("Schema applied")


def seed_defaults():
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO auction_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )
        # Strip the old emoji default from existing installs (leaves customizations intact)
        conn.execute(
            "UPDATE auction_config SET msg_sold = %s WHERE msg_sold = %s",
            (
                "SOLD! {team} to {bidder} for ${amount}",
                "SOLD! {team} to {bidder} for ${amount} \U0001f528",
            ),
        )
        # Update the going-twice wording to the terse "TWICE" on existing installs
        conn.execute(
            "UPDATE auction_config SET msg_going_twice = %s WHERE msg_going_twice = %s",
            ("TWICE", "Going twice... {team} to {bidder} for ${amount}"),
        )

        # Clean stray wrapping chars from participant names (e.g. "<Paddy's Pub>")
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM participants")
            rows = cur.fetchall()
        for pid, pname in rows:
            clean = pname.strip("<>\"'@ ").strip()
            if clean and clean != pname:
                dup = conn.execute(
                    "SELECT 1 FROM participants WHERE name_lower = %s AND id <> %s",
                    (clean.lower(), pid),
                ).fetchone()
                if not dup:
                    conn.execute(
                        "UPDATE participants SET name = %s, name_lower = %s WHERE id = %s",
                        (clean, clean.lower(), pid),
                    )
        conn.execute(
            "INSERT INTO auction_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )

        count = conn.execute("SELECT COUNT(*) FROM increment_bands").fetchone()[0]
        if count == 0:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO increment_bands (min_price, increment) VALUES (%s, %s)",
                    [(0, 1), (50, 2), (100, 5), (200, 10)],
                )
            logger.info("Seeded increment bands")

        count = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
        if count == 0:
            from data.teams import TEAMS
            positions = list(range(1, len(TEAMS) + 1))
            random.shuffle(positions)
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO teams (name, flag, draw_position) VALUES (%s, %s, %s)",
                    [(t["name"], t["flag"], pos) for t, pos in zip(TEAMS, positions)],
                )
            logger.info("Seeded %d teams", len(TEAMS))

        count = conn.execute("SELECT COUNT(*) FROM payout_rules").fetchone()[0]
        if count == 0:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO payout_rules (key, label, rate, sort) VALUES (%s, %s, %s, %s)",
                    _PAYOUT_RULES,
                )
            logger.info("Seeded payout rules")

        count = conn.execute("SELECT COUNT(*) FROM side_awards").fetchone()[0]
        if count == 0:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO side_awards (key, label, rate, sort) VALUES (%s, %s, %s, %s)",
                    _SIDE_AWARDS,
                )
            logger.info("Seeded side awards")

    logger.info("Defaults seeded")
