"""Entry point: Flask app, blueprint registration, error handlers, and the
admin-only logical clock endpoint.

Startup state: the store is empty and the logical clock is exactly
2026-09-01T00:00:00Z (set in db.py). Nothing is seeded.
"""

import os

from flask import Flask

from db import db, fmt_instant
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authorize, ROLE_PLATFORM_ADMIN
from respond import ok, register_error_handlers
from validate import json_body, v_dt

import programs
import products
import runs
import retailers
import commitments
import shipments
import claims
import warehouses
import dispositions
import contracts
import reports


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (programs, products, runs, retailers, commitments, shipments,
                   claims, warehouses, dispositions, contracts, reports):
        app.register_blueprint(module.bp)

    register_error_handlers(app)

    @app.post("/confection/_clock/set_current_utc")
    def set_clock():
        data = json_body()
        to_dt, _raw = v_dt(data, "to_iso8601")
        authorize(ROLE_PLATFORM_ADMIN)
        db.clock = to_dt
        return ok({"current_utc": fmt_instant(db.clock)})

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
