"""Request dispatcher: auth, permissions, scope, routing and error shaping.

Validation precedence follows PRD section 2.11: the header check runs first, then
the permission check, then the client-scope check, and only then does the handler
resolve resource ids and apply state and domain rules.
"""

from flask import request, jsonify

import response
import middleware
import routes
import workflow_one as engine
from errors import ApiError, ERR_INVALID_REQUEST


def register(app):
    """Install the after-request error shaper and every declared route."""

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(response.error(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(response.error("ERR_NOT_FOUND", "The requested path does not exist.")), 404

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return (
            jsonify(response.error("ERR_INVALID_REQUEST", "The HTTP method is not allowed here.")),
            405,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return jsonify(response.error(exc.error_id, exc.message)), exc.http_status
        import traceback

        traceback.print_exc()
        return (
            jsonify(response.error(ERR_INVALID_REQUEST, "The request could not be processed.")),
            400,
        )

    for method, path, handler, roles, scope in routes.ROUTES:
        endpoint = "%s %s" % (method, path)
        app.add_url_rule(
            path,
            endpoint=endpoint,
            view_func=_make_view(handler, roles, scope),
            methods=[method],
        )


def _make_view(handler, roles, scope):
    def view(**path_params):
        # Advancing the logical clock is not a passive act: reaching a booked
        # departure, delivery or analyzer instant moves the scheduled resource on
        # its own, so the clock-driven events are re-evaluated on every request.
        engine.fire_clock_events()
        actor = middleware.extract_actor(request.headers)
        middleware.require_role(actor, roles)
        body = _body()
        if scope is not None:
            client_id = scope(path_params, body)
            middleware.enforce_client_scope(actor, client_id)
        # Handlers see path segments and query parameters in one mapping, since
        # list endpoints read their filters and pagination window from the query
        # string while action endpoints read identifiers from the path.
        params = dict(path_params)
        params.update(request.args.to_dict())
        try:
            result = handler(params, body, actor)
        except ApiError:
            raise
        if isinstance(result, dict) and "_list" in result:
            return jsonify(response.success(result["_list"], "array", result["_meta"])), 200
        return jsonify(response.success(result, "object")), _status_for(request.method, handler)

    view.__name__ = "view_" + handler.__name__
    return view


def _body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError(ERR_INVALID_REQUEST, "The request payload is not valid JSON.")
    if not isinstance(payload, dict):
        raise ApiError(ERR_INVALID_REQUEST, "The request payload must be a JSON object.")
    return payload


# Handlers whose success code is 201; every other success is 200.
CREATED = {
    "h_client_create",
    "h_courier_create",
    "h_catalog_create",
    "h_specimen_create",
    "h_specimen_aliquot_create",
    "h_order_create",
    "h_instrument_create",
    "h_build_create",
    "h_message_create",
    "h_ledger_create",
    "h_advisory_create",
}


def _status_for(method, handler):
    if handler.__name__ in CREATED:
        return 201
    return 200