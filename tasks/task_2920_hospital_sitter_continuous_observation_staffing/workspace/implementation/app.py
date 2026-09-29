"""Hospital Sitter & Continuous Observation Staffing API.

Entry point: registers every route blueprint and renders the standard response
envelope for errors. Storage is process-local and in memory; the store is empty
on every boot and nothing is ever seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_assignments
import routes_core
import routes_events
import routes_orders
import routes_reads
import routes_stations
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reads.bp)
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_assignments.bp)
    app.register_blueprint(routes_stations.bp)
    app.register_blueprint(routes_events.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", "No such resource path.", 404)
        if status == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path.", 405
            )
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_response("ERR_INTERNAL", exc.name, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
