"""Design System Governance API -- entry point.

Storage is in-memory and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded. Every row is created through the API.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from responses import error as error_response
from routes import (clock, components, deprecation, grants, proposals, releases,
                    teams, tokens)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(teams.bp)
    app.register_blueprint(tokens.bp)
    app.register_blueprint(components.bp)
    app.register_blueprint(proposals.bp)
    app.register_blueprint(releases.bp)
    app.register_blueprint(deprecation.bp)
    app.register_blueprint(grants.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return error_response(errors.ERR_INVALID_REQUEST,
                                  "The requested resource path does not exist.", 404)
        if status == 405:
            return error_response(errors.ERR_INVALID_REQUEST,
                                  "The HTTP method is not allowed on this path.", 405)
        if status == 400:
            return error_response(errors.ERR_INVALID_REQUEST,
                                  "The request could not be understood.", 400)
        return error_response(errors.ERR_INVALID_REQUEST,
                              exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response(errors.ERR_INVALID_REQUEST,
                              "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
