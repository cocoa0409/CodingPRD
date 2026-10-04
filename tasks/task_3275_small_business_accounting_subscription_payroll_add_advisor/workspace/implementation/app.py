"""Flask entry point: error handlers + route registration."""
import os
from flask import Flask
import db
from errors import ApiError, err


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body, status = err(e.error_id, e.http_status, e.message)
        return body, status

    @app.errorhandler(404)
    def handle_404(e):
        body, status = err("ERR_NOT_FOUND", 404, "Not found")
        return body, status

    @app.errorhandler(405)
    def handle_405(e):
        body, status = err("ERR_NOT_FOUND", 404, "Not found")
        return body, status

    @app.errorhandler(Exception)
    def handle_generic(e):
        body, status = err("ERR_INVALID_REQUEST", 400, str(e))
        return body, status

    from routes.sim import bp as sim_bp
    from routes.plans import bp as plans_bp
    from routes.firms import bp as firms_bp
    from routes.companies import bp as companies_bp
    from routes.users import bp as users_bp
    from routes.subscriptions import bp as subs_bp
    from routes.payroll import bp as payroll_bp
    from routes.invoices import bp as invoices_bp
    from routes.bank import bp as bank_bp
    from routes.rules import bp as rules_bp
    from routes.recons import bp as recons_bp
    from routes.integrations import bp as integrations_bp
    from routes.migrations import bp as migrations_bp
    from routes.transfers import bp as transfers_bp
    from routes.grants import bp as grants_bp
    from routes.exports import bp as exports_bp
    from routes.flat import bp as flat_bp

    for bp in (sim_bp, plans_bp, firms_bp, companies_bp, users_bp, subs_bp,
               payroll_bp, invoices_bp, bank_bp, rules_bp, recons_bp,
               integrations_bp, migrations_bp, transfers_bp, grants_bp,
               exports_bp, flat_bp):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
