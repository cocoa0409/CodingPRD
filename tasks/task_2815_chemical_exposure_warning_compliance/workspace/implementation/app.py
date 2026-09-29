"""Proposition 65 chemical exposure warning compliance API.

Flask entry point.  Every module of state lives in memory only (see db.py) and
the store starts completely empty on every boot: nothing is seeded here.
"""
import os
import sys
import traceback

from flask import Flask, jsonify

import response
from errors import STATUS, ApiError
from routes import (assessments, clock, determinations, enforcement, materials,
                    products, reformulation, registry, suppliers)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (registry, suppliers, materials, products, assessments,
                   determinations, enforcement, reformulation, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        body = response.error_body(exc.error_id, exc.message)
        return jsonify(body), STATUS.get(exc.error_id, 422)

    @app.errorhandler(404)
    def _not_found(exc):
        body = response.error_body("ERR_NOT_FOUND", "the requested resource does not exist")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _not_allowed(exc):
        body = response.error_body("ERR_NOT_FOUND",
                                   "the requested method is not served on this path")
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        traceback.print_exc(file=sys.stderr)
        body = response.error_body("ERR_INVALID_REQUEST", "unhandled server error: %s" % exc)
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
