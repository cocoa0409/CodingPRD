"""Authentication, role authorization and entity-backed ownership (PRD 2.1 / 2.11)."""
from __future__ import annotations

from flask import g, request

from errors import ApiError
from store import store

ROLES = ("CEManager", "BiomedTech", "SecurityOfficer", "DeptSteward", "VendorRep")


def authenticate(allowed_roles):
    """Steps 1 and 2 of the rejection order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not call this endpoint." % role)
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def current_user():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)


def _violation():
    return ApiError("ERR_OWNERSHIP_VIOLATION", "The caller does not own the addressed resource.")


# --------------------------------------------------------------------------
# ownership checks — step 3, evaluated before path/body existence whenever the
# addressed row can be resolved.
# --------------------------------------------------------------------------

def own_department(dept_id):
    """A DeptSteward may only read its own Department row."""
    if current_role() == "DeptSteward" and dept_id is not None and dept_id != current_user():
        raise _violation()


def own_device(device):
    """A DeptSteward may only act on devices in its own department."""
    if current_role() == "DeptSteward" and device is not None:
        if device.get("department_id") != current_user():
            raise _violation()


def own_device_id(device_id):
    if current_role() != "DeptSteward":
        return
    device = store.get("Device", device_id)
    if device is not None:
        own_device(device)


def own_work_order(work_order):
    """DeptSteward owns the order through its device's department; VendorRep
    owns it through the order's vendor_id."""
    if work_order is None:
        return
    role = current_role()
    if role == "DeptSteward":
        device = store.get("Device", work_order.get("device_id"))
        if device is not None and device.get("department_id") != current_user():
            raise _violation()
    elif role == "VendorRep":
        if work_order.get("vendor_id") != current_user():
            raise _violation()


def own_work_order_id(work_order_id):
    work_order = store.get("WorkOrder", work_order_id)
    if work_order is not None:
        own_work_order(work_order)


def own_loaner(assignment):
    if assignment is None:
        return
    if current_role() == "DeptSteward":
        own_work_order_id(assignment.get("work_order_id"))


def own_service_contract(contract):
    if contract is None:
        return
    if current_role() == "VendorRep" and contract.get("vendor_id") != current_user():
        raise _violation()
