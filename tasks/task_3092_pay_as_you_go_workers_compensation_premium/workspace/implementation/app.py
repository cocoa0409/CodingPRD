"""Application entry point."""
import os
from flask import Flask

from errors import ApiError, invalid_request, not_found
from response import error_response
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(not_found("Resource not found"))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(invalid_request("Malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        from errors import ERR_INVALID_REQUEST
        e = ApiError(ERR_INVALID_REQUEST, str(err), 400)
        return error_response(e)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
