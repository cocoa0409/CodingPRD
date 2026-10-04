"""Associate and Certification groups, including the suspension cascade."""
from errors import fail, invalid
from http_support import (
    Endpoint, as_list, as_string, body, envelope_array, opt, query, req,
)
from response import ok_object
from util import dt_add_hours, norm_dt, parse_dt
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
WRITE_ROLES = ["PlatformAdmin", "DeliManager"]

PRIMARY_ROLES = ("DELI_CLERK", "DELI_MANAGER", "BAKERY_COORDINATOR")
CERT_TYPES = ("SLICER_OPERATION", "FOOD_HANDLING", "ALLERGEN_MANAGEMENT")
CERT_STATUSES = ("ACTIVE", "EXPIRED", "REVOKED", "RENEWED")
ASSOC_STATUSES = ("ACTIVE", "SUSPENDED")
ALLERGENS = ("MILK", "WHEAT", "SOY", "EGG", "FISH", "SESAME")
SUSPEND_REASONS = ("CERTIFICATION_EXPIRED", "SAFETY_VIOLATION", "TRANSFER")

# At most two reopenings per slicer per production day.
MAX_REOPEN_PER_DAY = 2


def register(app):
    Endpoint(app, "POST", "/deli/associates", WRITE_ROLES, create_associate)
    Endpoint(app, "GET", "/deli/associates/<id>", READ_ROLES, get_associate)
    Endpoint(app, "GET", "/deli/associates", READ_ROLES, list_associates)
    Endpoint(app, "POST", "/deli/associates/<id>/suspend", WRITE_ROLES, suspend)
    Endpoint(app, "POST", "/deli/associates/<id>/reinstate", WRITE_ROLES, reinstate)
    Endpoint(app, "GET", "/deli/associates/<id>/sanitation-usage", READ_ROLES,
             sanitation_usage)
    Endpoint(app, "GET", "/deli/associates/<id>/certification-usage", READ_ROLES,
             certification_usage)

    Endpoint(app, "POST", "/deli/certifications", WRITE_ROLES, create_cert)
    Endpoint(app, "GET", "/deli/certifications/<id>", READ_ROLES, get_cert)
    Endpoint(app, "GET", "/deli/certifications", READ_ROLES, list_certs)
    Endpoint(app, "POST", "/deli/certifications/<id>/renew", WRITE_ROLES, renew)
    Endpoint(app, "POST", "/deli/certifications/<id>/revoke", WRITE_ROLES, revoke)
    Endpoint(app, "POST", "/deli/certifications/<id>/reopen", WRITE_ROLES, reopen)
    Endpoint(app, "GET", "/deli/certifications/<id>/waste-usage", READ_ROLES,
             waste_usage)


# ------------------------------------------------------------- associates -----
def create_associate(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    employee_number = as_string(req(payload, "employee_number"), "employee_number")
    if any(a["employee_number"] == employee_number for a in store.associates.values()):
        invalid("employee_number must be unique across the chain.")
    primary_role = req(payload, "primary_role")
    if primary_role not in PRIMARY_ROLES:
        invalid("primary_role must be one of %s." % ", ".join(PRIMARY_ROLES))
    allergy_set = as_list(opt(payload, "allergy_set", default=[]), "allergy_set")
    for flag in allergy_set:
        if flag not in ALLERGENS:
            invalid("allergy_set must be drawn from %s." % ", ".join(ALLERGENS))
    row = svc.create(store, "associates", {
        "store_id": store_id,
        "employee_number": employee_number,
        "full_name": as_string(req(payload, "full_name"), "full_name"),
        "primary_role": primary_role,
        "status": "ACTIVE",
        "allergy_set": list(allergy_set),
        "active_certification_count": 0,
        "assigned_slicer_id": None,
    })
    svc.recompute_store(store, store_id)
    return ok_object(store, views.associate(row), 201)


def get_associate(store, actor, view_args):
    row = svc.get_plain(store, "associates", view_args["id"])
    _refresh_associate(store, row)
    return ok_object(store, views.associate(row))


def list_associates(store, actor, view_args):
    rows = svc.all_rows(store, "associates")
    for row in rows:
        _refresh_associate(store, row)
    store_id = query("store_id")
    primary_role = query("primary_role")
    status = query("status")
    if store_id:
        rows = [r for r in rows if r["store_id"] == store_id]
    if primary_role:
        rows = [r for r in rows if r["primary_role"] == primary_role]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return envelope_array(store, rows, views.associate)


def _refresh_associate(store, row):
    count = calc.active_certification_count(
        svc.all_rows(store, "certifications"), row["id"], store.now())
    if row["active_certification_count"] != count:
        row["active_certification_count"] = count
        svc.touch(store, row)


def suspend(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "associates", view_args["id"])
    reason = req(payload, "reason")
    if reason not in SUSPEND_REASONS:
        invalid("reason must be one of %s." % ", ".join(SUSPEND_REASONS))
    if row["status"] == "SUSPENDED":
        fail("ERR_INVALID_STATE")
    store_id = row["store_id"]
    row["status"] = "SUSPENDED"
    svc.touch(store, row)

    # Cascade 1a: every certification the associate holds is revoked.
    for cert in svc.all_rows(store, "certifications"):
        if cert["associate_id"] == row["id"] and cert["status"] != "REVOKED":
            cert["status"] = "REVOKED"
            svc.touch(store, cert)
    # Cascade 1b: recompute the certified-slicer count; HALT when it reaches 0.
    svc.recompute_store(store, store_id, bump=False)
    if store.stores[store_id]["posture"] == "HALT":
        svc.store_halt_cascade(store, store_id)
    svc.recompute_store(store, store_id, bump=False)
    _refresh_associate(store, row)
    return ok_object(store, views.associate(row))


def reinstate(store, actor, view_args):
    row = svc.get_plain(store, "associates", view_args["id"])
    if row["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE")
    row["status"] = "ACTIVE"
    svc.touch(store, row)
    svc.recompute_store(store, row["store_id"])
    _refresh_associate(store, row)
    return ok_object(store, views.associate(row))


def sanitation_usage(store, actor, view_args):
    row = svc.get_plain(store, "associates", view_args["id"])
    rows = [c for c in svc.all_rows(store, "sanitation_cycles")
            if c["verified_by_associate_id"] == row["id"]]
    return envelope_array(store, rows, views.cycle)


def certification_usage(store, actor, view_args):
    row = svc.get_plain(store, "associates", view_args["id"])
    rows = [c for c in svc.all_rows(store, "certifications")
            if c["revoked_by_manager_id"] == row["id"]]
    return envelope_array(store, rows, views.certification)


# --------------------------------------------------------- certifications -----
def create_cert(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    associate_id = as_string(req(payload, "associate_id"), "associate_id")
    associate = svc.get_associate(store, associate_id)
    if associate["store_id"] != store_id:
        fail("ERR_NOT_FOUND")
    cert_type = req(payload, "cert_type")
    if cert_type not in CERT_TYPES:
        invalid("cert_type must be one of %s." % ", ".join(CERT_TYPES))
    issued = _instant(req(payload, "issued_at"), "issued_at")
    expires = _instant(req(payload, "expires_at"), "expires_at")
    if parse_dt(expires) <= parse_dt(issued):
        invalid("expires_at must be strictly after issued_at.")
    deli_item_id = opt(payload, "deli_item_id")
    if deli_item_id is not None:
        svc.get_plain(store, "items", deli_item_id)
    row = svc.create(store, "certifications", {
        "store_id": store_id,
        "associate_id": associate_id,
        "deli_item_id": deli_item_id,
        "revoked_by_manager_id": None,
        "cert_type": cert_type,
        "issued_at": issued,
        "expires_at": expires,
        "status": "ACTIVE",
        "grace_reminder": False,
    })
    svc.refresh_certification_counters(store, store_id)
    svc.recompute_store(store, store_id)
    _refresh_associate(store, associate)
    return ok_object(store, views.certification(row), 201)


def get_cert(store, actor, view_args):
    row = svc.get_plain(store, "certifications", view_args["id"])
    _refresh_cert(store, row)
    return ok_object(store, views.certification(row))


def list_certs(store, actor, view_args):
    rows = svc.all_rows(store, "certifications")
    for row in rows:
        _refresh_cert(store, row)
    for name, key in (("associate_id", "associate_id"), ("store_id", "store_id"),
                      ("cert_type", "cert_type"), ("status", "status")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.certification)


def _refresh_cert(store, row):
    flag = calc.grace_reminder(row, store.now())
    if row["grace_reminder"] != flag:
        row["grace_reminder"] = flag
        svc.touch(store, row)


def renew(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "certifications", view_args["id"])
    if row["status"] != "EXPIRED":
        fail("ERR_INVALID_STATE")
    expires = _instant(req(payload, "expires_at"), "expires_at")
    issued = store.now()
    if parse_dt(expires) <= parse_dt(issued):
        invalid("expires_at must be strictly after the logical clock.")
    successor = svc.create(store, "certifications", {
        "store_id": row["store_id"],
        "associate_id": row["associate_id"],
        "deli_item_id": row["deli_item_id"],
        "revoked_by_manager_id": None,
        "cert_type": row["cert_type"],
        "issued_at": issued,
        "expires_at": expires,
        "status": "ACTIVE",
        "grace_reminder": False,
    })
    row["status"] = "RENEWED"
    svc.touch(store, row)
    svc.refresh_certification_counters(store, row["store_id"])
    svc.recompute_store(store, row["store_id"])
    associate = store.associates.get(row["associate_id"])
    if associate is not None:
        _refresh_associate(store, associate)
    return ok_object(store, views.certification(successor))


def revoke(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "certifications", view_args["id"])
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    manager_id = as_string(req(payload, "revoked_by_manager_id"),
                           "revoked_by_manager_id")
    # Self-dealing rule: a manager cannot revoke their own credential.
    if manager_id == row["associate_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    svc.get_associate(store, manager_id)
    row["revoked_by_manager_id"] = manager_id
    row["status"] = "REVOKED"
    svc.touch(store, row)
    store_id = row["store_id"]
    svc.refresh_certification_counters(store, store_id)
    svc.recompute_store(store, store_id, bump=False)
    if store.stores[store_id]["posture"] == "HALT":
        svc.store_halt_cascade(store, store_id)
        svc.recompute_store(store, store_id, bump=False)
    associate = store.associates.get(row["associate_id"])
    if associate is not None:
        _refresh_associate(store, associate)
    return ok_object(store, views.certification(row))


def reopen(store, actor, view_args):
    row = svc.get_plain(store, "certifications", view_args["id"])
    if row["status"] != "RENEWED":
        fail("ERR_INVALID_STATE")
    row["issued_at"] = store.now()
    row["expires_at"] = dt_add_hours(store.now(), 24 * 365)
    row["status"] = "ACTIVE"
    svc.touch(store, row)
    svc.refresh_certification_counters(store, row["store_id"])
    svc.recompute_store(store, row["store_id"])
    associate = store.associates.get(row["associate_id"])
    if associate is not None:
        _refresh_associate(store, associate)
    return ok_object(store, views.certification(row))


def waste_usage(store, actor, view_args):
    row = svc.get_plain(store, "certifications", view_args["id"])
    rows = [w for w in svc.all_rows(store, "waste_records")
            if w["verified_by_certification_id"] == row["id"]]
    return envelope_array(store, rows, views.waste)


def _instant(raw, field):
    try:
        return norm_dt(raw)
    except (TypeError, ValueError):
        invalid("%s must be an ISO 8601 instant." % field)