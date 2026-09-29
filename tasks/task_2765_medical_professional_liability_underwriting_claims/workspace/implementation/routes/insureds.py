"""Insureds, credentialing, risk-management enrollments and peer review (PRD 3.2, 3.3)."""
from flask import Blueprint, g

import constants as C
from auth import endpoint, enrollment as fetch_enrollment, insured as fetch_insured
from auth import own_insured_id, peer_review_case, specialty_class
from envelope import created, listing, ok, pagination
from errors import ApiError
from routes import common
from store import all_of, db, new_record, touch
from val import ZERO, add_days, body, d, r2, r4, v_bool, v_date, v_decimal, v_enum
from val import v_int, v_str
from services import rating

bp = Blueprint("insureds", __name__, url_prefix=C.API_PREFIX)


@bp.post("/insureds")
@endpoint([C.R_UNDERWRITER])
def create_insured():
    payload = body()
    entity_type = v_enum(payload, "entity_type", C.ENTITY_TYPES)
    legal_name = v_str(payload, "legal_name")
    class_id = v_str(payload, "specialty_class_id")
    venue_code = v_enum(payload, "venue_code", C.VENUE_CODES)
    procedure_pct = v_decimal(
        payload,
        "high_severity_procedure_pct",
        places=6,
        minimum=ZERO,
        maximum=100,
    )
    years = v_int(payload, "years_in_practice", required=False, default=0, minimum=0)
    board_certified = v_bool(payload, "board_certified", required=False, default=False)

    specialty_class(class_id)

    record = new_record(
        {
            "entity_type": entity_type,
            "legal_name": legal_name,
            "specialty_class_id": class_id,
            "venue_code": venue_code,
            "high_severity_procedure_pct": procedure_pct,
            "years_in_practice": years,
            "board_certified": board_certified,
            "status": "PROSPECT",
            "credentialing_status": "PENDING",
            "credentialing_expires_on": None,
            "risk_class_score": r2(ZERO),
            "risk_class_code": "R1",
            "risk_class_factor": C.RISK_CLASS_FACTOR["R1"],
            "surcharge_pct": r4(ZERO),
            "closed_paid_claim_count": 0,
            "open_claim_count": 0,
            "npdb_reported_payment_total": r2(ZERO),
        }
    )
    score, code, factor = rating.classify(record, "UNDERWRITING_SNAPSHOT")
    record["risk_class_score"] = score
    record["risk_class_code"] = code
    record["risk_class_factor"] = factor
    db.insureds[record["id"]] = record
    return created(record)


@bp.get("/insureds/<record_id>")
@endpoint(C.CARRIER_AND_INSURED)
def get_insured(record_id):
    if g.role == C.R_INSURED and record_id in db.insureds:
        own_insured_id(record_id)
    return ok(fetch_insured(record_id))


@bp.get("/insureds")
@endpoint(C.CARRIER_ROLES)
def list_insureds():
    limit, offset = pagination()
    records = all_of(db.insureds)
    records = common.eq(records, "specialty_class_id", common.arg("specialty_class_id"))
    records = common.eq(records, "entity_type", common.arg("entity_type"))
    records = common.eq(records, "status", common.arg("status"))
    records = common.eq(
        records, "credentialing_status", common.arg("credentialing_status")
    )
    records = common.eq(records, "risk_class_code", common.arg("risk_class_code"))
    return listing(records, limit, offset)


@bp.post("/insureds/<record_id>/credentialing-decision")
@endpoint([C.R_UNDERWRITER])
def credentialing_decision(record_id):
    payload = body()
    verdict = v_enum(payload, "credentialing_status", C.CREDENTIALING_STATUSES)
    expires_on = v_date(payload, "credentialing_expires_on", required=False)

    insured = fetch_insured(record_id)

    insured["credentialing_status"] = verdict
    insured["credentialing_expires_on"] = expires_on
    if verdict in ("LAPSED", "DENIED") and insured["status"] == "ACTIVE":
        insured["status"] = "SUSPENDED"
    elif verdict in ("CREDENTIALED", "PROVISIONAL") and insured["status"] == "SUSPENDED":
        if expires_on is not None and d(expires_on) >= db.logical_date():
            insured["status"] = "ACTIVE"
    touch(insured)
    return ok(insured)


@bp.post("/insureds/<record_id>/enrollments")
@endpoint([C.R_UNDERWRITER])
def create_enrollment(record_id):
    insured = fetch_insured(record_id)

    payload = body()
    program_code = v_enum(payload, "program_code", C.PROGRAM_CODES)
    enrolled_on = v_date(payload, "enrolled_on")
    expected_version = v_int(payload, "expected_insured_version")

    if expected_version != insured["version"]:
        raise ApiError("ERR_STALE_INSURED_VERSION")

    for existing in rating.enrollments_of(insured["id"]):
        if existing["program_code"] == program_code and existing["status"] == "ENROLLED":
            raise ApiError("ERR_DUPLICATE_PROGRAM_ENROLLMENT")

    record = new_record(
        {
            "insured_id": insured["id"],
            "program_code": program_code,
            "enrolled_on": enrolled_on,
            "completed_on": None,
            "attestation_reference": None,
            "credit_pct_snapshot": r4(ZERO),
            "expires_on": None,
            "status": "ENROLLED",
        }
    )
    db.enrollments[record["id"]] = record
    touch(insured)
    return created(record)


@bp.get("/enrollments/<record_id>")
@endpoint(C.CARRIER_ROLES)
def get_enrollment(record_id):
    return ok(fetch_enrollment(record_id))


@bp.get("/enrollments")
@endpoint(C.CARRIER_ROLES)
def list_enrollments():
    limit, offset = pagination()
    records = all_of(db.enrollments)
    records = common.eq(records, "insured_id", common.arg("insured_id"))
    records = common.eq(records, "program_code", common.arg("program_code"))
    records = common.eq(records, "status", common.arg("status"))
    return listing(records, limit, offset)


@bp.post("/enrollments/<record_id>/completion")
@endpoint([C.R_UNDERWRITER])
def complete_enrollment(record_id):
    payload = body()
    completed_on = v_date(payload, "completed_on")
    attestation = v_str(payload, "attestation_reference")

    enrollment = fetch_enrollment(record_id)

    if enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID")
    if d(completed_on) < d(enrollment["enrolled_on"]):
        raise ApiError("ERR_VALIDATION", "completed_on may not precede enrolled_on.")

    enrollment["status"] = "COMPLETED"
    enrollment["completed_on"] = completed_on
    enrollment["attestation_reference"] = attestation
    enrollment["credit_pct_snapshot"] = C.PROGRAM_CREDIT_PCT[enrollment["program_code"]]
    enrollment["expires_on"] = add_days(completed_on, C.PROGRAM_EXPIRY_DAYS)
    touch(enrollment)

    rating.rerate_drafts(enrollment["insured_id"])
    return ok(enrollment)


# --- peer review (PRD 3.3) --------------------------------------------------
@bp.post("/peer-review-cases")
@endpoint([C.R_CHAIR, C.R_ADJUSTER])
def create_peer_review_case():
    payload = body()
    insured_id = v_str(payload, "insured_id")
    trigger_source = v_enum(payload, "trigger_source", C.PEER_TRIGGER_SOURCES)
    referral_note = v_str(payload, "referral_note")

    fetch_insured(insured_id)

    record = new_record(
        {
            "insured_id": insured_id,
            "trigger_source": trigger_source,
            "referral_note": referral_note,
            "status": "REFERRED",
            "chart_review_outcome": None,
            "external_review_outcome": None,
            "committee_vote_result": None,
            "votes_for": None,
            "votes_against": None,
            "surcharge_pct_assigned": r4(ZERO),
            "closed_on": None,
            "chair_user_id": None,
        }
    )
    db.peer_review_cases[record["id"]] = record
    return created(record)


@bp.get("/peer-review-cases/<record_id>")
@endpoint(C.CARRIER_ROLES)
def get_peer_review_case(record_id):
    return ok(peer_review_case(record_id))


@bp.get("/peer-review-cases")
@endpoint(C.CARRIER_ROLES)
def list_peer_review_cases():
    limit, offset = pagination()
    records = all_of(db.peer_review_cases)
    records = common.eq(records, "insured_id", common.arg("insured_id"))
    records = common.eq(records, "status", common.arg("status"))
    records = common.eq(records, "trigger_source", common.arg("trigger_source"))
    return listing(records, limit, offset)


@bp.post("/peer-review-cases/<record_id>/reviews")
@endpoint([C.R_CHAIR])
def record_review_track(record_id):
    payload = body()
    track = v_enum(payload, "review_track", C.REVIEW_TRACKS)
    outcome = v_enum(payload, "outcome", C.REVIEW_OUTCOMES)

    case = peer_review_case(record_id)

    if case["status"] not in ("REFERRED", "IN_REVIEW"):
        raise ApiError("ERR_PEER_REVIEW_STATE_INVALID")

    field = "chart_review_outcome" if track == "CHART" else "external_review_outcome"
    if case[field] is not None:
        raise ApiError("ERR_REVIEW_TRACK_ALREADY_RECORDED")

    case[field] = outcome
    if case["chart_review_outcome"] is not None and case["external_review_outcome"] is not None:
        case["status"] = "REVIEWS_COMPLETE"
    else:
        case["status"] = "IN_REVIEW"
    touch(case)
    return ok(case)


@bp.post("/peer-review-cases/<record_id>/committee-vote")
@endpoint([C.R_CHAIR])
def record_committee_vote(record_id):
    payload = body()
    vote_result = v_enum(payload, "vote_result", C.VOTE_RESULTS)
    votes_for = v_int(payload, "votes_for", minimum=0)
    votes_against = v_int(payload, "votes_against", minimum=0)

    case = peer_review_case(record_id)

    if case["status"] != "REVIEWS_COMPLETE":
        raise ApiError("ERR_PEER_REVIEW_STATE_INVALID")
    if not votes_for > votes_against:
        raise ApiError("ERR_VALIDATION", "The committee vote must carry a majority.")

    case["committee_vote_result"] = vote_result
    case["votes_for"] = votes_for
    case["votes_against"] = votes_against
    case["chair_user_id"] = g.user_id
    case["surcharge_pct_assigned"] = C.PEER_REVIEW_SURCHARGE_PCT[vote_result]
    case["closed_on"] = db.logical_date().isoformat()
    case["status"] = "CLOSED"
    touch(case)

    insured = db.insureds.get(case["insured_id"])
    if insured is not None:
        rating.recompute_surcharge(insured)
        rating.rerate_drafts(insured["id"])
        if vote_result == "DEVIATION_MAJOR" and insured["status"] == "ACTIVE":
            insured["status"] = "SUSPENDED"
            touch(insured)
    return ok(case)
