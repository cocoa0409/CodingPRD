"""Medical Device Vendor Credentialing & OR Access Control API.

A single Flask process holding every entity in plain in-memory dictionaries.
Nothing is persisted and nothing is seeded: a fresh boot starts from an empty
estate with the logical clock at its default instant (PRD 2.4).
"""
import os
import sys

from flask import Flask

import cascades
from envelope import respond_error
from errors import ApiError
from routes.cases import bp as cases_bp
from routes.compliance import bp as compliance_bp
from routes.core import bp as core_bp
from routes.kiosk import bp as kiosk_bp
from routes.products import bp as products_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(core_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(kiosk_bp)
    app.register_blueprint(compliance_bp)

    @app.before_request
    def _start_operation():
        # Every request begins with an empty dirty set, so a row rewritten by
        # this operation has its version incremented exactly once (PRD 2.8).
        cascades.reset()

    @app.errorhandler(ApiError)
    def _catalogued(error):
        return respond_error(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _no_route(_error):
        return respond_error("ERR_NOT_FOUND", "No such endpoint.", 404)

    @app.errorhandler(405)
    def _no_method(_error):
        return respond_error(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this endpoint.", 405
        )

    @app.errorhandler(415)
    def _bad_media_type(_error):
        return respond_error(
            "ERR_INVALID_REQUEST", "The request body must be JSON.", 400
        )

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return respond_error(error.error_id, error.message, error.http_status)
        print("unhandled error: %r" % (error,), file=sys.stderr)
        return respond_error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
