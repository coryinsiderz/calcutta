# World Cup 2026 Calcutta — Auction Bot

## What this is
A Telegram auction bot + Flask web panel for running a Calcutta pool on the 2026 FIFA World Cup.

- **Bot worker** (`main.py`): long-polling Telegram worker. Runs the live auction, accepts bids, fires the silence timer.
- **Web panel** (`web_main.py`): Flask app. Live board (poll every 2s), config editor, admin overrides.

## Architecture
- Single asyncio event loop in the bot serialises all bid/state mutations — no locks needed.
- DB is Neon (Postgres). Both services have their own connection pool.
- Web panel writes to `pending_overrides`; bot picks them up within 2 s via the override poller.
- Bot is the sole writer of auction state. Web panel is read-only except config and override queue.

## Setup

### 1. Create the Telegram bot
Message @BotFather → `/newbot` → copy the token.

### 2. Neon database
Create a new Neon project. Copy the connection string.

### 3. Railway services
Deploy **two** services from this repo:

| Service | Start command | Env vars needed |
|---------|--------------|-----------------|
| Worker  | `python main.py` | all four below |
| Web     | `gunicorn --bind 0.0.0.0:$PORT --workers 1 web_main:app` | DATABASE_URL, ADMIN_PASSWORD |

### 4. Env vars
```
TELEGRAM_BOT_TOKEN=   # from BotFather
DATABASE_URL=         # Neon connection string
ADMIN_USER_IDS=       # comma-separated Telegram user IDs (get from @userinfobot)
ADMIN_PASSWORD=       # password for the web panel (HTTP basic auth)
```

## Bot commands

| Command | Who | Effect |
|---------|-----|--------|
| `/start` | Admin | Begin auction (must be run in the group chat) |
| `/bid 50` | Anyone | Place a bid |
| `/pause` | Admin | Pause (timer stops) |
| `/resume` | Admin | Resume (timer restarts) |
| `/next` | Admin | Advance to next team immediately |
| `/undo` | Admin | Re-auction the last sold team |
| `/correct 175` | Admin | Correct last sold team's price |
| `/shuffle` | Admin | Randomise remaining draw order |
| `/reset CONFIRM` | Admin | Wipe all bids/sales, reset to idle, reshuffle (for clearing test data) |
| `/results` | Anyone | Show all sold teams + pot total |
| `/status` | Anyone | Show current auction state |
| `/config` | Admin | Show current config |
| `/ping` | Anyone | Sanity check |

## Bidding rules
- Opening bid: any amount ≥ floor (default $1). Must be typed: `/bid 25`
- Subsequent bids: tap inline keyboard buttons or `/bid N`
- Minimum raise follows increment bands (default: +$1 below $50, +$2 $50–$99, +$5 $100–$199, +$10 $200+)
- Can't bid against yourself
- Silence timer: 15 s quiet → "going once", 5 s more → "going twice", 5 s more → SOLD
- Any accepted bid resets the timer to zero (anti-snipe built in)

## Web panel
- `/` — Live board (no auth required)
- `/config` — Edit timers, floor, bands, message templates (auth required)
- `/admin` — Pause/resume, undo, correct price, shuffle (auth required)

## Teams
All 48 qualified teams are seeded on first startup with a random draw order.
List is in `data/teams.py`. To re-shuffle at any time: `/shuffle` in Telegram or the button in the admin panel.

## Payout structure (agreed pre-auction)
Rates are percentage of pot. Teams bank each rung they clear (cumulative).

| Milestone | Rate | Teams |
|-----------|------|-------|
| Qualify w/o winning group (2nd/3rd equal) | 0.5% | 20 |
| Win group (2× a qualifier) | 1.0% | 12 |
| Reach R16 (win R32) | 0.5% | 16 |
| Reach QF | 1.5% | 8 |
| Reach SF | 3.0% | 4 |
| Reach final | 7.0% | 2 |
| Champion | 16.0% | 1 |
| 3rd place playoff winner | 2.0% | 1 |
| Least goals scored (group stage) | 3.0% | 1 |
| Worst goal differential (group stage) | 3.0% | 1 |
| Most goals scored (group stage) | 2.0% | 1 |
| Highest FIFA ranking to qualify for KO | 2.0% | 1 |
| Least goals conceded, KO qualifiers (excl. PKs) | 2.0% | 1 |
| Most goals conceded, full tournament | 1.0% | 1 |
| Most red cards, tournament | 1.0% | 1 |
| **Total** | **100%** | |
