"""Crane Rigging Lift API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_clock
import routes_gear
import routes_invoice
import routes_permit
import routes_plan
import routes_review
import routes_setup
import routes_standby


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (routes_setup, routes_gear, routes_plan, routes_review, routes_permit,
                   routes_standby, routes_invoice, routes_clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return respond_error("ERR_INVALID_REQUEST", "No such route.", 404)
        if status == 405:
            return respond_error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)
        if status == 400:
            return respond_error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return respond_error("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return respond_error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
