"""Sports Remote Production Operations API.

Boots from a fresh process on every launch. All state lives in module-level Python dicts
(see store.py) and is therefore wiped by every restart. Nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_crew
import routes_production
import routes_registry
import routes_show
import routes_systems
import routes_transport
from core import ApiError, respond_error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_production.bp)
    app.register_blueprint(routes_transport.bp)
    app.register_blueprint(routes_crew.bp)
    app.register_blueprint(routes_systems.bp)
    app.register_blueprint(routes_show.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return respond_error(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif status == 415:
            error_id = "ERR_INVALID_REQUEST"
        elif status == 400:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_HTTP_%d" % status
        return respond_error(error_id, error.description or "Request could not be served.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return respond_error("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
