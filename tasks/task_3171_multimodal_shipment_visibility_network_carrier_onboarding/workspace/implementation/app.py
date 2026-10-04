"""Flask entry point: envelope, auth, route registration.

No seeding. The store starts empty on every boot; tests build all state
through the declared API surface.
"""
import os
from functools import wraps

from flask import Flask, jsonify, request

from helpers import ApiError, request_id, wall_ts, err_missing_user_context, err_insufficient_permissions
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
    return error_response("ERR_INVALID_REQUEST", 404, "resource not found")


@app.errorhandler(405)
def handle_405(_):
    return error_response("ERR_INVALID_REQUEST", 404, "resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    import traceback
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", 400, "unhandled server error: %s" % err)


def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or not isinstance(role, str) or not isinstance(user_id, str):
        raise err_missing_user_context()
    if role not in ALL_ROLES:
        raise err_missing_user_context("Unknown role: %s" % role)
    return {"role": role, "user_id": user_id}


def register(method, path, handler, roles):
    endpoint_name = "%s %s" % (method, path)

    @wraps(handler)
    def view(**kwargs):
        user = authenticate()
        if user["role"] not in roles:
            raise err_insufficient_permissions(
                "Role %s is not permitted for %s" % (user["role"], endpoint_name)
            )
        result = handler(user, request, **kwargs)
        if isinstance(result, tuple) and len(result) == 3:
            data, status, pagination = result
            return success_array(data, status, pagination)
        data, status = result
        return success_object(data, status)

    app.add_url_rule(path, endpoint_name, view, methods=[method])


for method, path, handler, roles in ROUTES:
    register(method, path, handler, roles)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
