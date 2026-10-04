"""App entry point: blueprint registration, error handlers, server boot."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION, raise_err
from response import error_response, success_object
from routes import crawl, funding, loans, patrons, rights, scanning, system, waitlist
from routes import libraries_works


def create_app():
    app = Flask(__name__)
    app.register_blueprint(system.bp)
    app.register_blueprint(patrons.bp)
    app.register_blueprint(libraries_works.bp)
    app.register_blueprint(scanning.bp)
    app.register_blueprint(loans.bp)
    app.register_blueprint(waitlist.bp)
    app.register_blueprint(crawl.bp)
    app.register_blueprint(rights.bp)
    app.register_blueprint(funding.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_VALIDATION", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
