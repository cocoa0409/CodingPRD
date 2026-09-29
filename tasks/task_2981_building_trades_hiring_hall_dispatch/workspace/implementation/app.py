"""Building Trades Hiring Hall Dispatch API.

A fresh process starts with an empty in-memory store and the logical clock
parked at 2026-08-01T00:00:00Z. Nothing is seeded and nothing is persisted.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import ApiError, error_response
import routes_admin
import routes_griev
import routes_ref
import routes_reg
import routes_work


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_reg.bp)
    app.register_blueprint(routes_work.bp)
    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_griev.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        body, _status = error_response("ERR_INVALID_REQUEST",
                                       exc.description or exc.name)
        return body, exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        body, _status = error_response("ERR_INVALID_REQUEST", str(exc))
        return body, 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
