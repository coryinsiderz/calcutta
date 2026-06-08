import os

from flask import Flask

from web.routes.api import api_bp
from web.routes.pages import pages_bp


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.secret_key = os.environ.get("ADMIN_PASSWORD", "dev-secret")

    @app.context_processor
    def inject_contests():
        # Contest tabs. Single contest for now; the multi-contest retrofit will
        # make this DB-driven (one entry per contest, active flag from the DB).
        return {
            "nav_contests": [{"label": "WC '26", "href": "/", "active": True}],
        }

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(pages_bp)

    return app
