"""Certificate of Need Review API — Flask application factory and entry point.

Storage is entirely in memory and starts empty on every boot: no seeding, no files.
"""

import os
from decimal import Decimal

from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

import envelope
import r_appeals
import r_applications
import r_certificates
import r_config
import r_cycles
import r_loi
import r_participation
import r_scoring
from errors import ApiError

BLUEPRINTS = (
    r_config.bp,
    r_cycles.bp,
    r_loi.bp,
    r_applications.bp,
    r_participation.bp,
    r_scoring.bp,
    r_certificates.bp,
    r_appeals.bp,
)


class NumberFriendlyProvider(DefaultJSONProvider):
    """Never emit a Decimal as a JSON string: money and rates are always numbers."""

    sort_keys = False

    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            if value == value.to_integral_value():
                return int(value)
            return float(value)
        return DefaultJSONProvider.default(value)


def create_app():
    app = Flask(__name__)
    app.json = NumberFriendlyProvider(app)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(envelope.error_body(error.error_id, error.message)), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            error_id = "ERR_INVALID_REQUEST"
            status = 404
        elif error.code == 405:
            error_id = "ERR_INVALID_REQUEST"
            status = 405
        else:
            error_id = "ERR_INVALID_REQUEST"
            status = error.code or 400
        message = error.description or "The request could not be processed."
        return jsonify(envelope.error_body(error_id, message)), status

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        body = envelope.error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % error)
        return jsonify(body), 500

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
