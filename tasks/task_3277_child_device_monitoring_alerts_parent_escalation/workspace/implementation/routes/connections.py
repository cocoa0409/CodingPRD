"""Service connection routes: get, state transitions, content-item listing."""
from flask import Blueprint, request
from db import store
from errors import fail
from response import success_object, success_list, parse_pagination
from middleware import authenticate, require_role, require_parent_scope, family_id_of_connection
import services as svc

bp = Blueprint("connections", __name__)

CONNECTION_STATUSES = {"AWAITING_CONSENT", "ACTIVE", "PAUSED", "REVOKED"}

EDGES = {
    ("AWAITING_CONSENT", "ACTIVE"),
    ("ACTIVE", "PAUSED"),
    ("PAUSED", "ACTIVE"),
    ("ACTIVE", "REVOKED"),
    ("PAUSED", "REVOKED"),
    ("REVOKED", "AWAITING_CONSENT"),
}


def _get_connection(conn_id):
    conn = store.connections.get(conn_id)
    if not conn:
        fail("ERR_NOT_FOUND", "Connection not found")
    return conn


@bp.get("/api/connections/<conn_id>")
def get_connection(conn_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    conn = _get_connection(conn_id)
    if role == "Parent":
        require_parent_scope(uid, family_id_of_connection(conn))
    return success_object(svc.ser_connection(conn))


@bp.get("/api/connections/<conn_id>/content-items")
def list_connection_content(conn_id):
    role, _uid = authenticate()
    require_role(role, {"PlatformAdmin"})
    conn = _get_connection(conn_id)
    limit, offset = parse_pagination(request.args)
    items = [ci for ci in store.content_items.values()
             if ci.get("service_connection_id") == conn["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_content_item(ci, include_raw=True) for ci in page],
                        limit, offset, total)


@bp.post("/api/connections/<conn_id>/state")
def connection_state(conn_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    conn = _get_connection(conn_id)
    require_parent_scope(uid, family_id_of_connection(conn))
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if to_status not in CONNECTION_STATUSES:
        fail("ERR_INVALID_REQUEST", "invalid to_status")
    current = conn["consent_status"]
    if (current, to_status) not in EDGES:
        fail("ERR_INVALID_STATE",
             "Transition %s -> %s not permitted" % (current, to_status))
    child = store.children.get(conn["child_profile_id"])
    family = store.families.get(child["family_account_id"]) if child else None
    if to_status == "ACTIVE" and current == "AWAITING_CONSENT":
        if child and child["profile_status"] != "ACTIVE":
            fail("ERR_CHILD_ARCHIVED", "Child is archived")
        if family and family["account_status"] != "ACTIVE":
            fail("ERR_FAMILY_SUSPENDED", "Family is suspended")
    elif to_status == "ACTIVE" and current == "PAUSED":
        if child and child["profile_status"] != "ACTIVE":
            fail("ERR_CHILD_ARCHIVED", "Child is archived")
    elif to_status == "AWAITING_CONSENT" and current == "REVOKED":
        if child and child["profile_status"] != "ACTIVE":
            fail("ERR_CHILD_ARCHIVED", "Child is archived")
    with store.lock:
        conn["consent_status"] = to_status
        svc.touch(conn)
    return success_object(svc.ser_connection(conn))
