from flask import request

from errors import err
from helpers import VALID_ROLES


def ctx():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in VALID_ROLES or not uid:
        raise err("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return {"role": role, "uid": uid}


def require_roles(c, allowed):
    if c["role"] not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", 403, "role not permitted for this endpoint")


def enforce_ownership(c, member_id):
    if c["role"] == "Member" and c["uid"] != member_id:
        raise err("ERR_FORBIDDEN_ROLE", 403, "ownership mismatch")
