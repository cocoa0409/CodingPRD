"""Platform namespace: logical clock, role permissions, payment simulation."""
from auth import KNOWN_ROLES
from errors import fail, invalid
from http_support import Endpoint, as_enum, as_list, as_string, req
from response import ok_object
from util import norm_dt

PLATFORM = ["PlatformAdmin"]

OUTCOMES = ("APPROVED", "DECLINED", "PENDING")


def register(app):
    Endpoint(app, "POST", "/_clock/set_current_utc", PLATFORM, set_clock)
    Endpoint(app, "POST", "/_rbac/role-permissions", PLATFORM, role_permissions)
    Endpoint(app, "POST", "/_payments/simulate", PLATFORM, simulate_payment)


def set_clock(store, actor, view_args):
    payload = _body()
    raw = req(payload, "current_utc")
    try:
        store.clock = norm_dt(raw)
    except (TypeError, ValueError):
        invalid("current_utc must be an ISO 8601 instant.")
    return ok_object(store, {"current_utc": store.clock})


def role_permissions(store, actor, view_args):
    payload = _body()
    role = as_string(req(payload, "role"), "role")
    if role not in KNOWN_ROLES:
        invalid("role must be one of %s." % ", ".join(KNOWN_ROLES))
    permissions = [as_string(p, "permissions[]") for p in as_list(req(payload, "permissions"), "permissions")]
    # The replacement is authoritative even when empty: an empty list omits
    # every operation, which is exactly the denial path this capability exists
    # to exercise.
    store.role_permissions[role] = permissions
    active_role_count = sum(
        1 for value in store.role_permissions.values() if value
    )
    return ok_object(store, {
        "role": role,
        "permissions": permissions,
        "active_role_count": active_role_count,
    })


def simulate_payment(store, actor, view_args):
    payload = _body()
    order_id = as_string(req(payload, "catering_order_id"), "catering_order_id")
    outcome = as_enum(req(payload, "outcome"), OUTCOMES, "outcome")
    if order_id not in store.catering_orders:
        fail("ERR_NOT_FOUND")
    store.payments.append({
        "catering_order_id": order_id,
        "outcome": outcome,
    })
    return ok_object(store, {"catering_order_id": order_id, "outcome": outcome})


def _body():
    from http_support import body
    return body()