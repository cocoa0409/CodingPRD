"""Admin-domain routes: logical clock, patients, suppliers, par-level
policies, transport coolers, cooler checkouts, wastage views."""

from flask import Blueprint, request

import errors as E
import logic
import store
from common import (
    endpoint, get_body, req_str, opt_str, req_int, opt_int, req_enum,
    req_dt, opt_dt, req_date_ymd, opt_str_list, as_int,
    patient_by_path, supplier_by_path, policy_by_path, cooler_by_path,
    checkout_by_path, wastage_by_path, fk_exists,
)
from constants import (
    ROLES, ABO_TYPES, RH_TYPES, PRODUCT_TYPES, SPECIAL_REQUIREMENTS,
    WASTAGE_REASONS, MAX_CHECKOUT_DURATION_HOURS,
    COOLER_REDISPATCH_BUFFER_MINUTES,
)
from datetime import timedelta
from envelope import object_response, list_response
from errors import ApiError
from serializers import (
    ser_patient, ser_supplier, ser_policy, ser_cooler, ser_checkout, ser_wastage,
)
from store import DB, new_entity, touch, now, set_clock
from timeutil import fmt_dt, parse_dt

bp = Blueprint("admin", __name__)

ALL = ROLES
SUPERVISOR = ["BloodBankSupervisor"]
TECH = ["BloodBankTechnologist"]


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/_clock/set_current_utc")
@endpoint(SUPERVISOR)
def clock_set(user_id, role):
    body = get_body()
    target = req_dt(body, "to_iso8601")
    set_clock(target)
    return object_response({"current_utc": fmt_dt(store.now())})


@bp.post("/blood-bank/_clock/sweep")
@endpoint(SUPERVISOR)
def clock_sweep(user_id, role):
    counts = logic.run_sweep()
    return object_response(counts)


# ---------------------------------------------------------------------------
# Patients (PRD 3.1)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/patients")
@endpoint(["BloodBankTechnologist", "BloodBankSupervisor"])
def patient_create(user_id, role):
    body = get_body()
    mrn = req_str(body, "mrn")
    full_name = req_str(body, "full_name")
    dob = req_date_ymd(body, "date_of_birth")
    special = opt_str_list(body, "special_requirements", allowed=SPECIAL_REQUIREMENTS)
    if any(p["mrn"] == mrn for p in DB.patients.values()):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"mrn {mrn} is already registered")
    patient = new_entity({
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": dob,
        "special_requirements": special,
        "current_abo_type": "UNKNOWN",
        "current_rh_type": "UNKNOWN",
        "antibody_status": "UNKNOWN",
        "identified_antibodies": [],
        "abo_confirmed": False,
        "total_units_transfused": 0,
    })
    DB.patients[patient["id"]] = patient
    return object_response(ser_patient(patient), status=201)


@bp.get("/blood-bank/patients")
@endpoint(ALL)
def patient_list(user_id, role):
    rows = list(DB.patients.values())
    mrn = request.args.get("mrn")
    if mrn is not None:
        rows = [p for p in rows if p["mrn"] == mrn]
    abo = request.args.get("current_abo_type")
    if abo is not None:
        rows = [p for p in rows if p["current_abo_type"] == abo]
    active = request.args.get("has_active_type_and_screen")
    if active is not None:
        flag = active.strip().lower()
        if flag in ("true", "false"):
            want = flag == "true"
            rows = [p for p in rows if logic.patient_has_active_ts(p["id"]) == want]
        else:
            rows = []
    return list_response(rows, request.args, ser_patient)


@bp.get("/blood-bank/patients/<pid>")
@endpoint(ALL)
def patient_get(pid, user_id, role):
    return object_response(ser_patient(patient_by_path(pid)))


# ---------------------------------------------------------------------------
# Suppliers (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/suppliers")
@endpoint(SUPERVISOR)
def supplier_create(user_id, role):
    body = get_body()
    name = req_str(body, "name")
    license_number = req_str(body, "license_number")
    lead = opt_int(body, "default_lead_time_hours", default=48)
    if any(s["license_number"] == license_number for s in DB.suppliers.values()):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"license_number {license_number} is already registered")
    supplier = new_entity({
        "name": name,
        "license_number": license_number,
        "default_lead_time_hours": lead,
        "status": "ACTIVE",
        "suspended_at": None,
        "suspend_reason": None,
    })
    DB.suppliers[supplier["id"]] = supplier
    return object_response(ser_supplier(supplier), status=201)


@bp.get("/blood-bank/suppliers")
@endpoint(ALL)
def supplier_list(user_id, role):
    rows = list(DB.suppliers.values())
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return list_response(rows, request.args, ser_supplier)


@bp.get("/blood-bank/suppliers/<sid>")
@endpoint(ALL)
def supplier_get(sid, user_id, role):
    return object_response(ser_supplier(supplier_by_path(sid)))


@bp.post("/blood-bank/suppliers/<sid>/suspend")
@endpoint(SUPERVISOR)
def supplier_suspend(sid, user_id, role):
    supplier = supplier_by_path(sid)
    body = get_body()
    reason = req_str(body, "reason")
    if supplier["status"] != "ACTIVE":
        raise ApiError(E.ERR_SUPPLIER_SUSPENDED, 409, "Supplier is not ACTIVE")
    supplier["status"] = "SUSPENDED"
    supplier["suspended_at"] = now()
    supplier["suspend_reason"] = reason
    touch(supplier)
    # Cascade-hold every live unit of this supplier (PRD 2.11, 3.2).
    for unit in DB.units.values():
        if unit["supplier_id"] == supplier["id"] and unit["status"] in (
            "QUARANTINED", "AVAILABLE", "RESERVED",
        ):
            logic.hold_unit(unit, "SUPPLIER_SUSPENSION")
    return object_response(ser_supplier(supplier))


@bp.post("/blood-bank/suppliers/<sid>/reinstate")
@endpoint(SUPERVISOR)
def supplier_reinstate(sid, user_id, role):
    supplier = supplier_by_path(sid)
    if supplier["status"] != "SUSPENDED":
        raise ApiError(E.ERR_SUPPLIER_SUSPENDED, 409, "Supplier is not SUSPENDED")
    supplier["status"] = "ACTIVE"
    supplier["suspended_at"] = None
    touch(supplier)
    # Release exactly the SUPPLIER_SUSPENSION holds — always to AVAILABLE,
    # regardless of hold origin (the crossmatch was cancelled at hold time).
    for unit in DB.units.values():
        if unit["status"] == "QUARANTINED_HOLD" and unit["hold_reason"] == "SUPPLIER_SUSPENSION":
            logic.release_hold_to_available(unit)
    return object_response(ser_supplier(supplier))


# ---------------------------------------------------------------------------
# Par-level policies (PRD 3.8)
# ---------------------------------------------------------------------------

def _check_threshold_order(watch, shortage, critical):
    if not (watch >= shortage >= critical >= 0):
        raise ApiError(
            E.ERR_THRESHOLD_ORDER_INVALID, 400,
            "Thresholds must satisfy watch >= shortage >= critical >= 0",
        )


@bp.post("/blood-bank/par-level-policies")
@endpoint(SUPERVISOR)
def policy_create(user_id, role):
    body = get_body()
    product_type = req_enum(body, "product_type", PRODUCT_TYPES)
    abo_type = req_enum(body, "abo_type", ABO_TYPES)
    rh_type = req_enum(body, "rh_type", RH_TYPES)
    watch = as_int(body.get("watch_threshold"), "watch_threshold") if body.get("watch_threshold") is not None else None
    shortage = as_int(body.get("shortage_threshold"), "shortage_threshold") if body.get("shortage_threshold") is not None else None
    critical = as_int(body.get("critical_threshold"), "critical_threshold") if body.get("critical_threshold") is not None else None
    if watch is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field 'watch_threshold': is required")
    if shortage is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field 'shortage_threshold': is required")
    if critical is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field 'critical_threshold': is required")
    min_shelf = opt_int(body, "min_shelf_life_hours", default=4, min_value=0)
    # Bucket uniqueness before threshold ordering (validation priority 18 < 19).
    if logic.active_policy_for(product_type, abo_type, rh_type) is not None:
        raise ApiError(
            E.ERR_POLICY_BUCKET_DUPLICATE, 409,
            f"An ACTIVE policy already exists for bucket {product_type}:{abo_type}:{rh_type}",
        )
    _check_threshold_order(watch, shortage, critical)
    policy = new_entity({
        "product_type": product_type,
        "abo_type": abo_type,
        "rh_type": rh_type,
        "watch_threshold": watch,
        "shortage_threshold": shortage,
        "critical_threshold": critical,
        "min_shelf_life_hours": min_shelf,
        "status": "ACTIVE",
    })
    DB.policies[policy["id"]] = policy
    return object_response(ser_policy(policy), status=201)


@bp.get("/blood-bank/par-level-policies")
@endpoint(ALL)
def policy_list(user_id, role):
    rows = list(DB.policies.values())
    product = request.args.get("product_type")
    if product is not None:
        rows = [p for p in rows if p["product_type"] == product]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return list_response(rows, request.args, ser_policy)


@bp.get("/blood-bank/par-level-policies/<pid>")
@endpoint(ALL)
def policy_get(pid, user_id, role):
    return object_response(ser_policy(policy_by_path(pid)))


@bp.put("/blood-bank/par-level-policies/<pid>")
@endpoint(SUPERVISOR)
def policy_update(pid, user_id, role):
    policy = policy_by_path(pid)
    body = get_body()
    expected = req_int(body, "expected_policy_version")
    # OCC (priority 6) precedes the ACTIVE state check (priority 7).
    if expected != policy["version"]:
        raise ApiError(
            E.ERR_STALE_VERSION, 412,
            f"expected_policy_version {expected} does not match current version {policy['version']}",
        )
    if policy["status"] != "ACTIVE":
        raise ApiError(E.ERR_POLICY_NOT_ACTIVE, 409, "Policy is not ACTIVE")
    watch = opt_int(body, "watch_threshold", default=policy["watch_threshold"])
    shortage = opt_int(body, "shortage_threshold", default=policy["shortage_threshold"])
    critical = opt_int(body, "critical_threshold", default=policy["critical_threshold"])
    min_shelf = opt_int(body, "min_shelf_life_hours", default=policy["min_shelf_life_hours"], min_value=0)
    _check_threshold_order(watch, shortage, critical)
    policy["watch_threshold"] = watch
    policy["shortage_threshold"] = shortage
    policy["critical_threshold"] = critical
    policy["min_shelf_life_hours"] = min_shelf
    touch(policy)
    return object_response(ser_policy(policy))


@bp.post("/blood-bank/par-level-policies/<pid>/retire")
@endpoint(SUPERVISOR)
def policy_retire(pid, user_id, role):
    policy = policy_by_path(pid)
    if policy["status"] != "ACTIVE":
        raise ApiError(E.ERR_POLICY_NOT_ACTIVE, 409, "Policy is not ACTIVE")
    policy["status"] = "RETIRED"
    touch(policy)
    return object_response(ser_policy(policy))


@bp.get("/blood-bank/par-level-policies/<pid>/posture")
@endpoint(ALL)
def policy_posture(pid, user_id, role):
    policy = policy_by_path(pid)
    bucket = (policy["product_type"], policy["abo_type"], policy["rh_type"])
    return object_response({
        "product_type": policy["product_type"],
        "abo_type": policy["abo_type"],
        "rh_type": policy["rh_type"],
        "usable_units": logic.bucket_usable_units(*bucket),
        "inbound_units_24h": logic.bucket_inbound_units_24h(*bucket),
        "physical_posture": logic.physical_posture(*bucket),
        "prospective_posture": logic.prospective_posture(*bucket),
        "excessive_wastage": logic.bucket_excessive_wastage(*bucket),
    })


# ---------------------------------------------------------------------------
# Transport coolers and checkout windows (PRD 3.9)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/coolers")
@endpoint(SUPERVISOR)
def cooler_create(user_id, role):
    body = get_body()
    tag = req_str(body, "cooler_tag")
    if any(c["cooler_tag"] == tag for c in DB.coolers.values()):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"cooler_tag {tag} is already registered")
    cooler = new_entity({
        "cooler_tag": tag,
        "status": "AVAILABLE",
        "restock_until": None,
    })
    DB.coolers[cooler["id"]] = cooler
    return object_response(ser_cooler(cooler), status=201)


@bp.get("/blood-bank/coolers")
@endpoint(ALL)
def cooler_list(user_id, role):
    rows = list(DB.coolers.values())
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return list_response(rows, request.args, ser_cooler)


@bp.get("/blood-bank/coolers/<cid>")
@endpoint(ALL)
def cooler_get(cid, user_id, role):
    return object_response(ser_cooler(cooler_by_path(cid)))


@bp.post("/blood-bank/cooler-checkouts")
@endpoint(TECH)
def checkout_create(user_id, role):
    body = get_body()
    cooler_id = req_str(body, "cooler_id")
    planned_start = req_dt(body, "planned_start")
    planned_end = req_dt(body, "planned_end")
    cooler = fk_exists(DB.coolers, cooler_id, "TransportCooler")
    buffer = timedelta(minutes=COOLER_REDISPATCH_BUFFER_MINUTES)
    # Window validity before conflict (both validation priority 16, validity first).
    if planned_end <= planned_start or planned_end - planned_start > timedelta(hours=MAX_CHECKOUT_DURATION_HOURS):
        raise ApiError(
            E.ERR_CHECKOUT_WINDOW_INVALID, 400,
            "planned_end must be strictly after planned_start and duration must be <= 12h",
        )
    new_effective_end = planned_end + buffer
    for other in DB.checkouts.values():
        if other["cooler_id"] != cooler["id"]:
            continue
        existing_effective_end = (other["actual_returned_at"] or other["planned_end"]) + buffer
        # Closed-interval collision with 60-minute buffer; touching endpoints
        # (equality) do NOT conflict.
        if planned_start < existing_effective_end and other["planned_start"] < new_effective_end:
            raise ApiError(
                E.ERR_COOLER_WINDOW_CONFLICT, 409,
                "Checkout window collides with another checkout plus its 60-minute buffer",
            )
    checkout = new_entity({
        "cooler_id": cooler["id"],
        "planned_start": planned_start,
        "planned_end": planned_end,
        "checked_out_by_user_id": user_id,
        "actual_returned_at": None,
        "status": "OPEN",
    })
    DB.checkouts[checkout["id"]] = checkout
    # Occupancy follows the window: covering now moves AVAILABLE -> CHECKED_OUT.
    if planned_start <= now() <= planned_end and cooler["status"] == "AVAILABLE":
        cooler["status"] = "CHECKED_OUT"
        touch(cooler)
    return object_response(ser_checkout(checkout), status=201)


@bp.get("/blood-bank/cooler-checkouts")
@endpoint(ALL)
def checkout_list(user_id, role):
    rows = list(DB.checkouts.values())
    cooler_id = request.args.get("cooler_id")
    if cooler_id is not None:
        rows = [c for c in rows if c["cooler_id"] == cooler_id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return list_response(rows, request.args, ser_checkout)


@bp.get("/blood-bank/cooler-checkouts/<cid>")
@endpoint(ALL)
def checkout_get(cid, user_id, role):
    return object_response(ser_checkout(checkout_by_path(cid)))


@bp.post("/blood-bank/cooler-checkouts/<cid>/return")
@endpoint(TECH)
def checkout_return(cid, user_id, role):
    checkout = checkout_by_path(cid)
    if checkout["status"] != "OPEN":
        raise ApiError(E.ERR_CHECKOUT_NOT_RETURNABLE, 409, "Checkout is not OPEN")
    returned_at = now()
    checkout["actual_returned_at"] = returned_at
    checkout["status"] = "RETURNED"
    touch(checkout)
    cooler = DB.coolers.get(checkout["cooler_id"])
    if cooler is not None and cooler["status"] == "CHECKED_OUT":
        cooler["status"] = "RESTOCKING"
        cooler["restock_until"] = returned_at + timedelta(minutes=COOLER_REDISPATCH_BUFFER_MINUTES)
        touch(cooler)
    return object_response(ser_checkout(checkout))


# ---------------------------------------------------------------------------
# Wastage views (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.get("/blood-bank/wastage-records")
@endpoint(ALL)
def wastage_list(user_id, role):
    rows = list(DB.wastage.values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        rows = [w for w in rows if w["unit_id"] == unit_id]
    product = request.args.get("product_type")
    if product is not None:
        rows = [w for w in rows if w["product_type"] == product]
    reason = request.args.get("reason")
    if reason is not None:
        rows = [w for w in rows if w["reason"] == reason]
    return list_response(rows, request.args, ser_wastage)


@bp.get("/blood-bank/wastage-records/<wid>")
@endpoint(ALL)
def wastage_get(wid, user_id, role):
    return object_response(ser_wastage(wastage_by_path(wid)))


@bp.get("/blood-bank/wastage-summary")
@endpoint(ALL)
def wastage_summary(user_id, role):
    raw_days = request.args.get("window_days")
    window_days = None
    if raw_days is not None:
        try:
            window_days = int(raw_days)
            if window_days <= 0:
                window_days = None
        except (TypeError, ValueError):
            window_days = None
    buckets = set()
    for u in DB.units.values():
        buckets.add((u["product_type"], u["abo_type"], u["rh_type"]))
    for w in DB.wastage.values():
        buckets.add((w["product_type"], w["abo_type"], w["rh_type"]))
    product_filter = request.args.get("product_type")
    if product_filter is not None:
        buckets = {b for b in buckets if b[0] == product_filter}
    entries = []
    for product_type, abo_type, rh_type in sorted(buckets):
        rate, wasted, received, excessive = logic.rolling_wastage(
            product_type, abo_type, rh_type, window_days=window_days
        )
        entries.append({
            "product_type": product_type,
            "abo_type": abo_type,
            "rh_type": rh_type,
            "wasted_units": wasted,
            "received_units": received,
            "wastage_rate": float(rate),
            "excessive_wastage": excessive,
        })
    return object_response({
        "as_of_utc": fmt_dt(store.now()),
        "window_days": window_days if window_days is not None else 30,
        "buckets": entries,
    })
