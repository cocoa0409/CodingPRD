"""Air Hub Sort Operations API — application entry point.

The contract (INSTRUCTION.md): `bash start.sh` from ./implementation/ must run
the server in the foreground on 0.0.0.0:$PORT (default 10000).
"""

import os
import sys

from flask import Flask, request
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import (  # noqa: E402
    ENDPOINTS,
    authenticate,
    authorize,
    check_body_fks,
    check_body_shape,
    check_path_resources,
)
from errors import ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND  # noqa: E402
from response import error_response  # noqa: E402
from store import STORE  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    from routes import aircraft, failures, feeders, hubs, lanes, moves, packages, shifts

    for module in (hubs, aircraft, packages, lanes, moves, feeders, shifts, failures):
        app.register_blueprint(module.bp)

    @app.before_request
    def _guard():
        if request.method == "OPTIONS":
            return None
        rule = request.url_rule
        if rule is None:
            return None
        spec = ENDPOINTS.get((request.method, rule.rule))
        if spec is None:
            return None
        _, role = authenticate()
        authorize(spec, role)
        json_body = request.get_json(silent=True)
        if json_body is not None and not isinstance(json_body, dict):
            raise ApiError(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
        check_body_shape(request.method, rule.rule, json_body or {})
        check_path_resources(STORE, spec, request.view_args or {})
        if spec["body_order"]:
            payload = json_body or {}
            hub_scope = None
            if payload.get("hub_id"):
                hub_scope = payload["hub_id"]
            elif request.view_args:
                hub_scope = _hub_scope_from_path(request.view_args)
            check_body_fks(STORE, spec, payload, hub_scope)
        return None

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 405:
            return error_response(ERR_INVALID_REQUEST, exc.description, 405)
        if exc.code == 404:
            return error_response(ERR_RESOURCE_NOT_FOUND, exc.description, 404)
        return error_response(ERR_INVALID_REQUEST, exc.description, exc.code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return _http_error(exc)
        return error_response(ERR_INVALID_REQUEST, str(exc), 500)

    return app


def _hub_scope_from_path(view_args):
    for value in view_args.values():
        if not isinstance(value, str):
            continue
        for table in ("hubs", "banks", "aircraft", "packages", "lanes", "moves",
                      "buildups", "feeders", "shifts", "failures"):
            record = STORE.get(table, value)
            if record is not None and record.get("hub_id"):
                return record["hub_id"]
    return None


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)