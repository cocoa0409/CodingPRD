"""Entry point: Flask app, clock endpoint, scoped lists, error handling."""
import os

from flask import Flask

from core import (ApiError, STORE, auth, body, err_resp, get_repair_order, install_lazy_hook,
                  ok_obj, paginate, pagination, parse_iso, require, ser_entitlement,
                  ser_follow_up, ser_verification, set_logical_now)
import parties
import network
import appointments
import orders
import ops


def create_app():
    app = Flask(__name__)

    app.register_blueprint(parties.bp, url_prefix="/repair")
    app.register_blueprint(network.bp, url_prefix="/repair")
    app.register_blueprint(appointments.bp, url_prefix="/repair")
    app.register_blueprint(orders.bp, url_prefix="/repair")
    app.register_blueprint(ops.bp, url_prefix="/repair")

    install_lazy_hook(app)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return err_resp(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return err_resp("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return err_resp("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(500)
    def _internal(e):
        return err_resp("ERR_INVALID_REQUEST", "Internal server error", 500)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    @app.post("/repair/_clock/set_current_utc")
    def set_clock():
        auth({"PlatformAdmin"})
        data = require(body(), "to_iso8601")
        dt = parse_iso(data["to_iso8601"])
        set_logical_now(dt)
        from core import iso_z, logical_now
        return ok_obj({"current_utc": iso_z(logical_now())})

    # ------------------------------------------------------------------
    # Scoped list endpoints (nested under repair orders)
    # ------------------------------------------------------------------

    @app.get("/repair/repair-orders/<oid>/coverage-entitlements")
    def order_entitlements(oid):
        auth({"Customer", "Technician", "CustomerService"})
        order = get_repair_order(oid)
        limit, offset = pagination()
        items = [ser_entitlement(e) for e in STORE["coverage_entitlements"].values()
                 if e["repair_order_id"] == order["id"]]
        return paginate(items, limit, offset)

    @app.get("/repair/repair-orders/<oid>/security-verifications")
    def order_verifications(oid):
        auth({"Technician", "CustomerService"})
        order = get_repair_order(oid)
        limit, offset = pagination()
        items = [ser_verification(v) for v in STORE["security_verifications"].values()
                 if v["repair_order_id"] == order["id"]]
        return paginate(items, limit, offset)

    @app.get("/repair/repair-orders/<oid>/quality-follow-ups")
    def order_follow_ups(oid):
        auth({"Customer", "CustomerService"})
        order = get_repair_order(oid)
        limit, offset = pagination()
        items = [ser_follow_up(f) for f in STORE["quality_follow_ups"].values()
                 if f["repair_order_id"] == order["id"]]
        return paginate(items, limit, offset)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
