"""Flask entry point: envelope, auth, route registration.

No seeding. The store starts empty on every boot; tests build all state
through the declared API surface.
"""
import os
from functools import wraps

from flask import Flask, jsonify, request

from helpers import ApiError, request_id, wall_ts
from routes import ROUTES, ALL_ROLES

app = Flask(__name__)
app.json.sort_keys = False


def make_meta(pagination=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_ts()}
    if pagination:
        meta.update(pagination)
    return meta


def success_object(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_array(items, status, pagination):
    body = {"meta": make_meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(_):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_405(_):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Never leak a bare 500 without the envelope
    import traceback
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", 400, "unhandled server error: %s" % err)


def authenticate():
    """Priority 1-2 validation: headers present/non-empty, role recognized."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are required and must be non-empty")
    if role not in ALL_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "Unrecognized X-User-Role: %s" % role)
    return {"role": role, "user_id": user_id}


def register(method, path, handler, roles):
    endpoint_name = "%s %s" % (method, path)

    @wraps(handler)
    def view(**kwargs):
        user = authenticate()
        if user["role"] not in roles:
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                           "Role %s is not permitted for %s" % (user["role"], endpoint_name))
        result = handler(user, **kwargs)
        if len(result) == 3:
            data, status, pagination = result
            return success_array(data, status, pagination)
        data, status = result
        return success_object(data, status)

    app.add_url_rule(path, endpoint_name, view, methods=[method])


for method, path, handler, roles in ROUTES:
    register(method, path, handler, roles)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
