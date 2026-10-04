"""Flask app entry point: blueprint registration, error handlers, 0.0.0.0:$PORT."""
import os

from flask import Flask

import errors
import response as resp

API_PREFIX = "/marketplace"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_leases
    import routes_offers
    import routes_closing

    app.register_blueprint(routes_core.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_leases.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_offers.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_closing.bp, url_prefix=API_PREFIX)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return resp.err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return resp.err("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return resp.err("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return resp.err(e.error_id, e.http_status, e.message)
        return resp.err("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
