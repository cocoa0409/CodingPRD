"""Entry point: Flask app, blueprint registration, error handlers.

The store starts empty on every boot -- nothing is seeded here. start.sh
re-invocation wipes all state (module-level dicts only).
"""
import os

from flask import Flask

import agreements
import capacity
import chillers
import clock
import inventory
import lots
import placements
import readings
import shipments
import stores
import tickets
import trials
from envelope import err
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

for _bp in (clock.bp, stores.bp, agreements.bp, chillers.bp, readings.bp,
            placements.bp, tickets.bp, shipments.bp, lots.bp, inventory.bp,
            capacity.bp, trials.bp):
    app.register_blueprint(_bp)


@app.errorhandler(ApiError)
def _api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _not_found(e):
    return err("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(e):
    return err("ERR_NOT_FOUND", 405, "Method not allowed")


@app.errorhandler(Exception)
def _generic(e):
    return err("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False)
