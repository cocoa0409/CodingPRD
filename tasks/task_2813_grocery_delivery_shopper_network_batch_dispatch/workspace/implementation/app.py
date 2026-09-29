"""Grocery Batch Dispatch API — Flask entry point.

Storage is in-memory only and the store boots empty: no entity is seeded,
preloaded or hardcoded at startup.  Every row is created through a declared
endpoint.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import aisle, batches, catalog, customers, fulfillment, orders, shoppers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (catalog, customers, shoppers, orders, batches, aisle, fulfillment):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_INVALID_REQUEST", "Unknown resource path.")), 404
        if exc.code == 405:
            return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 405
        if exc.code == 400:
            return jsonify(error_body("ERR_INVALID_REQUEST", "The request is malformed.")), 400
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Request failed")), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
