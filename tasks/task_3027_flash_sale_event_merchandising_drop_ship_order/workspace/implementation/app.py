"""Entry point: registers the route modules and the global error handlers.

Storage is in-memory only and the process is re-launched by ``start.sh`` before
every test, so the store is empty at each boot.  Nothing is seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body

import routes_catalog
import routes_orders
import routes_buying

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes_catalog.bp)
app.register_blueprint(routes_orders.bp)
app.register_blueprint(routes_buying.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    from flask import jsonify
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    from flask import jsonify
    if exc.code == 404:
        return jsonify(error_body("ERR_INVALID_REQUEST", "No such endpoint.")), 404
    if exc.code == 405:
        return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 405
    return jsonify(error_body("ERR_INVALID_REQUEST", exc.description)), exc.code


@app.errorhandler(Exception)
def handle_unexpected(exc):
    from flask import jsonify
    from werkzeug.exceptions import HTTPException as _HTTPException
    if isinstance(exc, _HTTPException):
        return handle_http_error(exc)
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    app.logger.exception("unhandled error")
    return jsonify(error_body("ERR_INVALID_REQUEST", "Internal server error.")), 500


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)