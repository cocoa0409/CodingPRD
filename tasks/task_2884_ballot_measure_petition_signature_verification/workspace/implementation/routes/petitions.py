"""Petition lifecycle: intake, format review, titling, circulation, filing,
verification rounds, cure periods, challenges, determination and reports."""

from flask import Blueprint

import response
import validation as v
from db import (CHALLENGE_REVIEW_DAYS, MAX_CURE_PERIODS,
                MAX_FORMAT_REVIEW_ROUNDS, db, fmt_instant, get_cure_period,
                get_petition, get_standard, new_resource, now, plus_days,
                rounds_of_petition, serialize, touch)
from errors import ApiError
from middleware import require_auth, require_petition_owner
from services import calculations as calc
from services import cascades

ALL_ROLES = ("SosAdmin", "ElectionsExaminer", "TitleExaminer", "Proponent",
             "CountyClerk", "CirculatorAgent", "Challenger")

SUBJECT_CODES = ("TAX", "ELECTIONS", "EDUCATION", "HEALTH", "ENVIRONMENT",
                 "PUBLIC_SAFETY")

bp = Blueprint("petitions", __name__)


def serialize_cure_period(cure_period):
    out = serialize(cure_period)
    out["supplemental_raw_count"] = calc.supplemental_raw_count(cure_period)
    return out


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------
@bp.route("/petitions", methods=["POST"])
def create_petition():
    user_id, role = require_auth(["Proponent"])
    body = v.body()
    standard_id = v.as_id(v.required(body, "standard_id"), "standard_id")
    proponent_name = v.as_string(v.required(body, "proponent_name"), "proponent_name")
    submitted_title = v.as_string(v.required(body, "submitted_title"), "submitted_title")
    codes = v.as_str_array(v.required(body, "measure_subject_codes"),
                           "measure_subject_codes", min_items=1, max_items=5,
                           allowed=SUBJECT_CODES)
    standard = get_standard(standard_id)
    petition = new_resource({
        "standard_id": standard["id"],
        "proponent_user_id": user_id,
        "proponent_name": proponent_name,
        "submitted_title": submitted_title,
        "measure_subject_codes": codes,
        "official_title": None,
        "official_summary": None,
        "status": "DRAFT",
        "challenge_status": "NONE",
        "format_review_round": 0,
        "cleared_at": None,
        "circulation_deadline": None,
        "required_valid_signatures": 0,
        "raw_signature_count": 0,
        "accepted_raw_total": 0,
        "projected_valid_count": 0,
        "verified_valid_count": 0,
        "qualifying_county_count": 0,
        "verification_cost_accrued_cents": 0,
        "voided_signature_count": 0,
        "cure_period_count": 0,
        "_cleared_at_dt": None,
        "_circulation_deadline_dt": None,
    })
    db.petitions[petition["id"]] = petition
    return response.single(serialize(petition), 201)


@bp.route("/petitions/<petition_id>", methods=["GET"])
def read_petition(petition_id):
    require_auth(ALL_ROLES)
    return response.single(serialize(get_petition(petition_id)))


@bp.route("/petitions", methods=["GET"])
def list_petitions():
    require_auth(ALL_ROLES)
    return response.listing(list(db.petitions.values()), {
        "standard_id": ("str", "standard_id"),
        "status": ("str", "status"),
        "challenge_status": ("str", "challenge_status"),
    })


# ---------------------------------------------------------------------------
# format review
# ---------------------------------------------------------------------------
@bp.route("/petitions/<petition_id>/submit", methods=["POST"])
def submit_petition(petition_id):
    user_id, role = require_auth(["Proponent"])
    v.body()
    petition = get_petition(petition_id)
    require_petition_owner(petition, user_id, role)
    if petition["status"] not in ("DRAFT", "FORMAT_REJECTED"):
        raise ApiError("ERR_INVALID_PETITION_STATE")
    if petition["format_review_round"] >= MAX_FORMAT_REVIEW_ROUNDS:
        raise ApiError("ERR_FORMAT_REVIEW_ROUNDS_EXHAUSTED")
    petition["status"] = "FORMAT_REVIEW"
    touch(petition)
    return response.single(serialize(petition))


@bp.route("/petitions/<petition_id>/format-decision", methods=["POST"])
def format_decision(petition_id):
    require_auth(["ElectionsExaminer"])
    body = v.body()
    decision = v.as_enum(v.required(body, "decision"), "decision",
                         ("APPROVE", "REJECT"))
    if "reviewer_note" in body and body["reviewer_note"] is not None:
        v.as_string(body["reviewer_note"], "reviewer_note")
    petition = get_petition(petition_id)
    if petition["status"] != "FORMAT_REVIEW":
        raise ApiError("ERR_INVALID_PETITION_STATE")
    if decision == "APPROVE" and len(petition["measure_subject_codes"]) != 1:
        raise ApiError("ERR_SINGLE_SUBJECT_VIOLATION")
    # The counter tracks rounds consumed, so both outcomes increment it.
    petition["format_review_round"] += 1
    petition["status"] = "TITLE_PENDING" if decision == "APPROVE" else "FORMAT_REJECTED"
    touch(petition)
    return response.single(serialize(petition))


@bp.route("/petitions/<petition_id>/title-summary", methods=["PUT"])
def set_title_summary(petition_id):
    require_auth(["TitleExaminer"])
    body = v.body()
    official_title = v.as_string(v.required(body, "official_title"), "official_title")
    official_summary = v.as_string(v.required(body, "official_summary"),
                                   "official_summary")
    expected_version = v.as_int(v.required(body, "expected_petition_version"),
                                "expected_petition_version")
    petition = get_petition(petition_id)
    if expected_version != petition["version"]:
        raise ApiError("ERR_STALE_PETITION_VERSION")
    if petition["status"] != "TITLE_PENDING":
        raise ApiError("ERR_INVALID_PETITION_STATE")
    petition["official_title"] = official_title
    petition["official_summary"] = official_summary
    touch(petition)
    return response.single(serialize(petition))


@bp.route("/petitions/<petition_id>/clear-for-circulation", methods=["POST"])
def clear_for_circulation(petition_id):
    require_auth(["SosAdmin"])
    v.body()
    petition = get_petition(petition_id)
    if petition["status"] != "TITLE_PENDING":
        raise ApiError("ERR_INVALID_PETITION_STATE")
    if not petition["official_title"] or not petition["official_summary"]:
        raise ApiError("ERR_TITLE_SUMMARY_MISSING")
    standard = get_standard(petition["standard_id"])
    cleared_at = now()
    deadline = plus_days(cleared_at, standard["circulation_window_days"])
    petition["cleared_at"] = fmt_instant(cleared_at)
    petition["_cleared_at_dt"] = cleared_at
    petition["circulation_deadline"] = fmt_instant(deadline)
    petition["_circulation_deadline_dt"] = deadline
    petition["required_valid_signatures"] = \
        calc.required_valid_signature_threshold(standard)
    petition["status"] = "CLEARED"
    touch(petition)
    return response.single(serialize(petition))


@bp.route("/petitions/<petition_id>/file-signatures", methods=["POST"])
def file_signatures(petition_id):
    user_id, role = require_auth(["Proponent"])
    v.body()
    petition = get_petition(petition_id)
    require_petition_owner(petition, user_id, role)
    if petition["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_PETITION_STATE")
    if petition["_circulation_deadline_dt"] is None \
            or now() > petition["_circulation_deadline_dt"]:
        raise ApiError("ERR_CIRCULATION_DEADLINE_PASSED")
    verified = [b for b in db.batches.values()
                if b["petition_id"] == petition["id"]
                and b["status"] == "AFFIDAVIT_VERIFIED"]
    if not verified:
        raise ApiError("ERR_NO_VERIFIED_BATCHES")
    calc.recompute_petition_counts(petition)
    calc.recompute_qualifying_counties(petition)
    petition["status"] = "SIGNATURES_FILED"
    touch(petition)
    return response.single(serialize(petition))


# ---------------------------------------------------------------------------
# verification rounds
# ---------------------------------------------------------------------------
ROUND_FROM_STATUS = {
    "RANDOM_SAMPLE": ("SIGNATURES_FILED",),
    "FULL_CHECK": ("SIGNATURES_FILED", "FULL_CHECK"),
    "CURE_RECHECK": ("CURE_PERIOD",),
}


@bp.route("/petitions/<petition_id>/verification-rounds", methods=["POST"])
def open_verification_round(petition_id):
    require_auth(["ElectionsExaminer"])
    body = v.body()
    round_type = v.as_enum(v.required(body, "round_type"), "round_type",
                           ("RANDOM_SAMPLE", "FULL_CHECK", "CURE_RECHECK"))
    cure_period_id = v.optional(body, "cure_period_id")
    if cure_period_id is not None:
        cure_period_id = v.as_id(cure_period_id, "cure_period_id")
    if round_type == "CURE_RECHECK" and cure_period_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "cure_period_id is required for a CURE_RECHECK round")

    petition = get_petition(petition_id)
    cure_period = None
    if cure_period_id is not None:
        cure_period = get_cure_period(cure_period_id)
        if cure_period["petition_id"] != petition["id"]:
            raise ApiError("ERR_CURE_PERIOD_NOT_FOUND")

    if any(r["status"] == "OPEN" for r in rounds_of_petition(petition["id"])):
        raise ApiError("ERR_ROUND_ALREADY_OPEN")
    if petition["status"] not in ROUND_FROM_STATUS[round_type]:
        raise ApiError("ERR_INVALID_PETITION_STATE")
    if round_type == "CURE_RECHECK" and cure_period["status"] != "OPEN":
        raise ApiError("ERR_CURE_PERIOD_NOT_OPEN")

    standard = get_standard(petition["standard_id"])
    pool_size, selected = calc.select_sample(petition, standard, round_type)
    if pool_size == 0:
        raise ApiError("ERR_EMPTY_ELIGIBLE_POOL")

    rnd = new_resource({
        "petition_id": petition["id"],
        "cure_period_id": cure_period["id"] if round_type == "CURE_RECHECK" else None,
        "round_type": round_type,
        "round_index": len(rounds_of_petition(petition["id"])) + 1,
        "status": "OPEN",
        "eligible_pool_size": pool_size,
        "sample_size": len(selected),
        "sampled_valid_count": 0,
        "validity_rate_bps": 0,
        "projected_valid_count": 0,
        "determination": "PENDING",
        "tallied_by_examiner_id": None,
        "accrued_cost_cents": 0,
        "voided_reason": None,
        "_selected_ids": [r["id"] for r in selected],
        "_batch_status_before": {},
    })
    db.rounds[rnd["id"]] = rnd
    for record in selected:
        record["in_sample"] = True
        record["validated_in_round_id"] = rnd["id"]
        touch(record)

    new_status = petition["status"]
    if round_type == "RANDOM_SAMPLE":
        new_status = "SAMPLE_VERIFICATION"
    elif round_type == "FULL_CHECK":
        new_status = "FULL_CHECK"
    if new_status != petition["status"]:
        petition["status"] = new_status
        touch(petition)
    return response.single(serialize(rnd), 201)


# ---------------------------------------------------------------------------
# cure periods
# ---------------------------------------------------------------------------
@bp.route("/petitions/<petition_id>/cure-periods", methods=["POST"])
def open_cure_period(petition_id):
    require_auth(["SosAdmin"])
    v.body()
    petition = get_petition(petition_id)
    if petition["status"] != "CURE_PERIOD":
        raise ApiError("ERR_INVALID_PETITION_STATE")
    standard = get_standard(petition["standard_id"])
    opened_at = now()
    deadline_at = plus_days(opened_at, standard["cure_window_days"])
    for existing in db.cure_periods.values():
        if existing["petition_id"] != petition["id"]:
            continue
        if opened_at < existing["_deadline_at_dt"] \
                and existing["_opened_at_dt"] < deadline_at:
            raise ApiError("ERR_CURE_PERIOD_OVERLAP")
    if petition["cure_period_count"] >= MAX_CURE_PERIODS:
        raise ApiError("ERR_CURE_LIMIT_REACHED")
    best_valid = calc.best_valid_for_cure(petition)
    if not calc.cure_eligible(petition, standard, best_valid):
        raise ApiError("ERR_CURE_NOT_ELIGIBLE")

    rnd = calc.latest_closed_round(petition)
    shortfall, assumed, target = calc.cure_target(petition, rnd)
    cure_period = new_resource({
        "petition_id": petition["id"],
        "opened_at": fmt_instant(opened_at),
        "deadline_at": fmt_instant(deadline_at),
        "shortfall_at_open": shortfall,
        "assumed_validity_rate_bps": assumed,
        "cure_target_raw_signatures": target,
        "supplemental_raw_count": 0,
        "status": "OPEN",
        "_opened_at_dt": opened_at,
        "_deadline_at_dt": deadline_at,
    })
    db.cure_periods[cure_period["id"]] = cure_period
    petition["cure_period_count"] = len(
        [c for c in db.cure_periods.values() if c["petition_id"] == petition["id"]])
    touch(petition)
    return response.single(serialize_cure_period(cure_period), 201)


# ---------------------------------------------------------------------------
# challenges
# ---------------------------------------------------------------------------
@bp.route("/petitions/<petition_id>/challenges", methods=["POST"])
def file_challenge(petition_id):
    user_id, role = require_auth(["Challenger"])
    body = v.body()
    challenger_name = v.as_string(v.required(body, "challenger_name"), "challenger_name")
    grounds = v.as_enum(v.required(body, "grounds"), "grounds",
                        ("COUNT_ERROR", "FORGERY", "CIRCULATOR_INELIGIBLE",
                         "FORMAT_DEFECT"))
    statement = v.as_string(v.required(body, "statement"), "statement")
    petition = get_petition(petition_id)
    if petition["challenge_status"] != "NONE":
        raise ApiError("ERR_CHALLENGE_ALREADY_FILED")
    if petition["status"] not in ("PENDING_CERTIFICATION", "PENDING_FAILURE"):
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED")
    filed_at = now()
    review_deadline = plus_days(filed_at, CHALLENGE_REVIEW_DAYS)
    challenge = new_resource({
        "petition_id": petition["id"],
        "challenger_user_id": user_id,
        "challenger_name": challenger_name,
        "grounds": grounds,
        "statement": statement,
        "filed_at": fmt_instant(filed_at),
        "review_deadline_at": fmt_instant(review_deadline),
        "court_docket_number": None,
        "ruling": None,
        "status": "FILED",
        "_filed_at_dt": filed_at,
        "_review_deadline_at_dt": review_deadline,
    })
    db.challenges[challenge["id"]] = challenge
    petition["challenge_status"] = "CHALLENGE_FILED"
    touch(petition)
    return response.single(serialize(challenge), 201)


# ---------------------------------------------------------------------------
# determination and reports
# ---------------------------------------------------------------------------
@bp.route("/petitions/<petition_id>/determination", methods=["POST"])
def issue_determination(petition_id):
    user_id, role = require_auth(["SosAdmin", "ElectionsExaminer"])
    body = v.body()
    determination = v.as_enum(v.required(body, "determination"), "determination",
                              ("CERTIFY", "FAIL"))
    petition = get_petition(petition_id)
    rnd = calc.latest_closed_round(petition)
    if rnd is not None and rnd["tallied_by_examiner_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    expected = "PENDING_CERTIFICATION" if determination == "CERTIFY" else "PENDING_FAILURE"
    if petition["status"] != expected:
        raise ApiError("ERR_INVALID_PETITION_STATE")
    if petition["challenge_status"] in ("CHALLENGE_FILED", "COURT_REVIEW"):
        raise ApiError("ERR_CHALLENGE_PENDING")
    for referral in db.fraud_referrals.values():
        if referral["petition_id"] == petition["id"] \
                and referral["status"] in ("OPENED", "REFERRED_TO_AG"):
            raise ApiError("ERR_FRAUD_REFERRAL_OPEN")
    standard = get_standard(petition["standard_id"])
    if determination == "CERTIFY":
        if petition["qualifying_county_count"] < standard["required_qualifying_counties"]:
            raise ApiError("ERR_COUNTY_DISTRIBUTION_UNMET")
        petition["status"] = "CERTIFIED"
    else:
        petition["status"] = "FAILED"
    touch(petition)
    return response.single(serialize(petition))


@bp.route("/petitions/<petition_id>/distribution-report", methods=["GET"])
def distribution_report(petition_id):
    require_auth(["SosAdmin", "ElectionsExaminer", "Proponent", "Challenger"])
    petition = get_petition(petition_id)
    standard = get_standard(petition["standard_id"])
    entries = calc.county_distribution(petition, standard)
    return response.single({
        "petition_id": petition["id"],
        "required_qualifying_counties": standard["required_qualifying_counties"],
        "qualifying_county_count": sum(1 for e in entries if e["qualifies"]),
        "counties": entries,
    })


@bp.route("/petitions/<petition_id>/verification-invoice", methods=["GET"])
def verification_invoice(petition_id):
    require_auth(["SosAdmin", "ElectionsExaminer", "CountyClerk"])
    petition = get_petition(petition_id)
    standard = get_standard(petition["standard_id"])
    return response.single(calc.verification_invoice(petition, standard))
