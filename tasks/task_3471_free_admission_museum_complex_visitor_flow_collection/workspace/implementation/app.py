"""Museum Campus Collections API — Flask entry point.

Mounts every business blueprint (all paths live under /campus) plus the
unprefixed test-driving logical-clock endpoint POST /_clock/set_current_utc.
The store starts empty on every boot; no entities are seeded anywhere.
"""

import os

from flask import Flask

import db
import routes_assignments
import routes_exhibitions
import routes_expenditures
import routes_funds
import routes_loans
import routes_members
import routes_museums
import routes_objects
import routes_passes
import routes_programs
import routes_reports
import routes_research
import routes_reservations
import routes_reviews
import routes_tickets
import util
from envelope import error as error_envelope
from envelope import success
from errors import ApiError, fail
from middleware import auth, require_role

BLUEPRINTS = (
    routes_museums.bp,
    routes_passes.bp,
    routes_members.bp,
    routes_exhibitions.bp,
    routes_tickets.bp,
    routes_programs.bp,
    routes_assignments.bp,
    routes_reservations.bp,
    routes_objects.bp,
    routes_loans.bp,
    routes_reports.bp,
    routes_reviews.bp,
    routes_funds.bp,
    routes_expenditures.bp,
    routes_research.bp,
)


def create_app():
    app = Flask(__name__)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        """Set the server logical clock (PlatformAdmin only). Responds with the
        echo of the supplied current_utc."""
        _uid, role = auth()
        require_role(role, ["PlatformAdmin"])
        b = util.body()
        raw = util.req_str(b, "current_utc")
        parsed = util.parse_datetime(raw)
        if parsed is None:
            fail("ERR_INVALID_REQUEST", "current_utc must be a valid ISO 8601 UTC datetime")
        db.set_clock(raw, parsed)
        return success({"current_utc": raw})

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_envelope(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_envelope(ApiError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_envelope(ApiError("ERR_NOT_FOUND", "Method not allowed", 405))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
