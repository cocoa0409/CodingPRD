"""Endangered Species Consultation & Habitat Conservation Planning API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_action
import routes_consult
import routes_permit
import routes_plan
import routes_read
import routes_species
from errors import ApiError


class _Generic(object):
    """An envelope-shaped stand-in for framework-level failures."""

    def __init__(self, error_id, http_status, message):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_species.bp)
    app.register_blueprint(routes_action.bp)
    app.register_blueprint(routes_consult.bp)
    app.register_blueprint(routes_plan.bp)
    app.register_blueprint(routes_permit.bp)
    app.register_blueprint(routes_read.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.failure(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        status = err.code or 500
        if status == 404:
            return envelope.failure(
                _Generic("ERR_INVALID_REQUEST", 404, "No such resource path.")
            )
        if status == 405:
            return envelope.failure(
                _Generic(
                    "ERR_INVALID_REQUEST", 405, "Method not allowed for this path."
                )
            )
        return envelope.failure(
            _Generic("ERR_INVALID_REQUEST", status, err.description or "Bad request.")
        )

    @app.errorhandler(Exception)
    def _unhandled(err):
        return envelope.failure(
            _Generic("ERR_INVALID_REQUEST", 500, "Unexpected server failure.")
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
