"""Request guards: body parsing, identity, authorization and path resolution."""
from flask import request

from core import DB, fail

ROLES = {
    "PLATFORM_ADMIN": "PlatformAdmin",
    "PRINT_OPERATIONS_DIRECTOR": "PrintOperationsDirector",
    "DELIVERY_NETWORK_MANAGER": "DeliveryNetworkManager",
    "NEWSROOM_OPERATIONS_MANAGER": "NewsroomOperationsManager",
    "CUSTOMER_SERVICE": "CustomerService",
    "SUBSCRIBER": "Subscriber",
    "AUDITOR": "Auditor",
}


def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def identity(endpoint_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        fail("ERR_UNAUTHENTICATED")
    if role not in set(ROLES.values()):
        fail("ERR_UNAUTHENTICATED")
    if role == "Subscriber":
        if DB.get("subscribers", uid) is None:
            fail("ERR_UNAUTHENTICATED")
    if role not in endpoint_roles:
        fail("ERR_UNAUTHORIZED")
    return role, uid


def role_of():
    return request.headers.get("X-User-Role")


def resolve_path(*pairs):
    """Resolve (collection, id) pairs left to right. Returns the resolved rows."""
    rows = []
    for coll, rid in pairs:
        row = DB.get(coll, rid)
        if row is None:
            fail("ERR_RESOURCE_NOT_FOUND")
        rows.append(row)
    return rows


def resolve_path_scoped(parent_coll, parent_id, child_coll, child_id, fk_field):
    parent = path_one(parent_coll, parent_id)
    child = DB.get(child_coll, child_id)
    if child is None or child.get(fk_field) != parent.get("id"):
        fail("ERR_RESOURCE_NOT_FOUND")
    return parent, child


def path_one(coll, rid):
    row = DB.get(coll, rid)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return row


def require_row(coll, rid, error_id="ERR_REFERENCE_NOT_FOUND"):
    row = DB.get(coll, rid)
    if row is None:
        fail(error_id)
    return row


def query_pagination():
    return request.args.get("limit"), request.args.get("offset")