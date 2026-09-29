"""Motor Carrier Operating Authority API.

Flask application factory and process entry point. All state lives in the
in-memory dictionaries of store.py and is empty on every boot: nothing is
seeded, preloaded or hardcoded.
"""

import os

from flask import Flask

import envelope
import routes_applications
import routes_authorities
import routes_commercial
import routes_compliance
import routes_filings
import routes_registry
from errors import CATALOG, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_applications.bp)
    app.register_blueprint(routes_authorities.bp)
    app.register_blueprint(routes_filings.bp)
    app.register_blueprint(routes_compliance.bp)
    app.register_blueprint(routes_commercial.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message,
                             exc.http_status or CATALOG.get(exc.error_id, 400))

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error("ERR_REFERENCE_NOT_FOUND", "No such resource.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return envelope.error("ERR_REFERENCE_NOT_FOUND",
                              "That method is not allowed on this path.", 404)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return envelope.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        return envelope.error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
