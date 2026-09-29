"""Incentive Travel / Corporate Event Program API.

Storage is an in-memory dict store that starts completely empty on every
boot, so the harness can relaunch this process before each test.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import CATALOGUE, ApiError
from routes import (activities, clock, contracts, destinations, milestones,
                    programs, qualifiers, registrations, signups, tax_reports,
                    tiers)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (programs, tiers, qualifiers, destinations, contracts,
                   milestones, registrations, activities, signups,
                   tax_reports, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_PROGRAM_NOT_FOUND",
                                  CATALOGUE["ERR_PROGRAM_NOT_FOUND"],
                                  "The requested resource does not exist.")
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  CATALOGUE["ERR_INVALID_REQUEST"],
                                  "The method is not allowed for this path.")
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  CATALOGUE["ERR_INVALID_REQUEST"],
                                  "The request could not be parsed.")
        return error_response("ERR_INVALID_REQUEST",
                              CATALOGUE["ERR_INVALID_REQUEST"],
                              exc.description or "Request failed.")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
