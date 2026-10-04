"""Application entry point: Flask app, error handlers, blueprint registration,
and the platform-level clock endpoint (which lives OUTSIDE the /msha prefix).

PRD section 4: POST /_clock/set_current_utc sets the logical clock; advancing
it at or past an APPROVED mine plan's next_revision_due_at flips that plan to
REVISION_DUE.
"""
import os

from flask import Flask

import clock
import store
from constants import ROLE_MSHA_ADMIN
from envelope import error_body, ok_object
from errors import ApiError, ERR_INTERNAL, ERR_NOT_FOUND
from routes_accidents import bp as accidents_bp
from routes_citations import bp as citations_bp
from routes_contests import bp as contests_bp
from routes_cycles import bp as cycles_bp
from routes_idos import bp as idos_bp
from routes_inspections import bp as inspections_bp
from routes_plans import bp as plans_bp
from routes_pov import bp as pov_bp
from routes_registry import bp as registry_bp
from validate import parse_body, require_roles


def create_app():
    app = Flask(__name__)

    app.register_blueprint(registry_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(citations_bp)
    app.register_blueprint(idos_bp)
    app.register_blueprint(contests_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(accidents_bp)
    app.register_blueprint(pov_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_body(error)

    @app.errorhandler(404)
    def handle_not_found(_error):
        return error_body(ApiError(ERR_NOT_FOUND, "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return error_body(ApiError(ERR_NOT_FOUND, "resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return error_body(error)
        return error_body(ApiError(ERR_INTERNAL, "internal error"))

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        require_roles(ROLE_MSHA_ADMIN)
        body = parse_body({"current_utc": ("datetime", True)})
        clock.set_now(body["current_utc"])
        current = clock.now()
        # Scheduled flip: APPROVED plans whose revision horizon has been reached
        # become REVISION_DUE (and a REVISION_DUE plan no longer satisfies the
        # inspection-completion plan gate).
        for plan in store.plans.values():
            if (
                plan["status"] == "APPROVED"
                and plan["next_revision_due_at"] is not None
                and plan["next_revision_due_at"] <= current
            ):
                plan["status"] = "REVISION_DUE"
                store.touch(plan)
        return ok_object({"current_utc": clock.render_domain(current)})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
