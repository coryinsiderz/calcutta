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
    msg_going_twice   TEXT NOT NULL DEFAULT 'Going twice... {team} to {bidder} for ${amount}',
    msg_sold          TEXT NOT NULL DEFAULT 'SOLD! {team} to {bidder} for ${amount} 🔨',
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
"""


def apply_schema():
    with get_conn() as conn:
        conn.execute(_SCHEMA)
    logger.info("Schema applied")


def seed_defaults():
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO auction_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
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

    logger.info("Defaults seeded")
