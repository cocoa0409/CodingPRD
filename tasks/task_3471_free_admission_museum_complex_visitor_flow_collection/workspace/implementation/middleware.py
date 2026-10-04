"""Auth header extraction and role/ownership helpers (PRD 2.1, 2.8).

Pipeline priorities 1-4:
  1. X-User-Role and X-User-ID present and non-empty -> else ERR_UNAUTHENTICATED (401)
  2. Role in the endpoint's authorized list -> else ERR_UNAUTHORIZED_ROLE (403)
     (resource-dependent ownership checks run in the handlers right after the
     resource is loaded, since they cannot be evaluated without it)
  3./4. Path- and body-referenced resources exist -> else ERR_NOT_FOUND (404)
"""

from flask import request

import db
from errors import fail


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        fail(
            "ERR_UNAUTHORIZED_ROLE",
            f"Role '{role}' is not authorized for this endpoint",
        )


def get_or_404(collection, resource_id, label="Resource"):
    obj = db.STORE[collection].get(resource_id)
    if obj is None:
        fail("ERR_NOT_FOUND", f"{label} not found: {resource_id}")
    return obj
