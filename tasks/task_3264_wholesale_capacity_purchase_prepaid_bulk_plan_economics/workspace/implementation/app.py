"""Entry point: error handlers, route registration, server bootstrap.

The store is empty at boot; nothing is seeded here or anywhere else.
"""

import os

from flask import Flask, jsonify, request

import respond
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    body = respond.error_body(exc.error_id, exc.message)
    app.logger.info("ApiError %s on %s %s", exc.error_id, request.method, request.path)
    return jsonify(body), exc.http_status


@app.errorhandler(404)
def _handle_404(_exc):
    return jsonify(respond.error_body("ERR_INVALID_REQUEST", "no such route")), 404


@app.errorhandler(405)
def _handle_405(_exc):
    return jsonify(respond.error_body("ERR_INVALID_REQUEST", "method not allowed")), 405


@app.errorhandler(500)
def _handle_500(_exc):
    return jsonify(respond.error_body("ERR_INVALID_REQUEST", "internal server error")), 500


import res_agreements  # noqa: E402
import res_plans  # noqa: E402
import res_subscribers  # noqa: E402
import res_terms  # noqa: E402
import res_cycles  # noqa: E402
import res_activations  # noqa: E402
import res_partners  # noqa: E402
import res_support  # noqa: E402
import res_addons  # noqa: E402
import res_clock  # noqa: E402

for module in (res_agreements, res_plans, res_subscribers, res_terms, res_cycles,
               res_activations, res_partners, res_support, res_addons, res_clock):
    module.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))