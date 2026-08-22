"""Brand Inspection Board API — entry point, error handling, route registration.

The store is entirely in-memory and starts empty on every boot: no entity is
seeded, preloaded or hardcoded here. Every row is created by an API call.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

API_PREFIX = "/brand-inspection"

BLUEPRINT_MODULES = (
    "routes.owners",
    "routes.territories",
    "routes.inspectors",
    "routes.brand_applications",
    "routes.brand_registrations",
    "routes.conflict_claims",
    "routes.bills_of_sale",
    "routes.inspection_orders",
    "routes.animal_lots",
    "routes.estray_cases",
    "routes.theft_investigations",
    "routes.fee_remittances",
    "routes.ops",
)


class SerializedMiddleware:
    """Serialise request handling.

    Every board operation is a multi-step read-modify-write over the in-memory
    store, and several of them (assignment under an OCC token, the remittance
    waterfall, the facility capacity projection) are only correct when evaluated
    atomically. A single global lock gives each request a consistent snapshot.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.RLock()

    def __call__(self, environ, start_response):
        with self.lock:
            chunks = self.wsgi_app(environ, start_response)
            try:
                body = b"".join(chunks)
            finally:
                close = getattr(chunks, "close", None)
                if close is not None:
                    close()
        return [body]


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    import importlib

    for module_path in BLUEPRINT_MODULES:
        module = importlib.import_module(module_path)
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "No such route.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    app.wsgi_app = SerializedMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
