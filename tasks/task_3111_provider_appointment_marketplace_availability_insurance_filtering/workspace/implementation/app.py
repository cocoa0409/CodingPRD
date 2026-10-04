"""Provider Appointment Marketplace API — Flask entry point and routes."""

import os
import re

from flask import Flask, request, jsonify

from core import (
    DB, ApiError, success_object, success_list, error_body, get_actor, require_role,
    get_json_body, req_str, opt_str, req_int, opt_int, opt_bool, req_enum, req_datetime,
    parse_pagination, paginate, sort_by_created, new_resource, touch, public,
    parse_iso, fmt_iso, is_int, ANY,
)
import services as svc

app = Flask(__name__)

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@app.errorhandler(ApiError)
def handle_api_error(err):
    body, status = error_body(err)
    return jsonify(body), status


@app.errorhandler(404)
def handle_404(err):
    body, status = error_body(ApiError("ERR_INVALID_REQUEST", "Route not found"))
    return jsonify(body), status


@app.errorhandler(405)
def handle_405(err):
    body, status = error_body(ApiError("ERR_INVALID_REQUEST", "Method not allowed"))
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Lookup helpers (existence, with the correct error ids)
# ---------------------------------------------------------------------------

def get_practice(pid):
    p = DB.practices.get(pid)
    if p is None:
        raise ApiError("ERR_PRACTICE_NOT_FOUND", f"Practice {pid} not found")
    return p


def get_provider(pid):
    p = DB.providers.get(pid)
    if p is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", f"Provider {pid} not found")
    return p


def get_slot(sid):
    s = DB.slots.get(sid)
    if s is None:
        raise ApiError("ERR_SLOT_NOT_FOUND", f"Slot {sid} not found")
    return s


def get_type(tid):
    t = DB.appointment_types.get(tid)
    if t is None:
        raise ApiError("ERR_TYPE_NOT_FOUND", f"AppointmentType {tid} not found")
    return t


def get_plan(pid):
    p = DB.plans.get(pid)
    if p is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", f"InsurancePlan {pid} not found")
    return p


def get_attestation(aid):
    a = DB.attestations.get(aid)
    if a is None:
        raise ApiError("ERR_ATTESTATION_NOT_FOUND", f"Attestation {aid} not found")
    return a


def get_patient(pid):
    p = DB.patients.get(pid)
    if p is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", f"Patient {pid} not found")
    return p


def get_booking(bid):
    b = DB.bookings.get(bid)
    if b is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", f"Booking {bid} not found")
    return b


def get_charge(cid):
    c = DB.charges.get(cid)
    if c is None:
        raise ApiError("ERR_CHARGE_NOT_FOUND", f"Charge {cid} not found")
    return c


def get_invoice(iid):
    i = DB.invoices.get(iid)
    if i is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", f"Invoice {iid} not found")
    return i


def get_complaint(cid):
    c = DB.complaints.get(cid)
    if c is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND", f"Complaint {cid} not found")
    return c


def get_review(rid):
    r = DB.reviews.get(rid)
    if r is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", f"Review {rid} not found")
    return r


def get_case(cid):
    c = DB.audit_cases.get(cid)
    if c is None:
        raise ApiError("ERR_AUDIT_CASE_NOT_FOUND", f"AuditCase {cid} not found")
    return c


def get_event(eid):
    e = DB.contact_events.get(eid)
    if e is None:
        raise ApiError("ERR_INVALID_REQUEST", f"ContactEvent {eid} not found")
    return e


def get_entry(eid):
    e = DB.ledger_entries.get(eid)
    if e is None:
        raise ApiError("ERR_INVALID_REQUEST", f"LedgerEntry {eid} not found")
    return e


def get_visit_record(rid):
    r = DB.visit_records.get(rid)
    if r is None:
        raise ApiError("ERR_INVALID_REQUEST", f"VisitRecord {rid} not found")
    return r


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------

def own_check(role, uid, matches):
    if not matches:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "Resource outside caller's ownership scope")


# ---------------------------------------------------------------------------
# Clock / ops
# ---------------------------------------------------------------------------

@app.post("/marketplace/_clock/set_current_utc")
def set_clock():
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    to_dt = req_datetime(body, "to_iso8601")
    DB.clock._dt = to_dt
    return _obj({"current_utc": DB.clock.now_iso()})


def _obj(data, status=200):
    body, st = success_object(data, status)
    return jsonify(body), st


def _list(items, status=200):
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    body, st = success_list([public(i) for i in page], total, limit, offset, status)
    return jsonify(body), st


@app.post("/marketplace/ops/run-epoch")
def run_epoch():
    require_role(["OpsAdmin"])
    epoch, decayed, updated = svc.run_epoch()
    return _obj({"epoch": epoch, "decayed_strikes": decayed, "patients_updated": updated})


# ---------------------------------------------------------------------------
# Practices
# ---------------------------------------------------------------------------

@app.post("/marketplace/practices")
def create_practice():
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    name = req_str(body, "name")
    timezone = req_str(body, "timezone")
    billing_mode = opt_str(body, "billing_mode", "PER_BOOKING")
    if billing_mode not in ("PER_BOOKING", "SUBSCRIPTION"):
        raise ApiError("ERR_INVALID_REQUEST", "billing_mode must be PER_BOOKING or SUBSCRIPTION")
    sub_fee = opt_int(body, "subscription_fee_cents", 30000)
    new_lead = opt_int(body, "new_patient_lead_time_hours", 24)
    exist_lead = opt_int(body, "existing_patient_lead_time_hours", 4)
    rec = new_resource(DB.next_seq())
    rec.update({
        "name": name,
        "timezone": timezone,
        "billing_mode": billing_mode,
        "subscription_fee_cents": sub_fee,
        "new_patient_lead_time_hours": new_lead,
        "existing_patient_lead_time_hours": exist_lead,
        "status": "DRAFT",
    })
    DB.practices[rec["id"]] = rec
    return _obj(public(rec), 201)


@app.get("/marketplace/practices")
def list_practices():
    require_role([ANY])
    status = request.args.get("status")
    items = sort_by_created(list(DB.practices.values()))
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return _list(items)


@app.get("/marketplace/practices/<practice_id>")
def get_practice_route(practice_id):
    require_role([ANY])
    return _obj(public(get_practice(practice_id)))


def _practice_transition(practice_id, allowed_from, to, cascade=False):
    require_role(["OpsAdmin"])
    practice = get_practice(practice_id)
    if practice["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", f"Practice is {practice['status']}")
    if cascade:
        svc.practice_delist_cascade(practice)
    else:
        practice["status"] = to
        touch(practice)
        svc.recompute_practice_providers(practice["id"])
    return _obj(public(practice))


@app.post("/marketplace/practices/<practice_id>/activate")
def activate_practice(practice_id):
    return _practice_transition(practice_id, ("DRAFT",), "ACTIVE")


@app.post("/marketplace/practices/<practice_id>/suspend")
def suspend_practice(practice_id):
    return _practice_transition(practice_id, ("ACTIVE",), "SUSPENDED")


@app.post("/marketplace/practices/<practice_id>/reinstate")
def reinstate_practice(practice_id):
    return _practice_transition(practice_id, ("SUSPENDED",), "ACTIVE")


@app.post("/marketplace/practices/<practice_id>/delist")
def delist_practice(practice_id):
    return _practice_transition(practice_id, ("ACTIVE", "SUSPENDED"), "DELISTED", cascade=True)


@app.post("/marketplace/practices/<practice_id>/billing-mode")
def switch_billing_mode(practice_id):
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    billing_mode = req_enum(body, "billing_mode", {"PER_BOOKING", "SUBSCRIPTION"})
    practice = get_practice(practice_id)
    if any(
        c["practice_id"] == practice_id and c["status"] == "BILLABLE"
        for c in DB.charges.values()
    ):
        raise ApiError("ERR_PENDING_CHARGES", "Practice has BILLABLE charges")
    practice["billing_mode"] = billing_mode
    touch(practice)
    return _obj(public(practice))


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@app.post("/marketplace/providers")
def create_provider():
    uid, role = require_role(["PracticeStaff"])
    body = get_json_body(required=True)
    practice_id = req_str(body, "practice_id")
    display_name = req_str(body, "display_name")
    specialty = req_str(body, "specialty")
    lead_override = opt_int(body, "lead_time_override_hours", None)
    # ownership (priority 4) before existence (priority 5)
    own_check(role, uid, practice_id == uid)
    get_practice(practice_id)
    rec = new_resource(DB.next_seq())
    rec.update({
        "practice_id": practice_id,
        "display_name": display_name,
        "specialty": specialty,
        "lead_time_override_hours": lead_override,
        "insurance_mismatch_count": 0,
        "bookable_in_directory": False,
        "status": "PENDING",
    })
    DB.providers[rec["id"]] = rec
    svc.recompute_bookable(rec)
    return _obj(public(rec), 201)


@app.get("/marketplace/providers")
def list_providers():
    require_role([ANY])
    specialty = request.args.get("specialty")
    plan_id = request.args.get("plan_id")
    bookable_only = request.args.get("bookable_only")
    practice_id = request.args.get("practice_id")
    items = sort_by_created(list(DB.providers.values()))
    if specialty is not None:
        items = [p for p in items if p["specialty"] == specialty]
    if practice_id is not None:
        items = [p for p in items if p["practice_id"] == practice_id]
    if plan_id is not None:
        items = [p for p in items if svc.plan_accepted(p["id"], plan_id)]
    if bookable_only is not None and bookable_only.lower() == "true":
        items = [p for p in items if p["bookable_in_directory"]]
    return _list(items)


@app.get("/marketplace/providers/<provider_id>")
def get_provider_route(provider_id):
    require_role([ANY])
    return _obj(public(get_provider(provider_id)))


@app.post("/marketplace/providers/<provider_id>/activate")
def activate_provider(provider_id):
    require_role(["OpsAdmin"])
    provider = get_provider(provider_id)
    if provider["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", f"Provider is {provider['status']}")
    practice = DB.practices.get(provider["practice_id"])
    if practice is None or practice["status"] != "ACTIVE":
        raise ApiError("ERR_PRACTICE_NOT_ACTIVE", "Owning practice is not ACTIVE")
    provider["status"] = "ACTIVE"
    svc.recompute_bookable(provider)
    touch(provider)
    return _obj(public(provider))


@app.post("/marketplace/providers/<provider_id>/suspend")
def suspend_provider(provider_id):
    require_role(["OpsAdmin"])
    provider = get_provider(provider_id)
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Provider is {provider['status']}")
    svc.provider_suspend_cascade(provider)
    return _obj(public(provider))


@app.post("/marketplace/providers/<provider_id>/reinstate")
def reinstate_provider(provider_id):
    require_role(["OpsAdmin"])
    provider = get_provider(provider_id)
    if provider["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", f"Provider is {provider['status']}")
    practice = DB.practices.get(provider["practice_id"])
    if practice is None or practice["status"] != "ACTIVE":
        raise ApiError("ERR_PRACTICE_NOT_ACTIVE", "Owning practice is not ACTIVE")
    provider["status"] = "ACTIVE"
    svc.recompute_bookable(provider)
    touch(provider)
    return _obj(public(provider))


@app.post("/marketplace/providers/<provider_id>/delist")
def delist_provider(provider_id):
    require_role(["OpsAdmin"])
    provider = get_provider(provider_id)
    if provider["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", f"Provider is {provider['status']}")
    svc.provider_delist_cascade(provider)
    return _obj(public(provider))


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------

def _check_slot_publish(provider_id):
    provider = get_provider(provider_id)
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_BOOKABLE", "Provider is not ACTIVE")
    practice = DB.practices.get(provider["practice_id"])
    if practice is None or practice["status"] != "ACTIVE":
        raise ApiError("ERR_PRACTICE_NOT_ACTIVE", "Owning practice is not ACTIVE")
    return provider


def _slot_publish_ownership(uid, role, provider):
    if role == "Provider":
        own_check(role, uid, provider["id"] == uid)
    elif role == "PracticeStaff":
        own_check(role, uid, provider["practice_id"] == uid)


@app.post("/marketplace/providers/<provider_id>/slots")
def create_slot(provider_id):
    uid, role = require_role(["Provider", "PracticeStaff"])
    body = get_json_body(required=True)
    start_at = req_str(body, "start_at")
    end_at = req_str(body, "end_at")
    try:
        start_dt = parse_iso(start_at)
        end_dt = parse_iso(end_at)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "start_at and end_at must be ISO 8601 datetimes")
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    provider = get_provider(provider_id)
    _slot_publish_ownership(uid, role, provider)
    if start_dt <= DB.clock.now():
        raise ApiError("ERR_SLOT_IN_PAST", "Slot start_at must be strictly after the logical clock")
    _check_slot_publish(provider_id)
    if svc.slot_overlaps(provider_id, start_dt, end_dt):
        raise ApiError("ERR_SLOT_OVERLAP", "Slot overlaps an existing OPEN or BOOKED slot")
    rec = new_resource(DB.next_seq())
    rec.update({
        "provider_id": provider_id,
        "start_at": fmt_iso(start_dt),
        "end_at": fmt_iso(end_dt),
        "status": "OPEN",
        "close_reason": None,
        "current_booking_id": None,
    })
    DB.slots[rec["id"]] = rec
    touch(provider)
    return _obj(public(rec), 201)


@app.post("/marketplace/providers/<provider_id>/slots/bulk-publish")
def bulk_publish(provider_id):
    uid, role = require_role(["Provider", "PracticeStaff"])
    body = get_json_body(required=True)
    slots_in = body.get("slots")
    if not isinstance(slots_in, list):
        raise ApiError("ERR_INVALID_REQUEST", "slots must be an array")
    if "expected_provider_version" not in body:
        raise ApiError("ERR_INVALID_REQUEST", "expected_provider_version is required")
    expected = body["expected_provider_version"]
    if not is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_provider_version must be an integer")
    parsed = []
    for item in slots_in:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each slot must be an object")
        s_raw = item.get("start_at")
        e_raw = item.get("end_at")
        if not isinstance(s_raw, str) or not isinstance(e_raw, str):
            raise ApiError("ERR_INVALID_REQUEST", "each slot needs start_at and end_at")
        try:
            s_dt = parse_iso(s_raw)
            e_dt = parse_iso(e_raw)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "slot times must be ISO 8601 datetimes")
        if e_dt <= s_dt:
            raise ApiError("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
        parsed.append((s_dt, e_dt))
    provider = get_provider(provider_id)
    _slot_publish_ownership(uid, role, provider)
    now = DB.clock.now()
    for s_dt, _e in parsed:
        if s_dt <= now:
            raise ApiError("ERR_SLOT_IN_PAST", "Slot start_at must be strictly after the logical clock")
    _check_slot_publish(provider_id)
    # OCC
    if provider["version"] != expected:
        raise ApiError("ERR_STALE_VERSION", "expected_provider_version does not match")
    # overlap pre-check: against existing OPEN/BOOKED and within payload itself
    for s_dt, e_dt in parsed:
        if svc.slot_overlaps(provider_id, s_dt, e_dt):
            raise ApiError("ERR_SLOT_OVERLAP", "Slot overlaps an existing OPEN or BOOKED slot")
    sorted_payload = sorted(parsed, key=lambda se: se[0])
    for i in range(len(sorted_payload)):
        for j in range(i + 1, len(sorted_payload)):
            a_s, a_e = sorted_payload[i]
            b_s, b_e = sorted_payload[j]
            if b_s >= a_e:
                break
            if a_s < b_e and b_s < a_e:
                raise ApiError("ERR_SLOT_OVERLAP", "Payload slots overlap each other")
    # commit: supersede future OPEN slots not in payload
    payload_intervals = set((s, e) for s, e in parsed)
    closed_count = 0
    for slot in list(DB.slots.values()):
        if slot["provider_id"] != provider_id or slot["status"] != "OPEN":
            continue
        s_dt = parse_iso(slot["start_at"])
        if s_dt <= now:
            continue
        if (s_dt, parse_iso(slot["end_at"])) not in payload_intervals:
            slot["status"] = "CLOSED"
            slot["close_reason"] = "PROVIDER_CLOSED"
            touch(slot)
            closed_count += 1
    created_count = 0
    for s_dt, e_dt in parsed:
        rec = new_resource(DB.next_seq())
        rec.update({
            "provider_id": provider_id,
            "start_at": fmt_iso(s_dt),
            "end_at": fmt_iso(e_dt),
            "status": "OPEN",
            "close_reason": None,
            "current_booking_id": None,
        })
        DB.slots[rec["id"]] = rec
        created_count += 1
    touch(provider)
    return _obj({"created_count": created_count, "closed_count": closed_count})


@app.get("/marketplace/slots")
def list_slots():
    require_role([ANY])
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    from_q = request.args.get("from")
    to_q = request.args.get("to")
    items = sort_by_created(list(DB.slots.values()))
    if provider_id is not None:
        items = [s for s in items if s["provider_id"] == provider_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if from_q is not None:
        try:
            from_dt = parse_iso(from_q)
            items = [s for s in items if parse_iso(s["start_at"]) >= from_dt]
        except Exception:
            pass
    if to_q is not None:
        try:
            to_dt = parse_iso(to_q)
            items = [s for s in items if parse_iso(s["start_at"]) <= to_dt]
        except Exception:
            pass
    return _list(items)


@app.get("/marketplace/slots/<slot_id>")
def get_slot_route(slot_id):
    require_role([ANY])
    return _obj(public(get_slot(slot_id)))


@app.post("/marketplace/slots/<slot_id>/close")
def close_slot(slot_id):
    uid, role = require_role(["Provider", "PracticeStaff"])
    slot = get_slot(slot_id)
    provider = DB.providers.get(slot["provider_id"])
    if role == "Provider":
        own_check(role, uid, slot["provider_id"] == uid)
    else:
        own_check(role, uid, provider is not None and provider["practice_id"] == uid)
    if slot["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Slot is {slot['status']}")
    slot["status"] = "CLOSED"
    slot["close_reason"] = "PROVIDER_CLOSED"
    touch(slot)
    return _obj(public(slot))


# ---------------------------------------------------------------------------
# Appointment types
# ---------------------------------------------------------------------------

@app.post("/marketplace/providers/<provider_id>/appointment-types")
def create_type(provider_id):
    uid, role = require_role(["Provider", "PracticeStaff"])
    body = get_json_body(required=True)
    code = req_str(body, "code")
    display_name = req_str(body, "display_name")
    duration = req_int(body, "duration_minutes")
    copay = req_int(body, "booked_copay_cents")
    accepts_new = opt_bool(body, "accepts_new_patients", True)
    provider = get_provider(provider_id)
    _slot_publish_ownership(uid, role, provider)
    rec = new_resource(DB.next_seq())
    rec.update({
        "provider_id": provider_id,
        "code": code,
        "display_name": display_name,
        "duration_minutes": duration,
        "booked_copay_cents": copay,
        "accepts_new_patients": accepts_new,
        "status": "ACTIVE",
    })
    DB.appointment_types[rec["id"]] = rec
    return _obj(public(rec), 201)


@app.get("/marketplace/appointment-types")
def list_types():
    require_role([ANY])
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    items = sort_by_created(list(DB.appointment_types.values()))
    if provider_id is not None:
        items = [t for t in items if t["provider_id"] == provider_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return _list(items)


@app.get("/marketplace/appointment-types/<type_id>")
def get_type_route(type_id):
    require_role([ANY])
    return _obj(public(get_type(type_id)))


@app.post("/marketplace/appointment-types/<type_id>/retire")
def retire_type(type_id):
    uid, role = require_role(["Provider", "PracticeStaff"])
    atype = get_type(type_id)
    provider = DB.providers.get(atype["provider_id"])
    if role == "Provider":
        own_check(role, uid, atype["provider_id"] == uid)
    else:
        own_check(role, uid, provider is not None and provider["practice_id"] == uid)
    if atype["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"AppointmentType is {atype['status']}")
    atype["status"] = "RETIRED"
    touch(atype)
    return _obj(public(atype))


# ---------------------------------------------------------------------------
# Insurance plans
# ---------------------------------------------------------------------------

@app.post("/marketplace/insurance-plans")
def create_plan():
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    carrier = req_str(body, "carrier")
    plan_name = req_str(body, "plan_name")
    plan_code = req_str(body, "plan_code")
    if any(p["plan_code"] == plan_code for p in DB.plans.values()):
        raise ApiError("ERR_INVALID_REQUEST", "plan_code must be unique across all plans")
    rec = new_resource(DB.next_seq())
    rec.update({
        "carrier": carrier,
        "plan_name": plan_name,
        "plan_code": plan_code,
        "status": "ACTIVE",
    })
    DB.plans[rec["id"]] = rec
    return _obj(public(rec), 201)


@app.get("/marketplace/insurance-plans")
def list_plans():
    require_role([ANY])
    carrier = request.args.get("carrier")
    status = request.args.get("status")
    items = sort_by_created(list(DB.plans.values()))
    if carrier is not None:
        items = [p for p in items if p["carrier"] == carrier]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return _list(items)


@app.get("/marketplace/insurance-plans/<plan_id>")
def get_plan_route(plan_id):
    require_role([ANY])
    return _obj(public(get_plan(plan_id)))


@app.post("/marketplace/insurance-plans/<plan_id>/retire")
def retire_plan(plan_id):
    require_role(["OpsAdmin"])
    plan = get_plan(plan_id)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"InsurancePlan is {plan['status']}")
    plan["status"] = "RETIRED"
    touch(plan)
    return _obj(public(plan))


# ---------------------------------------------------------------------------
# Attestations
# ---------------------------------------------------------------------------

@app.post("/marketplace/attestations")
def create_attestation():
    uid, role = require_role(["Provider", "PracticeStaff"])
    body = get_json_body(required=True)
    provider_id = req_str(body, "provider_id")
    plan_id = req_str(body, "plan_id")
    eff_from = req_str(body, "effective_from")
    eff_to = req_str(body, "effective_to")
    try:
        from_dt = parse_iso(eff_from)
        to_dt = parse_iso(eff_to)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "effective_from/effective_to must be ISO 8601 datetimes")
    if to_dt <= from_dt:
        raise ApiError("ERR_INVALID_REQUEST", "effective_to must be strictly after effective_from")
    # ownership (priority 4) before existence (priority 5)
    if role == "Provider":
        own_check(role, uid, provider_id == uid)
    else:
        prov = DB.providers.get(provider_id)
        own_check(role, uid, prov is not None and prov["practice_id"] == uid)
    get_provider(provider_id)
    get_plan(plan_id)
    if any(
        a["provider_id"] == provider_id and a["plan_id"] == plan_id
        and a["status"] in ("ATTESTED", "VERIFIED")
        for a in DB.attestations.values()
    ):
        raise ApiError("ERR_DUPLICATE_ATTESTATION", "An ATTESTED or VERIFIED attestation already exists for this provider and plan")
    rec = new_resource(DB.next_seq())
    rec.update({
        "provider_id": provider_id,
        "plan_id": plan_id,
        "effective_from": fmt_iso(from_dt),
        "effective_to": fmt_iso(to_dt),
        "status": "ATTESTED",
        "verified_by": None,
    })
    DB.attestations[rec["id"]] = rec
    return _obj(public(rec), 201)


def _attestation_scope(uid, role, att):
    if role == "OpsAdmin":
        return
    if role == "Provider":
        own_check(role, uid, att["provider_id"] == uid)
    else:  # PracticeStaff
        prov = DB.providers.get(att["provider_id"])
        own_check(role, uid, prov is not None and prov["practice_id"] == uid)


@app.get("/marketplace/attestations")
def list_attestations():
    uid, role = require_role(["OpsAdmin", "Provider", "PracticeStaff"])
    provider_id = request.args.get("provider_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    items = sort_by_created(list(DB.attestations.values()))
    if role != "OpsAdmin":
        if role == "Provider":
            items = [a for a in items if a["provider_id"] == uid]
        else:
            own_providers = {p["id"] for p in DB.providers.values() if p["practice_id"] == uid}
            items = [a for a in items if a["provider_id"] in own_providers]
    if provider_id is not None:
        items = [a for a in items if a["provider_id"] == provider_id]
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return _list(items)


@app.get("/marketplace/attestations/<attestation_id>")
def get_attestation_route(attestation_id):
    uid, role = require_role(["OpsAdmin", "Provider", "PracticeStaff"])
    att = get_attestation(attestation_id)
    _attestation_scope(uid, role, att)
    return _obj(public(att))


@app.post("/marketplace/attestations/<attestation_id>/verify")
def verify_attestation(attestation_id):
    uid, role = require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    decision = req_enum(body, "decision", {"VERIFY", "REJECT"})
    att = get_attestation(attestation_id)
    if att["status"] != "ATTESTED":
        raise ApiError("ERR_INVALID_STATE", f"Attestation is {att['status']}")
    if decision == "VERIFY":
        plan = DB.plans.get(att["plan_id"])
        if plan is None or plan["status"] != "ACTIVE":
            raise ApiError("ERR_PLAN_NOT_ACTIVE", "Insurance plan is not ACTIVE")
        att["status"] = "VERIFIED"
        att["verified_by"] = uid
    else:
        att["status"] = "REJECTED"
    touch(att)
    return _obj(public(att))


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@app.post("/marketplace/patients")
def create_patient():
    require_role(["Anonymous"])
    body = get_json_body(required=True)
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    plan_id = opt_str(body, "plan_id", None)
    if any(p["email"] == email for p in DB.patients.values()):
        raise ApiError("ERR_INVALID_REQUEST", "email must be unique across all patients")
    if plan_id is not None:
        get_plan(plan_id)
    rec = new_resource(DB.next_seq())
    rec.update({
        "full_name": full_name,
        "email": email,
        "plan_id": plan_id,
        "reliability_score": 100,
        "provisional_score": 100,
        "strikes": [],
        "recovery_count": 0,
    })
    DB.patients[rec["id"]] = rec
    return _obj(public(rec), 201)


@app.get("/marketplace/patients")
def list_patients():
    require_role(["OpsAdmin"])
    plan_id = request.args.get("plan_id")
    items = sort_by_created(list(DB.patients.values()))
    if plan_id is not None:
        items = [p for p in items if p["plan_id"] == plan_id]
    return _list(items)


@app.get("/marketplace/patients/<patient_id>")
def get_patient_route(patient_id):
    uid, role = require_role(["Patient", "OpsAdmin"])
    patient = get_patient(patient_id)
    if role == "Patient":
        own_check(role, uid, patient_id == uid)
    return _obj(public(patient))


@app.patch("/marketplace/patients/<patient_id>")
def patch_patient(patient_id):
    uid, role = require_role(["Patient"])
    body = get_json_body(required=True)
    if "expected_patient_version" not in body:
        raise ApiError("ERR_INVALID_REQUEST", "expected_patient_version is required")
    expected = body["expected_patient_version"]
    if not is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_patient_version must be an integer")
    plan_id = body.get("plan_id", None)
    if plan_id is not None and not isinstance(plan_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "plan_id must be a string or null")
    own_check(role, uid, patient_id == uid)
    patient = get_patient(patient_id)
    if plan_id is not None:
        get_plan(plan_id)
    if patient["version"] != expected:
        raise ApiError("ERR_STALE_VERSION", "expected_patient_version does not match")
    patient["plan_id"] = plan_id
    touch(patient)
    return _obj(public(patient))


# ---------------------------------------------------------------------------
# Contact events
# ---------------------------------------------------------------------------

@app.post("/marketplace/contact-events")
def create_contact_event():
    uid, role = require_role(["PracticeStaff"])
    body = get_json_body(required=True)
    patient_id = req_str(body, "patient_id")
    provider_id = opt_str(body, "provider_id", None)
    contacted_at = req_str(body, "contacted_at")
    channel = req_enum(body, "channel", {"PHONE", "EMAIL", "PORTAL", "WALKIN"})
    try:
        contacted_dt = parse_iso(contacted_at)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "contacted_at must be an ISO 8601 datetime")
    get_patient(patient_id)
    if provider_id is not None:
        get_provider(provider_id)
    rec = new_resource(DB.next_seq(), common=False)
    rec.update({
        "patient_id": patient_id,
        "practice_id": uid,
        "provider_id": provider_id,
        "contacted_at": fmt_iso(contacted_dt),
        "channel": channel,
    })
    DB.contact_events[rec["id"]] = rec
    return _obj(public(rec), 201)


def _event_scope(uid, role, ev):
    if role == "OpsAdmin":
        return
    own_check(role, uid, ev["practice_id"] == uid)


@app.get("/marketplace/contact-events")
def list_contact_events():
    uid, role = require_role(["PracticeStaff", "OpsAdmin"])
    patient_id = request.args.get("patient_id")
    practice_id = request.args.get("practice_id")
    provider_id = request.args.get("provider_id")
    items = sort_by_created(list(DB.contact_events.values()))
    if role == "PracticeStaff":
        items = [e for e in items if e["practice_id"] == uid]
    if patient_id is not None:
        items = [e for e in items if e["patient_id"] == patient_id]
    if practice_id is not None:
        items = [e for e in items if e["practice_id"] == practice_id]
    if provider_id is not None:
        items = [e for e in items if e["provider_id"] == provider_id]
    return _list(items)


@app.get("/marketplace/contact-events/<event_id>")
def get_contact_event(event_id):
    uid, role = require_role(["PracticeStaff", "OpsAdmin"])
    ev = get_event(event_id)
    _event_scope(uid, role, ev)
    return _obj(public(ev))


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

@app.post("/marketplace/slots/<slot_id>/bookings")
def create_booking(slot_id):
    uid, role = require_role(["Patient"])
    body = get_json_body(required=True)
    patient_id = req_str(body, "patient_id")
    type_id = req_str(body, "appointment_type_id")
    plan_id = body.get("insurance_plan_id", None)
    if plan_id is not None and not isinstance(plan_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "insurance_plan_id must be a string or null")
    # ownership (priority 4) before existence (priority 5)
    own_check(role, uid, patient_id == uid)
    # existence: path first, then body refs
    slot = get_slot(slot_id)
    get_patient(patient_id)
    get_type(type_id)
    if plan_id is not None:
        get_plan(plan_id)
    provider = get_provider(slot["provider_id"])
    practice = DB.practices.get(provider["practice_id"])
    # state: slot must be OPEN
    if slot["status"] != "OPEN":
        raise ApiError("ERR_SLOT_NOT_OPEN", f"Slot is {slot['status']}")
    # new-patient determination
    is_new = not any(
        b["patient_id"] == patient_id and b["practice_id"] == provider["practice_id"]
        and b["status"] == "COMPLETED"
        for b in DB.bookings.values()
    )
    # temporal: lead time
    lead_hours = provider["lead_time_override_hours"]
    if lead_hours is None:
        lead_hours = practice["new_patient_lead_time_hours"] if is_new else practice["existing_patient_lead_time_hours"]
    slot_start = parse_iso(slot["start_at"])
    if (slot_start - DB.clock.now()).total_seconds() < lead_hours * 3600:
        raise ApiError("ERR_LEAD_TIME_VIOLATION", "Slot start is sooner than the applicable lead time")
    # constraint: insurance acceptance
    if plan_id is not None and not svc.plan_accepted(provider["id"], plan_id):
        raise ApiError("ERR_PLAN_NOT_ACCEPTED", "Provider does not hold a VERIFIED attestation covering this plan")
    # constraint: type mapping
    atype = DB.appointment_types[type_id]
    if atype["provider_id"] != provider["id"] or atype["status"] != "ACTIVE":
        raise ApiError("ERR_TYPE_MAPPING_MISSING", "Appointment type does not belong to the slot's provider or is RETIRED")
    # constraint: new-patient gate
    if not atype["accepts_new_patients"] and is_new:
        raise ApiError("ERR_NEW_PATIENT_TYPE_BLOCKED", "Appointment type does not accept new patients")
    # constraint: reliability gate
    patient = DB.patients[patient_id]
    if patient["reliability_score"] < 50:
        raise ApiError("ERR_RELIABILITY_GATE", "Patient reliability_score is below 50")
    # create booking
    now_iso = DB.clock.now_iso()
    attribution = svc.compute_attribution(patient_id, provider["practice_id"], provider["id"], DB.clock.now())
    rec = new_resource(DB.next_seq())
    rec.update({
        "slot_id": slot_id,
        "patient_id": patient_id,
        "provider_id": provider["id"],
        "practice_id": provider["practice_id"],
        "appointment_type_id": type_id,
        "insurance_plan_id": plan_id,
        "start_at": slot["start_at"],
        "end_at": slot["end_at"],
        "booked_copay_cents": atype["booked_copay_cents"],
        "is_new_patient": is_new,
        "attribution_status": attribution,
        "late_cancel": False,
        "cancel_reason": None,
        "status": "CONFIRMED",
    })
    DB.bookings[rec["id"]] = rec
    slot["status"] = "BOOKED"
    slot["current_booking_id"] = rec["id"]
    touch(slot)
    if attribution == "ATTRIBUTED" and practice["billing_mode"] == "PER_BOOKING":
        svc.create_charge(rec, practice)
    return _obj(public(rec), 201)


def _booking_scope(uid, role, booking):
    if role == "OpsAdmin":
        return
    if role == "Patient":
        own_check(role, uid, booking["patient_id"] == uid)
    else:  # PracticeStaff
        own_check(role, uid, booking["practice_id"] == uid)


@app.get("/marketplace/bookings")
def list_bookings():
    uid, role = require_role(["Patient", "PracticeStaff", "OpsAdmin"])
    items = sort_by_created(list(DB.bookings.values()))
    if role == "Patient":
        items = [b for b in items if b["patient_id"] == uid]
    elif role == "PracticeStaff":
        items = [b for b in items if b["practice_id"] == uid]
    for param in ("patient_id", "provider_id", "slot_id", "practice_id",
                  "appointment_type_id", "insurance_plan_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b.get(param) == v]
    return _list(items)


@app.get("/marketplace/bookings/<booking_id>")
def get_booking_route(booking_id):
    uid, role = require_role(["Patient", "PracticeStaff", "OpsAdmin"])
    booking = get_booking(booking_id)
    _booking_scope(uid, role, booking)
    return _obj(public(booking))


@app.post("/marketplace/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    uid, role = require_role(["Patient", "PracticeStaff"])
    booking = get_booking(booking_id)
    _booking_scope(uid, role, booking)
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_BOOKING_NOT_CANCELLABLE", f"Booking is {booking['status']}")
    hours_before = (parse_iso(booking["start_at"]) - DB.clock.now()).total_seconds() / 3600
    if hours_before < 2:
        raise ApiError("ERR_CANCELLATION_TOO_LATE", "Cancellation requires at least 2 hours before start")
    patient = DB.patients.get(booking["patient_id"])
    if hours_before < 24:
        booking["late_cancel"] = True
        if patient is not None:
            patient["strikes"].append({
                "epoch": DB.epoch, "magnitude": svc.LATE_CANCEL_MAGNITUDE, "kind": "LATE_CANCEL",
            })
            svc.rescore(patient)
            touch(patient)
    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = "PATIENT" if role == "Patient" else "PRACTICE"
    touch(booking)
    slot = DB.slots.get(booking["slot_id"])
    if slot is not None and slot["status"] == "BOOKED":
        slot["status"] = "OPEN"
        slot["current_booking_id"] = None
        touch(slot)
    if patient is not None and booking["late_cancel"]:
        svc.reliability_gate_cascade(patient, exclude_booking_id=booking["id"])
    return _obj(public(booking))


@app.post("/marketplace/bookings/<booking_id>/check-in")
def check_in_booking(booking_id):
    uid, role = require_role(["PracticeStaff"])
    booking = get_booking(booking_id)
    _booking_scope(uid, role, booking)
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", f"Booking is {booking['status']}")
    booking["status"] = "CHECKED_IN"
    touch(booking)
    return _obj(public(booking))


@app.post("/marketplace/bookings/<booking_id>/complete")
def complete_booking(booking_id):
    uid, role = require_role(["PracticeStaff"])
    booking = get_booking(booking_id)
    _booking_scope(uid, role, booking)
    if booking["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", f"Booking is {booking['status']}")
    booking["status"] = "COMPLETED"
    touch(booking)
    # visit record
    vr = new_resource(DB.next_seq(), common=False)
    vr.update({
        "booking_id": booking["id"],
        "provider_id": booking["provider_id"],
        "patient_id": booking["patient_id"],
        "completed_at": DB.clock.now_iso(),
        "verification": "VERIFIED",
    })
    DB.visit_records[vr["id"]] = vr
    # recovery
    patient = DB.patients.get(booking["patient_id"])
    if patient is not None:
        patient["recovery_count"] += 1
        svc.rescore(patient)
        touch(patient)
    # slot BOOKED -> CLOSED
    slot = DB.slots.get(booking["slot_id"])
    if slot is not None and slot["status"] == "BOOKED":
        slot["status"] = "CLOSED"
        slot["close_reason"] = "PROVIDER_CLOSED"
        touch(slot)
    return _obj(public(booking))


@app.post("/marketplace/bookings/<booking_id>/mark-no-show")
def no_show_booking(booking_id):
    uid, role = require_role(["PracticeStaff"])
    booking = get_booking(booking_id)
    _booking_scope(uid, role, booking)
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", f"Booking is {booking['status']}")
    if DB.clock.now() < parse_iso(booking["start_at"]):
        raise ApiError("ERR_NO_SHOW_TOO_EARLY", "No-show can only be marked at or after the booking start")
    booking["status"] = "NO_SHOW"
    touch(booking)
    patient = DB.patients.get(booking["patient_id"])
    if patient is not None:
        patient["strikes"].append({
            "epoch": DB.epoch, "magnitude": svc.NO_SHOW_MAGNITUDE, "kind": "NO_SHOW",
        })
        svc.rescore(patient)
        touch(patient)
    slot = DB.slots.get(booking["slot_id"])
    if slot is not None and slot["status"] == "BOOKED":
        slot["status"] = "CLOSED"
        slot["close_reason"] = "PROVIDER_SUSPENDED"
        touch(slot)
    if patient is not None:
        svc.reliability_gate_cascade(patient, exclude_booking_id=booking["id"])
    return _obj(public(booking))


# ---------------------------------------------------------------------------
# Charges
# ---------------------------------------------------------------------------

def _charge_scope(uid, role, charge):
    if role == "OpsAdmin":
        return
    own_check(role, uid, charge["practice_id"] == uid)


@app.get("/marketplace/charges")
def list_charges():
    uid, role = require_role(["OpsAdmin", "PracticeStaff"])
    items = sort_by_created(list(DB.charges.values()))
    if role == "PracticeStaff":
        items = [c for c in items if c["practice_id"] == uid]
    for param in ("booking_id", "practice_id", "invoice_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    return _list(items)


@app.get("/marketplace/charges/<charge_id>")
def get_charge_route(charge_id):
    uid, role = require_role(["OpsAdmin", "PracticeStaff"])
    charge = get_charge(charge_id)
    _charge_scope(uid, role, charge)
    return _obj(public(charge))


# ---------------------------------------------------------------------------
# Billing / invoices
# ---------------------------------------------------------------------------

@app.post("/marketplace/billing/generate-invoices")
def generate_invoices():
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    practice_id = req_str(body, "practice_id")
    period = req_str(body, "period")
    if not PERIOD_RE.match(period):
        raise ApiError("ERR_INVALID_REQUEST", "period must be in YYYY-MM format")
    practice = get_practice(practice_id)
    invoice = svc.generate_invoice(practice, period)
    return _obj(public(invoice), 201)


def _invoice_scope(uid, role, invoice):
    if role == "OpsAdmin":
        return
    own_check(role, uid, invoice["practice_id"] == uid)


@app.get("/marketplace/invoices")
def list_invoices():
    uid, role = require_role(["OpsAdmin", "PracticeStaff"])
    items = sort_by_created(list(DB.invoices.values()))
    if role == "PracticeStaff":
        items = [i for i in items if i["practice_id"] == uid]
    practice_id = request.args.get("practice_id")
    status = request.args.get("status")
    if practice_id is not None:
        items = [i for i in items if i["practice_id"] == practice_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return _list(items)


@app.get("/marketplace/invoices/<invoice_id>")
def get_invoice_route(invoice_id):
    uid, role = require_role(["OpsAdmin", "PracticeStaff"])
    invoice = get_invoice(invoice_id)
    _invoice_scope(uid, role, invoice)
    return _obj(public(invoice))


@app.post("/marketplace/invoices/<invoice_id>/dispute")
def dispute_invoice(invoice_id):
    uid, role = require_role(["PracticeStaff"])
    body = get_json_body(required=True)
    charge_ids = body.get("charge_ids")
    if not isinstance(charge_ids, list) or not all(isinstance(c, str) for c in charge_ids):
        raise ApiError("ERR_INVALID_REQUEST", "charge_ids must be a non-empty array of strings")
    reason = req_str(body, "reason")
    invoice = get_invoice(invoice_id)
    charges = []
    for cid in charge_ids:
        charges.append(get_charge(cid))
    _invoice_scope(uid, role, invoice)
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_DISPUTABLE", f"Invoice is {invoice['status']}")
    practice = DB.practices.get(invoice["practice_id"])
    if practice is not None and practice["billing_mode"] == "SUBSCRIPTION":
        raise ApiError("ERR_BILLING_MODE_MISMATCH", "Charge-level dispute is unavailable for SUBSCRIPTION practices")
    for charge in charges:
        if charge["invoice_id"] != invoice_id:
            raise ApiError("ERR_CHARGE_NOT_IN_INVOICE", f"Charge {charge['id']} does not belong to this invoice")
        if charge["status"] != "INVOICED":
            raise ApiError("ERR_INVALID_STATE", f"Charge {charge['id']} is {charge['status']}")
    invoice["status"] = "DISPUTED"
    touch(invoice)
    for charge in charges:
        charge["status"] = "DISPUTED"
        touch(charge)
    return _obj(public(invoice))


@app.post("/marketplace/invoices/<invoice_id>/resolve-dispute")
def resolve_dispute(invoice_id):
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    resolutions = body.get("resolutions")
    if not isinstance(resolutions, list) or not resolutions:
        raise ApiError("ERR_INVALID_REQUEST", "resolutions must be a non-empty array")
    parsed = []
    for r in resolutions:
        if not isinstance(r, dict) or not isinstance(r.get("charge_id"), str):
            raise ApiError("ERR_INVALID_REQUEST", "each resolution needs a charge_id")
        action = r.get("action")
        if action not in ("KEEP", "REMOVE"):
            raise ApiError("ERR_INVALID_REQUEST", "action must be KEEP or REMOVE")
        parsed.append((r["charge_id"], action))
    invoice = get_invoice(invoice_id)
    if invoice["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", f"Invoice is {invoice['status']}")
    disputed = [c for c in DB.charges.values() if c["invoice_id"] == invoice_id and c["status"] == "DISPUTED"]
    disputed_ids = [c["id"] for c in disputed]
    res_ids = [cid for cid, _ in parsed]
    if sorted(res_ids) != sorted(disputed_ids) or len(set(res_ids)) != len(res_ids):
        raise ApiError("ERR_INVALID_REQUEST", "resolutions must cover every DISPUTED charge exactly once")
    for cid, action in parsed:
        charge = DB.charges[cid]
        if action == "KEEP":
            charge["status"] = "INVOICED"
        else:
            charge["status"] = "REFUNDED"
            svc.append_ledger(invoice_id, "DISPUTE_CREDIT", -charge["marketplace_fee_cents"], charge_id=cid)
        touch(charge)
    invoice["status"] = "ISSUED"
    svc.recompute_amount_due(invoice)
    touch(invoice)
    return _obj(public(invoice))


@app.post("/marketplace/invoices/<invoice_id>/pay")
def pay_invoice(invoice_id):
    uid, role = require_role(["PracticeStaff"])
    invoice = get_invoice(invoice_id)
    _invoice_scope(uid, role, invoice)
    if invoice["status"] != "ISSUED" or invoice["amount_due_cents"] <= 0:
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "Invoice must be ISSUED with a positive amount due")
    svc.append_ledger(invoice_id, "PAYMENT", -invoice["amount_due_cents"])
    svc.recompute_amount_due(invoice)
    invoice["status"] = "PAID"
    touch(invoice)
    for charge in DB.charges.values():
        if charge["invoice_id"] == invoice_id and charge["status"] == "INVOICED":
            charge["status"] = "SETTLED"
            touch(charge)
    return _obj(public(invoice))


@app.post("/marketplace/invoices/<invoice_id>/write-off")
def write_off_invoice(invoice_id):
    require_role(["OpsAdmin"])
    invoice = get_invoice(invoice_id)
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", f"Invoice is {invoice['status']}")
    svc.append_ledger(invoice_id, "WRITE_OFF", -invoice["amount_due_cents"])
    svc.recompute_amount_due(invoice)
    invoice["status"] = "WRITTEN_OFF"
    touch(invoice)
    return _obj(public(invoice))


# ---------------------------------------------------------------------------
# Ledger entries
# ---------------------------------------------------------------------------

def _entry_scope(uid, role, entry):
    if role == "OpsAdmin":
        return
    invoice = DB.invoices.get(entry["invoice_id"])
    own_check(role, uid, invoice is not None and invoice["practice_id"] == uid)


@app.get("/marketplace/ledger-entries")
def list_ledger_entries():
    uid, role = require_role(["OpsAdmin", "PracticeStaff"])
    items = sort_by_created(list(DB.ledger_entries.values()))
    if role == "PracticeStaff":
        allowed = {i["id"] for i in DB.invoices.values() if i["practice_id"] == uid}
        items = [e for e in items if e["invoice_id"] in allowed]
    for param in ("invoice_id", "charge_id", "entry_type"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    return _list(items)


@app.get("/marketplace/ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    uid, role = require_role(["OpsAdmin", "PracticeStaff"])
    entry = get_entry(entry_id)
    _entry_scope(uid, role, entry)
    return _obj(public(entry))


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

@app.post("/marketplace/complaints")
def create_complaint():
    uid, role = require_role(["Patient"])
    body = get_json_body(required=True)
    booking_id = req_str(body, "booking_id")
    complaint_type = req_enum(body, "complaint_type", {"INSURANCE_MISMATCH", "DIRECTORY_INACCURACY", "OTHER"})
    description = opt_str(body, "description", None)
    booking = get_booking(booking_id)
    own_check(role, uid, booking["patient_id"] == uid)
    if booking["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "Cannot file a complaint on a CANCELLED booking")
    rec = new_resource(DB.next_seq())
    rec.update({
        "booking_id": booking_id,
        "patient_id": booking["patient_id"],
        "provider_id": booking["provider_id"],
        "complaint_type": complaint_type,
        "description": description,
        "response": None,
        "outcome": None,
        "status": "OPEN",
    })
    DB.complaints[rec["id"]] = rec
    return _obj(public(rec), 201)


def _complaint_scope(uid, role, complaint):
    if role == "OpsAdmin":
        return
    if role == "Patient":
        own_check(role, uid, complaint["patient_id"] == uid)
    else:  # PracticeStaff
        provider = DB.providers.get(complaint["provider_id"])
        own_check(role, uid, provider is not None and provider["practice_id"] == uid)


@app.get("/marketplace/complaints")
def list_complaints():
    uid, role = require_role(["OpsAdmin", "PracticeStaff", "Patient"])
    items = sort_by_created(list(DB.complaints.values()))
    if role == "Patient":
        items = [c for c in items if c["patient_id"] == uid]
    elif role == "PracticeStaff":
        own_providers = {p["id"] for p in DB.providers.values() if p["practice_id"] == uid}
        items = [c for c in items if c["provider_id"] in own_providers]
    for param in ("booking_id", "provider_id", "patient_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    return _list(items)


@app.get("/marketplace/complaints/<complaint_id>")
def get_complaint_route(complaint_id):
    uid, role = require_role(["OpsAdmin", "PracticeStaff", "Patient"])
    complaint = get_complaint(complaint_id)
    _complaint_scope(uid, role, complaint)
    return _obj(public(complaint))


@app.post("/marketplace/complaints/<complaint_id>/respond")
def respond_complaint(complaint_id):
    uid, role = require_role(["PracticeStaff"])
    body = get_json_body(required=True)
    response = req_str(body, "response")
    complaint = get_complaint(complaint_id)
    _complaint_scope(uid, role, complaint)
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_NOT_OPEN", f"Complaint is {complaint['status']}")
    complaint["response"] = response
    complaint["status"] = "UNDER_REVIEW"
    touch(complaint)
    return _obj(public(complaint))


@app.post("/marketplace/complaints/<complaint_id>/resolve")
def resolve_complaint(complaint_id):
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    outcome = req_enum(body, "outcome", {"UPHOLD", "DISMISS"})
    complaint = get_complaint(complaint_id)
    if complaint["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_COMPLAINT_NOT_OPEN", f"Complaint is {complaint['status']}")
    if outcome == "DISMISS":
        complaint["outcome"] = "DISMISS"
        complaint["status"] = "RESOLVED_DISMISSED"
        touch(complaint)
        return _obj(public(complaint))
    # UPHOLD
    if complaint["complaint_type"] == "INSURANCE_MISMATCH":
        booking = DB.bookings.get(complaint["booking_id"])
        plan_id = booking.get("insurance_plan_id") if booking else None
        att = svc.select_verified_attestation(complaint["provider_id"], plan_id)
        if att is None:
            raise ApiError("ERR_INVALID_STATE", "No VERIFIED attestation exists for the booking's provider and plan")
        att["status"] = "REVOKED"
        touch(att)
        provider = DB.providers.get(complaint["provider_id"])
        if provider is not None:
            provider["insurance_mismatch_count"] += 1
            if provider["insurance_mismatch_count"] >= 3 and provider["status"] == "ACTIVE":
                svc.provider_suspend_cascade(provider)
            else:
                touch(provider)
    complaint["outcome"] = "UPHOLD"
    complaint["status"] = "RESOLVED_UPHELD"
    touch(complaint)
    return _obj(public(complaint))


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@app.post("/marketplace/reviews")
def create_review():
    uid, role = require_role(["Patient"])
    body = get_json_body(required=True)
    booking_id = req_str(body, "booking_id")
    rating = req_int(body, "rating")
    if rating < 1 or rating > 5:
        raise ApiError("ERR_INVALID_REQUEST", "rating must be between 1 and 5")
    text = opt_str(body, "text", None)
    booking = get_booking(booking_id)
    own_check(role, uid, booking["patient_id"] == uid)
    if any(r["booking_id"] == booking_id for r in DB.reviews.values()):
        raise ApiError("ERR_DUPLICATE_REVIEW", "A review already exists for this booking")
    if not any(v["booking_id"] == booking_id and v["verification"] == "VERIFIED" for v in DB.visit_records.values()):
        raise ApiError("ERR_VISIT_NOT_VERIFIED", "Review requires a VERIFIED visit record for the booking")
    rec = new_resource(DB.next_seq())
    rec.update({
        "booking_id": booking_id,
        "patient_id": booking["patient_id"],
        "provider_id": booking["provider_id"],
        "rating": rating,
        "text": text,
        "flag_reason": None,
        "status": "PUBLISHED",
    })
    DB.reviews[rec["id"]] = rec
    return _obj(public(rec), 201)


@app.get("/marketplace/reviews")
def list_reviews():
    require_role([ANY])
    items = sort_by_created(list(DB.reviews.values()))
    for param in ("provider_id", "booking_id", "patient_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return _list(items)


@app.get("/marketplace/reviews/<review_id>")
def get_review_route(review_id):
    require_role([ANY])
    return _obj(public(get_review(review_id)))


@app.post("/marketplace/reviews/<review_id>/flag")
def flag_review(review_id):
    uid, role = require_role(["PracticeStaff", "Provider"])
    body = get_json_body(required=True)
    reason = req_str(body, "reason")
    review = get_review(review_id)
    if role == "Provider":
        own_check(role, uid, review["provider_id"] == uid)
    else:
        provider = DB.providers.get(review["provider_id"])
        own_check(role, uid, provider is not None and provider["practice_id"] == uid)
    if review["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", f"Review is {review['status']}")
    review["flag_reason"] = reason
    review["status"] = "FLAGGED"
    touch(review)
    return _obj(public(review))


@app.post("/marketplace/reviews/<review_id>/moderate")
def moderate_review(review_id):
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    action = req_enum(body, "action", {"RESTORE", "REMOVE"})
    review = get_review(review_id)
    if action == "RESTORE":
        if review["status"] != "FLAGGED":
            raise ApiError("ERR_INVALID_STATE", f"Review is {review['status']}")
        review["status"] = "PUBLISHED"
        review["flag_reason"] = None
    else:  # REMOVE
        if review["status"] not in ("PUBLISHED", "FLAGGED"):
            raise ApiError("ERR_INVALID_STATE", f"Review is {review['status']}")
        review["status"] = "REMOVED"
    touch(review)
    return _obj(public(review))


# ---------------------------------------------------------------------------
# Visit records
# ---------------------------------------------------------------------------

def _visit_scope(uid, role, vr):
    if role == "OpsAdmin":
        return
    if role == "Patient":
        own_check(role, uid, vr["patient_id"] == uid)
    else:  # PracticeStaff
        provider = DB.providers.get(vr["provider_id"])
        own_check(role, uid, provider is not None and provider["practice_id"] == uid)


@app.get("/marketplace/visit-records")
def list_visit_records():
    uid, role = require_role(["PracticeStaff", "OpsAdmin", "Patient"])
    items = sort_by_created(list(DB.visit_records.values()))
    if role == "Patient":
        items = [v for v in items if v["patient_id"] == uid]
    elif role == "PracticeStaff":
        own_providers = {p["id"] for p in DB.providers.values() if p["practice_id"] == uid}
        items = [v for v in items if v["provider_id"] in own_providers]
    for param in ("booking_id", "provider_id", "patient_id"):
        v = request.args.get(param)
        if v is not None:
            items = [x for x in items if x.get(param) == v]
    return _list(items)


@app.get("/marketplace/visit-records/<record_id>")
def get_visit_record_route(record_id):
    uid, role = require_role(["PracticeStaff", "OpsAdmin", "Patient"])
    vr = get_visit_record(record_id)
    _visit_scope(uid, role, vr)
    return _obj(public(vr))


@app.get("/marketplace/bookings/<booking_id>/visit-records")
def list_booking_visit_records(booking_id):
    uid, role = require_role(["PracticeStaff", "OpsAdmin", "Patient"])
    booking = get_booking(booking_id)
    _booking_scope(uid, role, booking)
    items = sort_by_created([v for v in DB.visit_records.values() if v["booking_id"] == booking_id])
    return _list(items)


# ---------------------------------------------------------------------------
# Audit cases
# ---------------------------------------------------------------------------

@app.post("/marketplace/audit-cases")
def create_audit_case():
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    provider_id = req_str(body, "provider_id")
    scope = req_enum(body, "scope", {"AVAILABILITY", "INSURANCE", "FULL"})
    get_provider(provider_id)
    rec = new_resource(DB.next_seq())
    rec.update({
        "provider_id": provider_id,
        "scope": scope,
        "sampled_count": 0,
        "mismatch_count": 0,
        "mismatch_rate": 0,
        "severity": "CLEAN",
        "findings": [],
        "status": "OPEN",
    })
    DB.audit_cases[rec["id"]] = rec
    return _obj(public(rec), 201)


@app.get("/marketplace/audit-cases")
def list_audit_cases():
    require_role(["OpsAdmin"])
    items = sort_by_created(list(DB.audit_cases.values()))
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    if provider_id is not None:
        items = [c for c in items if c["provider_id"] == provider_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return _list(items)


@app.get("/marketplace/audit-cases/<case_id>")
def get_audit_case(case_id):
    require_role(["OpsAdmin"])
    return _obj(public(get_case(case_id)))


@app.post("/marketplace/audit-cases/<case_id>/run")
def run_audit_case(case_id):
    require_role(["OpsAdmin"])
    case = get_case(case_id)
    if case["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"AuditCase is {case['status']}")
    svc.run_audit(case)
    return _obj(public(case))


@app.post("/marketplace/audit-cases/<case_id>/resolve-finding")
def resolve_finding(case_id):
    require_role(["OpsAdmin"])
    body = get_json_body(required=True)
    finding_index = body.get("finding_index")
    if not is_int(finding_index):
        raise ApiError("ERR_INVALID_REQUEST", "finding_index must be an integer")
    resolution_note = req_str(body, "resolution_note")
    case = get_case(case_id)
    if case["status"] != "FINDINGS_OPEN":
        raise ApiError("ERR_INVALID_STATE", f"AuditCase is {case['status']}")
    target = None
    for f in case["findings"]:
        if f["finding_index"] == finding_index:
            target = f
            break
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", f"No finding with index {finding_index}")
    target["resolved"] = True
    touch(case)
    return _obj(public(case))


@app.post("/marketplace/audit-cases/<case_id>/close")
def close_audit_case(case_id):
    require_role(["OpsAdmin"])
    case = get_case(case_id)
    if case["status"] != "FINDINGS_OPEN":
        raise ApiError("ERR_INVALID_STATE", f"AuditCase is {case['status']}")
    if any(not f["resolved"] for f in case["findings"]):
        raise ApiError("ERR_UNRESOLVED_FINDINGS", "Every finding must be resolved before closing")
    case["status"] = "CLOSED"
    touch(case)
    return _obj(public(case))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
