"""App factory: blueprint registration, error handlers, response envelope,
the logical-clock test-driving endpoint, and the server entrypoint."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import clock
from errors import ApiError
from rbac import auth
from validators import body, f_str, envelope_ok, envelope_error

import regulation_standards
import engine_families
import aftertreatment_specs
import test_runs
import fleets_units
import telematics
import service_network
import warranty
import campaigns
import work_orders
import reman
import in_use_compliance

BLUEPRINTS = (
    regulation_standards.bp,
    engine_families.bp,
    aftertreatment_specs.bp,
    test_runs.bp,
    fleets_units.bp,
    telematics.bp,
    service_network.bp,
    warranty.bp,
    campaigns.bp,
    work_orders.bp,
    reman.bp,
    in_use_compliance.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return envelope_error(e)

    @app.errorhandler(HTTPException)
    def _http_error(e):
        if e.code == 404:
            err = ApiError("ERR_NOT_FOUND", 404, "Resource not found")
        elif e.code == 405:
            err = ApiError("ERR_INVALID_REQUEST", 400, "Method not allowed")
        else:
            err = ApiError("ERR_INVALID_REQUEST", e.code or 400, e.name)
        return envelope_error(err)

    @app.errorhandler(Exception)
    def _unexpected(e):
        import traceback
        traceback.print_exc()
        return envelope_error(ApiError("ERR_INVALID_REQUEST", 500, str(e)))

    # MODULE _system (test-driving): set the logical clock (PRD §2.4)
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        auth(("PlatformAdmin",))
        b = body()
        raw = f_str(b, "current_utc")
        try:
            dt = clock.parse_dt(raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "current_utc must be an ISO 8601 datetime")
        clock.set_now(dt)
        return envelope_ok({"current_utc": raw}, 200)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
