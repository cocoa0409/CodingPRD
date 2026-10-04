"""Rideshare Manifest Ops API — Flask entry point.

Boots cleanly from a fresh process on every invocation: the store is
in-memory and starts empty; the logical clock starts at 2026-09-01T00:00:00Z.
"""
import os

from flask import Flask

import routes_assignments
import routes_clock
import routes_contracts
import routes_customers
import routes_licenses
import routes_missions
import routes_postlaunch
import routes_range
from envelope import register_error_handlers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for mod in (
        routes_clock,
        routes_customers,
        routes_missions,
        routes_contracts,
        routes_assignments,
        routes_licenses,
        routes_range,
        routes_postlaunch,
    ):
        app.register_blueprint(mod.bp)
    register_error_handlers(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
