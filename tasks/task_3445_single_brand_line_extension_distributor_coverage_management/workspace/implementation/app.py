"""Brand Line Coverage API — Flask entrypoint.

The logical-clock endpoint lives OUTSIDE the /brand-ops prefix; every other
route is registered by the per-domain blueprints under /brand-ops.
"""
import os

from flask import Flask

from core import ApiError, ERROR_HTTP, err, err_response, fmt_dt, ok, set_clock, now, cmp_sec
from sweep import run_sweep
from validate import as_datetime, authenticate, authorize, body, need


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_brands
    import routes_secret
    import routes_markets
    import routes_distribution
    import routes_pricing
    import routes_promo
    import routes_defense

    for mod in (
        routes_brands, routes_secret, routes_markets, routes_distribution,
        routes_pricing, routes_promo, routes_defense,
    ):
        app.register_blueprint(mod.bp)

    # ------------------------------------------------------------------
    # Platform logical clock (mounted outside /brand-ops)
    # ------------------------------------------------------------------
    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        _, role = authenticate()
        authorize(role, ["PlatformAdmin"])
        b = body()
        target = as_datetime(need(b, "to_iso8601"), "to_iso8601")
        if cmp_sec(target, now()) <= 0:
            err("ERR_CLOCK_REGRESSION", "The clock must strictly advance")
        set_clock(target)
        run_sweep()
        return ok({"current_utc": fmt_dt(now())})

    # ------------------------------------------------------------------
    # Error handlers: everything answers in the standard envelope
    # ------------------------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return err_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err_response("ERR_INTERNAL", 500, "Unexpected error: %s" % e)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
