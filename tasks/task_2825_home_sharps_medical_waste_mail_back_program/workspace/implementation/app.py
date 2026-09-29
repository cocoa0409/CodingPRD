"""Home Sharps Mail-Back Program API.

Python + Flask, in-memory storage only. The store is empty on every boot: no
entity is ever seeded, preloaded or hardcoded, and the logical clock always
starts at exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.autoship import bp as autoship_bp
from routes.catalogue import bp as catalogue_bp
from routes.certificates import bp as certificates_bp
from routes.enrollments import bp as enrollments_bp
from routes.kitops import bp as kitops_bp
from routes.patients import bp as patients_bp
from routes.shipments import bp as shipments_bp
from routes.sponsors import bp as sponsors_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(catalogue_bp)
    app.register_blueprint(sponsors_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(kitops_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(autoship_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(response.error_body(error.error_id, error.message)), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
            message = "No route matches the requested path."
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
            message = "The HTTP method is not allowed for this path."
        elif status == 400:
            error_id = "ERR_INVALID_REQUEST"
            message = "The request could not be parsed."
        else:
            error_id = "ERR_INTERNAL"
            message = error.description or "Request failed."
        return jsonify(response.error_body(error_id, message)), status

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return (
            jsonify(response.error_body("ERR_INTERNAL", "Unexpected server error: %s" % error)),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
