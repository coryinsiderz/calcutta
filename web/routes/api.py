import json

from flask import Blueprint, jsonify, request

import db.queries as queries

api_bp = Blueprint("api", __name__)


@api_bp.route("/state")
def state():
    data = queries.get_live_state()
    # Convert any non-serialisable types
    return jsonify(data)


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
