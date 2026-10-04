from flask import request
from util import ApiErr, ROLES

def caller():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        raise ApiErr("ERR_UNAUTHENTICATED", 401, "missing or unknown X-User-Role / X-User-ID")
    return {"role": role, "id": uid}

def require_role(*roles):
    c = caller()
    if c["role"] not in roles:
        raise ApiErr("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return c
