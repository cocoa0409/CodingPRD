import os
from flask import Flask

import store
from envelope import error_envelope
from errors import ApiError

from routes_cases import bp as cases_bp
from routes_members import bp as members_bp
from routes_addresses import bp as addresses_bp
from routes_deployments import bp as deployments_bp
from routes_claims import bp as claims_bp
from routes_products import bp as products_bp
from routes_households import bp as households_bp
from routes_clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (cases_bp, members_bp, addresses_bp, deployments_bp,
               claims_bp, products_bp, households_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_envelope(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_envelope("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(Exception)
    def _generic(e):
        # Never leak stack traces; return a stable 400 envelope.
        return error_envelope("ERR_INVALID_REQUEST", str(e) or "bad request", 400)

    @app.before_request
    def _locked():
        store.LOCK.acquire()

    @app.teardown_request
    def _unlock(exc):
        try:
            store.LOCK.release()
        except RuntimeError:
            pass

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
