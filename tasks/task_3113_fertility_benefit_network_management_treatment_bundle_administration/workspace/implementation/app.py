"""Fertility Benefit Network API — application entry point.

The store lives entirely in process memory and starts empty: nothing is
seeded, preloaded or hardcoded at startup.  Every entity a caller observes
was constructed through a declared endpoint.
"""

import os

from flask import Flask

from bp import api
from errors import APIError
from response import error_response

# Importing the route package registers every endpoint on the shared blueprint.
import routes  # noqa: F401


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(api)

    @app.errorhandler(APIError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response("ERR_INVALID_REQUEST", "The method is not allowed for this resource.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))