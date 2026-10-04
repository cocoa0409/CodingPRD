"""Entry point: Flask app, error handlers, blueprint registration.

Boots cleanly from a fresh process; the in-memory store starts empty.
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from store import db
from util import ApiError, error_response

import routes_lenders
import routes_cases
import routes_appraisals
import routes_mip
import routes_reviews
import routes_indemnity
import routes_servicing

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_lenders, routes_cases, routes_appraisals, routes_mip,
               routes_reviews, routes_indemnity, routes_servicing):
    app.register_blueprint(module.bp)


@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc=None):
    if db.lock._is_owned():
        db.lock.release()


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "resource not found"))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    from flask import jsonify
    from util import _meta
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": "unexpected error: %s" % err}}
    return jsonify(body), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
