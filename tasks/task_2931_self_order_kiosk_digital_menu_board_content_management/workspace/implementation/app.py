"""Self-Order Kiosk Content Ops API.  Every route is mounted under /kiosk-ops."""
import os
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (availability, bundles, campaigns, devices, menu, misc, orders, pricing,
                    topology, upsell)

URL_PREFIX = "/kiosk-ops"
BLUEPRINTS = (topology.bp, menu.bp, pricing.bp, availability.bp, campaigns.bp, upsell.bp,
              bundles.bp, devices.bp, orders.bp, misc.bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=URL_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(response.error_body(
                "ERR_RESOURCE_NOT_FOUND", "no route matches this request")), 404
        if exc.code == 405:
            return jsonify(response.error_body(
                "ERR_RESOURCE_NOT_FOUND", "the method is not allowed on this path")), 404
        if exc.code == 401:
            return jsonify(response.error_body(
                "ERR_UNAUTHENTICATED", "authentication headers are required")), 401
        return jsonify(response.error_body(
            "ERR_INVALID_REQUEST", exc.description or "malformed request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return jsonify(response.error_body("ERR_INVALID_REQUEST", str(exc))), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
