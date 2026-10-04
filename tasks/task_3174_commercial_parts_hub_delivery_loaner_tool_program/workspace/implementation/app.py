"""Entry point: the WSGI application that serves the commercial parts hub API.

The application is read-only about its own contents: the in-memory store starts
empty on every boot and only the declared endpoints ever write to it.
"""

import json
import os
import traceback

from flask import Flask, request

import response
import router
from errors import ApiError
from middleware import authenticate, authorize
from routes.table import BOOK

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False


def _headers():
    # Werkzeug's header mapping is case-insensitive; keep it that way so a
    # client that spells the header `X-User-Id` is not rejected.
    return request.headers


def _body():
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    raw = request.get_data(as_text=True)
    if not raw or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


@app.route("/commercial", defaults={"subpath": ""},
           methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/commercial/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def dispatch(subpath):
    path = "/commercial" + ("/" + subpath if subpath else "")
    # strip a trailing slash so /commercial/parts/ and /commercial/parts match
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    try:
        match, params = BOOK.match(request.method, path)
        if match is None:
            method_exists = any(
                route.segments == router._split(path) for route in BOOK.routes
            )
            if method_exists:
                raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                               "This method is not available on that path.")
            raise ApiError("ERR_INVALID_REQUEST", "No route matches %s." % path)

        # priority 1: authentication
        user_id, role = authenticate(_headers())
        # priority 2: authorisation
        authorize(role, match.roles, request.method)

        body = _body()
        ctx = _Ctx(_headers(), request.args, body, request.method, path,
                   user_id, role)

        # priority 3: path identifiers, left to right
        resolved = router.resolve_path_params(params)
        result = match.handler(ctx, resolved)
        if isinstance(result, tuple) and len(result) == 2:
            payload, status = result
        else:
            payload, status = result, 200
        return _jsonify(payload, status)
    except ApiError as exc:
        return _jsonify(response.error_body(exc), exc.http_status)
    except Exception:  # pragma: no cover - defensive
        traceback.print_exc()
        exc = ApiError("ERR_INVALID_REQUEST", "The request could not be processed.")
        return _jsonify(response.error_body(exc), exc.http_status)


class _Ctx(object):
    __slots__ = ("body", "args", "method", "path", "user_id", "role", "headers")

    def __init__(self, headers, args, body, method, path, user_id, role):
        self.headers = headers
        self.args = args
        self.body = body
        self.method = method
        self.path = path
        self.user_id = user_id
        self.role = role

    @property
    def is_rep(self):
        return self.role == "CommercialSalesRep"


def _jsonify(payload, status):
    return app.response_class(
        json.dumps(payload, default=str),
        status=status,
        mimetype="application/json",
    )


@app.route("/health", methods=["GET"])
def health():
    return _jsonify({"status": "ok"}, 200)


os.environ.setdefault("FLASK_ENV", "production")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)