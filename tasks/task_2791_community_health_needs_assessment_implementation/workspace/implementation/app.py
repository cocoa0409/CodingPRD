"""Community Health Needs Assessment API — entry point.

In-memory only: every dict in core.Store starts empty on every boot and no
entity is ever seeded here. Tests build all preconditions through the declared
endpoints.
"""

import os

from flask import Flask

from core import ApiError, dumps, error_response
import routes_candidates
import routes_cycles
import routes_evaluations
import routes_indicators
import routes_interviews
import routes_parties
import routes_partnerships
import routes_reports
import routes_strategies


def _envelope(error_id, message, status):
    from core import _meta
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return dumps(body), status, {"Content-Type": "application/json"}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_cycles, routes_indicators, routes_parties,
                   routes_interviews, routes_candidates, routes_strategies,
                   routes_partnerships, routes_reports, routes_evaluations):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return _envelope("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _handle_405(_err):
        return _envelope("ERR_METHOD_NOT_ALLOWED",
                         "The method is not allowed for this resource.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return _envelope("ERR_INTERNAL", str(err) or "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
