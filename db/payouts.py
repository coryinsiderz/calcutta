"""Payout computation from tournament progress.

ko_stage scale (per team):
  0 = eliminated in group        1 = qualified (R32), lost in R32
  2 = reached R16                3 = reached QF
  4 = reached SF                5 = reached final (runner-up)
  6 = champion

Bracket payout is cumulative — a team banks every rung it clears. The group
entry rung is either "won_group" (if won_group) or "qualify_other".
Side awards stack on top of whatever a team earned in the bracket.
"""
from psycopg.rows import dict_row

from db.connection import get_conn

STAGE_LABELS = {
    0: "Group stage",
    1: "Qualified (R32)",
    2: "Round of 16",
    3: "Quarterfinal",
    4: "Semifinal",
    5: "Final",
    6: "Champion",
}

# Stage -> cumulative rung key earned at that stage (beyond the group-entry rung)
_STAGE_RUNGS = [
    (2, "reach_r16"),
    (3, "reach_qf"),
    (4, "reach_sf"),
    (5, "reach_final"),
    (6, "champion"),
]


def compute_standings() -> dict:
    """Return pot, per-team payout breakdown, and per-owner leaderboard."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT key, rate FROM payout_rules")
            rules = {r["key"]: float(r["rate"]) for r in cur.fetchall()}

            cur.execute(
                "SELECT key, label, rate, team_id FROM side_awards ORDER BY sort"
            )
            side_awards = cur.fetchall()

            cur.execute(
                """SELECT id, name, flag, status, sold_to_username, sold_price,
                          ko_stage, won_group
                   FROM teams ORDER BY name"""
            )
            teams = cur.fetchall()

    pot = sum((t["sold_price"] or 0) for t in teams if t["status"] == "sold")

    # Per-team rate
    per_team: dict[int, dict] = {}
    for t in teams:
        bracket_rate = 0.0
        if t["ko_stage"] >= 1:
            bracket_rate += rules.get("win_group", 0) if t["won_group"] else rules.get("qualify_other", 0)
        for stage, key in _STAGE_RUNGS:
            if t["ko_stage"] >= stage:
                bracket_rate += rules.get(key, 0)

        per_team[t["id"]] = {
            "id": t["id"],
            "name": t["name"],
            "flag": t["flag"],
            "status": t["status"],
            "owner": t["sold_to_username"],
            "price": t["sold_price"] or 0,
            "ko_stage": t["ko_stage"],
            "won_group": t["won_group"],
            "stage_label": STAGE_LABELS.get(t["ko_stage"], "?"),
            "bracket_rate": bracket_rate,
            "side_rate": 0.0,
            "side_awards": [],
        }

    # Apply side awards
    side_summary = []
    for a in side_awards:
        team_name = None
        if a["team_id"] and a["team_id"] in per_team:
            pt = per_team[a["team_id"]]
            pt["side_rate"] += float(a["rate"])
            pt["side_awards"].append(a["label"])
            team_name = pt["name"]
        side_summary.append({
            "key": a["key"],
            "label": a["label"],
            "rate": float(a["rate"]),
            "team_id": a["team_id"],
            "team_name": team_name,
            "payout": float(a["rate"]) * pot,
        })

    # Finalize per-team payouts
    team_rows = []
    for pt in per_team.values():
        pt["total_rate"] = pt["bracket_rate"] + pt["side_rate"]
        pt["payout"] = round(pt["total_rate"] * pot)
        team_rows.append(pt)

    # Per-owner leaderboard
    owners: dict[str, dict] = {}
    for pt in team_rows:
        if pt["status"] != "sold" or not pt["owner"]:
            continue
        o = owners.setdefault(pt["owner"], {
            "owner": pt["owner"], "spent": 0, "won": 0, "teams": []
        })
        o["spent"] += pt["price"]
        o["won"] += pt["payout"]
        o["teams"].append({
            "name": pt["name"], "flag": pt["flag"], "price": pt["price"],
            "payout": pt["payout"], "stage_label": pt["stage_label"],
        })

    leaderboard = []
    for o in owners.values():
        o["net"] = o["won"] - o["spent"]
        o["teams"].sort(key=lambda x: x["payout"], reverse=True)
        leaderboard.append(o)
    leaderboard.sort(key=lambda x: x["net"], reverse=True)

    team_rows.sort(key=lambda x: (x["payout"], x["price"]), reverse=True)

    total_paid_rate = sum(pt["total_rate"] for pt in team_rows)

    return {
        "pot": pot,
        "teams": team_rows,
        "leaderboard": leaderboard,
        "side_awards": side_summary,
        "total_paid_rate": total_paid_rate,
    }


def build_info_text() -> str:
    """Plain-text pot + sold-team list for Telegram (no markdown — usernames may
    contain underscores, which would break Telegram markdown). One line per sold
    team in sold order: "<flag> <name> - $<price> @<owner>"."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT name, flag, sold_to_username, sold_price
                   FROM teams WHERE status = 'sold' ORDER BY sold_at"""
            )
            rows = cur.fetchall()

    pot = sum((r["sold_price"] or 0) for r in rows)
    lines = [f"Pot: ${pot:,}  ·  {len(rows)}/48 sold"]
    for r in rows:
        price = r["sold_price"] or 0
        owner = r["sold_to_username"] or "?"
        lines.append(f"{r['flag']} {r['name']} - ${price:,} @{owner}")
    return "\n".join(lines)


def build_standings_text() -> str:
    """Per-owner leaderboard for Telegram: spent during the auction, spent/won/net
    once tournament results are in. Plain text (no markdown)."""
    data = compute_standings()
    pot = data["pot"]
    lb = data["leaderboard"]
    if not lb:
        return f"Standings  ·  Pot ${pot:,}\nNo teams sold yet."

    has_winnings = any(o["won"] for o in lb)
    rows = sorted(lb, key=lambda o: (o["net"] if has_winnings else o["spent"]), reverse=True)

    lines = [f"Standings  ·  Pot ${pot:,}"]
    for i, o in enumerate(rows, 1):
        n = len(o["teams"])
        teams = f"{n} team{'s' if n != 1 else ''}"
        if has_winnings:
            sign = "+" if o["net"] >= 0 else "-"
            lines.append(
                f"{i}. {o['owner']} — net {sign}${abs(o['net']):,} "
                f"(won ${o['won']:,}, spent ${o['spent']:,}, {teams})"
            )
        else:
            lines.append(f"{i}. {o['owner']} — spent ${o['spent']:,} ({teams})")
    return "\n".join(lines)
