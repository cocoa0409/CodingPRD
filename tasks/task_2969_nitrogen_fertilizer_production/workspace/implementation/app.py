"""Nitrogen fertilizer production operations service.

Flask application factory and the single error surface. Every module below this
one is pure domain code: the store is in memory, the clock is logical, and
nothing is ever seeded -- all state arrives through the declared endpoints.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import _meta, error_response
from errors import ApiError
from routes import (assets, charges, clock, emissions, hedge_lots, orders,
                    plants, product_lines, quotes, runs, shipments, tasks,
                    trains, turnarounds)

BLUEPRINTS = (
    plants.bp,
    trains.bp,
    charges.bp,
    hedge_lots.bp,
    product_lines.bp,
    runs.bp,
    orders.bp,
    assets.bp,
    shipments.bp,
    quotes.bp,
    turnarounds.bp,
    tasks.bp,
    emissions.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": err.description or err.name,
            },
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(err)},
        }
        return jsonify(body), 422

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
