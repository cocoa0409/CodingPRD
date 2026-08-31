"""Workforce Reduction & WARN Act Compliance API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response

import routes_plans
import routes_roster
import routes_selections
import routes_warn
import routes_compliance
import routes_offers
import routes_misc


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_plans.bp)
    app.register_blueprint(routes_roster.bp)
    app.register_blueprint(routes_selections.bp)
    app.register_blueprint(routes_warn.bp)
    app.register_blueprint(routes_compliance.bp)
    app.register_blueprint(routes_offers.bp)
    app.register_blueprint(routes_misc.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", 400, "Unknown resource path.")
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", 400, "Method not allowed for this path.")
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", 400, "Malformed request.")
        return error_response("ERR_INVALID_REQUEST", exc.code or 400, exc.description)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INVALID_REQUEST", 400, str(exc))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
