"""Surcharge & Cash Discount Program Compliance API -- entry point.

All state lives in process memory (see store.py); a fresh process therefore
starts with an empty store and nothing is seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import routes_artifacts
import routes_complaints
import routes_jurisdictions
import routes_merchants
import routes_programs
import routes_rates
import routes_refunds
import routes_terminals
import routes_transactions


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_jurisdictions.bp)
    app.register_blueprint(routes_merchants.bp)
    app.register_blueprint(routes_programs.bp)
    app.register_blueprint(routes_rates.bp)
    app.register_blueprint(routes_artifacts.bp)
    app.register_blueprint(routes_terminals.bp)
    app.register_blueprint(routes_transactions.bp)
    app.register_blueprint(routes_complaints.bp)
    app.register_blueprint(routes_refunds.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", err.description,
                                       http_status=err.code or 400))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "Unhandled server error: %s" % err,
                                       http_status=500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
