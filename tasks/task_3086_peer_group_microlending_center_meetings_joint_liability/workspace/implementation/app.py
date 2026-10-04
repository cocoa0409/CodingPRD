"""Flask entry point: envelope helpers, auth/role middleware, error handlers,
and route registration. Binds 0.0.0.0:$PORT (default 10000)."""
import os
import secrets
import string

from flask import Flask, jsonify, request

import core as C
import routes_admin
import routes_lending

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": C.fmt_created(C.now_dt()),
    }


def envelope_ok(data, status=200, meta_extra=None):
    meta = meta_base()
    if meta_extra:
        meta.update(meta_extra)
    response_type = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


# ---------------------------------------------------------------------------
# RBAC table
# ---------------------------------------------------------------------------
ALL_ROLES = {"ProgramAdmin", "BranchManager", "CenterManager", "FieldOfficer", "Member"}

WRITE_ROLES = {
    ("POST", "/_clock/set_current_utc"): {"ProgramAdmin"},
    ("POST", "/branches"): {"ProgramAdmin"},
    ("POST", "/branches/{id}/expansion-plans"): {"BranchManager"},
    ("POST", "/expansion-plans/{id}/decide"): {"ProgramAdmin"},
    ("POST", "/center-managers"): {"ProgramAdmin"},
    ("POST", "/centers"): {"ProgramAdmin"},
    ("PATCH", "/centers/{id}"): {"ProgramAdmin"},
    ("POST", "/peer-groups"): {"FieldOfficer"},
    ("POST", "/peer-groups/{id}/members"): {"FieldOfficer"},
    ("POST", "/peer-groups/{id}/dissolve"): {"FieldOfficer"},
    ("POST", "/peer-groups/{id}/loan-applications"): {"FieldOfficer"},
    ("POST", "/members"): {"FieldOfficer"},
    ("POST", "/members/{id}/savings/withdrawals"): {"Member"},
    ("POST", "/members/{id}/savings/unfreeze"): {"ProgramAdmin"},
    ("POST", "/members/{id}/savings/close"): {"Member"},
    ("POST", "/group-training-sessions"): {"CenterManager"},
    ("POST", "/group-training-sessions/{id}/complete"): {"CenterManager"},
    ("POST", "/group-training-sessions/{id}/cancel"): {"CenterManager"},
    ("POST", "/loan-applications/{id}/submit"): {"FieldOfficer"},
    ("POST", "/loan-applications/{id}/votes"): {"Member"},
    ("POST", "/loan-applications/{id}/disburse"): {"BranchManager"},
    ("POST", "/loans/{id}/restructures"): {"BranchManager"},
    ("POST", "/center-meetings"): {"CenterManager"},
    ("POST", "/center-meetings/{id}/open"): {"CenterManager"},
    ("POST", "/center-meetings/{id}/cancel"): {"CenterManager"},
    ("POST", "/center-meetings/{id}/attendance"): {"CenterManager"},
    ("POST", "/center-meetings/{id}/collections"): {"CenterManager"},
    ("POST", "/center-meetings/{id}/close"): {"CenterManager"},
    ("POST", "/center-meetings/{id}/reconcile"): {"BranchManager"},
    ("POST", "/repayment-transactions/{id}/void"): {"BranchManager"},
}


def match_write_rule(method, path):
    for (m, template), roles in WRITE_ROLES.items():
        if m != method:
            continue
        t_parts = [p for p in template.strip("/").split("/") if p != ""]
        p_parts = [p for p in path.strip("/").split("/") if p != ""]
        if len(t_parts) != len(p_parts):
            continue
        matched = True
        for tp, pp in zip(t_parts, p_parts):
            if tp.startswith("{") and tp.endswith("}"):
                continue
            if tp != pp:
                matched = False
                break
        if matched:
            return roles
    return None


@app.before_request
def authenticate():
    if request.endpoint == "static":
        return None
    if request.method not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
        return None
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "" \
            or role not in C.ROLES:
        raise C.err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID and X-User-Role headers must be present and non-empty")
    if request.method == "GET":
        return None
    roles = match_write_rule(request.method, request.path)
    if roles is not None and role not in roles:
        raise C.err("ERR_INSUFFICIENT_PERMISSIONS",
                    "Role is not permitted to invoke this endpoint")
    return None


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.errorhandler(C.ApiError)
def handle_api_error(e):
    return jsonify({
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


@app.errorhandler(404)
def handle_not_found(e):
    return jsonify({
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Resource not found"},
    }), 404


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return jsonify({
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    return jsonify({
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST",
                 "message": "Unexpected server error: %s" % type(e).__name__},
    }), 500


app.register_blueprint(routes_admin.bp)
app.register_blueprint(routes_lending.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
