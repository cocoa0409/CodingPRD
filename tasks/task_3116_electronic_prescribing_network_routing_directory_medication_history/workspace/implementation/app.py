"""Entry point: app factory, error handlers, route registration.

The store starts empty on every boot — nothing is seeded, preloaded or
hardcoded here. Every entity a caller observes was constructed through a
declared endpoint during the same process lifetime.
"""

import os
import traceback

from flask import Flask, jsonify, request

import clock
import db
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    db.reset()

    import routes.benefit_checks as benefit_checks_routes
    import routes.directory_endpoints as directory_endpoints_routes
    import routes.patients as patients_routes
    import routes.participants as participants_routes
    import routes.prescriptions as prescriptions_routes
    import routes.test_driving as test_driving_routes
    import routes.transaction_fees as transaction_fees_routes

    for module in (
        participants_routes,
        directory_endpoints_routes,
        patients_routes,
        prescriptions_routes,
        benefit_checks_routes,
        transaction_fees_routes,
        test_driving_routes,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = {
            "meta": {
                "api_request_id": clock.new_request_id(),
                "api_request_timestamp": clock.now_iso(),
            },
            "response_type": "error",
            "data": {"error_id": exc.error_id, "message": exc.message},
        }
        if clock.debug_enabled():
            print(f"[error] {exc.error_id} {request.method} {request.path}", flush=True)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        # The request body is still parsed so that a missing required field is reported
        # as such rather than as a routing failure.
        request.get_json(silent=True)
        body = {
            "meta": {
                "api_request_id": clock.new_request_id(),
                "api_request_timestamp": clock.now_iso(),
            },
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": f"No route is declared for {request.method} {request.path}.",
            },
        }
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        request.get_json(silent=True)
        body = {
            "meta": {
                "api_request_id": clock.new_request_id(),
                "api_request_timestamp": clock.now_iso(),
            },
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": f"The method {request.method} is not declared for {request.path}.",
            },
        }
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if clock.debug_enabled():
            traceback.print_exc()
        body = {
            "meta": {
                "api_request_id": clock.new_request_id(),
                "api_request_timestamp": clock.now_iso(),
            },
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": f"The request could not be processed: {exc.__class__.__name__}.",
            },
        }
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)