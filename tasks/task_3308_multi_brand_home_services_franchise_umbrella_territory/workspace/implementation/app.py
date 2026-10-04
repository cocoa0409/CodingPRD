"""Multi-Brand Home Services Franchise Umbrella & Territory Administration API.

In-memory only: every entity lives in a process-local dict and nothing is ever
seeded, so a fresh process starts with an empty world and a logical clock
reading 2026-09-01T00:00:00Z.
"""
import os
import traceback

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from serialize import DecimalJSONProvider
from routes.accounts import bp as accounts_bp
from routes.agreements import bp as agreements_bp
from routes.audits import bp as audits_bp
from routes.leads import bp as leads_bp
from routes.ops import bp as ops_bp
from routes.portfolio import bp as portfolio_bp
from routes.referrals import bp as referrals_bp
from routes.statements import bp as statements_bp
from routes.territories import bp as territories_bp
from routes.transfers import bp as transfers_bp
from routes.work_orders import bp as work_orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json = DecimalJSONProvider(app)

    app.register_blueprint(portfolio_bp)
    app.register_blueprint(territories_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(leads_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(audits_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The requested route does not exist.")), 404

    @app.errorhandler(405)
    def _bad_method(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "That HTTP method is not allowed on this route.")), 405

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        code = getattr(exc, "code", None)
        if code == 404:
            return _not_found(exc)
        if code == 405:
            return _bad_method(exc)
        if isinstance(code, int) and 400 <= code < 500:
            return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), code
        traceback.print_exc()
        return jsonify(error_body("ERR_INTERNAL", "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)