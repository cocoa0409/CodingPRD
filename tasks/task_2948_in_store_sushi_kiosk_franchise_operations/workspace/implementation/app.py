"""In-Store Sushi Kiosk Franchise Operations -- Flask entry point.

Storage is in-memory only (see db.py). Nothing is seeded: every entity is
created through the declared endpoints, and the process is expected to be
restarted between tests.
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response
from routes import audits, chefs, clock, fish, kiosks, packs, plans, rice
from routes import settlement, stores

API_PREFIX = "/kiosk-ops"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in (clock.bp, stores.bp, chefs.bp, kiosks.bp, plans.bp,
                      rice.bp, fish.bp, packs.bp, settlement.bp, audits.bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            message = "The requested resource does not exist."
        elif status == 405:
            message = "The HTTP method is not allowed for this path."
        else:
            message = exc.description or "The request could not be processed."
        return error_response("ERR_INVALID_REQUEST", message, status)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST",
                              "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
