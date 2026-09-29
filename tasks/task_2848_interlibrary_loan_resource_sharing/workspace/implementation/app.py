"""Interlibrary Loan & Resource Sharing API — application entry point.

The store is empty on every boot: no entity is seeded, preloaded or hardcoded
here.  Every row is created by the declared endpoints.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error, error_body
from routes import (bib, deliveries, finance, fulfilment, partners, patrons, pod,
                    requests as requests_routes, rotas, sourcing)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (patrons, partners, rotas, bib, requests_routes, sourcing, fulfilment,
               deliveries, pod, finance):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error(err)


@app.errorhandler(404)
def handle_not_found(err):
    return jsonify(error_body("ERR_INVALID_REQUEST",
                              "The requested resource does not exist.")), 404


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return jsonify(error_body("ERR_INVALID_REQUEST",
                              "The HTTP method is not allowed on this path.")), 405


@app.errorhandler(400)
def handle_bad_request(err):
    return jsonify(error_body("ERR_INVALID_REQUEST",
                              "The request payload or query is malformed.")), 400


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error(err)
    app.logger.exception("unhandled error")
    return jsonify(error_body("ERR_INTERNAL", str(err))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
