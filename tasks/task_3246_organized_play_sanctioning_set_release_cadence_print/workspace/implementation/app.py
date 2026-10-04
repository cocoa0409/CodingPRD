"""Organized Play Sanctioning API — entry point.

Boots a Flask server on 0.0.0.0:$PORT (default 10000). The store starts EMPTY
on every boot: nothing is seeded, preloaded or registered at startup. Every
entity any caller needs is constructed through the declared API surface.

Also exposes the registered-endpoint inventory at /op/_meta/endpoints so the
route surface can be verified against the scaffold's §1.5 table without
running the behaviour suite.
"""

import os
import sys

from flask import Flask, request
from werkzeug.exceptions import HTTPException

# Make sibling modules importable regardless of the invoking shell's cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import response as envelope  # noqa: E402
from errors import ApiError  # noqa: E402

from routes.stores import bp as stores_bp  # noqa: E402
from routes.set_releases import bp as set_releases_bp  # noqa: E402
from routes.formats import bp as formats_bp  # noqa: E402
from routes.event_applications import bp as applications_bp  # noqa: E402
from routes.prizes import bp as prizes_bp  # noqa: E402
from routes.enforcement import bp as enforcement_bp  # noqa: E402
from routes.code_redemptions import bp as codes_bp  # noqa: E402
from routes.products import bp as products_bp  # noqa: E402
from routes.reprints import bp as reprints_bp  # noqa: E402
from routes.judges import bp as judges_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for blueprint in (stores_bp, set_releases_bp, formats_bp, applications_bp,
                      prizes_bp, enforcement_bp, codes_bp, products_bp,
                      reprints_bp, judges_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return envelope.error_response(err.error_id, err.message), err.http_status

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        # An unrouted path or method answers with the catalog's not-found error
        # rather than Flask's default HTML body.
        return envelope.error_response(
            "ERR_NOT_FOUND", err.description or "Resource not found."), err.code or 404

    @app.errorhandler(Exception)
    def _handle_unexpected(err):  # pragma: no cover - defensive
        return envelope.error_response("ERR_INVALID_REQUEST", str(err)), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)