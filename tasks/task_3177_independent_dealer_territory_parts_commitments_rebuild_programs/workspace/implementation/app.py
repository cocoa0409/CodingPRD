"""Entry point: request dispatch, error handling and route registration.

The store starts empty on every boot.  Nothing in this module (or any module it
imports) seeds, preloads or registers an entity at startup.
"""

from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify, request as flask_request

import db
import middleware
import registry as reg
import response as resp
from errors import ApiError, ERROR_CATALOG, E_INVALID_REQUEST
from request import Request, parse_body

app = Flask(__name__)
app.url_map.strict_slashes = False


def _load_routes():
    from routes import _clock, dealer_network, equipment_service, parts

    _clock.register_routes()
    dealer_network.register_routes()
    parts.register_routes()
    equipment_service.register_routes()


_load_routes()


def _wants_actor(handler) -> bool:
    code = handler.__code__
    return "actor" in code.co_varnames[:code.co_argcount]


@app.route("/<path:any_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def dispatch(any_path):
    path = "/" + any_path
    method = flask_request.method
    route, path_params = reg.resolve(method, path)

    if route is None:
        return jsonify(resp.failure("ERR_DEALER_NOT_FOUND", "no route matches %s %s" % (method, path))), 404

    with db.LOCK:
        try:
            actor = middleware.authenticate(flask_request.headers, db.TABLES["dealers"])
            middleware.authorize(actor, route.roles)

            body = parse_body()
            if body:
                from request import check_declared, validate_types

                check_declared(body, route.inputs)
                validate_types(body)
            request = Request(method, path_params, body, flask_request.args, flask_request.headers)

            if _wants_actor(route.handler):
                payload, status = route.handler(request, actor)
            else:
                payload, status = route.handler(request)
            return jsonify(payload), status
        except ApiError as error:
            return jsonify(resp.failure(error.error_id, error.message)), error.http_status
        except Exception:  # pragma: no cover - defensive
            traceback.print_exc()
            return jsonify(resp.failure(E_INVALID_REQUEST, "the request could not be processed")), 400


@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify(resp.failure("ERR_DEALER_NOT_FOUND", "method not allowed for this path")), 404


@app.errorhandler(404)
def not_found(_error):
    return jsonify(resp.failure("ERR_DEALER_NOT_FOUND", "no route matches this path")), 404


@app.errorhandler(500)
def server_error(_error):
    return jsonify(resp.failure(E_INVALID_REQUEST, "the request could not be processed")), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)