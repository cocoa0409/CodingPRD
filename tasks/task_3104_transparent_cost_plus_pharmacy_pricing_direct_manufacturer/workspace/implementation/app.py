"""Application factory, route registration and transport-level error handling.

This module is intentionally thin: it wires the route table in routes.py onto
a Flask app, builds the per-request context, and renders the response
envelopes declared in PRD §2.2. There is no data here — the store is empty on
every boot.
"""

import os

from flask import Flask, jsonify, request

import routes as route_table
from auth import declared_role
from errors import ApiError, error_payload
from requestctx import RequestContext
from views_clock import health


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for method, rule, target, allowed in route_table.ROUTES:
        handler = route_table.resolve(target)
        app.add_url_rule(rule, endpoint=target, view_func=_wrap(handler, allowed),
                         methods=[method])

    _install_error_handlers(app)
    return app


def _wrap(handler, allowed):
    def view(**kwargs):
        ctx = RequestContext(request, request.url_rule.rule if request.url_rule else request.path)
        ctx.declare_identity(allowed)
        payload, status = handler(ctx, **kwargs)
        return jsonify(payload), status

    view.__name__ = handler.__name__
    return view


def _role_of(request_obj):
    """Validate the declared role before any other consideration (PRD §2.1)."""
    return declared_role(request_obj.headers.get("X-User-Role"))


def _install_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_payload(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        try:
            _role_of(request)
        except ApiError as role_error:
            return jsonify(error_payload(role_error.error_id, role_error.message)), role_error.http_status
        return jsonify(
            error_payload("ERR_RESOURCE_NOT_FOUND", "No route matches this request path.")
        ), 404

    @app.errorhandler(405)
    def handle_bad_method(exc):
        try:
            _role_of(request)
        except ApiError as role_error:
            return jsonify(error_payload(role_error.error_id, role_error.message)), role_error.http_status
        return jsonify(
            error_payload("ERR_RESOURCE_NOT_FOUND", "No route matches this method and path.")
        ), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return jsonify(error_payload(exc.error_id, exc.message)), exc.http_status
        return jsonify(error_payload("ERR_RESOURCE_NOT_FOUND", str(exc))), 500


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )