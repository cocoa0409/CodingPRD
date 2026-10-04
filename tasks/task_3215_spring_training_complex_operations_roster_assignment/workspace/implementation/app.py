"""Entry point: request dispatch, auth, pagination and error rendering."""

import os
import re
import sys

from flask import Flask, Response, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rules as K
import state as S
from core import (ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                  ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, envelope, error_envelope,
                  list_envelope, bad)
from store import db

import routes_a
import routes_b
import routes_c

MODULES = [routes_a, routes_b, routes_c]

app = Flask(__name__)


def _compile(pattern):
    parts = []
    for segment in pattern.strip("/").split("/"):
        if segment.startswith("<") and segment.endswith(">"):
            parts.append(r"(?P<%s>[^/]+)" % segment[1:-1])
        else:
            parts.append(re.escape(segment))
    return re.compile("^/" + "/".join(parts) + "$")


ROUTES = []
for method, pattern, roles, handler_name, response_type, status, _paginated in K.ENDPOINT_TABLE:
    handler = None
    for module in MODULES:
        if hasattr(module, handler_name):
            handler = getattr(module, handler_name)
            break
    if handler is None:
        raise RuntimeError("No handler named %s" % handler_name)
    ROUTES.append((method, _compile(pattern), frozenset(roles), handler,
                   response_type, status))


def _param_names():
    names = set()
    for _method, regex, _roles, _handler, _rt, _status in ROUTES:
        names.update(regex.groupindex.keys())
    return names


PARAM_NAMES = _param_names()


def _match(method, path):
    for route_method, regex, roles, handler, response_type, status in ROUTES:
        if route_method != method:
            continue
        match = regex.match(path)
        if match:
            return roles, handler, response_type, status, match.groupdict()
    return None


def _json_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        raise bad("The request body is not valid JSON.")
    if not isinstance(body, dict):
        raise bad("The request body must be a JSON object.")
    return body


def _auth(expected_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in K.ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "X-User-ID and X-User-Role must name a declared role.")
    if role not in expected_roles:
        raise ApiError(ERR_UNAUTHORIZED, "That role may not perform this operation.")
    return uid, role


def _pagination():
    limit = 10
    offset = 0
    if "limit" in request.args:
        raw = request.args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("limit is outside its permitted span.")
    if "offset" in request.args:
        raw = request.args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad("offset must be an integer.")
        if offset < 0:
            raise bad("offset must not be negative.")
    return limit, offset


def _run(env, matched):
    roles, handler, response_type, status, path_params = matched
    uid, role = _auth(roles)
    env["uid"] = uid
    env["role"] = role
    env["path"] = path_params
    if request.method in ("POST", "PUT", "PATCH"):
        body = _json_body()
    else:
        body = {}
    env["body"] = body
    env["query"] = dict(request.args)

    data = handler(env)
    if response_type != "array":
        return jsonify(envelope("object", data if isinstance(data, dict) else data)), status
    limit, offset = _pagination()
    items = data if isinstance(data, list) else []
    total = len(items)
    window = items[offset:offset + limit]
    return jsonify(list_envelope(window, limit, offset, total)), status


@app.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def dispatch(subpath):
    env = {"request_id": None}
    matched = _match(request.method, "/" + subpath.strip("/"))
    header_id = request.headers.get("X-Request-ID")
    try:
        if matched is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "No such endpoint.")
        payload, status = _run(env, matched)
        if header_id:
            pass
        return payload, status
    except ApiError as err:
        return jsonify(error_envelope(err, header_id)), err.http_status
    except Exception as exc:  # pragma: no cover - defensive
        import traceback
        traceback.print_exc()
        err = ApiError(ERR_INVALID_REQUEST, "The request could not be processed: %s" % exc)
        return jsonify(error_envelope(err, header_id)), err.http_status


@app.route("/", methods=["GET", "POST"])
def root():
    err = ApiError(ERR_RESOURCE_NOT_FOUND, "Use the /camp-ops API prefix.")
    return jsonify(error_envelope(err)), err.http_status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)