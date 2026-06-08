import logging
import os

from dotenv import load_dotenv

load_dotenv()

from db import schema
from web.app import create_app

logging.basicConfig(level=logging.INFO)

schema.apply_schema()
schema.seed_defaults()

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
