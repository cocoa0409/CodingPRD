"""Destination Outdoor Retail API — Flask entry point.

Storage is entirely in-memory (see core.DB); the process starts with every
table empty and nothing is ever seeded or preloaded.
"""
import os
import re
import uuid
from datetime import timezone

from flask import Flask, request, jsonify

from core import (ApiError, ERROR_HTTP, iso, CLOCK, norm_now, parse_dt, err)

app = Flask(__name__)
app.url_map.strict_slashes = False

ROUTE_TABLE = []          # list of (method, path, roles, handler, endpoint)
_REGISTERED = set()


def _werkzeug_rule(path):
    """Translate the scaffold's {param} placeholders into Werkzeug <param>."""
    def repl(match):
        name, conv = match.group(1), match.group(2) or ""
        return "<%s%s>" % (conv, name)
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([a-z]+))?\}", repl, path)


def route(method, path, roles):
    def deco(fn):
        endpoint = "ep_%s_%s" % (method.lower(), path.strip("/").replace("/", "_")
                                 .replace("{", "").replace("}", "")
                                 .replace("-", "_").replace(".", "_") or "root")
        base = endpoint
        i = 2
        while endpoint in _REGISTERED:
            endpoint = "%s_%d" % (base, i)
            i += 1
        _REGISTERED.add(endpoint)
        ROUTE_TABLE.append((method, path, set(roles), fn))
        app.add_url_rule(_werkzeug_rule(path), endpoint=endpoint, view_func=_wrap(fn),
                         methods=[method])
        return fn
    return deco


class Ctx:
    """Per-request helper handed to every handler."""

    def __init__(self, path_params):
        self.path = path_params
        self._body = None
        self.args = request.args

    @property
    def body(self):
        if self._body is None:
            data = request.get_json(silent=True)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                err("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
            self._body = data
        return self._body

    def p(self, name):
        return self.path.get(name)

    @property
    def user_id(self):
        value = request.headers.get("X-User-ID")
        if value is None or value == "":
            return None
        return value

    @property
    def role(self):
        return request.headers.get("X-User-Role")


def _wrap(fn):
    def view(**path_params):
        ctx = Ctx(path_params)
        try:
            _check_auth(fn, path_params)
            data, status, kind, pmeta = fn(ctx)
            return _success(data, status, kind, pmeta)
        except ApiError as exc:
            return _error(exc.error_id, exc.message, exc.http_status)
        except Exception as exc:                      # pragma: no cover
            import traceback
            traceback.print_exc()
            return _error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 400)
    view.__name__ = fn.__name__
    return view


ROLE_BY_HANDLER = {}


def _check_auth(fn, path_params):
    roles = ROLE_BY_HANDLER.get(fn.__name__)
    if roles is None:
        roles = _roles_for(fn)
        ROLE_BY_HANDLER[fn.__name__] = roles
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    anonymous_ok = "Anonymous" in roles
    if not user_id or not role:
        if anonymous_ok:
            return
        err("ERR_UNAUTHENTICATED")
    if role not in roles:
        err("ERR_FORBIDDEN_ROLE")


def _roles_for(fn):
    for _m, path, roles, handler in ROUTE_TABLE:
        if handler is fn:
            return roles
    return set()


# ---------------------------------------------------------------------------
# Response envelope (§1.0 / PRD §2.2)
# ---------------------------------------------------------------------------
_ALPHANUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _request_id():
    return "req_" + uuid.uuid4().hex.upper()[:18]


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(norm_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _clean(value):
    """Drop server-internal bookkeeping keys from outgoing payloads."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _success(data, status, kind, pmeta):
    body = {"meta": _meta(pmeta), "response_type": kind, "data": _clean(data)}
    return jsonify(body), status


def _error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def ok(data, status=200):
    return data, status, "object", None


def ok_list(rows, pmeta):
    return rows, 200, "array", pmeta


def created(data):
    return data, 201, "object", None


# Register every route module after the helpers are defined.
import routes_floor          # noqa: E402,F401
import routes_deal           # noqa: E402,F401
import routes_permit         # noqa: E402,F401


@app.errorhandler(404)
def not_found(exc):
    return _error("ERR_RESOURCE_NOT_FOUND", "No route matches this request.", 404)


@app.errorhandler(405)
def method_not_allowed(exc):
    return _error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 400)


if __name__ == "__main__":
    # Running this file directly makes the interpreter execute it twice: once as
    # __main__ and once as the "app" module the route packages import from. The
    # routes therefore live on the "app" module's Flask instance, so serve that
    # one rather than the bare __main__ copy.
    import sys as _sys
    _module = _sys.modules.get("app")
    flask_app = getattr(_module, "app", app)
    port = int(os.environ.get("PORT", "10000"))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)