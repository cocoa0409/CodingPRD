"""Emerging-Contaminant Sampling & Treatment Compliance API.

Boots completely empty on every invocation: the in-memory store seeds nothing.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.determinations import bp as determinations_bp
from routes.finance import bp as finance_bp
from routes.registry import bp as registry_bp
from routes.sampling import bp as sampling_bp
from routes.treatment import bp as treatment_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(registry_bp)
    app.register_blueprint(sampling_bp)
    app.register_blueprint(determinations_bp)
    app.register_blueprint(treatment_bp)
    app.register_blueprint(finance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", "No such route.", 404)
        if status == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this route.", 405
            )
        if status == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be understood.", 422
            )
        return error_response("ERR_INTERNAL", exc.description or "Unhandled error.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unhandled server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
