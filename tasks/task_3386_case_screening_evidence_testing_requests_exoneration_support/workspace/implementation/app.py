"""Innocence Case Review API — Flask entry point.

Wires the per-domain blueprints, renders the standard error envelope for
ApiError and for unrouted/mismatched requests, and serves on 0.0.0.0:$PORT
(default 10000) in the foreground.
"""

import os

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_cases
import routes_clients
import routes_compensation
import routes_evidence
import routes_intake
import routes_jurisdictions
import routes_lab
import routes_ops
import routes_petitions
import routes_policy
import routes_reentry
import routes_testing

for module in (
    routes_ops,
    routes_jurisdictions,
    routes_clients,
    routes_intake,
    routes_cases,
    routes_evidence,
    routes_testing,
    routes_lab,
    routes_petitions,
    routes_compensation,
    routes_reentry,
    routes_policy,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_not_found(_err):
    return jsonify(error_body("ERR_NOT_FOUND",
                              "The requested path does not exist")), 404


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return jsonify(error_body("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed on this path")), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return jsonify(error_body("ERR_INTERNAL_ERROR",
                              "Internal error: %s" % err)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
