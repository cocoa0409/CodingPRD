"""Entry point: error handlers, router discovery, and the Flask server."""

import importlib
import os
import pkgutil
import sys

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from error import CatalogError  # noqa: E402
from envelope import fail  # noqa: E402
from store import DB  # noqa: E402

app = Flask(__name__)
app.url_map.strict_slashes = False


def _register_routers(application):
    """Import every routes_*.py module and let it register its blueprints."""
    here = os.path.dirname(os.path.abspath(__file__))
    names = sorted(
        name for _, name, _ in pkgutil.iter_modules([here])
        if name.startswith("routes_")
    )
    registered = []
    for name in names:
        module = importlib.import_module(name)
        if hasattr(module, "register"):
            module.register(application)
            registered.append(name)
    return registered


@app.errorhandler(CatalogError)
def handle_catalog_error(exc):
    return fail(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    from error import ERR_RESOURCE_NOT_FOUND
    return fail(ERR_RESOURCE_NOT_FOUND, "No route matches this request.", 404)


@app.errorhandler(405)
def handle_405(exc):
    from error import ERR_INVALID_REQUEST
    return fail(ERR_INVALID_REQUEST, "Method not allowed for this route.", 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    from error import ERR_INVALID_REQUEST
    if isinstance(exc, CatalogError):
        return fail(exc.error_id, exc.message, exc.http_status)
    app.logger.exception("unhandled error")
    return fail(ERR_INVALID_REQUEST, "The request could not be processed.", 400)


@app.before_request
def _parse_json():
    # Bodies are bound positionally by some endpoints, so keep the raw payload
    # available alongside the parsed one.
    request.raw_payload = request.get_json(silent=True)


REGISTERED = _register_routers(app)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "routers": REGISTERED})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)