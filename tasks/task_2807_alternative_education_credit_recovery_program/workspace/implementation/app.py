"""Alternative Education & Credit Recovery API -- application entrypoint.

All state lives in process memory (see store.py); nothing is persisted, so a
fresh process starts from an empty district with the logical clock parked at
2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, jsonify

import routes_award
import routes_enrollment
import routes_placement
import routes_proctor
import routes_referral
import routes_setup
import routes_support
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (routes_setup, routes_referral, routes_placement,
                   routes_enrollment, routes_award, routes_proctor,
                   routes_support):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_response(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_missing_route(exc):
        return jsonify(error_response("ERR_NOT_FOUND", "no such route")), 404

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return jsonify(
            error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_response("ERR_INTERNAL", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
