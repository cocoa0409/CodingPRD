"""Custody RIA Advisor Transition API — application entry point.

Storage is in-memory only and the store starts empty on every boot: this module
never seeds, preloads or registers entity rows.  All preconditions are built by
the caller through the declared API surface.
"""

import os

from flask import Flask, request

from core.context import check_authorized, parse_identity
from core.errors import ApiError
from core.response import error
from core import router as router_module


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    api = router_module.build(app)

    from routes import register_all
    register_all(api)

    @app.before_request
    def _authenticate_and_authorize():
        identity = parse_identity()
        rule = request.url_rule.rule if request.url_rule else None
        if rule is not None:
            check_authorized(identity, rule, request.method)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_RESOURCE_NOT_FOUND", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error("ERR_RESOURCE_NOT_FOUND", "Method not allowed on this route.", 405)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        return error("ERR_INVALID_STATE", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)