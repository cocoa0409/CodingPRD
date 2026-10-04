"""Entry point: request pipeline, error handlers, route registration."""

import os
import traceback

from flask import Flask, g, request

from db import DB
from errors import ApiError
from middleware import authorize, extract_context
from response import error_body
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/v1")

    @app.before_request
    def authenticate():
        if request.method == "OPTIONS":
            return None
        user_id, role = extract_context(request.headers)
        g.user_id = user_id
        g.role = role
        authorize(request.method, request.path, user_id, role)
        return None

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_body(exc.error_id, exc.message)
        return body, exc.status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        body = error_body("ERR_INVALID_REQUEST", "No operation is declared for this path.")
        return body, 400

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        body = error_body("ERR_INVALID_REQUEST", "The method is not declared for this path.")
        return body, 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        if isinstance(exc, (KeyError, TypeError, ValueError, IndexError, AttributeError)):
            return error_body("ERR_INVALID_REQUEST",
                              "Request body is malformed, a field is absent, or a value has the wrong type."), 400
        traceback.print_exc()
        return error_body("ERR_INVALID_REQUEST", str(exc)), 400

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)