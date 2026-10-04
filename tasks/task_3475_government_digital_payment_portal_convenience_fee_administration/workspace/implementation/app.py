"""Government Digital Payment Portal — entry point.

In-memory Flask implementation; boots clean from a fresh process with an
empty store on every invocation. Listens on 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_accounts
import routes_agencies
import routes_attestations
import routes_authorizations
import routes_batches
import routes_chargebacks
import routes_clock
import routes_payers
import routes_quotes
import routes_refunds
import routes_selffunding
import routes_services
import routes_tiers
import routes_transactions
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_clock,
        routes_agencies,
        routes_accounts,
        routes_tiers,
        routes_attestations,
        routes_services,
        routes_authorizations,
        routes_payers,
        routes_quotes,
        routes_transactions,
        routes_batches,
        routes_refunds,
        routes_chargebacks,
        routes_selffunding,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return envelope.err(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def _not_found(e):
        return envelope.err("ERR_NOT_FOUND", "The requested path does not exist", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return envelope.err(
            "ERR_METHOD_NOT_ALLOWED_ON_PATH",
            "The method is not supported on this path",
            405,
        )

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, HTTPException):
            return envelope.err("ERR_HTTP", str(e), e.code or 500)
        return envelope.err("ERR_INTERNAL", "Internal server error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
