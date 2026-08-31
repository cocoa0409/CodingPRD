"""Indirect Auto Lending & Dealer Reserve API - entry point.

Storage is entirely in-memory and starts empty on every boot; no entity is
seeded, preloaded or hardcoded at startup.
"""
import os

from flask import Flask, g, request

from core import ApiError, LOCK, authenticate, error_response
import routes_dealers
import routes_agreements
import routes_applications
import routes_contracts
import routes_misc


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_dealers.bp)
    app.register_blueprint(routes_agreements.bp)
    app.register_blueprint(routes_applications.bp)
    app.register_blueprint(routes_contracts.bp)
    app.register_blueprint(routes_misc.bp)

    @app.before_request
    def _before():
        LOCK.acquire()
        g._locked = True
        authenticate()

    @app.teardown_request
    def _teardown(exc):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_INVALID_REQUEST", "No such route.")

    @app.errorhandler(405)
    def _not_allowed(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route.")

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message)
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error: %s" % err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
