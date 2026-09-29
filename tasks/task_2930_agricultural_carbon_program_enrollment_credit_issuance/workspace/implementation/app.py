"""Agricultural Carbon Program API -- Flask entry point.

All state lives in process memory (see db.py): every invocation of start.sh
begins with an empty store.  No business entity is ever seeded; the only row
written at boot is the single programme buffer pool ledger that PRD section
2.12 requires the server to seed with pool_code PROGRAM_BUFFER.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response as resp
from errors import ApiError
from routes import (
    baselines,
    batches,
    clock,
    enrollments,
    fields,
    growers,
    packets,
    payments,
    reversals,
    runs,
    standards,
    verifications,
)

BLUEPRINTS = (
    clock.bp,
    growers.bp,
    fields.bp,
    standards.bp,
    enrollments.bp,
    baselines.bp,
    packets.bp,
    runs.bp,
    verifications.bp,
    batches.bp,
    reversals.bp,
    payments.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_request():
        db.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return resp.error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return resp.error_response(ApiError("ERR_NOT_FOUND"))

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return resp.error_response(ApiError("ERR_METHOD_NOT_ALLOWED"))

    @app.errorhandler(400)
    def _bad_request(err):
        return resp.error_response(ApiError("ERR_INVALID_REQUEST"))

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return resp.error_response(ApiError("ERR_NOT_FOUND"))
        if err.code == 405:
            return resp.error_response(ApiError("ERR_METHOD_NOT_ALLOWED"))
        if err.code and err.code < 500:
            return resp.error_response(ApiError("ERR_INVALID_REQUEST"))
        return resp.error_response(ApiError("ERR_INTERNAL"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return resp.error_response(err)
        app.logger.exception("unhandled error: %s", err)
        return resp.error_response(ApiError("ERR_INTERNAL"))

    # PRD section 2.12: exactly one buffer pool, seeded by the server at startup.
    db.buffer_pool()

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
