"""Entry point: error handlers, blueprint registration, foreground server boot."""

import os
import traceback

from flask import Flask, jsonify, request

from errors import ApiError
from response import error_body
from routes import api

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["PROPAGATE_EXCEPTIONS"] = False

app.register_blueprint(api, url_prefix="/route-settlement")


def _not_found(_err):
    err = ApiError("ERR_INVALID_REQUEST", "no such endpoint: %s" % request.path, 404)
    return jsonify(error_body(err)), 404


def _method_not_allowed(_err):
    err = ApiError("ERR_INVALID_REQUEST", "method not allowed for %s" % request.path, 405)
    return jsonify(error_body(err)), 405


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return jsonify(error_body(err)), err.http_status


@app.errorhandler(404)
def _handle_404(err):
    return _not_found(err)


@app.errorhandler(405)
def _handle_405(err):
    return _method_not_allowed(err)


@app.errorhandler(Exception)
def _handle_unexpected(err):
    traceback.print_exc()
    wrapped = ApiError("ERR_INVALID_REQUEST", "the request could not be processed", 400)
    return jsonify(error_body(wrapped)), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)