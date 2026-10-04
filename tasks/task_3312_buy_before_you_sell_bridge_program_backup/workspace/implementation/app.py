"""Entry point for the Buy-Before-You-Sell Bridge Program API.

The store starts empty on every boot: nothing is seeded, preloaded or hardcoded
here or in any module initialiser.  Every entity a caller needs is created
through the declared API surface, and because the test harness relaunches this
process before each individual test, no state can carry over between runs.
"""

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ERR_INVALID_REQUEST, ApiError
from response import error_response
from routes import (
    advances,
    agents,
    carrying,
    households,
    listings,
    loans,
    offers,
    partners,
    programs,
    qualifications,
    settlements,
)

BLUEPRINTS = (
    households.bp,
    agents.bp,
    qualifications.bp,
    programs.bp,
    loans.bp,
    advances.bp,
    carrying.bp,
    offers.bp,
    listings.bp,
    partners.bp,
    settlements.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        body, status = error_response(error)
        return jsonify(body), status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        api_error = ApiError(ERR_INVALID_REQUEST, error.description or error.name)
        body, status = error_response(api_error)
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - safety net
        api_error = ApiError(ERR_INVALID_REQUEST, "The request could not be processed.")
        body, status = error_response(api_error)
        return jsonify(body), status

    @app.route("/knock/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)