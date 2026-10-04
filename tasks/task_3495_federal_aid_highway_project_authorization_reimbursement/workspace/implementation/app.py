"""Federal-Aid Highway Project Authorization & Reimbursement API.

Entry point: Flask app assembly, blueprint registration, and error handlers.
The store is in-memory and empty at every boot (no seeding); all state is
built through the declared API surface.
"""
import os

from flask import Flask

from errors import ApiError, err
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_audits import bp as audits_bp
    from routes_authorizations import bp as authorizations_bp
    from routes_bidding import bp as bidding_bp
    from routes_change_orders import bp as change_orders_bp
    from routes_clearances import bp as clearances_bp
    from routes_funding import bp as funding_bp
    from routes_platform import bp as platform_bp
    from routes_projects import bp as projects_bp
    from routes_stips import bp as stips_bp
    from routes_vouchers import bp as vouchers_bp

    app.register_blueprint(platform_bp)
    app.register_blueprint(funding_bp)
    app.register_blueprint(stips_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(bidding_bp)
    app.register_blueprint(clearances_bp)
    app.register_blueprint(authorizations_bp)
    app.register_blueprint(vouchers_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(audits_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(ApiError("ERR_INTERNAL", 500, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
