"""Flask application factory and error handling.

State lives only in the in-memory Store of core.py: every byte vanishes when
this process exits, and nothing is seeded at boot.
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import core
import routes_consumers
import routes_inquiries
import routes_ops
import routes_propagation
import routes_registry
import routes_requests
import routes_suppression
from core import ApiError, error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (routes_registry, routes_consumers, routes_requests,
                   routes_propagation, routes_suppression, routes_inquiries,
                   routes_ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        # A refused call may still have left durable state behind (PRD 3.7),
        # so the deferred version/updated_at flush runs on the error path too.
        core.flush()
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(error_body(
            "ERR_INVALID_REQUEST",
            "no endpoint is registered for this path")), 404

    @app.errorhandler(405)
    def _not_allowed(exc):
        return jsonify(error_body(
            "ERR_INVALID_REQUEST",
            "this method is not allowed on this path")), 405

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return jsonify(error_body(
                "ERR_INVALID_REQUEST",
                "the request body must be a JSON object")), 400
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  exc.description or "invalid request")), \
            exc.code or 400

    @app.teardown_request
    def _clear(_exc):
        g.pop("dirty", None)
        g.pop("created", None)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
