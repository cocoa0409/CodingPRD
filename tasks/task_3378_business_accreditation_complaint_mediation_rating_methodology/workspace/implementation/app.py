"""Entry point: Flask app assembly, error handlers, blueprint registration.

The in-memory store lives in module scope (db.STORE); every fresh process
boots with an empty store and the logical clock at its pinned start.
"""
import os

from flask import Flask

import web
from errors import ApiError
from routes_accreditation import bp as accreditation_bp
from routes_complaints import bp as complaints_bp
from routes_core import bp as core_bp
from routes_escalation import bp as escalation_bp
from routes_rating import bp as rating_bp
from routes_surveillance import bp as surveillance_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(core_bp)
    app.register_blueprint(accreditation_bp)
    app.register_blueprint(complaints_bp)
    app.register_blueprint(escalation_bp)
    app.register_blueprint(rating_bp)
    app.register_blueprint(surveillance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return web.error_response(error)

    @app.errorhandler(404)
    def handle_not_found(_error):
        # an unmatched route: no domain resource id was resolved
        return web.error_response(
            ApiError("ERR_INVALID_REQUEST", "route not found")
        )[0], 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        body = {
            "meta": {
                "api_request_id": "req_unknown",
                "api_request_timestamp": None,
            },
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "method not allowed",
            },
        }
        from flask import jsonify

        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        app.logger.exception("unexpected error: %s", error)
        body = {
            "meta": {
                "api_request_id": "req_unknown",
                "api_request_timestamp": None,
            },
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(error)},
        }
        from flask import jsonify

        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
