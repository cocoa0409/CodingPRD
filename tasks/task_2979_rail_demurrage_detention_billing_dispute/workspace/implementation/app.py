"""Rail Demurrage & Detention Billing Dispute API.

Every route is mounted under the `/demurrage` prefix (PRD §4).  Storage is
process-local and in-memory only: a fresh process starts with zero consignees,
zero rule sets, zero facilities, zero cars and the cold-start logical clock of
2026-08-01T00:00:00Z.  Nothing is ever seeded.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_billing
import routes_cycles
import routes_disputes
import routes_reference
import routes_regulatory
from envelope import error_response
from errors import ApiError

API_PREFIX = "/demurrage"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (routes_reference, routes_cycles, routes_billing,
                   routes_disputes, routes_regulatory):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        # An unrouted path or an unsupported method never reaches the ladder, so
        # it reports the generic malformed-request code at its own status.
        return error_response(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be routed.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INVALID_REQUEST",
                             "Unexpected server error: %s" % exc, 500)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            threaded=True,
            use_reloader=False,
            debug=False)
