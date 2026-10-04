"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from util import ApiError, err_response
from routes_core import bp as core_bp
from routes_editorial import bp as editorial_bp
from routes_program import bp as program_bp
from routes_royalty import bp as royalty_bp
from routes_misc import bp as misc_bp


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err_response(e)
        if isinstance(e, HTTPException):
            if e.code == 404:
                return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))
            if e.code == 405:
                return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))
            return err_response(ApiError("ERR_INVALID_REQUEST", 400, e.name))
        return err_response(ApiError("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % e))

    app.register_blueprint(core_bp)
    app.register_blueprint(editorial_bp)
    app.register_blueprint(program_bp)
    app.register_blueprint(royalty_bp)
    app.register_blueprint(misc_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
