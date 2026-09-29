"""Essential Air Service Subsidy Program -- Flask application entry point.

State lives entirely in process memory (see db.py). Nothing is seeded: every
entity in the system is created through the API.
"""

import os

from flask import Flask

import errors
import response
from routes import (agreements, periods, petitions, proposals, reference,
                    renegotiations, solicitations)

API_PREFIX = "/eas"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(reference.clock_bp, url_prefix="/_clock")
    app.register_blueprint(reference.bp, url_prefix=API_PREFIX)
    app.register_blueprint(solicitations.bp, url_prefix=API_PREFIX)
    app.register_blueprint(proposals.bp, url_prefix=API_PREFIX)
    app.register_blueprint(agreements.bp, url_prefix=API_PREFIX)
    app.register_blueprint(periods.bp, url_prefix=API_PREFIX)
    app.register_blueprint(petitions.bp, url_prefix=API_PREFIX)
    app.register_blueprint(renegotiations.bp, url_prefix=API_PREFIX)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_missing_route(exc):
        return response.error_response(
            errors.ERR_INVALID_REQUEST, "No such resource path.", 404)

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return response.error_response(
            errors.ERR_INVALID_REQUEST,
            "The HTTP method is not allowed on this path.", 405)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return response.error_response(
            errors.ERR_INVALID_REQUEST, "The request could not be parsed.", 400)

    @app.errorhandler(415)
    def handle_bad_media_type(exc):
        return response.error_response(
            errors.ERR_INVALID_REQUEST, "The request body must be JSON.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return response.error_response(exc.error_id, exc.message,
                                           exc.http_status)
        app.logger.exception("unhandled error")
        return response.error_response(
            errors.ERR_INVALID_REQUEST,
            "The request could not be processed: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False,
            use_reloader=False)
