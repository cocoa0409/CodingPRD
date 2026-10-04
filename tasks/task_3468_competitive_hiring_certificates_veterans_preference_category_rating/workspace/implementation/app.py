"""Application entry point: Flask app factory, blueprint registration,
error handlers. In-memory store starts empty on every boot (no seeding)."""
import os

from flask import Flask

import routes_announcements
import routes_applicants
import routes_applications
import routes_assessments
import routes_appeals
import routes_certificates
import routes_clock
import routes_offers
import routes_passovers
import routes_series
from envelope import error_body
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in (
        routes_series.bp,
        routes_announcements.bp,
        routes_applicants.bp,
        routes_applications.bp,
        routes_assessments.bp,
        routes_certificates.bp,
        routes_passovers.bp,
        routes_offers.bp,
        routes_appeals.bp,
        routes_clock.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_body("ERR_NOT_FOUND", "resource not found")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
