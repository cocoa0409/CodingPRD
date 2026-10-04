"""Request body shape validation (priority 2.5) and shared cascade logic."""
from flask import request

import store
from errors import err


def get_body():
    """JSON body; must be an object for mutation endpoints."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def require_fields(body, spec):
    """spec: list of (name, kind, required). kind in {'str','int','bool','list','enum:set'}.
    Unknown fields ignored (per §2.11)."""
    for entry in spec:
        name, kind, required = entry
        if name not in body or body[name] is None:
            if required:
                raise err("ERR_INVALID_REQUEST", f"missing required field: {name}")
            continue
        val = body[name]
        if kind == "str":
            if not isinstance(val, str):
                raise err("ERR_INVALID_REQUEST", f"field {name} must be a string")
        elif kind == "int":
            if isinstance(val, bool) or not isinstance(val, int):
                raise err("ERR_INVALID_REQUEST", f"field {name} must be an integer")
        elif kind == "bool":
            if not isinstance(val, bool):
                raise err("ERR_INVALID_REQUEST", f"field {name} must be a boolean")
        elif kind == "list":
            if not isinstance(val, list):
                raise err("ERR_INVALID_REQUEST", f"field {name} must be an array")
        elif kind.startswith("enum:"):
            members = set(kind[5:].split("|"))
            if not isinstance(val, str) or val not in members:
                raise err("ERR_INVALID_REQUEST", f"field {name} must be one of {sorted(members)}")
        elif kind == "int_list":
            if not isinstance(val, list) or any(isinstance(x, bool) or not isinstance(x, int) for x in val):
                raise err("ERR_INVALID_REQUEST", f"field {name} must be an array of integers")


# ---------------------------------------------------------------------------
# Cascades (§3.1, §3.4, §3.6)
# ---------------------------------------------------------------------------

def cascade_grant_suspended(grant):
    """Grant ACTIVE -> SUSPENDED side effects: revoke extension grants, seats_in_use -> 0."""
    for eg in store.extension_grants.values():
        if eg["license_grant_id"] == grant["id"] and eg["status"] == "ACTIVE":
            eg["status"] = "REVOKED"
            store.touch(eg)
    grant["status"] = "SUSPENDED"
    grant["seats_in_use"] = 0
    store.touch(grant)


def cascade_grant_terminal(grant, terminal_status):
    """Grant -> EXPIRED/REVOKED side effects (same as suspension plus terminal status)."""
    for eg in store.extension_grants.values():
        if eg["license_grant_id"] == grant["id"] and eg["status"] == "ACTIVE":
            eg["status"] = "REVOKED"
            store.touch(eg)
    grant["status"] = terminal_status
    grant["seats_in_use"] = 0
    store.touch(grant)


def cascade_user_disabled(user):
    """NamedUser ACTIVE -> DISABLED side effects."""
    user["status"] = "DISABLED"
    store.touch(user)
    grant = store.license_grants.get(user["home_license_grant_id"])
    if grant is not None and grant["seats_in_use"] > 0:
        grant["seats_in_use"] -= 1
        store.touch(grant)
    for key in store.api_keys.values():
        if key["named_user_id"] == user["id"] and key["status"] == "ACTIVE":
            key["status"] = "REVOKED"
            store.touch(key)
    for item in store.content_items.values():
        if (item["owner_named_user_id"] == user["id"]
                and item["status"] == "PUBLISHED"
                and item["sharing_level"] == "PUBLIC"):
            item["sharing_level"] = "ORGANIZATION"
            store.touch(item)


def cascade_org_suspended(org):
    """Organization ACTIVE -> SUSPENDED full cascade (§3.1)."""
    org["status"] = "SUSPENDED"
    store.touch(org)
    for user in store.named_users.values():
        if user["organization_id"] == org["id"] and user["status"] == "ACTIVE":
            cascade_user_disabled(user)
    for grant in store.license_grants.values():
        if grant["organization_id"] == org["id"] and grant["status"] == "ACTIVE":
            cascade_grant_suspended(grant)


def org_of(entity):
    return store.orgs.get(entity.get("organization_id"))
