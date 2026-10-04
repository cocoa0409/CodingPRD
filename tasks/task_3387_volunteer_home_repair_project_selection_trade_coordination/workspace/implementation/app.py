"""Volunteer Home Repair API — Flask entry point.

Mounts the /rebuild route modules plus the /_clock test-driving endpoint.
The in-memory store (db.py) starts empty on every boot.
"""
import os

from flask import Flask

from errors import ApiError, E_INVALID_REQUEST
from helpers import error_envelope

import routes_cycles
import routes_sponsors
import routes_applications
import routes_assessments
import routes_projects
import routes_events
import routes_volunteers
import routes_contractors
import routes_work_orders
import routes_materials
import routes_warranty


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        routes_cycles, routes_sponsors, routes_applications,
        routes_assessments, routes_projects, routes_events,
        routes_volunteers, routes_contractors, routes_work_orders,
        routes_materials, routes_warranty,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_envelope(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_envelope(E_INVALID_REQUEST, 404, "route not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_envelope(E_INVALID_REQUEST, 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_envelope(E_INVALID_REQUEST, 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
