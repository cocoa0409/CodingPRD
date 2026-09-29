"""Eye Bank Corneal Tissue Recovery and Distribution API.

Flask application factory. All state lives in process memory (see store.py) and the
store starts completely empty on every boot: nothing is seeded, preloaded or
hardcoded, and every row in the system is created by an API call.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_allocations
import routes_clock
import routes_donors
import routes_lookback
import routes_recoveries
import routes_reports
import routes_serology
import routes_shipments
import routes_surgeons
import routes_technicians
import routes_tissues
from errors import ApiError

BLUEPRINTS = (
    routes_donors.bp,
    routes_serology.bp,
    routes_technicians.bp,
    routes_recoveries.bp,
    routes_tissues.bp,
    routes_surgeons.bp,
    routes_allocations.bp,
    routes_shipments.bp,
    routes_reports.bp,
    routes_lookback.bp,
    routes_clock.bp,
)

HTTP_FALLBACK = {
    400: ("ERR_INVALID_REQUEST", "The request payload could not be parsed."),
    401: ("ERR_UNAUTHENTICATED", "Authentication headers are missing or malformed."),
    403: ("ERR_FORBIDDEN_ROLE", "The acting role may not perform this operation."),
    404: ("ERR_NOT_FOUND", "No such resource."),
    405: ("ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this path."),
    415: ("ERR_INVALID_REQUEST", "The request body must be JSON."),
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        error_id, message = HTTP_FALLBACK.get(
            err.code, ("ERR_INVALID_REQUEST", err.description or "Request failed.")
        )
        wrapped = ApiError(error_id, message)
        wrapped.http_status = err.code or 400
        return envelope.error_response(wrapped)

    @app.errorhandler(Exception)
    def _unhandled(err):
        wrapped = ApiError("ERR_INTERNAL", "%s: %s" % (type(err).__name__, err))
        wrapped.http_status = 500
        return envelope.error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
