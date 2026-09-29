"""VoIP Porting & E911 API -- application entry point.

All state lives in the in-memory dictionaries of store.py, so a fresh process
starts with an empty world and the logical clock parked at 2026-08-01T00:00:00Z.
Nothing is read from or written to disk.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import error_response
from errors import ApiError
from routes.devices import bp as devices_bp
from routes.e911 import bp as e911_bp
from routes.fees import bp as fees_bp
from routes.inventory import bp as inventory_bp
from routes.porting import bp as porting_bp
from routes.reference import bp as reference_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in (reference_bp, inventory_bp, porting_bp, devices_bp, e911_bp,
                      fees_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(error_response(error.error_id, error.message)), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 400:
            return jsonify(error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed.")), 400
        if error.code in (404, 405):
            return jsonify(error_response(
                "ERR_RESOURCE_NOT_FOUND", "No such route on this API.")), 404
        return jsonify(error_response(
            "ERR_INVALID_REQUEST", error.description or "Request refused.")), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return jsonify(error_response(
            "ERR_INVALID_REQUEST", "Unhandled server error: %s" % error)), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
