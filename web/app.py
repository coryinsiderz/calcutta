import os

from flask import Flask

from web.routes.api import api_bp
from web.routes.pages import pages_bp


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.secret_key = os.environ.get("ADMIN_PASSWORD", "dev-secret")

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(pages_bp)

    return app
