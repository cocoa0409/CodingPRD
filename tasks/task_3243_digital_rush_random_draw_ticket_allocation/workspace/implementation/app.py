"""Entry point: envelope error handlers, blueprint registration and the server."""

import os

from flask import Flask

from errors import ApiError
from response import error


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = True

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(_exc):
        return error(
            "ERR_REFERENCE_NOT_FOUND",
            "The requested route does not resolve to a declared operation.",
            404,
        )

    @app.errorhandler(405)
    def _handle_method_not_allowed(_exc):
        return error(
            "ERR_INVALID_STATE",
            "The requested method is not declared on this route.",
            405,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        if os.environ.get("PRDBENCH_DEBUG"):
            import traceback

            traceback.print_exc()
        if isinstance(exc, ValueError):
            return error("ERR_INVALID_STATE", str(exc), 409)
        return error("ERR_INVALID_STATE", "The request could not be completed.", 500)

    import routes

    routes.register_all(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)