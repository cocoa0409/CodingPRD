"""Craft brewery taproom and self-distribution operations API.

In-memory only. Nothing is seeded: every entity is created through the API.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_brewery
import routes_cellar
import routes_excise
import routes_kegs
import routes_licensing
import routes_orders
import routes_runs
import store
import validation
from errors import ApiError
from validation import ALL_ROLES, authenticate


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        pass

    app.register_blueprint(routes_brewery.bp)
    app.register_blueprint(routes_cellar.bp)
    app.register_blueprint(routes_runs.bp)
    app.register_blueprint(routes_kegs.bp)
    app.register_blueprint(routes_licensing.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_excise.bp)

    @app.post("/_clock/set_current_utc")
    def set_clock():
        authenticate(ALL_ROLES)
        payload = validation.body()
        instant = validation.field_datetime(payload, "current_utc")
        store.set_clock(instant)
        return envelope.object_response({"current_utc": store.fmt_dt(store.clock_now())})

    @app.get("/_clock/current_utc")
    def read_clock():
        authenticate(ALL_ROLES)
        return envelope.object_response({"current_utc": store.fmt_dt(store.clock_now())})

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return envelope.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif status == 415:
            error_id = "ERR_INVALID_REQUEST"
            status = 400
        elif status == 400:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        return envelope.error_response(error_id, error.description or error_id, status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return envelope.error_response("ERR_INTERNAL", str(error) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
