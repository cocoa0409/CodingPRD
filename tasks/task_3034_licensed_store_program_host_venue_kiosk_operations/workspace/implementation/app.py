"""Entry point: Flask app wiring, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

import routes.base  # noqa: F401  (registers routes on its own blueprint)
from routes.clock import bp as clock_bp
from routes.agreements import bp as agreements_bp
import routes.assortment  # noqa: F401
import routes.supply  # noqa: F401
import routes.training  # noqa: F401
import routes.sales  # noqa: F401
import routes.inspections  # noqa: F401
import routes.loyalty  # noqa: F401
import routes.campaigns  # noqa: F401


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    app.register_blueprint(routes.base.bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(agreements_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        from errors import err_not_found
        return error_response(err_not_found("route not found"))

    @app.errorhandler(405)
    def handle_405(err):
        from errors import err_not_found
        return error_response(err_not_found("method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        from errors import ApiError as _AE
        return error_response(_AE("ERR_INVALID_REQUEST", 400, f"unexpected error: {err}"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
