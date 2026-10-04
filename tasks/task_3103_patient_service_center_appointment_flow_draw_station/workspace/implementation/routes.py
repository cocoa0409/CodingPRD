"""All API routes, registered onto the Flask app by `register(app)`."""

from datetime import timedelta

from flask import request

from core import (
    ApiError, db, fail, ok, ok_list, ok_empty, require_auth, body, new_id,
    stamp, touch, parse_iso, iso, now_iso, get_clock, cents, get_center,
    get_patient, get_order, get_appointment, get_specimen, get_run, get_plan,
    require_fields, check_enum, sorted_rows, API_PREFIX,
    SLOT_MINUTES_DEFAULT, DRAW_HOLD_MINUTES_DEFAULT, TIME_MAX_FUTURE_BOOKING_MINUTES,
    EARLY_CHECKIN_MINUTES, GRACE_MINUTES, WAIT_MAX_CALL_WAIT_MINUTES,
    ATTEMPTS_MAX_TOTAL, REPEAT_WINDOW_HOURS, REJECTION_DAY_CAP,
    COURIER_CUTOFF_BEFORE_DISPATCH_MINUTES, COURIER_MAX_SPECIMENS_PER_RUN,
    STABILITY_FACTOR, COLLECTION_MODES, CREDENTIALS, TUBE_CODES, PLAN_TYPES,
    PHLEBOTOMIST_STATUSES, TEST_PANELS, TUBE_PANELS, COMPROMISE_REASONS,
    ESTIMATE_VARIANTS, CLSI_MAX_SAFETY_ORDER, INSURANCE_STATUSES,
)
import domain
import checks
import seed


# ===========================================================================
# Service centers
# ===========================================================================
def create_service_center():
    require_auth({"CenterSupervisor"})
    d = body()
    require_fields(d, ["name", "state_code", "timezone_offset_minutes",
                       "station_count", "open_local_minutes",
                       "close_local_minutes"])
    row = stamp({
        "name": d["name"],
        "state_code": d["state_code"],
        "timezone_offset_minutes": int(d["timezone_offset_minutes"]),
        "slot_minutes": int(d.get("slot_minutes", SLOT_MINUTES_DEFAULT)),
        "open_local_minutes": int(d["open_local_minutes"]),
        "close_local_minutes": int(d["close_local_minutes"]),
        "pediatric_capable": bool(d.get("pediatric_capable", False)),
        "draw_hold_minutes": int(d.get("draw_hold_minutes", DRAW_HOLD_MINUTES_DEFAULT)),
        "station_count": int(d["station_count"]),
        "ops_run_index": 0,
        "staffed_minutes_available": 0,
    })
    db.service_centers[row["id"]] = row
    return ok(row, status=201)


def read_service_center(cid):
    require_auth({"CenterSupervisor", "IntakeCoordinator", "LabLiaison",
                  "LabSystem", "Phlebotomist", "Patient"})
    return ok(get_center(cid))


# ===========================================================================
# Patients
# ===========================================================================
def create_patient():
    require_auth({"IntakeCoordinator"})
    d = body()
    require_fields(d, ["full_name", "birth_date", "mrn"])
    for p in db.patients.values():
        if p["mrn"] == d["mrn"]:
            fail("ERR_DUPLICATE_MRN")
    row = stamp({
        "full_name": d["full_name"],
        "birth_date": d["birth_date"],
        "mrn": d["mrn"],
    })
    db.patients[row["id"]] = row
    return ok(row, status=201)


def list_patients():
    require_auth({"IntakeCoordinator", "LabLiaison", "Phlebotomist"})
    rows = sorted_rows(db.patients.values())
    mrn = request.args.get("mrn")
    if mrn is not None:
        rows = [r for r in rows if r["mrn"] == mrn]
    return ok_list(rows)


def read_patient(pid):
    require_auth({"IntakeCoordinator", "LabLiaison", "Phlebotomist"})
    return ok(get_patient(pid))


def patch_patient(pid):
    require_auth({"IntakeCoordinator"})
    p = get_patient(pid)
    d = body()
    if "full_name" in d:
        p["full_name"] = d["full_name"]
    if "birth_date" in d:
        p["birth_date"] = d["birth_date"]
    touch(p)
    return ok(p)


# ===========================================================================
# Phlebotomists
# ===========================================================================
def create_phlebotomist():
    require_auth({"CenterSupervisor"})
    d = body()
    require_fields(d, ["service_center_id", "full_name", "credential",
                       "shift_start_local_minutes", "shift_end_local_minutes"])
    center = get_center(d["service_center_id"])
    check_enum(d["credential"], CREDENTIALS, "credential")
    start = int(d["shift_start_local_minutes"])
    end = int(d["shift_end_local_minutes"])
    if end <= start:
        fail("ERR_INVALID_REQUEST", "shift end must be after shift start")

    from datetime import datetime, timezone
    clock = get_clock()
    base = datetime(clock.year, clock.month, clock.day, tzinfo=timezone.utc)
    list_start = base + timedelta(minutes=start - center["timezone_offset_minutes"])
    list_end = base + timedelta(minutes=end - center["timezone_offset_minutes"])
    checks.staff_listing_check(None, list_start, list_end)

    row = stamp({
        "service_center_id": center["id"],
        "full_name": d["full_name"],
        "credential": d["credential"],
        "shift_start_local_minutes": start,
        "shift_end_local_minutes": end,
        "max_concurrent_attempts_referral": ATTEMPTS_MAX_TOTAL,
        "status": "ON_DUTY",
        "_listing_start": list_start,
        "_listing_end": list_end,
    })
    db.phlebotomists[row["id"]] = row
    return ok(_public_phleb(row), status=201)


def _public_phleb(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def patch_phlebotomist(pid):
    require_auth({"CenterSupervisor"})
    p = db.phlebotomists.get(pid)
    if p is None:
        raise ApiError("ERR_INVALID_REQUEST", "Phlebotomist not found")
    d = body()
    if "status" in d:
        check_enum(d["status"], PHLEBOTOMIST_STATUSES, "status")
        p["status"] = d["status"]
    touch(p)
    return ok(_public_phleb(p))


def list_phlebotomists():
    require_auth({"CenterSupervisor", "IntakeCoordinator", "Phlebotomist"})
    rows = sorted_rows(db.phlebotomists.values())
    cid = request.args.get("service_center_id")
    if cid is not None:
        rows = [r for r in rows if r["service_center_id"] == cid]
    return ok_list([_public_phleb(r) for r in rows])


def read_phlebotomist(pid):
    require_auth({"CenterSupervisor", "IntakeCoordinator", "Phlebotomist"})
    p = db.phlebotomists.get(pid)
    if p is None:
        raise ApiError("ERR_INVALID_REQUEST", "Phlebotomist not found")
    return ok(_public_phleb(p))


# ===========================================================================
# Insurance plans
# ===========================================================================
def create_insurance_plan():
    require_auth({"IntakeCoordinator"})
    d = body()
    require_fields(d, ["payer_name", "plan_type", "copay_cents", "coinsurance_pct",
                       "deductible_remaining_cents", "allowed_amount_cents"])
    check_enum(d["plan_type"], PLAN_TYPES, "plan_type")
    row = stamp({
        "payer_name": d["payer_name"],
        "plan_type": d["plan_type"],
        "copay_cents": int(d["copay_cents"]),
        "coinsurance_pct": float(d["coinsurance_pct"]),
        "deductible_remaining_cents": int(d["deductible_remaining_cents"]),
        "allowed_amount_cents": int(d["allowed_amount_cents"]),
        "prior_paid_pct": float(d.get("prior_paid_pct", 0.0)),
        "status": "ACTIVE",
    })
    db.insurance_plans[row["id"]] = row
    return ok(row, status=201)


def list_insurance_plans():
    require_auth({"IntakeCoordinator", "LabLiaison"})
    rows = sorted_rows(db.insurance_plans.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list(rows)


def read_insurance_plan(pid):
    require_auth({"IntakeCoordinator", "LabLiaison"})
    return ok(get_plan(pid))


def patch_insurance_plan(pid):
    require_auth({"IntakeCoordinator"})
    plan = get_plan(pid)
    d = body()
    if "status" in d:
        check_enum(d["status"], {"ACTIVE", "TERMINATED"}, "status")
        plan["status"] = d["status"]
        if d["status"] == "TERMINATED":
            _cascade_terminate(plan)
    touch(plan)
    return ok(plan)


def _cascade_terminate(plan):
    for o in db.test_orders.values():
        if o.get("insurance_plan_id") != plan["id"]:
            continue
        if o.get("insurance_status") != "ELIGIBLE":
            continue
        o["insurance_status"] = "EXPIRED"
        o["est_copay_cents"] = 0
        o["est_coinsurance_cents"] = 0
        touch(o)


# ===========================================================================
# Medical necessity rules
# ===========================================================================
def create_necessity_rule():
    require_auth({"IntakeCoordinator"})
    d = body()
    require_fields(d, ["test_panel", "icd10_code"])
    check_enum(d["test_panel"], TEST_PANELS, "test_panel")
    row = stamp({
        "test_panel": d["test_panel"],
        "icd10_code": d["icd10_code"],
        "is_covered": bool(d.get("is_covered", True)),
    })
    db.necessity_rules[row["id"]] = row
    return ok(row, status=201)


def list_necessity_rules():
    require_auth({"IntakeCoordinator", "LabLiaison"})
    rows = sorted_rows(db.necessity_rules.values())
    panel = request.args.get("test_panel")
    if panel is not None:
        rows = [r for r in rows if r["test_panel"] == panel]
    code = request.args.get("icd10_code")
    if code is not None:
        rows = [r for r in rows if r["icd10_code"] == code]
    return ok_list(rows)


# ===========================================================================
# Tube requirements
# ===========================================================================
def _tube_public(row):
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    out["can_become_hard"] = row["order_of_draw"] >= CLSI_MAX_SAFETY_ORDER
    return out


def create_tube_requirement():
    require_auth({"LabLiaison"})
    d = body()
    require_fields(d, ["test_panel", "tube_code", "required_volume_ml",
                       "min_volume_ml", "order_of_draw", "stability_minutes",
                       "max_urgency_hours"])
    check_enum(d["test_panel"], TUBE_PANELS, "test_panel")
    check_enum(d["tube_code"], TUBE_CODES, "tube_code")
    req_v = float(d["required_volume_ml"])
    min_v = float(d["min_volume_ml"])
    if not (0 < min_v <= req_v):
        fail("ERR_INVALID_REQUEST",
             "min_volume_ml must be > 0 and <= required_volume_ml")
    row = stamp({
        "test_panel": d["test_panel"],
        "tube_code": d["tube_code"],
        "required_volume_ml": req_v,
        "min_volume_ml": min_v,
        "order_of_draw": int(d["order_of_draw"]),
        "stability_minutes": int(d["stability_minutes"]),
        "max_urgency_hours": int(d["max_urgency_hours"]),
        "special_handling_codes": list(d.get("special_handling_codes") or []),
        "is_recollection_eligible": bool(d.get("is_recollection_eligible", True)),
        "status": "ACTIVE",
    })
    db.tube_requirements[row["id"]] = row
    return ok(_tube_public(row), status=201)


def list_tube_requirements():
    require_auth({"LabLiaison", "Phlebotomist", "IntakeCoordinator"})
    rows = sorted_rows(db.tube_requirements.values())
    panel = request.args.get("test_panel")
    if panel is not None:
        rows = [r for r in rows if r["test_panel"] == panel]
    tube = request.args.get("tube_code")
    if tube is not None:
        rows = [r for r in rows if r["tube_code"] == tube]
    return ok_list([_tube_public(r) for r in rows])


def transition_tube_requirement(tid):
    require_auth({"LabLiaison"})
    row = db.tube_requirements.get(tid)
    if row is None:
        raise ApiError("ERR_INVALID_REQUEST", "Tube requirement not found")
    d = body()
    row["status"] = d.get("status", row.get("status"))
    touch(row)
    for o in db.test_orders.values():
        domain.recompute_order_plan(o)
        touch(o)
    return ok(_tube_public(row))


def delete_tube_requirement(tid):
    require_auth({"LabLiaison"})
    row = db.tube_requirements.get(tid)
    if row is None:
        raise ApiError("ERR_INVALID_REQUEST", "Tube requirement not found")
    affected = set()
    for o in db.test_orders.values():
        if row["tube_code"] in (o.get("resolved_tubes") or []):
            affected.add(o["id"])
    del db.tube_requirements[tid]
    for oid in affected:
        o = db.test_orders[oid]
        domain.recompute_order_plan(o)
        o["tube_cost_delta_minutes"] = 15
        touch(o)
    return ok_empty()


# ===========================================================================
# Test orders
# ===========================================================================
def _order_public(order):
    out = {k: v for k, v in order.items() if not k.startswith("_")}
    out["fasting_deadline_utc"] = (
        iso(domain.fasting_deadline_for(order))
        if order.get("is_fasting_required") else None)
    out["fasting_overdue"] = domain.fasting_overdue_order(order)
    domain.recompute_order_pediatric(order)
    out["patient_is_pediatric"] = order["patient_is_pediatric"]
    # PRD §3.1: the necessity outcome is settled by the grid; the outcome follows
    # from the codes and the grid alone, so every read reflects the current grid.
    domain.recompute_necessity(order)
    out["necessity_status"] = order["necessity_status"]
    spec = domain.resolve_tubes(order)
    out["resolved_tubes"] = [r["tube_code"] for r in spec]
    out["draw_order_spec"] = [{"tube_code": r["tube_code"],
                               "order_of_draw": r["order_of_draw"]} for r in spec]
    order["resolved_tubes"] = out["resolved_tubes"]
    order["draw_order_spec"] = out["draw_order_spec"]
    order["concurrence_hash"] = domain.compute_concurrence_hash(
        order["test_panel"], sorted(out["resolved_tubes"]),
        domain.handling_for(order))
    out["concurrence_hash"] = order["concurrence_hash"]
    return out


def create_test_order():
    require_auth({"IntakeCoordinator", "LabSystem"})
    d = body()
    require_fields(d, ["service_center_id", "patient_id", "ordering_provider_npi",
                       "test_panel", "collection_mode", "insurance_plan_id"])
    center = get_center(d["service_center_id"])
    patient = get_patient(d["patient_id"])
    check_enum(d["test_panel"], TEST_PANELS, "test_panel")
    check_enum(d["collection_mode"], COLLECTION_MODES, "collection_mode")
    plan_id = d.get("insurance_plan_id")
    if plan_id is not None:
        get_plan(plan_id)

    row = stamp({
        "service_center_id": center["id"],
        "patient_id": patient["id"],
        "ordering_provider_npi": d["ordering_provider_npi"],
        "test_panel": d["test_panel"],
        "collection_mode": d["collection_mode"],
        "is_fasting_required": bool(d.get("is_fasting_required", False)),
        "fasting_hours_required": int(d.get("fasting_hours_required", 0)),
        "patient_last_food_utc": d.get("patient_last_food_utc"),
        "list_price_cents": int(d.get("list_price_cents", 5000)),
        "icd10_codes": list(d.get("icd10_codes") or []),
        "insurance_plan_id": plan_id,
        "patient_is_pediatric": domain.is_pediatric(patient),
        "necessity_status": "PASS",
        "insurance_status": "UNVERIFIED",
        "est_copay_cents": 0,
        "est_coinsurance_cents": 0,
        "self_pay_rate_cents": 0,
        "patient_responsibility_cents": 0,
        "self_pay_discount_cents": 0,
        "prepay_required_cents": 0,
        "prepay_collected_cents": 0,
        "balance_remaining_cents": 0,
        "status": "RECEIVED",
        "resolved_tubes": [],
        "draw_order_spec": [],
        "concurrence_hash": "",
        "rejection_reason": None,
        "day_rejection_index": 0,
        "_covered_panels": None,
    })
    # The deadline is pinned here, at intake (PRD §3.8). With the pin key still
    # absent, fasting_deadline_for reproduces last-food + required hours exactly.
    dl = domain.fasting_deadline_for(row)
    row["_fasting_pinned_bl"] = iso(dl) if dl else None
    db.test_orders[row["id"]] = row
    domain.recompute_necessity(row)
    domain.recompute_order_plan(row)
    row["self_pay_rate_cents"] = int(domain.self_pay_rate(row))
    return ok(_order_public(row), status=201)


def list_test_orders():
    require_auth({"IntakeCoordinator", "LabLiaison", "LabSystem"})
    rows = sorted_rows(db.test_orders.values())
    for param, key in (("service_center_id", "service_center_id"),
                       ("patient_id", "patient_id"),
                       ("insurance_plan_id", "insurance_plan_id"),
                       ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    return ok_list([_order_public(r) for r in rows])


def read_test_order(oid):
    require_auth({"IntakeCoordinator", "LabLiaison", "LabSystem", "Patient",
                  "Phlebotomist"})
    order = get_order(oid)
    role = request.headers.get("X-User-Role")
    if role == "Patient" and request.headers.get("X-User-ID") != order["patient_id"]:
        fail("ERR_FORBIDDEN_ROLE")
    return ok(_order_public(order))


def read_tube_plan(oid):
    require_auth({"Phlebotomist", "LabLiaison", "IntakeCoordinator"})
    order = get_order(oid)
    domain.recompute_order_pediatric(order)
    resolved = domain.resolve_tubes(order)
    return ok({"resolved_tubes": [r["tube_code"] for r in resolved]})


def necessity_check(oid):
    require_auth({"IntakeCoordinator", "LabSystem"})
    order = get_order(oid)
    domain.recompute_necessity(order)
    touch(order)
    return ok(_order_public(order))


def insurance_resolve(oid):
    require_auth({"IntakeCoordinator", "LabSystem"})
    order = get_order(oid)
    plan = db.insurance_plans.get(order.get("insurance_plan_id"))
    if plan is not None and plan["status"] == "ACTIVE":
        order["insurance_status"] = "ELIGIBLE"
        order["est_copay_cents"] = int(plan["copay_cents"])
        order["est_coinsurance_cents"] = cents(
            float(plan["allowed_amount_cents"]) * float(plan.get("coinsurance_pct") or 0.0)
            * (1 - float(plan.get("prior_paid_pct") or 0.0)))
    elif plan is not None and plan["status"] == "TERMINATED":
        order["insurance_status"] = "EXPIRED"
        order["est_copay_cents"] = 0
        order["est_coinsurance_cents"] = 0
    else:
        order["insurance_status"] = "INELIGIBLE"
        order["est_copay_cents"] = 0
        order["est_coinsurance_cents"] = 0
    order["self_pay_rate_cents"] = int(domain.self_pay_rate(order))
    touch(order)
    return ok(_order_public(order))


def schedule_order(oid):
    require_auth({"IntakeCoordinator"})
    order = get_order(oid)
    if order["status"] not in ("RECEIVED", "SCHEDULED"):
        fail("ERR_INVALID_STATE")
    if order["insurance_status"] == "UNVERIFIED":
        order["insurance_status"] = "INELIGIBLE"
    if order["insurance_status"] != "ELIGIBLE":
        fail("ERR_INSURANCE_INELIGIBLE")
    if order["necessity_status"] == "FAIL":
        fail("ERR_MEDICAL_NECESSITY_FAILED")
    if order["necessity_status"] == "PENDING":
        fail("ERR_MEDICAL_NECESSITY_PENDING")
    appt = domain.appointment_for_order(oid, active_only=True)
    if appt is None or appt["draw_state"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "No open appointment in SCHEDULED state")
    order["status"] = "SCHEDULED"
    touch(order)
    return ok(_order_public(order))


def cancel_order(oid):
    require_auth({"IntakeCoordinator"})
    order = get_order(oid)
    if order["status"] not in ("RECEIVED", "SCHEDULED"):
        fail("ERR_INVALID_STATE")
    for s in db.specimens.values():
        if s["test_order_id"] == oid and s["status"] in (
                "ASSIGNED", "IN_TRANSIT", "RECEIVED"):
            fail("ERR_INVALID_STATE",
                 "Specimens are already in transit for this order.")
    order["status"] = "CANCELLED"
    for a in db.appointments.values():
        if a["test_order_id"] == oid and a["draw_state"] not in (
                "DRAWN", "RESCHEDULED", "NO_SHOW"):
            a["draw_state"] = "NO_SHOW"
            touch(a)
    for s in db.specimens.values():
        if s["test_order_id"] == oid and s["status"] not in (
                "RECEIVED", "RECOLLECTED", "REJECTED", "COMPROMISED"):
            s["status"] = "REJECTED"
            touch(s)
    touch(order)
    return ok(_order_public(order))


def create_estimate(oid):
    require_auth({"IntakeCoordinator"})
    order = get_order(oid)
    d = body()
    require_fields(d, ["variant", "expected_test_order_version"])
    check_enum(d["variant"], ESTIMATE_VARIANTS, "variant")
    if int(d["expected_test_order_version"]) != order["version"]:
        fail("ERR_STALE_VERSION")
    for e in db.estimates.values():
        if e["test_order_id"] == oid and e["variant"] == d["variant"]:
            fail("ERR_INVALID_STATE",
                 "An estimate for this variant has already been collected.")
    supersedes = d.get("supersedes_estimate_id")
    if supersedes is not None and supersedes not in db.estimates:
        fail("ERR_INVALID_REQUEST", "supersedes_estimate_id does not resolve")

    result = domain.compute_estimate(order, d["variant"])
    row = stamp({
        "test_order_id": oid,
        "variant": d["variant"],
        "supersedes_estimate_id": supersedes,
        "copay_component_cents": result["copay_component_cents"],
        "coinsurance_component_cents": result["coinsurance_component_cents"],
        "deductible_component_cents": result["deductible_component_cents"],
        "gross_cents": result["gross_cents"],
        "discount_cents": result["discount_cents"],
        "net_patient_cents": result["net_patient_cents"],
        "weighted_blend_cents": int(domain.weighted_blend_cents(order)),
    })
    db.estimates[row["id"]] = row
    domain.apply_estimate_to_order(order, result)
    touch(order)
    return ok(row, status=201)


def read_estimate(eid):
    require_auth({"IntakeCoordinator", "Patient"})
    e = db.estimates.get(eid)
    if e is None:
        fail("ERR_INVALID_REQUEST", "Estimate not found")
    return ok(e)


def list_estimates_for_order(oid):
    require_auth({"IntakeCoordinator", "Patient"})
    get_order(oid)
    rows = [e for e in db.estimates.values() if e["test_order_id"] == oid]
    return ok_list(sorted_rows(rows))


def list_estimates():
    require_auth({"IntakeCoordinator", "Patient"})
    rows = sorted_rows(db.estimates.values())
    oid = request.args.get("test_order_id")
    if oid is not None:
        rows = [r for r in rows if r["test_order_id"] == oid]
    sup = request.args.get("supersedes_estimate_id")
    if sup is not None:
        rows = [r for r in rows if r.get("supersedes_estimate_id") == sup]
    return ok_list(rows)


# ===========================================================================
# Appointments
# ===========================================================================
def _appt_public(appt):
    out = {k: v for k, v in appt.items() if not k.startswith("_")}
    order = db.test_orders.get(appt["test_order_id"])
    center = db.service_centers.get(appt["service_center_id"])
    if order is not None:
        dl = domain.appointment_fasting_deadline(appt, order)
        out["fasting_deadline_utc"] = iso(dl) if dl is not None else None
        out["fasting_overdue"] = domain.appointment_fasting_overdue(appt, order)
        out["complexity_score"] = appt.get("complexity_score",
                                           domain.base_score(order["collection_mode"]))
    else:
        out["fasting_deadline_utc"] = None
        out["fasting_overdue"] = False
        out["complexity_score"] = appt.get("complexity_score", 10)
    sp = appt.get("staff_pending_at_utc")
    if sp and center is not None:
        out["draw_hold_expires_utc"] = iso(checks.draw_hold_expires(center, parse_iso(sp)))
        out["draw_hold_expired"] = (appt["draw_state"] == "STAFF_PENDING"
                                    and get_clock() > checks.draw_hold_expires(
                                        center, parse_iso(sp)))
    else:
        out["draw_hold_expires_utc"] = None
        out["draw_hold_expired"] = False
    out["draws_today"] = _draws_today(order)
    out["draws_remaining_today"] = max(0, ATTEMPTS_MAX_TOTAL - appt.get("attempt_count", 0))
    return out


def _draws_today(order):
    if order is None:
        return 0
    return len([a for a in db.appointments.values()
                if a["test_order_id"] == order["id"]
                and a["draw_state"] in ("DRAWN", "ATTEMPT_LIMIT_REACHED")])


def create_appointment():
    require_auth({"IntakeCoordinator", "Patient", "LabSystem"})
    d = body()
    require_fields(d, ["service_center_id", "test_order_id", "scheduled_start_utc",
                       "slot_span", "source", "expected_test_order_version"])
    center = get_center(d["service_center_id"])
    order = get_order(d["test_order_id"])
    if int(d["expected_test_order_version"]) != order["version"]:
        fail("ERR_STALE_VERSION")

    if "source" not in d or d["source"] not in ("BOOKED", "WALK_IN"):
        fail("ERR_INVALID_REQUEST", "source must be BOOKED or WALK_IN")
    start = parse_iso(d["scheduled_start_utc"])
    if start is None:
        fail("ERR_INVALID_REQUEST", "scheduled_start_utc is invalid")
    slot_span = int(d["slot_span"])
    if slot_span < 1:
        fail("ERR_INVALID_REQUEST", "slot_span must be >= 1")
    span_minutes = slot_span * int(center["slot_minutes"])
    end = start + timedelta(minutes=span_minutes)
    clock = get_clock()

    # Priority 5 safety, then priority 6 fiscal, then priority 7 temporal.
    _booking_guards(order, center, start, clock)
    checks.temporal_ladder_for_appointment(center, start, end, span_minutes)

    appt = stamp({
        "service_center_id": center["id"],
        "test_order_id": order["id"],
        "scheduled_start_utc": iso(start),
        "slot_span": slot_span,
        "source": d["source"],
        "draw_state": "SCHEDULED",
        "queue_state": "NONE",
        "checkin_utc": None,
        "station_index": -1,
        "phlebotomist_id": None,
        "complexity_score": domain.base_score(order["collection_mode"]),
        "attempt_count": 0,
        "staff_pending_at_utc": None,
        "_pinned_fasting_deadline": None,
    })
    db.appointments[appt["id"]] = appt
    touch(order)
    return ok(_appt_public(appt), status=201)


def _booking_guards(order, center, start, clock):
    """Priority 5 then 6 for appointment creation (safety 5a..5f precedes fiscal)."""
    domain.recompute_order_pediatric(order)
    checks.safety_pediatric_center_capable(order, center)
    checks.safety_collection_mode(None, order)
    checks.safety_fasting_window(order, start)
    if start < clock:
        fail("ERR_INVALID_REQUEST", "scheduled_start_utc is in the past")
    if start > clock + timedelta(minutes=TIME_MAX_FUTURE_BOOKING_MINUTES):
        fail("ERR_FUTURE_APPOINTMENT_TOO_FAR")


def create_walk_in():
    require_auth({"IntakeCoordinator", "Patient", "LabSystem"})
    d = body()
    require_fields(d, ["service_center_id", "test_order_id",
                       "expected_test_order_version"])
    center = get_center(d["service_center_id"])
    order = get_order(d["test_order_id"])
    if int(d["expected_test_order_version"]) != order["version"]:
        fail("ERR_STALE_VERSION")
    appt = stamp({
        "service_center_id": center["id"],
        "test_order_id": order["id"],
        "scheduled_start_utc": now_iso(),
        "slot_span": 1,
        "source": "WALK_IN",
        "draw_state": "SCHEDULED",
        "queue_state": "NONE",
        "checkin_utc": None,
        "station_index": -1,
        "phlebotomist_id": None,
        "complexity_score": domain.base_score(order["collection_mode"]),
        "attempt_count": 0,
        "staff_pending_at_utc": None,
        "_pinned_fasting_deadline": None,
    })
    db.appointments[appt["id"]] = appt
    touch(order)
    return ok(_appt_public(appt), status=201)


def list_appointments():
    require_auth({"IntakeCoordinator", "Phlebotomist", "Patient", "LabSystem"})
    rows = sorted_rows(db.appointments.values())
    for param in ("service_center_id", "test_order_id", "phlebotomist_id",
                  "draw_state"):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("draw_state") == status]
    return ok_list([_appt_public(r) for r in rows])


def read_appointment(aid):
    require_auth({"IntakeCoordinator", "Phlebotomist", "Patient"})
    appt = get_appointment(aid)
    _assert_patient_owns(appt)
    return ok(_appt_public(appt))


def _assert_patient_owns(appt):
    if request.headers.get("X-User-Role") != "Patient":
        return
    order = db.test_orders.get(appt["test_order_id"])
    if order is None or request.headers.get("X-User-ID") != order["patient_id"]:
        fail("ERR_FORBIDDEN_ROLE")


def check_in(aid):
    require_auth({"Patient", "IntakeCoordinator"})
    appt = get_appointment(aid)
    _assert_patient_owns(appt)
    order = get_order(appt["test_order_id"])
    if appt["draw_state"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    if order["necessity_status"] == "PENDING":
        fail("ERR_MEDICAL_NECESSITY_PENDING")
    clock = get_clock()
    start = parse_iso(appt["scheduled_start_utc"])
    if clock < start - timedelta(minutes=EARLY_CHECKIN_MINUTES):
        fail("ERR_INVALID_STATE", "Too early to check in.")
    if clock > start + timedelta(minutes=GRACE_MINUTES):
        fail("ERR_INVALID_STATE", "Past the check-in grace window.")
    appt["draw_state"] = "CHECKED_IN"
    appt["queue_state"] = "WAITING"
    appt["checkin_utc"] = now_iso()
    if order["status"] == "RECEIVED":
        order["status"] = "SCHEDULED"
    dl = domain.fasting_deadline_for(order)
    appt["_pinned_fasting_deadline"] = iso(dl) if dl else None
    appt["complexity_score"] = domain.compute_complexity_score(
        appt, order, db.service_centers[appt["service_center_id"]])
    touch(appt)
    return ok(_appt_public(appt))


def queue_status(aid):
    require_auth({"Patient", "IntakeCoordinator", "Phlebotomist"})
    appt = get_appointment(aid)
    _assert_patient_owns(appt)
    order = get_order(appt["test_order_id"])
    wait, band = domain.expected_wait(appt)
    served = _served_at(order, appt)
    gate = "PASS"
    if order.get("is_fasting_required"):
        dl = domain.appointment_fasting_deadline(appt, order)
        if dl is not None:
            gate = "PASS" if served <= dl else "FAIL"
    return ok({"estimated_wait_minutes": wait, "wait_band": band,
               "fasting_gate": gate})


def _served_at(order, appt):
    if order["status"] == "COLLECTED":
        collected = order.get("_coordinated_collection_utc")
        if collected:
            return parse_iso(collected)
    return get_clock()


def call_appointment(aid):
    require_auth({"IntakeCoordinator"})
    appt = get_appointment(aid)
    order = get_order(appt["test_order_id"])
    if appt["queue_state"] != "WAITING":
        fail("ERR_INVALID_STATE")
    center = db.service_centers[appt["service_center_id"]]
    staff = domain.resolving_staff(center["id"], order["collection_mode"])
    if not staff:
        # No credential covers the mode, so the call cannot move the row out of
        # the waiting room; the automatic CHECKED_IN -> STAFF_PENDING park is
        # entered without a queue move (PRD §3.3).
        appt["draw_state"] = "STAFF_PENDING"
        appt["staff_pending_at_utc"] = now_iso()
        appt["station_index"] = -1
        appt["phlebotomist_id"] = None
        touch(appt)
        fail("ERR_STAFF_CREDENTIAL_INSUFFICIENT")
    appt["complexity_score"] = domain.compute_complexity_score(appt, order, center)
    # PRD §3.3: a successful call moves `queue_state` to CALLED and recomputes
    # the score; the clinical dimension is left where it was. Station assignment
    # and the IN_DRAW / AT_STATION posture belong to the draw itself (§3.4).
    appt["queue_state"] = "CALLED"
    touch(appt)
    return ok(_appt_public(appt))


def _free_station(center, appt):
    used = set()
    for a in db.appointments.values():
        if a["service_center_id"] != center["id"] or a["id"] == appt["id"]:
            continue
        if a["draw_state"] in ("IN_DRAW", "STAFF_PENDING") and a["station_index"] >= 0:
            used.add(a["station_index"])
    for i in range(int(center["station_count"])):
        if i not in used:
            return i
    return 0


def start_draw(aid):
    require_auth({"Phlebotomist"})
    appt = get_appointment(aid)
    order = get_order(appt["test_order_id"])
    center = db.service_centers[appt["service_center_id"]]
    # PRD §3.4: start-draw is reached from the called queue — the visit must
    # already be past CHECKED_IN (from a call, or from the STAFF_PENDING hold's
    # automatic resolution) and the queue must sit at CALLED or AT_STATION.
    if appt["draw_state"] not in ("IN_DRAW", "CHECKED_IN") \
            or appt["queue_state"] not in ("CALLED", "AT_STATION"):
        fail("ERR_INVALID_STATE")
    uid = request.headers.get("X-User-ID")
    if appt.get("phlebotomist_id") and appt["phlebotomist_id"] != uid:
        fail("ERR_FORBIDDEN_ROLE")
    # priority 6 fiscal FIRST (the deliberate inversion), then priority 5 safety.
    if order["insurance_status"] == "UNVERIFIED":
        order["insurance_status"] = "INELIGIBLE"
    checks.fiscal_necessity(order)
    checks.fiscal_insurance(order)
    checks.fiscal_prepay(order)
    domain.recompute_order_pediatric(order)
    checks.safety_pediatric_draw_floor(order, center)
    checks.safety_order_of_draw(order)
    checks.safety_fasting_window(order, get_clock())
    _assert_tubes_match(order)

    # PRD §3.4: the act of starting moves the visit into the draw posture.
    appt["draw_state"] = "IN_DRAW"
    appt["queue_state"] = "AT_STATION"
    if not appt.get("phlebotomist_id"):
        appt["phlebotomist_id"] = uid
        appt["station_index"] = _free_station(center, appt)
    if order["status"] == "SCHEDULED":
        order["status"] = "IN_PROGRESS"
    order["self_pay_rate_cents"] = int(domain.self_pay_rate(order))
    result = domain.compute_estimate(order, "ATTENDED_COLLECTED")
    domain.apply_estimate_to_order(order, result)
    touch(order)
    touch(appt)
    return ok(_appt_public(appt))


def _assert_tubes_match(order):
    have = []
    for s in db.specimens.values():
        if s["test_order_id"] == order["id"]:
            have.append(s["tube_code"])
    expected = sorted(domain.resolve_tubes(order) and
                      [r["tube_code"] for r in domain.resolve_tubes(order)])
    if have and sorted(have) != expected:
        fail("ERR_COLLECTION_MODE_MISMATCH",
             "Declared tubes do not match the order's resolved tubes.")


def finish_draw(aid):
    require_auth({"Phlebotomist"})
    appt = get_appointment(aid)
    order = get_order(appt["test_order_id"])
    center = db.service_centers[appt["service_center_id"]]
    if appt["queue_state"] != "AT_STATION":
        fail("ERR_INVALID_STATE")
    if appt["draw_state"] != "IN_DRAW":
        fail("ERR_INVALID_STATE")
    specimens = [s for s in db.specimens.values() if s["test_order_id"] == order["id"]]
    if not specimens:
        fail("ERR_INVALID_STATE", "No specimen has been registered for this order.")
    domain.recompute_order_pediatric(order)
    checks.safety_pediatric_draw_floor(order, center)
    checks.safety_order_of_draw(order)
    appt["draw_state"] = "DRAWN"
    appt["queue_state"] = "COMPLETED"
    order["status"] = "COLLECTED"
    order["_coordinated_collection_utc"] = now_iso()
    for s in specimens:
        s["status"] = "UNASSIGNED"
        touch(s)
    touch(order)
    touch(appt)
    return ok(_appt_public(appt))


def reschedule_appointment(aid):
    require_auth({"IntakeCoordinator"})
    appt = get_appointment(aid)
    order = get_order(appt["test_order_id"])
    if appt["attempt_count"] < ATTEMPTS_MAX_TOTAL:
        fail("ERR_INVALID_STATE", "The attempt limit has not been reached.")
    first = appt.get("_first_attempt_utc")
    if first is None:
        fail("ERR_INVALID_STATE", "No first-attempt instant is recorded.")
    if not (get_clock() > parse_iso(first) + timedelta(minutes=60)):
        fail("ERR_INVALID_STATE",
             "Strictly more than 60 minutes must elapse since the first attempt.")
    if order["collection_mode"] in ("PEDIATRIC", "DIFFICULT_DRAW"):
        fail("ERR_INVALID_STATE",
             "Pediatric and difficult-draw visits are not rescheduled this way.")
    d = body()
    appt["draw_state"] = "RESCHEDULED"
    touch(appt)
    new_start = parse_iso(d.get("scheduled_start_utc") or now_iso())
    fresh = stamp({
        "service_center_id": appt["service_center_id"],
        "test_order_id": order["id"],
        "scheduled_start_utc": iso(new_start),
        "slot_span": 1,
        "source": appt.get("source", "BOOKED"),
        "draw_state": "SCHEDULED",
        "queue_state": "NONE",
        "checkin_utc": None,
        "station_index": -1,
        "phlebotomist_id": None,
        "complexity_score": domain.base_score(order["collection_mode"]),
        "attempt_count": appt["attempt_count"],
        "staff_pending_at_utc": None,
        "_pinned_fasting_deadline": None,
    })
    db.appointments[fresh["id"]] = fresh
    order["status"] = "SCHEDULED"
    touch(order)
    return ok(_appt_public(appt))


def prepay(aid):
    require_auth({"IntakeCoordinator"})
    appt = get_appointment(aid)
    order = get_order(appt["test_order_id"])
    d = body()
    require_fields(d, ["amount_cents"])
    amount = int(d["amount_cents"])
    order["prepay_collected_cents"] = order.get("prepay_collected_cents", 0) + amount
    order["balance_remaining_cents"] = max(
        0, order.get("patient_responsibility_cents", 0)
        - order["prepay_collected_cents"])
    touch(order)
    return ok(_appt_public(appt))


# ===========================================================================
# Specimens
# ===========================================================================
def _specimen_public(s):
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    dl = domain.specimen_stability_deadline(s)
    out["stability_deadline_utc"] = iso(dl)
    out["tests_covered"] = _tests_covered(s)
    order = db.test_orders.get(s["test_order_id"])
    center = db.service_centers.get(s["service_center_id"])
    idx = s.get("day_rejection_index", 0)
    out["rejection_waived"] = idx >= REJECTION_DAY_CAP
    out["is_recollection_eligible"] = _recollection_eligible(s)
    return out


def _tests_covered(s):
    row = domain.requirement_for(s)
    if row is None:
        return []
    out = []
    for panel in TEST_PANELS:
        resolved = [r for r in db.tube_requirements.values()
                    if r["test_panel"] == panel and r["tube_code"] == s["tube_code"]]
        for r in resolved:
            if r["max_urgency_hours"] is not None:
                out.append(panel)
                break
    return sorted(set(out))


def _recollection_eligible(s):
    row = domain.requirement_for(s)
    if row is None:
        return False
    return bool(row.get("is_recollection_eligible", True))


def create_specimen():
    require_auth({"Phlebotomist", "LabSystem"})
    d = body()
    require_fields(d, ["test_order_id", "tube_code", "volume_ml", "order_of_draw"])
    order = get_order(d["test_order_id"])
    check_enum(d["tube_code"], TUBE_CODES, "tube_code")
    row = stamp({
        "service_center_id": order["service_center_id"],
        "test_order_id": order["id"],
        "tube_code": d["tube_code"],
        "volume_ml": float(d["volume_ml"]),
        "order_of_draw": int(d["order_of_draw"]),
        "special_handling_codes": list(d.get("special_handling_codes") or []),
        "collected_utc": now_iso(),
        "courier_run_id": None,
        "status": "UNASSIGNED",
        "compromise_reason": None,
        "recollection_approved_at_utc": None,
        "day_rejection_index": 0,
    })
    db.specimens[row["id"]] = row
    appt = domain.appointment_for_order(order["id"])
    if appt is not None and appt["draw_state"] in ("IN_DRAW", "AT_STATION",
                                                   "CHECKED_IN", "CALLED"):
        if appt.get("_first_attempt_utc") is None:
            appt["_first_attempt_utc"] = now_iso()
            appt["attempt_count"] = 1
        touch(appt)
    return ok(_specimen_public(row), status=201)


def list_specimens():
    require_auth({"LabLiaison", "Phlebotomist", "IntakeCoordinator", "LabSystem"})
    rows = sorted_rows(db.specimens.values())
    for param in ("service_center_id", "test_order_id", "status", "courier_run_id"):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    return ok_list([_specimen_public(r) for r in rows])


def specimen_selector():
    require_auth({"LabLiaison"})
    center_id = request.args.get("service_center_id")
    candidates = []
    for s in db.specimens.values():
        if center_id is not None and s["service_center_id"] != center_id:
            continue
        if s["status"] != "COMPROMISED":
            continue
        if s.get("compromise_reason") not in COMPROMISE_REASONS:
            continue
        row = domain.requirement_for(s)
        if row is None or not row.get("is_recollection_eligible", True):
            continue
        candidates.append((s, row))
    candidates.sort(key=lambda pair: (
        pair[1]["max_urgency_hours"],
        -pair[1]["stability_minutes"],
        pair[0]["created_at"],
    ))
    return ok_list([_specimen_public(s) for s, _ in candidates])


def read_specimen(sid):
    require_auth({"LabLiaison", "Phlebotomist", "IntakeCoordinator"})
    return ok(_specimen_public(get_specimen(sid)))


def assign_courier(sid):
    require_auth({"LabLiaison"})
    s = get_specimen(sid)
    d = body()
    require_fields(d, ["courier_run_id"])
    run = get_run(d["courier_run_id"])
    order = get_order(s["test_order_id"])
    if s["status"] != "UNASSIGNED":
        fail("ERR_INVALID_STATE")
    if run["direction"] != "OUTBOUND" or run["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "The run must be OUTBOUND and PLANNED.")
    if run["service_center_id"] != s["service_center_id"]:
        fail("ERR_INVALID_STATE", "The run belongs to another centre.")
    if int(d.get("expected_specimen_version", s["version"])) != s["version"]:
        fail("ERR_STALE_VERSION")
    # Priority 5 safety precedes priority 7 temporal (the declared inversion).
    checks.safety_order_of_draw(order)
    _assignment_window(order, run)
    _stability_window(s, run)
    checks.assign_capacity_guard(run)
    s["status"] = "ASSIGNED"
    s["courier_run_id"] = run["id"]
    run["committed_specimen_count"] = run.get("committed_specimen_count", 0) + 1
    touch(run)
    touch(s)
    return ok(_specimen_public(s))


def _assignment_window(order, run):
    appt = domain.appointment_for_order(order["id"])
    if appt is None:
        fail("ERR_NO_ELIGIBLE_COURIER_RUN")
    clock = get_clock()
    if appt.get("checkin_utc"):
        # D1 (PRD §3.6): the clock must be no earlier than 30 minutes before the
        # scheduled start.
        start = parse_iso(appt["scheduled_start_utc"])
        lo = start - timedelta(minutes=30)
        if clock < lo:
            fail("ERR_NO_ELIGIBLE_COURIER_RUN")
    dispatch = parse_iso(run["dispatch_utc"])
    if clock + timedelta(minutes=COURIER_CUTOFF_BEFORE_DISPATCH_MINUTES) > dispatch:
        fail("ERR_INVALID_STATE", "The dispatch cutoff has passed.")


def _stability_window(s, run):
    deadline = domain.specimen_stability_deadline(s)
    dispatch = parse_iso(run["dispatch_utc"])
    if deadline is None or deadline > dispatch:
        fail("ERR_INVALID_STATE", "The specimen's stability window closes late.")


def compromise_specimen(sid):
    require_auth({"LabLiaison"})
    s = get_specimen(sid)
    d = body()
    require_fields(d, ["compromise_reason"])
    if s["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE")
    run = get_run(s["courier_run_id"])
    clock = get_clock()
    cutoff = parse_iso(run["cutoff_utc"])
    dispatch = parse_iso(run["dispatch_utc"])
    if not (cutoff < clock < dispatch):
        fail("ERR_INVALID_STATE",
             "A compromise is only declared strictly inside the cutoff-to-dispatch window.")
    s["status"] = "COMPROMISED"
    s["compromise_reason"] = d["compromise_reason"]
    s["courier_run_id"] = None
    run["committed_specimen_count"] = max(
        0, run.get("committed_specimen_count", 1) - 1)
    touch(run)
    touch(s)
    return ok(_specimen_public(s))


def reject_specimen(sid):
    require_auth({"LabLiaison"})
    s = get_specimen(sid)
    order = get_order(s["test_order_id"])
    center = db.service_centers[s["service_center_id"]]
    if s["status"] != "COMPROMISED":
        fail("ERR_INVALID_STATE")
    row = domain.requirement_for(s)
    if row is None:
        fail("ERR_TUBE_REQUIREMENT_MISSING")
    day_index = domain.rejection_day_index(order, center)
    # PRD §3.7: the waiver is true once the index REACHES the cap, so the
    # rejection that would land the index on the cap is the one refused.
    if day_index + 1 >= REJECTION_DAY_CAP:
        fail("ERR_INVALID_STATE",
             "The day's rejection cap has been reached; a second opinion is required.")
    s["status"] = "REJECTED"
    s["day_rejection_index"] = day_index + 1
    order["status"] = "SCHEDULED"
    order["is_fasting_required"] = False
    order["fasting_hours_required"] = 0
    order["patient_last_food_utc"] = None
    order["_fasting_pinned_bl"] = None
    order["rejection_reason"] = s.get("compromise_reason")
    order["_fasting_conserved_at_utc"] = now_iso()
    touch(order)
    touch(s)
    return ok(_specimen_public(s))


def recollect_specimen(sid):
    require_auth({"LabLiaison"})
    s = get_specimen(sid)
    order = get_order(s["test_order_id"])
    center = db.service_centers[s["service_center_id"]]
    if s["status"] != "COMPROMISED":
        fail("ERR_INVALID_STATE")
    est = [e for e in db.estimates.values()
           if e["test_order_id"] == order["id"]
           and e["variant"] == "ATTENDED_COLLECTED"]
    if not est:
        fail("ERR_INVALID_STATE",
             "A recollection requires an ATTENDED_COLLECTED estimate.")
    window = timedelta(hours=REPEAT_WINDOW_HOURS)
    count = 0
    for other in db.specimens.values():
        if other["test_order_id"] != order["id"] or other["status"] != "RECOLLECTED":
            continue
        approved = other.get("recollection_approved_at_utc")
        if approved and get_clock() - parse_iso(approved) <= window:
            count += 1
    if count != 0:
        fail("ERR_INVALID_STATE", "Only the visit's first recollection is scheduled here.")
    row = domain.requirement_for(s)
    if row is None or not row.get("is_recollection_eligible", True):
        fail("ERR_INVALID_STATE", "This tube may not be recollected.")
    s["status"] = "RECOLLECTED"
    s["recollection_approved_at_utc"] = now_iso()
    order["status"] = "SCHEDULED"
    order["prepay_required_cents"] = 0
    order["balance_remaining_cents"] = max(
        0, order.get("patient_responsibility_cents", 0)
        - order.get("prepay_collected_cents", 0))
    touch(order)
    touch(s)
    fresh = stamp({
        "service_center_id": order["service_center_id"],
        "test_order_id": order["id"],
        "scheduled_start_utc": now_iso(),
        "slot_span": 1,
        "source": "BOOKED",
        "draw_state": "SCHEDULED",
        "queue_state": "NONE",
        "checkin_utc": None,
        "station_index": -1,
        "phlebotomist_id": None,
        "complexity_score": domain.base_score(order["collection_mode"]),
        "attempt_count": 0,
        "staff_pending_at_utc": None,
        "_pinned_fasting_deadline": None,
    })
    db.appointments[fresh["id"]] = fresh
    return ok(_specimen_public(s))


# ===========================================================================
# Courier runs
# ===========================================================================
def _run_public(run):
    out = {k: v for k, v in run.items() if not k.startswith("_")}
    out["cutoff_utc"] = run.get("cutoff_utc")
    out["committed_specimen_count"] = run.get("committed_specimen_count", 0)
    out["load_posture"] = checks.load_posture(run.get("committed_specimen_count", 0))
    return out


def create_courier_run():
    require_auth({"LabLiaison"})
    d = body()
    require_fields(d, ["service_center_id", "direction", "dispatch_utc"])
    center = get_center(d["service_center_id"])
    check_enum(d["direction"], {"OUTBOUND", "INBOUND"}, "direction")
    dispatch = parse_iso(d["dispatch_utc"])
    if dispatch is None:
        fail("ERR_INVALID_REQUEST", "dispatch_utc is invalid")
    checks.courier_dispatch_check(center, dispatch)
    cutoff = dispatch - timedelta(minutes=COURIER_CUTOFF_BEFORE_DISPATCH_MINUTES)
    row = stamp({
        "service_center_id": center["id"],
        "direction": d["direction"],
        "dispatch_utc": iso(dispatch),
        "cutoff_utc": iso(cutoff),
        "committed_specimen_count": 0,
        "status": "PLANNED",
    })
    db.courier_runs[row["id"]] = row
    return ok(_run_public(row), status=201)


def list_courier_runs():
    require_auth({"LabLiaison", "IntakeCoordinator", "LabSystem"})
    rows = sorted_rows(db.courier_runs.values())
    for param in ("service_center_id", "status", "direction"):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    return ok_list([_run_public(r) for r in rows])


def eligible_courier_runs():
    require_auth({"LabLiaison", "Patient", "IntakeCoordinator"})
    sid = request.args.get("specimen_id")
    if sid:
        s = get_specimen(sid)
        order = db.test_orders.get(s["test_order_id"])
    else:
        order = None
        for o in sorted(db.test_orders.values(), key=lambda r: r["created_at"]):
            order = o
            break
    if order is None:
        return ok_list([])
    # PRD §3.6 anchors the window on `checkin_utc`, which is the *drawn* visit's
    # check-in instant; that visit reaches draw_state DRAWN once finish-draw runs,
    # so the selector must read the most recent checked-in appointment rather
    # than only an open one.
    checked_in = [a for a in db.appointments.values()
                  if a["test_order_id"] == order["id"] and a.get("checkin_utc")]
    checked_in.sort(key=lambda a: a["created_at"])  # id is never consulted
    appt = checked_in[-1] if checked_in else None
    if appt is None:
        return ok_list([])
    checkin = parse_iso(appt["checkin_utc"])
    start = parse_iso(appt["scheduled_start_utc"])
    if start < checkin + timedelta(minutes=30):
        return ok_list([])
    if start >= checkin + timedelta(minutes=30 + 720):
        return ok_list([])
    lo = checkin + timedelta(minutes=1080)
    hi = lo + timedelta(minutes=60)
    out = []
    for run in sorted_rows(db.courier_runs.values()):
        if run["service_center_id"] != order["service_center_id"]:
            continue
        if run["direction"] != "OUTBOUND" or run["status"] != "PLANNED":
            continue
        if lo <= parse_iso(run["dispatch_utc"]) < hi:
            out.append(run)
    return ok_list([_run_public(r) for r in out])


def read_courier_run(rid):
    require_auth({"LabLiaison", "IntakeCoordinator", "LabSystem"})
    run = get_run(rid)
    recl = _maybe_autoadvance(run)
    return ok(_run_public(run))


def _maybe_autoadvance(run):
    if run["status"] == "DISPATCHED":
        run["status"] = "IN_TRANSIT"
        touch(run)
    return run


def commit_all(rid):
    require_auth({"LabLiaison"})
    run = get_run(rid)
    if run["status"] != "PLANNED" or run["direction"] != "OUTBOUND":
        fail("ERR_INVALID_STATE")
    candidates = [s for s in db.specimens.values()
                  if s["service_center_id"] == run["service_center_id"]
                  and s["status"] == "UNASSIGNED"]
    candidates.sort(key=lambda s: (
        domain.specimen_stability_deadline(s) or parse_iso(s["collected_utc"]),
        s["test_order_id"],
        s["created_at"],
    ))
    committed = 0
    for s in candidates:
        if run["committed_specimen_count"] >= COURIER_MAX_SPECIMENS_PER_RUN:
            break
        run["committed_specimen_count"] += 1
        s["status"] = "ASSIGNED"
        s["courier_run_id"] = run["id"]
        touch(s)
        committed += 1
    touch(run)
    return ok(_run_public(run))


def dispatch_run(rid):
    require_auth({"LabLiaison"})
    run = get_run(rid)
    if run["status"] != "PLANNED":
        fail("ERR_INVALID_STATE")
    if parse_iso(run["dispatch_utc"]) != get_clock():
        fail("ERR_INVALID_STATE",
             "The logical clock must equal the run's dispatch instant.")
    if run["committed_specimen_count"] <= 0:
        fail("ERR_INVALID_STATE", "The run has no committed specimens.")
    run["status"] = "DISPATCHED"
    for s in db.specimens.values():
        if s.get("courier_run_id") == run["id"] and s["status"] == "ASSIGNED":
            s["status"] = "IN_TRANSIT"
            touch(s)
    touch(run)
    return ok(_run_public(run))


def deliver_run(rid):
    require_auth({"LabLiaison"})
    run = get_run(rid)
    if run["status"] not in ("DISPATCHED", "IN_TRANSIT"):
        fail("ERR_INVALID_STATE")
    run["status"] = "DELIVERED"
    for s in db.specimens.values():
        if s.get("courier_run_id") == run["id"] and s["status"] == "IN_TRANSIT":
            s["status"] = "RECEIVED"
            touch(s)
    touch(run)
    return ok(_run_public(run))


def cancel_run(rid):
    require_auth({"LabLiaison"})
    run = get_run(rid)
    if run["status"] != "PLANNED":
        fail("ERR_INVALID_STATE")
    if run["committed_specimen_count"] != 0:
        fail("ERR_INVALID_STATE", "A run holding specimens cannot be cancelled.")
    run["status"] = "CANCELLED"
    touch(run)
    return ok(_run_public(run))


# ===========================================================================
# Operations checkpoint and seed-reference
# ===========================================================================
def run_ops():
    require_auth({"CenterSupervisor", "LabSystem"})
    d = body()
    require_fields(d, ["service_center_id"])
    center = get_center(d["service_center_id"])
    center["ops_run_index"] = center.get("ops_run_index", 0) + 1
    on_duty = len([p for p in db.phlebotomists.values()
                   if p["service_center_id"] == center["id"]
                   and p["status"] == "ON_DUTY"])
    center["staffed_minutes_available"] = 15 * on_duty
    clock = get_clock()
    for appt in db.appointments.values():
        if appt["service_center_id"] != center["id"]:
            continue
        if (appt["queue_state"] == "WAITING"
                and appt["draw_state"] == "CHECKED_IN"
                and appt.get("checkin_utc")):
            waited = clock - parse_iso(appt["checkin_utc"])
            if waited >= timedelta(minutes=WAIT_MAX_CALL_WAIT_MINUTES):
                appt["draw_state"] = "NO_SHOW"
                appt["queue_state"] = "ABANDONED"
                touch(appt)
        if appt["draw_state"] == "STAFF_PENDING":
            _resolve_staff_pending(appt, center)
    _recompute_courier_mismatches(center)
    touch(center)
    return ok(center)


def _resolve_staff_pending(appt, center):
    order = db.test_orders.get(appt["test_order_id"])
    if order is None:
        return
    staff = domain.resolving_staff(center["id"], order["collection_mode"])
    if not staff:
        return
    appt["draw_state"] = "IN_DRAW"
    appt["queue_state"] = "AT_STATION"
    appt["phlebotomist_id"] = staff[0]["id"]
    appt["station_index"] = _free_station(center, appt)
    touch(appt)


def _recompute_courier_mismatches(center):
    previous = db.runtime.setdefault("courier_selection", {})
    mismatches = []
    for s in db.specimens.values():
        if s["service_center_id"] != center["id"]:
            continue
        order = db.test_orders.get(s["test_order_id"])
        if order is None:
            continue
        current = domain.select_courier_run(order)
        cur_id = current["id"] if current else None
        if s["id"] in previous and previous[s["id"]] != cur_id:
            mismatches.append(s["id"])
        previous[s["id"]] = cur_id
    db.runtime["courier_selection_mismatches"] = mismatches


def seed_reference():
    require_auth({"CenterSupervisor", "LabSystem"})
    created, plan_id = seed.seed_reference()
    return ok({"seeded": created, "insurance_plan_id": plan_id})


# ===========================================================================
# Registration
# ===========================================================================
def register(app):
    p = API_PREFIX
    routes = [
        ("POST", "/psc/service-centers", create_service_center),
        ("GET", "/psc/service-centers/<cid>", read_service_center),

        ("POST", "/psc/patients", create_patient),
        ("GET", "/psc/patients", list_patients),
        ("GET", "/psc/patients/<pid>", read_patient),
        ("PATCH", "/psc/patients/<pid>", patch_patient),

        ("POST", "/psc/phlebotomists", create_phlebotomist),
        ("GET", "/psc/phlebotomists", list_phlebotomists),
        ("GET", "/psc/phlebotomists/<pid>", read_phlebotomist),
        ("PATCH", "/psc/phlebotomists/<pid>", patch_phlebotomist),

        ("POST", "/psc/insurance-plans", create_insurance_plan),
        ("GET", "/psc/insurance-plans", list_insurance_plans),
        ("GET", "/psc/insurance-plans/<pid>", read_insurance_plan),
        ("PATCH", "/psc/insurance-plans/<pid>", patch_insurance_plan),

        ("POST", "/psc/medical-necessity-rules", create_necessity_rule),
        ("GET", "/psc/medical-necessity-rules", list_necessity_rules),

        ("POST", "/psc/tube-requirements", create_tube_requirement),
        ("GET", "/psc/tube-requirements", list_tube_requirements),
        ("POST", "/psc/tube-requirements/<tid>/transition", transition_tube_requirement),
        ("DELETE", "/psc/tube-requirements/<tid>", delete_tube_requirement),

        ("POST", "/psc/test-orders", create_test_order),
        ("GET", "/psc/test-orders", list_test_orders),
        ("GET", "/psc/test-orders/<oid>", read_test_order),
        ("GET", "/psc/test-orders/<oid>/tube-plan", read_tube_plan),
        ("POST", "/psc/test-orders/<oid>/necessity-check", necessity_check),
        ("POST", "/psc/test-orders/<oid>/insurance-resolve", insurance_resolve),
        ("POST", "/psc/test-orders/<oid>/schedule", schedule_order),
        ("POST", "/psc/test-orders/<oid>/cancel", cancel_order),
        ("POST", "/psc/test-orders/<oid>/estimates", create_estimate),
        ("GET", "/psc/test-orders/<oid>/estimates", list_estimates_for_order),

        ("GET", "/psc/responsibility-estimates", list_estimates),
        ("GET", "/psc/responsibility-estimates/<eid>", read_estimate),

        ("POST", "/psc/appointments", create_appointment),
        ("POST", "/psc/appointments/walk-in", create_walk_in),
        ("GET", "/psc/appointments", list_appointments),
        ("GET", "/psc/appointments/<aid>", read_appointment),
        ("GET", "/psc/appointments/<aid>/queue-status", queue_status),
        ("POST", "/psc/appointments/<aid>/check-in", check_in),
        ("POST", "/psc/appointments/<aid>/call", call_appointment),
        ("POST", "/psc/appointments/<aid>/start-draw", start_draw),
        ("POST", "/psc/appointments/<aid>/finish-draw", finish_draw),
        ("POST", "/psc/appointments/<aid>/reschedule", reschedule_appointment),
        ("POST", "/psc/appointments/<aid>/prepay", prepay),

        ("POST", "/psc/specimens", create_specimen),
        ("GET", "/psc/specimens", list_specimens),
        ("GET", "/psc/specimens/selector", specimen_selector),
        ("GET", "/psc/specimens/<sid>", read_specimen),
        ("POST", "/psc/specimens/<sid>/assign-courier", assign_courier),
        ("POST", "/psc/specimens/<sid>/compromise", compromise_specimen),
        ("POST", "/psc/specimens/<sid>/reject", reject_specimen),
        ("POST", "/psc/specimens/<sid>/recollect", recollect_specimen),

        ("POST", "/psc/courier-runs", create_courier_run),
        ("GET", "/psc/courier-runs", list_courier_runs),
        ("GET", "/psc/courier-runs/eligible", eligible_courier_runs),
        ("GET", "/psc/courier-runs/<rid>", read_courier_run),
        ("POST", "/psc/courier-runs/<rid>/commit-all", commit_all),
        ("POST", "/psc/courier-runs/<rid>/dispatch", dispatch_run),
        ("POST", "/psc/courier-runs/<rid>/deliver", deliver_run),
        ("POST", "/psc/courier-runs/<rid>/cancel", cancel_run),

        ("POST", "/psc/run-ops", run_ops),
        ("POST", "/_scenarios/seed-reference", seed_reference),
    ]
    for method, path, view in routes:
        app.add_url_rule(path, endpoint="%s %s" % (method, path),
                         view_func=view, methods=[method])