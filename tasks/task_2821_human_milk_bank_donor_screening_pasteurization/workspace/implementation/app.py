"""Flask application for the Human Milk Bank Screening Pasteurization API.

Everything is mounted under the /milk-bank prefix (PRD 1).  Storage is entirely
in-memory: the process starts with an empty bank and a logical clock pinned to
2026-08-01T00:00:00Z, and nothing is ever written to disk.

Cross-cutting concerns live in one place each:
  * errors.py      - the 49-code catalogue and the ApiError exception
  * envelope.py    - the PRD 2.2 success / error envelope and PRD 2.3 pagination
  * auth.py        - checks 1-4 of the global rejection order
  * validate.py    - checks 6-7 (shape then range)
  * store.py       - the in-memory tables, the logical clock, version discipline
"""

import os

from flask import Flask, request

import domain_bubble
import routes_donors
import routes_lots
import routes_pools
import routes_rx
import routes_runs
import routes_shipments
from envelope import error_response
from errors import ApiError
from store import db

PREFIX = "/milk-bank"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_donors, routes_shipments, routes_pools, routes_runs,
                   routes_lots, routes_rx):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.before_request
    def _open_mutation_window():
        db.begin()

    @app.after_request
    def _close_mutation_window(response):
        # The two bubble-up rules of PRD 2.8 run at the end of every request
        # that could satisfy them, never triggered by a single endpoint.
        try:
            if request.method != "GET" and response.status_code < 400:
                domain_bubble.bubble_up()
        finally:
            db.commit()
        return response

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "No such resource.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "That method is not defined for this path.", 404)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST",
                              "The request could not be processed: %s" % exc, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
