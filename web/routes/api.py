import json

from flask import Blueprint, jsonify, request

import db.queries as queries
from db.payouts import compute_standings

api_bp = Blueprint("api", __name__)


@api_bp.route("/state")
def state():
    data = queries.get_live_state()
    # Convert any non-serialisable types
    return jsonify(data)


@api_bp.route("/standings")
def standings():
    return jsonify(compute_standings())


@api_bp.route("/results")
def results():
    teams = queries.get_results()
    pot = sum(t["sold_price"] or 0 for t in teams)
    return jsonify({
        "teams": [
            {
                "name": t["name"],
                "flag": t["flag"],
                "buyer": t["sold_to_username"],
                "price": t["sold_price"],
                "sold_at": t["sold_at"].isoformat() if t["sold_at"] else None,
            }
            for t in teams
        ],
        "pot": pot,
    })


@api_bp.route("/teams")
def teams():
    return jsonify({"teams": queries.get_all_teams()})


# ── Admin override endpoints ─────────────────────────────────────────────────

def _queue(action: str, params: dict | None = None):
    queries.queue_override(action, params)
    return jsonify({"ok": True})


@api_bp.route("/admin/pause", methods=["POST"])
def pause():
    return _queue("pause")


@api_bp.route("/admin/resume", methods=["POST"])
def resume():
    return _queue("resume")


@api_bp.route("/admin/undo", methods=["POST"])
def undo():
    return _queue("undo_last")


@api_bp.route("/admin/correct", methods=["POST"])
def correct():
    data = request.get_json(force=True)
    team_id = data.get("team_id")
    new_price = data.get("new_price")
    if not team_id or not new_price:
        return jsonify({"ok": False, "error": "team_id and new_price required"}), 400
    return _queue("correct_price", {"team_id": int(team_id), "new_price": int(new_price)})


@api_bp.route("/admin/shuffle", methods=["POST"])
def shuffle():
    queries.shuffle_pending_teams()
    return jsonify({"ok": True})


@api_bp.route("/admin/reset", methods=["POST"])
def reset():
    return _queue("reset")


@api_bp.route("/admin/team/<int:team_id>", methods=["POST"])
def update_team(team_id):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    status = data.get("status") or "pending"
    owner = (data.get("owner") or "").strip().lstrip("@") or None
    price_raw = data.get("price")

    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if status not in ("pending", "active", "sold"):
        return jsonify({"ok": False, "error": "bad status"}), 400

    if status == "sold":
        try:
            price = int(price_raw) if price_raw not in (None, "") else 0
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "price must be a number"}), 400
    else:
        price = None

    queries.admin_update_team(team_id, name, status, owner, price)
    queries.queue_override("reload_state")
    return jsonify({"ok": True})


@api_bp.route("/admin/progress", methods=["POST"])
def progress():
    """Set a team's tournament progress (ko_stage + won_group)."""
    data = request.get_json(force=True)
    team_id = data.get("team_id")
    try:
        ko_stage = int(data.get("ko_stage"))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "ko_stage must be a number"}), 400
    if not team_id:
        return jsonify({"ok": False, "error": "team_id required"}), 400
    if ko_stage < 0 or ko_stage > 6:
        return jsonify({"ok": False, "error": "ko_stage must be 0-6"}), 400
    won_group = bool(data.get("won_group"))
    queries.set_team_progress(int(team_id), ko_stage, won_group)
    return jsonify({"ok": True})


@api_bp.route("/admin/side_award", methods=["POST"])
def side_award():
    """Assign (or clear) the winning team for a side category."""
    data = request.get_json(force=True)
    key = data.get("key")
    team_id = data.get("team_id")
    if not key:
        return jsonify({"ok": False, "error": "key required"}), 400
    team_id = int(team_id) if team_id not in (None, "", "0", 0) else None
    queries.set_side_award_team(key, team_id)
    return jsonify({"ok": True})


@api_bp.route("/admin/set_high_bid", methods=["POST"])
def set_high_bid():
    data = request.get_json(force=True)
    amount = data.get("amount")
    bidder = (data.get("bidder") or "").strip().lstrip("@")
    try:
        amount = int(amount)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "amount must be a number"}), 400
    if amount < 1:
        return jsonify({"ok": False, "error": "amount must be >= 1"}), 400
    if not bidder:
        return jsonify({"ok": False, "error": "bidder required"}), 400
    return _queue("set_high_bid", {"amount": amount, "bidder": bidder})


@api_bp.route("/admin/reload_config", methods=["POST"])
def reload_config():
    return _queue("reload_config")


# ── Config ───────────────────────────────────────────────────────────────────

@api_bp.route("/config", methods=["GET"])
def get_config():
    return jsonify({
        "config": queries.get_auction_config(),
        "bands": queries.get_increment_bands(),
    })


@api_bp.route("/config", methods=["POST"])
def save_config():
    data = request.get_json(force=True)

    cfg_fields = {
        "silence_once_sec", "silence_twice_sec", "silence_sold_sec",
        "opening_floor", "msg_going_once", "msg_going_twice", "msg_sold",
    }
    cfg_updates = {k: v for k, v in data.items() if k in cfg_fields}
    if cfg_updates:
        queries.update_auction_config(cfg_updates)

    if "bands" in data:
        bands = [
            {"min_price": int(b["min_price"]), "increment": int(b["increment"])}
            for b in data["bands"]
        ]
        queries.replace_increment_bands(bands)

    # Tell bot to reload
    queries.queue_override("reload_config")
    return jsonify({"ok": True})
