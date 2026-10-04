"""Nonprofit Data Transparency API — application entry point.

The store starts empty on every boot: nothing is seeded or preloaded, and every
entity a client needs is constructed through a declared endpoint.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import clock
import errors
import response
import store

import routes_correction
import routes_filing
import routes_grant
import routes_identity
import routes_license
import routes_lists
import routes_org
import routes_seal

BLUEPRINTS = (
    routes_org.bp,
    routes_lists.bp,
    routes_filing.bp,
    routes_correction.bp,
    routes_license.bp,
    routes_seal.bp,
    routes_grant.bp,
    routes_identity.bp,
)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    # A fresh process must never inherit state from a previous run.
    store.reset()
    clock.reset()

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        body, status = response.error(exc.error_id, exc.message, exc.http_status)
        return jsonify(body), status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 405:
            error_id = errors.ERR_METHOD_NOT_ALLOWED
        else:
            error_id = errors.ERR_NOT_FOUND
        body, status = response.error(error_id, exc.description or "Request failed.", exc.code or 400)
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        body, status = response.error(
            errors.ERR_INVALID_REQUEST, "The request could not be processed: %s" % exc, 400
        )
        return jsonify(body), status

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
