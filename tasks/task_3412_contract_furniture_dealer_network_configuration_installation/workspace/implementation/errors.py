# Error surface (PRD 2.2 error envelope; PRD 5 catalog; scaffold Table 6).
from flask import jsonify

import clock


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# --- Convenience raisers pinned to the PRD 5 catalog ---

def unauthenticated(msg="Missing X-User-Role or X-User-ID header, or unknown role"):
    err("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized_role(msg="Role is not authorized for this endpoint"):
    err("ERR_UNAUTHORIZED_ROLE", 403, msg)


def forbidden_ownership(msg="Resource is outside the caller's ownership scope"):
    err("ERR_FORBIDDEN_OWNERSHIP", 403, msg)


def validation(msg="Request body shape violation"):
    err("ERR_VALIDATION", 400, msg)


def date_window(msg="Field-level date window invalid"):
    err("ERR_DATE_WINDOW_INVALID", 400, msg)


def not_found(error_id, msg):
    err(error_id, 404, msg)


def stale_version(msg="Expected version does not match the entity's current version"):
    err("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="Invalid state transition for the resource's current state"):
    err("ERR_INVALID_STATE", 409, msg)


def error_response_body(error_id, message):
    return {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": clock.now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _request_id():
    import uuid
    return "req_" + uuid.uuid4().hex[:24]


def api_error_response(exc):
    return jsonify(error_response_body(exc.error_id, exc.message)), exc.http_status
