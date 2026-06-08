import os
from functools import wraps

from flask import Blueprint, Response, render_template, request

import db.queries as queries
from db.payouts import compute_standings

pages_bp = Blueprint("pages", __name__)


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        pw = os.environ.get("ADMIN_PASSWORD", "changeme")
        if not auth or auth.password != pw:
            return Response(
                "Authentication required",
                401,
                {"WWW-Authenticate": 'Basic realm="Calcutta Admin"'},
            )
        return f(*args, **kwargs)
    return decorated


@pages_bp.route("/")
def index():
    return render_template("index.html")


@pages_bp.route("/standings")
def standings_page():
    return render_template("standings.html", data=compute_standings())


@pages_bp.route("/tournament")
@require_auth
def tournament_page():
    all_teams = queries.get_all_teams()
    side_awards = queries.get_side_awards()
    rules = queries.get_payout_rules()
    # sold teams only are eligible to be assigned side awards / tracked meaningfully
    sold_teams = [t for t in all_teams if t["status"] == "sold"]
    return render_template(
        "tournament.html",
        all_teams=all_teams,
        sold_teams=sold_teams,
        side_awards=side_awards,
        rules=rules,
    )


@pages_bp.route("/config")
@require_auth
def config_page():
    cfg = queries.get_auction_config()
    bands = queries.get_increment_bands()
    return render_template("config.html", config=cfg, bands=bands)


@pages_bp.route("/admin")
@require_auth
def admin_page():
    state = queries.get_auction_state()
    results = queries.get_results()
    sold_teams = queries.get_results()
    all_teams = queries.get_all_teams()
    last_sold = queries.get_last_sold_team()
    pot = sum(t["sold_price"] or 0 for t in results)
    return render_template(
        "admin.html",
        state=state,
        all_teams=all_teams,
        sold_teams=sold_teams,
        last_sold=last_sold,
        pot=pot,
    )
