"""Route handlers for the Destination Medicine API.

Every handler takes (user, **path_params) and returns either
  (data, status)             -> response_type "object"
  (items, status, pagination) -> response_type "array"
"""
from db import stores, get_clock, set_clock
from helpers import (
    ApiError, bad_request, not_found, invalid_state, new_entity, touch,
    get_entity, get_body, require_fields, is_string, is_int, is_bool,
    check_date_str, parse_iso8601_utc, iso_utc, now_ts, current_date_str,
    paginate, sort_created, ALL_ROLES,
)
import services as svc

ADMIN = ["PlatformAdmin"]
COORD = ["IntakeCoordinator"]
REVIEWER = ["CaseReviewer"]
FIN = ["FinancialCounselor"]
LOGI = ["LogisticsCoordinator"]

RECORD_TYPES = ["IMAGING", "LAB", "PATHOLOGY", "CLINICAL_NOTES", "MEDICATION_LIST"]
CASE_TYPES = ["DESTINATION", "SECOND_OPINION", "REMOTE_CONSULT"]
REMOTE_CASE_TYPES = {"SECOND_OPINION", "REMOTE_CONSULT"}
VISIT_TYPES = ["CONSULT", "IMAGING", "LAB_TEST", "PROCEDURE"]
OUTCOMES = ["APPROVE", "DECLINE"]
ARRANGEMENT_TYPES = ["TRAVEL", "LODGING", "INTERPRETER"]
COMM_TYPES = ["RESULTS_TO_REFERRER", "CONTINUITY_PLAN"]
CONTINUITY_OWNERS = ["LOCAL_PHYSICIAN", "DESTINATION_TEAM", "SHARED"]
TXN_TYPES = ["DEPOSIT", "SETTLEMENT", "REFUND"]
REVIEWABLE_STATES = {"INTAKE", "AWAITING_FINANCIAL", "FINANCIAL_CLEARED", "SCHEDULING"}

HOME_STATE = "MN"


# =============================================================================
# Clock
# =============================================================================

def set_current_utc(user):
    body = get_body()
    require_fields(body, ["current_utc"])
    dt = parse_iso8601_utc(body["current_utc"])
    set_clock(dt)
    # PRD §2.4: the clock capability "replies with the accepted current_utc" —
    # echo the submitted value verbatim rather than a normalized rendering.
    return {"current_utc": body["current_utc"]}, 200


# =============================================================================
# Specialty services
# =============================================================================

def create_specialty_service(user):
    body = get_body()
    require_fields(body, ["code", "name", "destination_daily_capacity",
                          "service_window_start_min", "service_window_end_min"])
    code = body["code"]
    name = body["name"]
    cap = body["destination_daily_capacity"]
    win_start = body["service_window_start_min"]
    win_end = body["service_window_end_min"]
    if not is_string(code) or not code:
        raise bad_request("code must be a non-empty string")
    if not is_string(name) or not name:
        raise bad_request("name must be a non-empty string")
    if not is_int(cap) or cap < 1:
        raise bad_request("destination_daily_capacity must be an integer >= 1")
    if not is_int(win_start) or not (0 <= win_start <= 1439):
        raise bad_request("service_window_start_min must be an integer in 0..1439")
    if not is_int(win_end) or not (0 <= win_end <= 1440):
        raise bad_request("service_window_end_min must be an integer in 0..1440")
    if not win_start < win_end:
        raise bad_request("service_window_start_min must be strictly before service_window_end_min")
    supports_imaging = body.get("supports_imaging", False)
    supports_remote = body.get("supports_remote_products", True)
    if not is_bool(supports_imaging):
        raise bad_request("supports_imaging must be a boolean")
    if not is_bool(supports_remote):
        raise bad_request("supports_remote_products must be a boolean")
    for existing in stores["specialty_services"].values():
        if existing["code"] == code:
            raise bad_request("code must be unique across all services")
    ent = new_entity({
        "code": code,
        "name": name,
        "destination_daily_capacity": cap,
        "service_window_start_min": win_start,
        "service_window_end_min": win_end,
        "supports_imaging": supports_imaging,
        "supports_remote_products": supports_remote,
    })
    stores["specialty_services"][ent["id"]] = ent
    return ent, 201


def list_specialty_services(user):
    from flask import request
    items = list(stores["specialty_services"].values())
    code = request.args.get("code")
    if code is not None:
        items = [s for s in items if s["code"] == code]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_specialty_service(user, service_id):
    return get_entity("specialty_services", service_id, "specialty service"), 200


# =============================================================================
# Slots
# =============================================================================

def create_slot(user, service_id):
    service = get_entity("specialty_services", service_id, "specialty service")
    body = get_body()
    require_fields(body, ["slot_date", "start_min", "end_min"])
    slot_date = body["slot_date"]
    start_min = body["start_min"]
    end_min = body["end_min"]
    check_date_str(slot_date, "slot_date")
    if not is_int(start_min) or not (0 <= start_min <= 1439):
        raise bad_request("start_min must be an integer in 0..1439")
    if not is_int(end_min) or not (1 <= end_min <= 1440):
        raise bad_request("end_min must be an integer in 1..1440")
    if not end_min > start_min:
        raise bad_request("end_min must be strictly greater than start_min")
    # window + not-in-the-past (ERR_OUTSIDE_SERVICE_WINDOW)
    if start_min < service["service_window_start_min"] or end_min > service["service_window_end_min"]:
        raise ApiError("ERR_OUTSIDE_SERVICE_WINDOW", 422,
                       "slot interval outside the service's daily window")
    if slot_date < current_date_str():
        raise ApiError("ERR_OUTSIDE_SERVICE_WINDOW", 422,
                       "slot_date is in the past")
    # half-open overlap against any live (non-terminal) slot on the same
    # service+date — PRD §3.1: "creation overlapping an existing slot is
    # rejected with ERR_SLOT_OVERLAP"
    for other in stores["appointment_slots"].values():
        if other["specialty_service_id"] != service_id or other["slot_date"] != slot_date:
            continue
        if other["status"] not in ("OPEN", "HELD", "CONFIRMED"):
            continue
        if svc.slots_overlap(start_min, end_min, other["start_min"], other["end_min"]):
            raise ApiError("ERR_SLOT_OVERLAP", 409,
                           "slot overlaps an existing slot on this service and date")
    ent = new_entity({
        "specialty_service_id": service_id,
        "slot_date": slot_date,
        "start_min": start_min,
        "end_min": end_min,
        "status": "OPEN",
        "held_by_case_id": None,
    })
    stores["appointment_slots"][ent["id"]] = ent
    return ent, 201


def list_service_slots(user, service_id):
    from flask import request
    get_entity("specialty_services", service_id, "specialty service")
    items = [s for s in stores["appointment_slots"].values()
             if s["specialty_service_id"] == service_id]
    slot_date = request.args.get("slot_date")
    if slot_date is not None:
        items = [s for s in items if s["slot_date"] == slot_date]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_slot(user, slot_id):
    return get_entity("appointment_slots", slot_id, "slot"), 200


def confirm_slot(user, slot_id):
    slot = get_entity("appointment_slots", slot_id, "slot")
    if slot["status"] != "HELD":
        raise invalid_state("slot is not HELD")
    case_id = slot.get("held_by_case_id")
    clearance = svc.case_clearance(case_id) if case_id else None
    if clearance is None or clearance["status"] not in ("CLEARED", "WAIVED"):
        raise ApiError("ERR_FINANCIAL_CLEARANCE_REQUIRED", 402,
                       "financial clearance must be CLEARED or WAIVED before slot confirmation")
    slot["status"] = "CONFIRMED"
    touch(slot)
    for visit in stores["visits"].values():
        if visit["appointment_slot_id"] == slot_id and visit["status"] == "PENDING":
            visit["status"] = "CONFIRMED"
            touch(visit)
    return slot, 200


def release_slot(user, slot_id):
    slot = get_entity("appointment_slots", slot_id, "slot")
    if slot["status"] != "HELD":
        raise invalid_state("slot is not HELD")
    case_id = slot.get("held_by_case_id")
    slot["status"] = "RELEASED"
    slot["held_by_case_id"] = None
    touch(slot)
    for visit in stores["visits"].values():
        if visit["appointment_slot_id"] == slot_id and visit["status"] == "PENDING":
            visit["status"] = "CANCELLED"
            touch(visit)
    if case_id:
        it = svc.case_itinerary(case_id)
        if it:
            # PRD §3.4: releasing a held slot — "the itinerary's revision
            # increments by one, and both totals are recomputed" — unconditional.
            it["revision"] += 1
            svc.recompute_itinerary_totals(it)
            touch(it)
    return slot, 200


# =============================================================================
# Referrals, patients, medical records
# =============================================================================

def create_referral(user):
    body = get_body()
    require_fields(body, ["patient", "referring_physician_name",
                          "referring_physician_contact", "reason"])
    patient = body["patient"]
    if not isinstance(patient, dict):
        raise bad_request("patient must be an object")
    for f in ("full_name", "date_of_birth", "residence_country", "preferred_language"):
        if f not in patient or patient[f] is None:
            raise bad_request("Missing required field: patient.%s" % f)
        if not is_string(patient[f]) or not patient[f]:
            raise bad_request("patient.%s must be a non-empty string" % f)
    residence_country = patient["residence_country"]
    residence_state = patient.get("residence_state")
    is_international = residence_country != "US"
    if not is_international:
        if residence_state is None or not is_string(residence_state) or not residence_state:
            raise bad_request("patient.residence_state is required for US residents")
        if residence_state == HOME_STATE:
            raise bad_request("referrals for Minnesota residents are not accepted")
    else:
        residence_state = None
    needs_interpreter = patient.get("needs_interpreter")
    if needs_interpreter is not None and not is_bool(needs_interpreter):
        raise bad_request("patient.needs_interpreter must be a boolean")
    requires_interpreter = needs_interpreter if needs_interpreter is not None \
        else (patient["preferred_language"] != "en")
    for f in ("referring_physician_name", "referring_physician_contact", "reason"):
        if not is_string(body[f]) or not body[f]:
            raise bad_request("%s must be a non-empty string" % f)

    pat = new_entity({
        "full_name": patient["full_name"],
        "date_of_birth": patient["date_of_birth"],
        "residence_country": residence_country,
        "residence_state": residence_state,
        "preferred_language": patient["preferred_language"],
        "is_international": is_international,
        "requires_interpreter": requires_interpreter,
    })
    stores["patients"][pat["id"]] = pat

    referral = new_entity({
        "patient_id": pat["id"],
        "patient": {
            "full_name": patient["full_name"],
            "date_of_birth": patient["date_of_birth"],
            "residence_country": residence_country,
            "residence_state": residence_state,
            "preferred_language": patient["preferred_language"],
            "needs_interpreter": requires_interpreter,
        },
        "referring_physician_name": body["referring_physician_name"],
        "referring_physician_contact": body["referring_physician_contact"],
        "reason": body["reason"],
        "status": "SUBMITTED",
    })
    stores["referrals"][referral["id"]] = referral
    return referral, 201


def list_referrals(user):
    from flask import request
    items = list(stores["referrals"].values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_referral(user, referral_id):
    return get_entity("referrals", referral_id, "referral"), 200


def get_referral_patient(user, referral_id):
    referral = get_entity("referrals", referral_id, "referral")
    patient = stores["patients"].get(referral["patient_id"])
    items = [patient] if patient else []
    page, meta = paginate(items)
    return page, 200, meta


def get_patient(user, patient_id):
    return get_entity("patients", patient_id, "patient"), 200


def create_medical_record(user, referral_id):
    referral = get_entity("referrals", referral_id, "referral")
    body = get_body()
    require_fields(body, ["record_type", "source_facility"])
    if body["record_type"] not in RECORD_TYPES:
        raise bad_request("record_type must be one of %s" % ", ".join(RECORD_TYPES))
    if not is_string(body["source_facility"]) or not body["source_facility"]:
        raise bad_request("source_facility must be a non-empty string")
    if referral["status"] not in ("SUBMITTED", "RECORDS_PENDING"):
        raise invalid_state("referral does not accept new medical records in its current state")
    record = new_entity({
        "referral_id": referral_id,
        "record_type": body["record_type"],
        "source_facility": body["source_facility"],
        "received_at": now_ts(),
        "received_by": user["user_id"],
        "status": "RECEIVED",
    })
    stores["medical_records"][record["id"]] = record
    if referral["status"] == "SUBMITTED":
        referral["status"] = "RECORDS_PENDING"
        touch(referral)
    return record, 201


def list_medical_records(user, referral_id):
    from flask import request
    get_entity("referrals", referral_id, "referral")
    items = [r for r in stores["medical_records"].values() if r["referral_id"] == referral_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_medical_record(user, record_id):
    return get_entity("medical_records", record_id, "medical record"), 200


def verify_medical_record(user, referral_id, record_id):
    get_entity("referrals", referral_id, "referral")
    record = get_entity("medical_records", record_id, "medical record")
    if record["referral_id"] != referral_id:
        raise not_found("medical record not found under referral: %s" % record_id)
    if record["status"] != "RECEIVED":
        raise invalid_state("medical record is not RECEIVED")
    if record.get("received_by") == user["user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "record verifier must differ from the receiving coordinator")
    record["status"] = "VERIFIED"
    touch(record)
    svc.bump_fatigue_on_verify(referral_id)
    return record, 200


def reject_medical_record(user, referral_id, record_id):
    get_entity("referrals", referral_id, "referral")
    record = get_entity("medical_records", record_id, "medical record")
    if record["referral_id"] != referral_id:
        raise not_found("medical record not found under referral: %s" % record_id)
    if record["status"] != "RECEIVED":
        raise invalid_state("medical record is not RECEIVED")
    record["status"] = "REJECTED"
    touch(record)
    return record, 200


def submit_review(user, referral_id):
    referral = get_entity("referrals", referral_id, "referral")
    if referral["status"] != "RECORDS_PENDING":
        raise invalid_state("referral is not RECORDS_PENDING")
    verified = any(
        r["referral_id"] == referral_id and r["status"] == "VERIFIED"
        for r in stores["medical_records"].values()
    )
    if not verified:
        raise ApiError("ERR_NO_VERIFIED_RECORDS", 409,
                       "at least one VERIFIED medical record is required")
    referral["status"] = "IN_REVIEW"
    touch(referral)
    return referral, 200


# =============================================================================
# Visit cases and reviews
# =============================================================================

def create_visit_case(user):
    body = get_body()
    require_fields(body, ["referral_id", "case_type", "care_team_specialty_ids"])
    referral_id = body["referral_id"]
    case_type = body["case_type"]
    team = body["care_team_specialty_ids"]
    if not is_string(referral_id):
        raise bad_request("referral_id must be a string")
    if case_type not in CASE_TYPES:
        raise bad_request("case_type must be one of %s" % ", ".join(CASE_TYPES))
    if not isinstance(team, list) or any(not is_string(t) for t in team):
        raise bad_request("care_team_specialty_ids must be an array of strings")

    referral = stores["referrals"].get(referral_id)
    if referral is None or referral["status"] != "IN_REVIEW":
        raise ApiError("ERR_REFERRAL_NOT_IN_REVIEW", 409,
                       "referral does not exist or is not IN_REVIEW")

    if len(set(team)) != len(team):
        raise ApiError("ERR_INVALID_CARE_TEAM", 422,
                       "care_team_specialty_ids must be distinct")
    if case_type == "DESTINATION":
        if not (2 <= len(team) <= 4):
            raise ApiError("ERR_INVALID_CARE_TEAM", 422,
                           "DESTINATION cases require 2..4 distinct specialties")
    else:
        if len(team) != 1:
            raise ApiError("ERR_INVALID_CARE_TEAM", 422,
                           "remote product cases require exactly 1 specialty")
    for sid in team:
        if sid not in stores["specialty_services"]:
            raise ApiError("ERR_INVALID_CARE_TEAM", 422,
                           "unknown specialty service: %s" % sid)
    if case_type in REMOTE_CASE_TYPES:
        service = stores["specialty_services"][team[0]]
        if not service["supports_remote_products"]:
            raise ApiError("ERR_REMOTE_PRODUCT_UNSUPPORTED", 422,
                           "service does not support remote products")

    case = new_entity({
        "referral_id": referral_id,
        "case_type": case_type,
        "assigned_coordinator_id": user["user_id"],
        "care_team_specialty_ids": list(team),
        "review_days_used": 0,
        "fatigue_score": 0,
        "status": "INTAKE",
        "deposit_amount_cents": None,
    })
    stores["visit_cases"][case["id"]] = case
    return case, 201


def list_visit_cases(user):
    from flask import request
    items = list(stores["visit_cases"].values())
    referral_id = request.args.get("referral_id")
    if referral_id is not None:
        items = [c for c in items if c["referral_id"] == referral_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_visit_case(user, case_id):
    return get_entity("visit_cases", case_id, "visit case"), 200


def create_case_review(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    body = get_body()
    require_fields(body, ["outcome", "notes"])
    outcome = body["outcome"]
    if outcome not in OUTCOMES:
        raise bad_request("outcome must be one of %s" % ", ".join(OUTCOMES))
    if not is_string(body["notes"]):
        raise bad_request("notes must be a string")

    # guard 1: case state
    if case["status"] not in REVIEWABLE_STATES:
        raise invalid_state("case is not reviewable in its current state")
    # guard 2: referral state
    referral = svc.case_referral(case)
    if referral is None or referral["status"] != "IN_REVIEW":
        raise ApiError("ERR_REFERRAL_NOT_IN_REVIEW", 409,
                       "referral is not IN_REVIEW")
    # guard 3: segregation of duties
    if user["user_id"] == case["assigned_coordinator_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "reviewer must not be the case's assigned coordinator")
    # guard 4: review fatigue guard (distinct calendar dates per case)
    today = current_date_str()
    existing_dates = {
        r["reviewed_on_date"] for r in stores["case_reviews"].values()
        if r["visit_case_id"] == case_id
    }
    if today not in existing_dates and len(existing_dates) >= svc.MAX_REVIEW_DAYS:
        raise ApiError("ERR_FATIGUE_GUARD", 409,
                       "reviewer would exceed 3 distinct review dates on this case")

    review = new_entity({
        "visit_case_id": case_id,
        "reviewer_id": user["user_id"],
        "outcome": outcome,
        "notes": body["notes"],
        "reviewed_on_date": today,
    })
    stores["case_reviews"][review["id"]] = review

    distinct_dates = {
        r["reviewed_on_date"] for r in stores["case_reviews"].values()
        if r["visit_case_id"] == case_id
    }
    case["review_days_used"] = len(distinct_dates)

    if outcome == "APPROVE":
        case["status"] = "AWAITING_FINANCIAL"
        # deposit seed from care-team-size base estimate (empty itinerary at approval)
        base_estimate = svc.approval_base_estimate(case)
        case["deposit_amount_cents"] = svc.compute_tiered_deposit(base_estimate)
        if case["case_type"] == "DESTINATION":
            itinerary = new_entity({
                "visit_case_id": case_id,
                "revision": 1,
                "provisional_total_cents": 0,
                "final_total_cents": 0,
                "status": "DRAFT",
            })
            stores["itineraries"][itinerary["id"]] = itinerary
        clearance = new_entity({
            "visit_case_id": case_id,
            # PRD §3.3/§3.6: the clearance is born PENDING and "waits for
            # money"; the required amount at birth is the case's seeded
            # tiered deposit (estimate-letter issuance later overwrites it).
            "required_deposit_cents": case["deposit_amount_cents"],
            "deposit_paid_cents": 0,
            "holds_released": False,
            "status": "PENDING",
        })
        stores["financial_clearances"][clearance["id"]] = clearance
        referral["status"] = "REVIEWED"
        touch(referral)
    else:  # DECLINE
        case["status"] = "DECLINED"
        referral["status"] = "DECLINED"
        touch(referral)
        svc.decline_logistics_cascade(case)

    touch(case)
    return review, 201


def list_case_reviews(user, case_id):
    get_entity("visit_cases", case_id, "visit case")
    items = [r for r in stores["case_reviews"].values() if r["visit_case_id"] == case_id]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_case_review(user, review_id):
    return get_entity("case_reviews", review_id, "case review"), 200


def withdraw_visit_case(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    if case["status"] not in svc.WITHDRAWABLE_CASE_STATES:
        raise invalid_state("case cannot be withdrawn from its current state")
    svc.withdraw_case(case)
    return case, 200


def authorize_travel(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    if case["status"] != "SCHEDULED":
        raise invalid_state("case is not SCHEDULED")
    itinerary = svc.case_itinerary(case_id)
    if itinerary is None or itinerary["status"] != "CONFIRMED":
        raise invalid_state("itinerary is not CONFIRMED")
    letter = svc.issued_letter(case_id)
    if letter is None:
        raise ApiError("ERR_STALE_ESTIMATE_LETTER", 409,
                       "no ISSUED estimate letter exists for this case")
    if letter["itinerary_revision_at_issue"] < itinerary["revision"]:
        raise ApiError("ERR_STALE_ESTIMATE_LETTER", 409,
                       "the ISSUED estimate letter is stale relative to the current itinerary revision")
    patient = svc.case_patient(case)
    if patient and patient["requires_interpreter"]:
        interpreter_booked = any(
            a["visit_case_id"] == case_id
            and a["arrangement_type"] == "INTERPRETER"
            and a["status"] == "BOOKED"
            for a in stores["logistics_arrangements"].values()
        )
        if not interpreter_booked:
            raise ApiError("ERR_INTERPRETER_NOT_BOOKED", 409,
                           "a required interpreter arrangement is not BOOKED")
    case["status"] = "READY_TO_TRAVEL"
    touch(case)
    return case, 200


# =============================================================================
# Financial clearance
# =============================================================================

def get_case_financial_clearance(user, case_id):
    get_entity("visit_cases", case_id, "visit case")
    clearance = svc.case_clearance(case_id)
    items = [clearance] if clearance else []
    page, meta = paginate(items)
    return page, 200, meta


def get_financial_clearance(user, clearance_id):
    return get_entity("financial_clearances", clearance_id, "financial clearance"), 200


def waive_clearance(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    clearance = svc.case_clearance(case_id)
    if clearance is None:
        raise not_found("financial clearance not found for case: %s" % case_id)
    if clearance["status"] != "PENDING":
        raise invalid_state("financial clearance is not PENDING")
    patient = svc.case_patient(case)
    if patient and patient["is_international"]:
        raise ApiError("ERR_INTERNATIONAL_WAIVER_FORBIDDEN", 422,
                       "international patients may not receive deposit waivers")
    clearance["status"] = "WAIVED"
    touch(clearance)
    if case["status"] == "AWAITING_FINANCIAL":
        case["status"] = "FINANCIAL_CLEARED"
        touch(case)
    return clearance, 200


def reopen_clearance(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    clearance = svc.case_clearance(case_id)
    if clearance is None:
        raise not_found("financial clearance not found for case: %s" % case_id)
    if clearance["status"] != "CLEARED":
        raise invalid_state("financial clearance is not CLEARED")
    if clearance["holds_released"]:
        raise ApiError("ERR_CLEARANCE_HOLD_RELEASED", 409,
                       "clearance holds were released; it cannot return to PENDING")
    clearance["status"] = "PENDING"
    touch(clearance)
    if case["status"] == "FINANCIAL_CLEARED":
        case["status"] = "AWAITING_FINANCIAL"
        touch(case)
    return clearance, 200


def forfeit_clearance(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    clearance = svc.case_clearance(case_id)
    if clearance is None:
        raise not_found("financial clearance not found for case: %s" % case_id)
    if clearance["status"] != "PENDING":
        raise invalid_state("financial clearance is not PENDING")
    if not svc.forfeit_deadline_breached(case_id):
        raise ApiError("ERR_DEADLINE_NOT_BREACHED", 409,
                       "deposit deadline has not yet been breached")

    # depth-3 cascade
    clearance["status"] = "FORFEITED"
    clearance["holds_released"] = True
    touch(clearance)

    itinerary = svc.case_itinerary(case_id)
    for slot in stores["appointment_slots"].values():
        if slot.get("held_by_case_id") == case_id and slot["status"] == "HELD":
            slot["status"] = "RELEASED"
            slot["held_by_case_id"] = None
            touch(slot)
    for visit in svc.case_visits(case_id):
        if visit["status"] == "PENDING":
            visit["status"] = "CANCELLED"
            touch(visit)
    if itinerary and itinerary["status"] == "DRAFT":
        itinerary["status"] = "CANCELLED"
        itinerary["revision"] += 1
        touch(itinerary)

    case["status"] = "WITHDRAWN"
    touch(case)
    return clearance, 200


# =============================================================================
# Estimate letters
# =============================================================================

def create_estimate_letter(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    itinerary = svc.case_itinerary(case_id)
    clearance = svc.case_clearance(case_id)
    if itinerary is None:
        raise invalid_state("case has no itinerary to estimate")
    svc.recompute_itinerary_totals(itinerary)
    final_total = itinerary["final_total_cents"]
    deposit = svc.compute_tiered_deposit(final_total)

    prior = svc.issued_letter(case_id)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    letter = new_entity({
        "visit_case_id": case_id,
        "itinerary_revision_at_issue": itinerary["revision"],
        "provisional_estimate_cents": itinerary["provisional_total_cents"],
        "final_estimate_cents": final_total,
        "deposit_amount_cents": deposit,
        "status": "ISSUED",
    })
    stores["estimate_letters"][letter["id"]] = letter

    if clearance is not None:
        # Issuance updates the clearance's required_deposit_cents from the new
        # letter's deposit; only a still-PENDING clearance can immediately clear.
        if clearance["status"] == "PENDING":
            clearance["required_deposit_cents"] = deposit
            touch(clearance)
            svc.maybe_clear_on_deposit(clearance)
        elif clearance["status"] == "CLEARED":
            clearance["required_deposit_cents"] = deposit
            touch(clearance)

    return svc.letter_view(letter), 201


def list_estimate_letters(user, case_id):
    get_entity("visit_cases", case_id, "visit case")
    items = [svc.letter_view(l) for l in stores["estimate_letters"].values()
             if l["visit_case_id"] == case_id]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_estimate_letter(user, letter_id):
    letter = get_entity("estimate_letters", letter_id, "estimate letter")
    return svc.letter_view(letter), 200


# =============================================================================
# Billing transactions
# =============================================================================

def create_billing_transaction(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    body = get_body()
    require_fields(body, ["txn_type", "amount_cents"])
    txn_type = body["txn_type"]
    amount = body["amount_cents"]
    if txn_type not in TXN_TYPES:
        raise bad_request("txn_type must be one of %s" % ", ".join(TXN_TYPES))
    if not is_int(amount) or amount <= 0:
        raise bad_request("amount_cents must be a positive integer")

    clearance = svc.case_clearance(case_id)
    if clearance is None:
        raise not_found("financial clearance not found for case: %s" % case_id)
    itinerary = svc.case_itinerary(case_id)

    if txn_type == "SETTLEMENT":
        if clearance["status"] != "CLEARED":
            raise invalid_state("financial clearance is not CLEARED")
        if case["status"] != "COMPLETED":
            raise ApiError("ERR_MINIMUM_COMPLETED_VISITS", 409,
                           "settlement requires the case to be COMPLETED")
        completed = sum(
            1 for v in svc.itinerary_visits(itinerary["id"])
            if v["status"] == "COMPLETED"
        ) if itinerary else 0
        if completed < 3:
            raise ApiError("ERR_MINIMUM_COMPLETED_VISITS", 409,
                           "settlement requires at least 3 COMPLETED visits")
        svc.recompute_itinerary_totals(itinerary)
        amount = max(0, itinerary["final_total_cents"] - clearance["deposit_paid_cents"])
        txn = new_entity({
            "visit_case_id": case_id,
            "financial_clearance_id": clearance["id"],
            "txn_type": "SETTLEMENT",
            "amount_cents": amount,
            "refunded_txn_id": None,
            "status": "POSTED",
        })
        stores["billing_transactions"][txn["id"]] = txn
        clearance["status"] = "SETTLED"
        touch(clearance)
        return txn, 201

    if txn_type == "DEPOSIT":
        if clearance["status"] != "PENDING":
            raise invalid_state("financial clearance is not PENDING")
        txn = new_entity({
            "visit_case_id": case_id,
            "financial_clearance_id": clearance["id"],
            "txn_type": "DEPOSIT",
            "amount_cents": amount,
            "refunded_txn_id": None,
            "status": "POSTED",
        })
        stores["billing_transactions"][txn["id"]] = txn
        clearance["deposit_paid_cents"] += amount
        touch(clearance)
        svc.maybe_clear_on_deposit(clearance)
        return txn, 201

    # REFUND: reverses a prior DEPOSIT posted on this case's clearance
    deposit_txn = None
    for t in sort_created(list(stores["billing_transactions"].values())):
        if t["visit_case_id"] == case_id and t["txn_type"] == "DEPOSIT" \
                and t["status"] == "POSTED":
            deposit_txn = t
    if deposit_txn is None:
        raise invalid_state("no POSTED deposit exists to refund")
    txn = new_entity({
        "visit_case_id": case_id,
        "financial_clearance_id": clearance["id"],
        "txn_type": "REFUND",
        "amount_cents": amount,
        "refunded_txn_id": deposit_txn["id"],
        "status": "POSTED",
    })
    stores["billing_transactions"][txn["id"]] = txn
    deposit_txn["status"] = "VOID"
    touch(deposit_txn)
    clearance["deposit_paid_cents"] -= amount
    touch(clearance)
    return txn, 201


def list_case_billing_transactions(user, case_id):
    from flask import request
    get_entity("visit_cases", case_id, "visit case")
    items = [t for t in stores["billing_transactions"].values()
             if t["visit_case_id"] == case_id]
    txn_type = request.args.get("txn_type")
    if txn_type is not None:
        items = [t for t in items if t["txn_type"] == txn_type]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_billing_transaction(user, txn_id):
    return get_entity("billing_transactions", txn_id, "billing transaction"), 200


def list_billing_transactions(user):
    from flask import request
    items = list(stores["billing_transactions"].values())
    clearance_id = request.args.get("financial_clearance_id")
    if clearance_id is not None:
        items = [t for t in items if t["financial_clearance_id"] == clearance_id]
    txn_type = request.args.get("txn_type")
    if txn_type is not None:
        items = [t for t in items if t["txn_type"] == txn_type]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


# =============================================================================
# Itinerary, slot holds, visits
# =============================================================================

def get_case_itinerary(user, case_id):
    get_entity("visit_cases", case_id, "visit case")
    itinerary = svc.case_itinerary(case_id)
    if itinerary is not None:
        svc.recompute_itinerary_totals(itinerary)
    items = [itinerary] if itinerary else []
    page, meta = paginate(items)
    return page, 200, meta


def get_itinerary(user, itinerary_id):
    itinerary = get_entity("itineraries", itinerary_id, "itinerary")
    svc.recompute_itinerary_totals(itinerary)
    return itinerary, 200


def create_slot_hold(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    body = get_body()
    require_fields(body, ["appointment_slot_id", "visit_type", "listed_price_cents",
                          "sequencing_priority", "expected_case_version"])
    slot_id = body["appointment_slot_id"]
    visit_type = body["visit_type"]
    listed_price = body["listed_price_cents"]
    seq = body["sequencing_priority"]
    expected_version = body["expected_case_version"]
    if not is_string(slot_id):
        raise bad_request("appointment_slot_id must be a string")
    if visit_type not in VISIT_TYPES:
        raise bad_request("visit_type must be one of %s" % ", ".join(VISIT_TYPES))
    if not is_int(listed_price) or listed_price <= 0:
        raise bad_request("listed_price_cents must be a positive integer")
    if not is_int(seq) or not (1 <= seq <= 99):
        raise bad_request("sequencing_priority must be an integer in 1..99")
    if not is_int(expected_version):
        raise bad_request("expected_case_version must be an integer")

    slot = stores["appointment_slots"].get(slot_id)
    if slot is None:
        raise not_found("slot not found: %s" % slot_id)

    # state preconditions
    if case["status"] not in ("FINANCIAL_CLEARED", "SCHEDULING"):
        raise invalid_state("booking is not open for the case in its current state")
    itinerary = svc.case_itinerary(case_id)
    if itinerary is None:
        raise invalid_state("case has no itinerary")
    if itinerary["status"] != "DRAFT":
        raise invalid_state("itinerary is not DRAFT")
    if slot["status"] != "OPEN":
        raise ApiError("ERR_SLOT_NOT_OPEN", 409, "slot is not OPEN")

    # OCC (after state checks)
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_case_version does not match the case's current version")

    service = stores["specialty_services"].get(slot["specialty_service_id"])

    # service window
    if service and (slot["start_min"] < service["service_window_start_min"]
                    or slot["end_min"] > service["service_window_end_min"]):
        raise ApiError("ERR_OUTSIDE_SERVICE_WINDOW", 422,
                       "slot interval outside the service's daily window")

    # overlap vs HELD/CONFIRMED on same service+date
    for other in stores["appointment_slots"].values():
        if other["id"] == slot_id:
            continue
        if other["specialty_service_id"] != slot["specialty_service_id"]:
            continue
        if other["slot_date"] != slot["slot_date"]:
            continue
        if other["status"] not in ("HELD", "CONFIRMED"):
            continue
        if svc.slots_overlap(slot["start_min"], slot["end_min"],
                             other["start_min"], other["end_min"]):
            raise ApiError("ERR_SLOT_OVERLAP", 409,
                           "slot overlaps a HELD/CONFIRMED slot on this service and date")

    # imaging support
    if visit_type == "IMAGING" and service and not service["supports_imaging"]:
        raise ApiError("ERR_IMAGING_NOT_SUPPORTED", 422,
                       "service does not support IMAGING visits")

    # capacity pool: strict < — reaching exactly capacity blocks the NEXT hold
    if service and svc.used_capacity(slot["specialty_service_id"], slot["slot_date"]) \
            >= service["destination_daily_capacity"]:
        raise ApiError("ERR_CAPACITY_EXHAUSTED", 409,
                       "destination capacity pool exhausted for this service and date")

    # apply: slot HELD, visit PENDING, case scheduling + version bump
    slot["status"] = "HELD"
    slot["held_by_case_id"] = case_id
    touch(slot)

    visit = new_entity({
        "itinerary_id": itinerary["id"],
        "visit_case_id": case_id,
        "appointment_slot_id": slot_id,
        "specialty_service_id": slot["specialty_service_id"],
        "visit_type": visit_type,
        "listed_price_cents": listed_price,
        "sequencing_priority": seq,
        "status": "PENDING",
    })
    stores["visits"][visit["id"]] = visit

    if case["status"] == "FINANCIAL_CLEARED":
        case["status"] = "SCHEDULING"
    touch(case)

    svc.recompute_itinerary_totals(itinerary)
    touch(itinerary)
    return visit, 201


def confirm_itinerary(user, itinerary_id):
    itinerary = get_entity("itineraries", itinerary_id, "itinerary")
    case = stores["visit_cases"].get(itinerary["visit_case_id"])
    if itinerary["status"] != "DRAFT":
        raise invalid_state("itinerary is not DRAFT")
    clearance = svc.case_clearance(itinerary["visit_case_id"])
    if clearance is None or clearance["status"] != "CLEARED":
        raise ApiError("ERR_FINANCIAL_CLEARANCE_REQUIRED", 402,
                       "financial clearance must be CLEARED before itinerary confirmation")
    pending = [v for v in svc.itinerary_visits(itinerary_id) if v["status"] == "PENDING"]
    if pending:
        raise ApiError("ERR_UNCONFIRMED_VISITS_REMAIN", 409,
                       "PENDING visits remain under the itinerary")
    distinct_dates = set()
    for v in svc.itinerary_visits(itinerary_id):
        if v["status"] in ("PENDING", "CONFIRMED"):
            slot = stores["appointment_slots"].get(v["appointment_slot_id"])
            if slot:
                distinct_dates.add(slot["slot_date"])
    if len(distinct_dates) > svc.MAX_WINDOW_DAYS:
        raise ApiError("ERR_ITINERARY_WINDOW_EXCEEDED", 422,
                       "itinerary spans more than 5 distinct dates")
    itinerary["status"] = "CONFIRMED"
    touch(itinerary)
    if case and case["status"] == "SCHEDULING":
        case["status"] = "SCHEDULED"
        touch(case)
    return itinerary, 200


def lock_itinerary(user, itinerary_id):
    itinerary = get_entity("itineraries", itinerary_id, "itinerary")
    case = stores["visit_cases"].get(itinerary["visit_case_id"])
    if itinerary["status"] != "CONFIRMED":
        raise invalid_state("itinerary is not CONFIRMED")
    if case is None or case["status"] != "READY_TO_TRAVEL":
        raise invalid_state("case is not READY_TO_TRAVEL")
    itinerary["status"] = "LOCKED"
    touch(itinerary)
    return itinerary, 200


def list_itinerary_visits(user, itinerary_id):
    from flask import request
    get_entity("itineraries", itinerary_id, "itinerary")
    items = [v for v in stores["visits"].values() if v["itinerary_id"] == itinerary_id]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_visit(user, visit_id):
    return get_entity("visits", visit_id, "visit"), 200


def list_visits(user):
    from flask import request
    items = list(stores["visits"].values())
    for param, field in (("visit_case_id", "visit_case_id"),
                         ("appointment_slot_id", "appointment_slot_id"),
                         ("specialty_service_id", "specialty_service_id"),
                         ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            items = [v for v in items if v[field] == value]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def complete_visit(user, visit_id):
    visit = get_entity("visits", visit_id, "visit")
    if visit["status"] != "CONFIRMED":
        raise invalid_state("visit is not CONFIRMED")
    slot = stores["appointment_slots"].get(visit["appointment_slot_id"])
    if slot and current_date_str() < slot["slot_date"]:
        raise ApiError("ERR_VISIT_NOT_DUE", 409,
                       "visit cannot be completed before its slot date")
    if svc.sequencing_blocker(visit) is not None:
        raise ApiError("ERR_SEQUENCING_VIOLATION", 409,
                       "a lower-priority same-day visit is still CONFIRMED")
    visit["status"] = "COMPLETED"
    touch(visit)
    case = stores["visit_cases"].get(visit["visit_case_id"])
    if case is not None:
        if case["case_type"] == "REMOTE_CONSULT":
            svc.decrement_fatigue_on_remote_consult(case)
        svc.reevaluate_case_completion(case)
    return visit, 200


def mark_no_show(user, visit_id):
    visit = get_entity("visits", visit_id, "visit")
    if visit["status"] != "CONFIRMED":
        raise invalid_state("visit is not CONFIRMED")
    slot = stores["appointment_slots"].get(visit["appointment_slot_id"])
    if slot and not (current_date_str() > slot["slot_date"]):
        raise ApiError("ERR_VISIT_NOT_DUE", 409,
                       "visit cannot be marked no-show before its slot date has passed")
    visit["status"] = "NO_SHOW"
    touch(visit)
    case = stores["visit_cases"].get(visit["visit_case_id"])
    if case is not None:
        svc.reevaluate_case_completion(case)
    return visit, 200


def cancel_visit(user, visit_id):
    visit = get_entity("visits", visit_id, "visit")
    if visit["status"] != "CONFIRMED":
        raise invalid_state("visit is not CONFIRMED")
    visit["status"] = "CANCELLED"
    touch(visit)
    slot = stores["appointment_slots"].get(visit["appointment_slot_id"])
    if slot is not None:
        slot["status"] = "CANCELLED"
        slot["held_by_case_id"] = None
        touch(slot)
    itinerary = stores["itineraries"].get(visit["itinerary_id"])
    if itinerary is not None:
        # PRD §3.4: visit-level cancellation "bumps the itinerary revision,
        # recomputes totals" — unconditional on itinerary status.
        itinerary["revision"] += 1
        svc.recompute_itinerary_totals(itinerary)
        touch(itinerary)
    return visit, 200


# =============================================================================
# Logistics
# =============================================================================

def create_logistics_arrangement(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    body = get_body()
    require_fields(body, ["arrangement_type", "details", "companion_count"])
    arrangement_type = body["arrangement_type"]
    details = body["details"]
    companion_count = body["companion_count"]
    if arrangement_type not in ARRANGEMENT_TYPES:
        raise bad_request("arrangement_type must be one of %s" % ", ".join(ARRANGEMENT_TYPES))
    if not is_string(details):
        raise bad_request("details must be a string")
    if not is_int(companion_count) or not (0 <= companion_count <= 2):
        raise bad_request("companion_count must be an integer in 0..2")
    if arrangement_type == "INTERPRETER":
        patient = svc.case_patient(case)
        if not patient or not patient["requires_interpreter"]:
            raise ApiError("ERR_INTERPRETER_NOT_REQUIRED", 422,
                           "patient does not require an interpreter")
    ent = new_entity({
        "visit_case_id": case_id,
        "arrangement_type": arrangement_type,
        "details": details,
        "companion_count": companion_count,
        "status": "REQUESTED",
    })
    stores["logistics_arrangements"][ent["id"]] = ent
    return ent, 201


def list_logistics_arrangements(user, case_id):
    from flask import request
    get_entity("visit_cases", case_id, "visit case")
    items = [a for a in stores["logistics_arrangements"].values()
             if a["visit_case_id"] == case_id]
    arrangement_type = request.args.get("arrangement_type")
    if arrangement_type is not None:
        items = [a for a in items if a["arrangement_type"] == arrangement_type]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_logistics_arrangement(user, arrangement_id):
    return get_entity("logistics_arrangements", arrangement_id, "logistics arrangement"), 200


def confirm_logistics_arrangement(user, case_id, arrangement_id):
    get_entity("visit_cases", case_id, "visit case")
    arr = get_entity("logistics_arrangements", arrangement_id, "logistics arrangement")
    if arr["visit_case_id"] != case_id:
        raise not_found("logistics arrangement not found under case: %s" % arrangement_id)
    if arr["status"] != "REQUESTED":
        raise invalid_state("logistics arrangement is not REQUESTED")
    if arr["arrangement_type"] == "INTERPRETER":
        case = stores["visit_cases"].get(case_id)
        patient = svc.case_patient(case) if case else None
        if not patient or not patient["requires_interpreter"]:
            raise ApiError("ERR_INTERPRETER_NOT_REQUIRED", 422,
                           "patient does not require an interpreter")
    arr["status"] = "BOOKED"
    touch(arr)
    return arr, 200


def cancel_logistics_arrangement(user, case_id, arrangement_id):
    get_entity("visit_cases", case_id, "visit case")
    arr = get_entity("logistics_arrangements", arrangement_id, "logistics arrangement")
    if arr["visit_case_id"] != case_id:
        raise not_found("logistics arrangement not found under case: %s" % arrangement_id)
    if arr["status"] not in ("REQUESTED", "BOOKED"):
        raise invalid_state("logistics arrangement cannot be cancelled from its current state")
    arr["status"] = "CANCELLED"
    touch(arr)
    return arr, 200


# =============================================================================
# Communications
# =============================================================================

def create_communication(user, case_id):
    case = get_entity("visit_cases", case_id, "visit case")
    body = get_body()
    require_fields(body, ["comm_type", "body"])
    comm_type = body["comm_type"]
    if comm_type not in COMM_TYPES:
        raise bad_request("comm_type must be one of %s" % ", ".join(COMM_TYPES))
    if not is_string(body["body"]):
        raise bad_request("body must be a string")
    plan = body.get("continuity_plan")
    if comm_type == "CONTINUITY_PLAN":
        if not isinstance(plan, dict):
            raise bad_request("continuity_plan is required for CONTINUITY_PLAN communications")
        owner = plan.get("owner")
        weeks = plan.get("follow_up_weeks")
        if owner not in CONTINUITY_OWNERS:
            raise bad_request("continuity_plan.owner must be one of %s" % ", ".join(CONTINUITY_OWNERS))
        if not is_int(weeks) or not (1 <= weeks <= 52):
            raise bad_request("continuity_plan.follow_up_weeks must be an integer in 1..52")
    ent = new_entity({
        "visit_case_id": case_id,
        "comm_type": comm_type,
        "body": body["body"],
        "continuity_plan": plan if comm_type == "CONTINUITY_PLAN" else None,
        "sent_at": now_ts(),
    })
    stores["communications"][ent["id"]] = ent
    svc.reevaluate_referral_closure(case)
    return ent, 201


def list_communications(user, case_id):
    from flask import request
    get_entity("visit_cases", case_id, "visit case")
    items = [c for c in stores["communications"].values() if c["visit_case_id"] == case_id]
    comm_type = request.args.get("comm_type")
    if comm_type is not None:
        items = [c for c in items if c["comm_type"] == comm_type]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_communication(user, comm_id):
    return get_entity("communications", comm_id, "communication"), 200


# =============================================================================
# Route table: (method, path, handler, allowed roles)
# =============================================================================

ROUTES = [
    ("POST", "/_clock/set_current_utc", set_current_utc, ADMIN),

    ("POST", "/specialty-services", create_specialty_service, ADMIN),
    ("GET", "/specialty-services", list_specialty_services, ALL_ROLES),
    ("GET", "/specialty-services/<service_id>", get_specialty_service, ALL_ROLES),

    ("POST", "/specialty-services/<service_id>/slots", create_slot, ADMIN),
    ("GET", "/specialty-services/<service_id>/slots", list_service_slots, ALL_ROLES),
    ("GET", "/slots/<slot_id>", get_slot, ALL_ROLES),
    ("POST", "/slots/<slot_id>/confirm", confirm_slot, COORD),
    ("POST", "/slots/<slot_id>/release", release_slot, COORD),

    ("POST", "/referrals", create_referral, COORD),
    ("GET", "/referrals", list_referrals, ALL_ROLES),
    ("GET", "/referrals/<referral_id>", get_referral, ALL_ROLES),
    ("GET", "/referrals/<referral_id>/patient", get_referral_patient, ALL_ROLES),
    ("GET", "/patients/<patient_id>", get_patient, ALL_ROLES),

    ("POST", "/referrals/<referral_id>/medical-records", create_medical_record, COORD),
    ("GET", "/referrals/<referral_id>/medical-records", list_medical_records, ALL_ROLES),
    ("GET", "/medical-records/<record_id>", get_medical_record, ALL_ROLES),
    ("POST", "/referrals/<referral_id>/medical-records/<record_id>/verify", verify_medical_record, REVIEWER),
    ("POST", "/referrals/<referral_id>/medical-records/<record_id>/reject", reject_medical_record, REVIEWER),
    ("POST", "/referrals/<referral_id>/submit-review", submit_review, COORD),

    ("POST", "/visit-cases", create_visit_case, COORD),
    ("GET", "/visit-cases", list_visit_cases, ALL_ROLES),
    ("GET", "/visit-cases/<case_id>", get_visit_case, ALL_ROLES),
    ("POST", "/visit-cases/<case_id>/reviews", create_case_review, REVIEWER),
    ("GET", "/visit-cases/<case_id>/reviews", list_case_reviews, ALL_ROLES),
    ("GET", "/reviews/<review_id>", get_case_review, ALL_ROLES),
    ("POST", "/visit-cases/<case_id>/withdraw", withdraw_visit_case, COORD),
    ("POST", "/visit-cases/<case_id>/authorize-travel", authorize_travel, COORD),

    ("GET", "/visit-cases/<case_id>/financial-clearance", get_case_financial_clearance, ALL_ROLES),
    ("POST", "/visit-cases/<case_id>/financial-clearance/waive", waive_clearance, FIN),
    ("POST", "/visit-cases/<case_id>/financial-clearance/reopen", reopen_clearance, FIN),
    ("POST", "/visit-cases/<case_id>/financial-clearance/forfeit", forfeit_clearance, FIN),
    ("GET", "/financial-clearances/<clearance_id>", get_financial_clearance, ALL_ROLES),

    ("POST", "/visit-cases/<case_id>/estimate-letters", create_estimate_letter, FIN),
    ("GET", "/visit-cases/<case_id>/estimate-letters", list_estimate_letters, ALL_ROLES),
    ("GET", "/estimate-letters/<letter_id>", get_estimate_letter, ALL_ROLES),

    ("POST", "/visit-cases/<case_id>/billing-transactions", create_billing_transaction, FIN),
    ("GET", "/visit-cases/<case_id>/billing-transactions", list_case_billing_transactions, ALL_ROLES),
    ("GET", "/billing-transactions/<txn_id>", get_billing_transaction, ALL_ROLES),
    ("GET", "/billing-transactions", list_billing_transactions, ALL_ROLES),

    ("GET", "/visit-cases/<case_id>/itinerary", get_case_itinerary, ALL_ROLES),
    ("GET", "/itineraries/<itinerary_id>", get_itinerary, ALL_ROLES),
    ("POST", "/visit-cases/<case_id>/slot-holds", create_slot_hold, COORD),
    ("POST", "/itineraries/<itinerary_id>/confirm", confirm_itinerary, COORD),
    ("POST", "/itineraries/<itinerary_id>/lock", lock_itinerary, COORD),
    ("GET", "/itineraries/<itinerary_id>/visits", list_itinerary_visits, ALL_ROLES),
    ("GET", "/visits/<visit_id>", get_visit, ALL_ROLES),
    ("GET", "/visits", list_visits, ALL_ROLES),
    ("POST", "/visits/<visit_id>/complete", complete_visit, COORD),
    ("POST", "/visits/<visit_id>/mark-no-show", mark_no_show, COORD),
    ("POST", "/visits/<visit_id>/cancel", cancel_visit, COORD),

    ("POST", "/visit-cases/<case_id>/logistics", create_logistics_arrangement, LOGI),
    ("GET", "/visit-cases/<case_id>/logistics", list_logistics_arrangements, ALL_ROLES),
    ("GET", "/logistics-arrangements/<arrangement_id>", get_logistics_arrangement, ALL_ROLES),
    ("POST", "/visit-cases/<case_id>/logistics/<arrangement_id>/confirm", confirm_logistics_arrangement, LOGI),
    ("POST", "/visit-cases/<case_id>/logistics/<arrangement_id>/cancel", cancel_logistics_arrangement, LOGI),

    ("POST", "/visit-cases/<case_id>/communications", create_communication, REVIEWER),
    ("GET", "/visit-cases/<case_id>/communications", list_communications, ALL_ROLES),
    ("GET", "/communications/<comm_id>", get_communication, ALL_ROLES),
]
