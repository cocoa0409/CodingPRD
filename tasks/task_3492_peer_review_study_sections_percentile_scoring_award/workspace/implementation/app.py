"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask, jsonify

from errors import ApiError
from util import _meta, error_body

import routes_applications
import routes_assignments
import routes_awards
import routes_core
import routes_council_jit
import routes_postaward
import routes_review
import routes_transfers

app = Flask(__name__)

for module in (
    routes_core,
    routes_applications,
    routes_review,
    routes_assignments,
    routes_council_jit,
    routes_awards,
    routes_postaward,
    routes_transfers,
):
    app.register_blueprint(module.bp)


def _envelope_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err)


@app.errorhandler(404)
def handle_not_found(err):
    return _envelope_error("ERR_NOT_FOUND", "route not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return _envelope_error("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return _envelope_error("ERR_INTERNAL", str(err), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
