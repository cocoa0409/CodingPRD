"""Mental Health Parity Comparative Analysis API.

Boots a completely empty in-memory store on every process start: nothing is
seeded, preloaded or read from disk.
"""

import os

from flask import Flask, jsonify

import store
from envelope import error_response, request_id, wall_now_iso
from errors import ApiError
from routes import (administrators, analyses, classifications, clock,
                    corrective_action_plans, data_submissions, nqtl_items, plan_years,
                    regulator_requests, vendor_requests)

PARITY_BLUEPRINTS = (
    administrators,
    plan_years,
    classifications,
    nqtl_items,
    analyses,
    vendor_requests,
    data_submissions,
    corrective_action_plans,
    regulator_requests,
)


def _envelope_error(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in PARITY_BLUEPRINTS:
        app.register_blueprint(module.bp, url_prefix="/parity")
    app.register_blueprint(clock.bp)

    @app.before_request
    def _acquire_lock():
        # One request at a time keeps every cascade atomic.
        store.LOCK.acquire()

    @app.teardown_request
    def _release_lock(_exception=None):
        try:
            store.LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_not_found(_err):
        return _envelope_error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(_err):
        return _envelope_error("ERR_METHOD_NOT_ALLOWED",
                               "The method is not allowed for this path.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return _envelope_error("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
