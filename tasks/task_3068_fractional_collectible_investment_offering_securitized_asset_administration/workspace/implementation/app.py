"""Application factory: dispatch with the pinned evaluation order (§2.4)."""
import os

from flask import Flask, request, g

import routes_art          # noqa: F401  (registers artists/artworks/appraisals)
import routes_inv          # noqa: F401  (registers investors/subscriptions)
import routes_off          # noqa: F401  (registers offerings and sub-resources)
import routes_ops          # noqa: F401  (registers custody/policies/decisions/...)
from router import ROUTES, match_path, identity, read_limit_offset
from envelope import error_response, ApiError, ok, SafeJSON


def create_app():
    app = Flask(__name__)
    app.json = SafeJSON(app)
    app.url_map.strict_slashes = False

    @app.before_request
    def _dispatch():
        identity()
        raw = request.path
        if raw != "/" and raw.endswith("/"):
            raw = raw.rstrip("/")
        template, params = match_path(raw)
        if template is None:
            return error_response(ApiError("ERR_ROUTE_NOT_FOUND",
                                           "No route is declared for this path."))
        methods = ROUTES[template]
        if request.method not in methods:
            return error_response(ApiError("ERR_METHOD_NOT_ALLOWED",
                                           "The route does not declare this method."))
        roles, handler = methods[request.method]
        try:
            if roles == ["Anonymous"]:
                # the single public onboarding surface
                result = handler(**params) if params else handler()
            else:
                from router import require_role
                require_role(roles)
                result = handler(**params) if params else handler()
        except ApiError as err:
            return error_response(err)
        if result is None:
            return error_response(ApiError("ERR_INVALID_REQUEST",
                                           "The request could not be processed."))
        return result

    @app.errorhandler(404)
    def _nf(_e):
        return error_response(ApiError("ERR_ROUTE_NOT_FOUND",
                                       "No route is declared for this path."))

    @app.errorhandler(405)
    def _mna(_e):
        return error_response(ApiError("ERR_METHOD_NOT_ALLOWED",
                                       "The route does not declare this method."))

    @app.errorhandler(ApiError)
    def _api(err):
        return error_response(err)

    @app.errorhandler(Exception)
    def _any(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error")
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)