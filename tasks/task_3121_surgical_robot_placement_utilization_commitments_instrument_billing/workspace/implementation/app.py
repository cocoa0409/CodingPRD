"""Application entry point.

Registers every blueprint, installs the two error handlers that emit the
scaffold's error envelope, and runs the Werkzeug server on 0.0.0.0:$PORT.

The store is process-local and starts empty on every boot. Nothing here seeds,
preloads or registers any entity: every resource a caller needs is constructed
through the declared API surface.
"""

import os
import sys

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import ALL_BLUEPRINTS


app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in ALL_BLUEPRINTS:
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    """Map framework-level failures onto the same envelope.

    405 and 404 from the router are ordinary REST routing outcomes; 400 is a
    body the request layer could not parse.
    """
    if exc.code == 400:
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  exc.description or "Malformed request.")), 400
    if exc.code == 404:
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The requested path does not resolve.")), 404
    if exc.code == 405:
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The HTTP method is not supported for this path.")), 405
    return jsonify(error_body("ERR_INVALID_REQUEST",
                              exc.description or "Request could not be processed.")), exc.code


@app.errorhandler(Exception)
def handle_unexpected(exc):
    """Last resort: never leak a stack trace as HTML, always answer the
    envelope. A programming error is reported as a malformed request."""
    print("unhandled: %r" % (exc,), file=sys.stderr)
    return jsonify(error_body("ERR_INVALID_REQUEST",
                              "The request could not be processed.")), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)