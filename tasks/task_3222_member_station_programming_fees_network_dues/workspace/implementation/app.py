#!/usr/bin/env python3
"""Member Station Programming Fees & Network Dues API.

Boot from a fresh process with an EMPTY store: nothing is seeded here or in any
module import path. Blueprints are registered explicitly so the URL rules match
the role matrix keys in core.middleware exactly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

from core import middleware  # noqa: E402
from routes import (  # noqa: E402
    carriage,
    clock,
    contributions,
    dues,
    feeds,
    programs,
    stations,
    underwriting,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        stations,
        clock,
        carriage,
        feeds,
        underwriting,
        contributions,
        programs,
        dues,
    ):
        app.register_blueprint(module.bp)

    middleware.install_error_handlers(app)
    return app


app = create_app()

# Every route this application serves, with the role matrix each one enforces.
from core.middleware import ROUTE_ROLES  # noqa: E402

ROUTE_INDEX = ROUTE_ROLES


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )