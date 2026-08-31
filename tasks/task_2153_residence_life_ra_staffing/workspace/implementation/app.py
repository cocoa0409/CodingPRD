"""Residence Life & RA Staffing API — application entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import responses
from errors import ApiError
from routes import (
    applications, breaks, conduct, damage, duty, housing, programs, reads,
    roomchange,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (reads, housing, applications, duty, conduct, damage,
                   roomchange, programs, breaks):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return responses.error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return responses.error_body(
            "ERR_INVALID_REQUEST", "The requested resource does not exist."
        ), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return responses.error_body(
            "ERR_INVALID_REQUEST", "Method not allowed for this resource."
        ), 405

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return responses.error_body(
            "ERR_INVALID_REQUEST", exc.description or "Bad request."
        ), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return responses.error_body(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc
        ), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
