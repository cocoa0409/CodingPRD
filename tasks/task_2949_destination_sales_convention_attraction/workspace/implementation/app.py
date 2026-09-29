"""Destination Sales & Convention Attraction API.

A single Flask process holding the entire system in memory: the store starts
completely empty on every boot and no entity data is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import api_error_response, error_response
from routes.bids import bp as bids_bp
from routes.clock import bp as clock_bp
from routes.commitments import bp as commitments_bp
from routes.estimates import bp as estimates_bp
from routes.funds import bp as funds_bp
from routes.inventory import bp as inventory_bp
from routes.opportunities import bp as opportunities_bp
from routes.reports import bp as reports_bp
from routes.servicing import bp as servicing_bp
from routes.space_holds import bp as space_holds_bp

BLUEPRINTS = (
    clock_bp,
    inventory_bp,
    opportunities_bp,
    space_holds_bp,
    commitments_bp,
    bids_bp,
    funds_bp,
    estimates_bp,
    servicing_bp,
    reports_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return api_error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "That method is not allowed on this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        if err.code == 400:
            return error_response("ERR_VALIDATION",
                                  "The request could not be parsed.", 400)
        return error_response("ERR_INTERNAL", "Unexpected server condition.",
                              err.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", "Unexpected server condition.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
