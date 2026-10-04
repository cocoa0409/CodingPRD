"""Entry point: Flask app factory, error handlers, route registration.

The API is mounted at the server root (api_prefix "/"): collections live at
/accident-cases, /investigations, /party-organizations, /party-designations,
/groups, /recorders, /safety-recommendations, /board-meetings, and the single
platform endpoint POST /_clock/set_current_utc is unprefixed.
"""

import os

from flask import Flask, jsonify

from envelope import error_response, make_meta
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "route not found",
            },
        }
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "method not allowed",
            },
        }
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(_err):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "internal server error",
            },
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
