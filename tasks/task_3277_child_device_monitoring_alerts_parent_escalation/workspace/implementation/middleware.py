"""Auth header extraction, role checking, and scope enforcement."""
from flask import request
from errors import fail
from db import store

ROLES = {"PlatformAdmin", "Parent", "SchoolAdmin", "DeviceAgent"}


def authenticate():
    """Priority 1: headers present and well-formed. Returns (role, user_id)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Malformed X-User-ID or X-User-Role header")
    return role, user_id


def require_role(role, allowed):
    """Priority 2: role listed for endpoint."""
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this endpoint" % role)


def family_id_of_child(child):
    return child.get("family_account_id") if child else None


def family_id_of_device(device):
    if not device:
        return None
    child = store.children.get(device.get("child_profile_id"))
    return family_id_of_child(child)


def family_id_of_connection(conn):
    if not conn:
        return None
    child = store.children.get(conn.get("child_profile_id"))
    return family_id_of_child(child)


def parent_family_id(user_id):
    member = store.parents.get(user_id)
    if not member or member.get("member_status") != "ACTIVE":
        return None
    return member.get("family_account_id")


def require_parent_scope(user_id, family_id):
    """Priority 4: Parent may only touch their own family's resources."""
    if parent_family_id(user_id) != family_id:
        fail("ERR_CROSS_FAMILY_ACCESS", "Resource belongs to a different family")


def school_admin_child_ids(district_id):
    """Children with an ACTIVE DistrictLink to this district."""
    ids = set()
    for link in store.district_links.values():
        if link.get("district_id") == district_id and link.get("link_status") == "ACTIVE":
            ids.add(link.get("child_profile_id"))
    return ids


def require_school_scope_child(user_id, child_id):
    if child_id not in school_admin_child_ids(user_id):
        fail("ERR_CROSS_DISTRICT_ACCESS", "No ACTIVE district link to this child")


def require_school_scope_alert(user_id, alert):
    require_school_scope_child(user_id, alert.get("child_profile_id"))
    if alert.get("severity") not in ("HIGH", "SEVERE"):
        fail("ERR_SEVERITY_VISIBILITY_DENIED", "SchoolAdmin may only view HIGH or SEVERE alerts")
