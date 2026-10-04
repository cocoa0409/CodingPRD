"""Urgent care benefit and pharmacy coordination (PRD section 3.8)."""
from flask import Blueprint, request

import constants as C
import db
import logical_clock
import response
import services
import validate as v
from errors import fail
from middleware import endpoint, require_owner

bp = Blueprint("urgent_rx", __name__)


@bp.post("/community-care/urgent-care-visits")
@endpoint([C.ROLE_VETERAN, C.ROLE_ELIGIBILITY_CLERK])
def create_urgent_visit(user_id, role):
    b = v.body()
    vet = v.body_fk(b, "veteran_id", "veterans", "veteran")
    veteran_id = v.req_str(b, "veteran_id")
    facility_name = v.req_str(b, "facility_name")
    if role == C.ROLE_VETERAN:
        require_owner(user_id, veteran_id, "urgent care visit")
    visit_date = logical_clock.today()
    # stage 9: one RECORDED visit per veteran per calendar date
    for visit in db.all_recs("urgent_care_visits"):
        if (visit["veteran_id"] == veteran_id and visit["status"] == "RECORDED"
                and visit["visit_date"] == visit_date.isoformat()):
            fail("ERR_SAME_DAY_URGENT_VISIT",
                 "a visit is already recorded for this veteran on this date")
    fiscal_year = visit_date.year + 1 if visit_date.month >= 10 else visit_date.year
    band = services.priority_band(vet["priority_group"])
    prior_count = sum(
        1 for visit in db.all_recs("urgent_care_visits")
        if visit["veteran_id"] == veteran_id and visit["status"] == "RECORDED"
        and visit["fiscal_year"] == fiscal_year)
    visit_index = prior_count + 1
    copay = services.urgent_copay_cents(band, visit_index)
    rec = db.create("urgent_care_visits", {
        "veteran_id": veteran_id,
        "facility_name": facility_name,
        "visit_date": visit_date.isoformat(),
        "fiscal_year": fiscal_year,
        "priority_band": band,
        "visit_index_in_fy": visit_index,
        "copay_cents": copay,
        "status": "RECORDED",
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/veterans/<rid>/urgent-care-visits")
@endpoint(C.ALL_ROLES)
def list_urgent_visits(user_id, role, rid):
    v.path_entity("veterans", rid, "veteran")
    preds = [lambda r: r["veteran_id"] == rid]
    fiscal_year = v.query_int("fiscal_year")
    if fiscal_year is not None:
        preds.append(lambda r: r["fiscal_year"] == fiscal_year)
    return response.list_response("urgent_care_visits", preds)


# ---------------- Prescription fill requests ----------------

@bp.post("/community-care/prescription-fill-requests")
@endpoint([C.ROLE_PROVIDER_REP])
def create_rx_request(user_id, role):
    b = v.body()
    # stage 3: whichever link ids are present must reference existing resources
    urgent_visit = v.body_fk(b, "urgent_care_visit_id", "urgent_care_visits",
                             "urgent care visit")
    appointment = v.body_fk(b, "appointment_id", "appointments", "appointment")
    # stage 4: exactly one of the two link fields (null counts as absent)
    urgent_id = b.get("urgent_care_visit_id")
    appt_id = b.get("appointment_id")
    if (urgent_id is None) == (appt_id is None):
        fail("ERR_INVALID_REQUEST",
             "exactly one of urgent_care_visit_id or appointment_id must be present")
    if urgent_id is not None and not isinstance(urgent_id, str):
        fail("ERR_INVALID_REQUEST", "urgent_care_visit_id must be a string")
    if appt_id is not None and not isinstance(appt_id, str):
        fail("ERR_INVALID_REQUEST", "appointment_id must be a string")
    medication_name = v.req_str(b, "medication_name")
    days_supply = v.req_int(b, "days_supply")
    controlled_substance = v.req_bool(b, "controlled_substance")
    # stage 6 + 7: appointment-linked requests are ownership- and state-gated
    if appt_id is not None:
        require_owner(user_id, appointment["provider_id"], "appointment")
        if appointment["status"] != "COMPLETED":
            fail("ERR_INVALID_STATE",
                 "appointment-linked fill requests require a COMPLETED appointment")
    # stage 8: safety — controlled substances never fillable; provider credentialed
    if controlled_substance:
        fail("ERR_CONTROLLED_RX_NOT_ALLOWED",
             "controlled substances cannot be filled through this channel")
    provider = db.get("providers", user_id)
    if provider is None:
        fail("ERR_NOT_FOUND", "acting provider %s does not exist" % user_id)
    if provider["credentialing_status"] != "CREDENTIALED":
        fail("ERR_PROVIDER_NOT_CREDENTIALED", "provider is not CREDENTIALED")
    # stage 10: supply cap follows the link type
    cap = C.RX_URGENT_MAX_DAYS if urgent_id is not None else C.RX_REFERRAL_MAX_DAYS
    if days_supply > cap:
        fail("ERR_DAYS_SUPPLY_EXCEEDED",
             "days_supply exceeds the %d-day cap for this link type" % cap)
    rec = db.create("rx_requests", {
        "urgent_care_visit_id": urgent_id,
        "appointment_id": appt_id,
        "medication_name": medication_name,
        "days_supply": days_supply,
        "controlled_substance": controlled_substance,
        "status": "REQUESTED",
        "decided_at": None,
        "refusal_reason": None,
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/prescription-fill-requests/<rid>")
@endpoint(C.ALL_ROLES)
def get_rx_request(user_id, role, rid):
    rec = v.path_entity("rx_requests", rid, "prescription fill request")
    return response.ok(db.public(rec))


@bp.get("/community-care/prescription-fill-requests")
@endpoint(C.ALL_ROLES)
def list_rx_requests(user_id, role):
    preds = []
    for field in ("urgent_care_visit_id", "appointment_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            preds.append(lambda r, f=field, val=raw: r[f] == val)
    return response.list_response("rx_requests", preds)


@bp.post("/community-care/prescription-fill-requests/<rid>/decide")
@endpoint([C.ROLE_SYSTEM_PHARMACIST])
def decide_rx_request(user_id, role, rid):
    rec = v.path_entity("rx_requests", rid, "prescription fill request")
    b = v.body()
    decision = v.req_enum(b, "decision", C.RX_DECISIONS)
    refusal_reason = None
    if decision == "REFUSED":
        refusal_reason = v.req_nonempty_str(b, "refusal_reason")
    if rec["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "only a REQUESTED fill request can be decided")
    rec["status"] = decision
    rec["decided_at"] = logical_clock.now_iso()
    if decision == "REFUSED":
        rec["refusal_reason"] = refusal_reason
    db.touch(rec)
    return response.ok(db.public(rec))
