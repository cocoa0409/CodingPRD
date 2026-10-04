"""Medicare Enrollment API — entry point.

Mounts 35 business endpoints under /medicare plus the two unprefixed
test-driving endpoints (/_clock/set_current_utc, /_ops/run_monthly_cycle).
"""
from __future__ import annotations

import os

from flask import Flask, jsonify

from envelope import error_payload
from errors import ApiError


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_appeals
    import routes_beneficiaries
    import routes_determinations
    import routes_elections
    import routes_employer
    import routes_enrollments
    import routes_invoices
    import routes_platform
    import routes_rates
    import routes_relief
    import routes_tax
    import routes_withholding

    for module in (routes_beneficiaries, routes_rates, routes_enrollments,
                   routes_employer, routes_tax, routes_determinations,
                   routes_appeals, routes_withholding, routes_invoices,
                   routes_elections, routes_relief, routes_platform):
        module.register(app)

    @app.errorhandler(ApiError)
    def _api_error(err: ApiError):
        return jsonify(error_payload(err.error_id, err.message)), \
            err.http_status

    @app.errorhandler(404)
    def _not_found(_err):
        return jsonify(error_payload("ERR_NOT_FOUND",
                                     "No such resource")), 404

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return jsonify(error_payload("ERR_METHOD_NOT_ALLOWED",
                                     "Method not allowed")), 405

    @app.errorhandler(Exception)
    def _unhandled(err: Exception):
        return jsonify(error_payload("ERR_INTERNAL", str(err))), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
