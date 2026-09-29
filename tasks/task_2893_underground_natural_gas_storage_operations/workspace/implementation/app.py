"""Underground Gas Storage Operations API — entry point.

The store is empty on every boot: nothing is seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import commercial, compressors, emergencies, fields, nominations, reports, tickets, wells


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (fields, wells, compressors, commercial, nominations,
                   tickets, emergencies, reports):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "No such route: %s." % exc.description, 400)
        if exc.code == 405:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed on this route.", 400)
        if exc.code in (400, 415):
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed as JSON.", 400)
        return envelope.error_response("ERR_INVALID_REQUEST", str(exc.description), exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return envelope.error_response("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
