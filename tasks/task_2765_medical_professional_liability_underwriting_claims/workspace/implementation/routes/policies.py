"""Policies, rated terms, issuance, cancellation and tail endorsements (PRD 3.4, 3.5)."""
from decimal import Decimal

from flask import Blueprint, g

import constants as C
from auth import endpoint, find, insured as fetch_insured, own_policy, own_tail, own_term
from auth import policy as fetch_policy, policy_term, tail_endorsement
from envelope import created, listing, ok, pagination
from errors import ApiError
from routes import common
from store import all_of, db, new_record, touch
from val import ZERO, add_years_minus_day, body, d, days_between, r2, r4, v_date
from val import v_enum, v_int, v_money, v_str
from services import rating

bp = Blueprint("policies", __name__, url_prefix=C.API_PREFIX)


@bp.post("/policies")
@endpoint([C.R_UNDERWRITER])
def create_policy():
    payload = body()
    insured_id = v_str(payload, "insured_id")
    coverage_form = v_enum(payload, "coverage_form", C.COVERAGE_FORMS)
    limit_per_claim = v_money(
        payload, "limit_per_claim", minimum=ZERO, exclusive_minimum=True
    )
    if limit_per_claim not in C.LIMIT_PER_CLAIM_VALUES:
        raise ApiError(
            "ERR_VALIDATION", "limit_per_claim must be one of the four published limits."
        )
    limit_aggregate = v_money(
        payload, "limit_aggregate", minimum=ZERO, exclusive_minimum=True
    )
    retroactive_date = v_date(payload, "retroactive_date", required=False)
    step_credit = v_int(
        payload, "prior_acts_step_credit", required=False, default=0, minimum=0, maximum=4
    )
    consent_clause = v_enum(
        payload, "consent_to_settle_clause", C.CONSENT_CLAUSES
    )

    if coverage_form == "CLAIMS_MADE" and retroactive_date is None:
        raise ApiError("ERR_RETRO_DATE_INVALID")
    if coverage_form == "OCCURRENCE" and retroactive_date is not None:
        raise ApiError("ERR_RETRO_DATE_INVALID")

    insured = fetch_insured(insured_id)
    if insured["status"] == "SUSPENDED":
        raise ApiError("ERR_INSURED_STATE_INVALID")

    record = new_record(
        {
            "insured_id": insured_id,
            "policy_number": db.next_policy_number(),
            "coverage_form": coverage_form,
            "limit_per_claim": limit_per_claim,
            "limit_aggregate": limit_aggregate,
            "retroactive_date": retroactive_date,
            "prior_acts_step_credit": step_credit,
            "consent_to_settle_clause": consent_clause,
            "status": "QUOTED",
            "current_term_id": None,
            "quoted_premium_total": r2(ZERO),
            "written_premium_net_total": r2(ZERO),
        }
    )
    db.policies[record["id"]] = record
    return created(record)


@bp.get("/policies/<record_id>")
@endpoint(C.CARRIER_AND_INSURED)
def get_policy(record_id):
    candidate = find(db.policies, record_id)
    if candidate is not None:
        own_policy(candidate)
    return ok(fetch_policy(record_id))


@bp.get("/policies")
@endpoint(C.CARRIER_ROLES)
def list_policies():
    limit, offset = pagination()
    records = all_of(db.policies)
    records = common.eq(records, "insured_id", common.arg("insured_id"))
    records = common.eq(records, "status", common.arg("status"))
    records = common.eq(records, "coverage_form", common.arg("coverage_form"))
    return listing(records, limit, offset)


@bp.post("/policies/<record_id>/terms")
@endpoint([C.R_UNDERWRITER])
def create_term(record_id):
    policy = fetch_policy(record_id)

    payload = body()
    effective_date = v_date(payload, "effective_date")
    expiration_date = v_date(payload, "expiration_date")
    expected_version = v_int(payload, "expected_policy_version")
    predecessor_id = v_str(payload, "predecessor_term_id", required=False)

    predecessor = None
    if predecessor_id is not None:
        predecessor = find(db.policy_terms, predecessor_id)
        if predecessor is None or predecessor["policy_id"] != policy["id"]:
            raise ApiError("ERR_POLICY_TERM_NOT_FOUND")

    if expected_version != policy["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION")

    if predecessor is not None and predecessor["status"] == "CANCELLED_FLAT":
        raise ApiError("ERR_TERM_STATE_INVALID")

    if not (d(expiration_date) > d(effective_date)):
        raise ApiError(
            "ERR_VALIDATION", "expiration_date must fall strictly after effective_date."
        )

    if predecessor is not None and d(effective_date) != d(predecessor["expiration_date"]):
        raise ApiError("ERR_TERM_PERIOD_GAP")

    for existing in rating.terms_of(policy["id"]):
        if existing["status"] == "CANCELLED_FLAT":
            continue
        if d(effective_date) < d(existing["expiration_date"]) and d(
            existing["effective_date"]
        ) < d(expiration_date):
            raise ApiError("ERR_TERM_PERIOD_OVERLAP")

    term_index = 1 if predecessor is None else int(predecessor["term_index"]) + 1
    variant = "UNDERWRITING_SNAPSHOT" if predecessor is None else "RENEWAL_PROSPECTIVE"

    record = new_record(
        {
            "policy_id": policy["id"],
            "predecessor_term_id": predecessor_id,
            "term_index": term_index,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "claims_made_step_year": 0,
            "step_factor": r2(ZERO),
            "rating_variant": variant,
            "rated_risk_class_code": "R1",
            "rated_risk_class_factor": r2(ZERO),
            "venue_severity_factor": r2(ZERO),
            "increased_limits_factor": r2(ZERO),
            "credit_pct_applied": r4(ZERO),
            "surcharge_pct_applied": r4(ZERO),
            "premium_manual": r2(ZERO),
            "premium_net": r2(ZERO),
            "administrative_fee": r2(ZERO),
            "guaranty_fund_assessment": r2(ZERO),
            "term_total": r2(ZERO),
            "return_premium": r2(ZERO),
            "aggregate_limit_remaining": r2(ZERO),
            "rate_revision_index_used": 0,
            "status": "DRAFT",
            "cancel_effective_date": None,
            "issued_at": None,
        }
    )
    db.policy_terms[record["id"]] = record
    rating.rate_term(record)
    rating.recompute_policy_money(policy)
    touch(policy)
    return created(record)


@bp.get("/policy-terms/<record_id>")
@endpoint(C.CARRIER_AND_INSURED)
def get_policy_term(record_id):
    candidate = find(db.policy_terms, record_id)
    if candidate is not None:
        own_term(candidate)
    return ok(policy_term(record_id))


@bp.get("/policy-terms")
@endpoint(C.CARRIER_ROLES)
def list_policy_terms():
    limit, offset = pagination()
    records = all_of(db.policy_terms)
    records = common.eq(records, "policy_id", common.arg("policy_id"))
    records = common.eq(records, "predecessor_term_id", common.arg("predecessor_term_id"))
    records = common.eq(records, "status", common.arg("status"))
    records = common.eq(records, "rating_variant", common.arg("rating_variant"))
    return listing(records, limit, offset)


@bp.post("/policy-terms/<record_id>/issuance")
@endpoint([C.R_UNDERWRITER])
def issue_term(record_id):
    term = policy_term(record_id)
    if term["status"] != "DRAFT":
        raise ApiError("ERR_TERM_STATE_INVALID")

    policy = db.policies[term["policy_id"]]
    insured = db.insureds[policy["insured_id"]]
    expires_on = insured.get("credentialing_expires_on")
    if insured["credentialing_status"] not in ("CREDENTIALED", "PROVISIONAL"):
        raise ApiError("ERR_CREDENTIALING_NOT_VALID_FOR_TERM")
    if expires_on is None or d(expires_on) < d(term["effective_date"]):
        raise ApiError("ERR_CREDENTIALING_NOT_VALID_FOR_TERM")

    if d(term["effective_date"]) <= db.logical_date():
        term["status"] = "IN_FORCE"
    else:
        term["status"] = "ISSUED"
    term["issued_at"] = db.logical_now()
    term["aggregate_limit_remaining"] = r2(policy["limit_aggregate"])
    touch(term)

    rating.recompute_policy_money(policy)
    rating.derive_current_term(policy)
    policy["status"] = "ACTIVE"
    touch(policy)

    if insured["status"] == "PROSPECT":
        insured["status"] = "ACTIVE"
        touch(insured)
    return ok(term)


@bp.post("/policy-terms/<record_id>/cancellation")
@endpoint([C.R_UNDERWRITER])
def cancel_term(record_id):
    payload = body()
    cancel_type = v_enum(payload, "cancel_type", C.CANCEL_TYPES)
    cancel_date = v_date(payload, "cancel_effective_date")

    term = policy_term(record_id)
    if term["status"] not in ("ISSUED", "IN_FORCE"):
        raise ApiError("ERR_TERM_STATE_INVALID")

    effective = d(term["effective_date"])
    expiration = d(term["expiration_date"])
    stamp = d(cancel_date)
    if cancel_type == "FLAT":
        if stamp != effective:
            raise ApiError("ERR_CANCEL_DATE_INVALID")
    else:
        if not (effective < stamp < expiration):
            raise ApiError("ERR_CANCEL_DATE_INVALID")

    policy = db.policies[term["policy_id"]]
    term["cancel_effective_date"] = cancel_date

    if cancel_type == "FLAT":
        term["status"] = "CANCELLED_FLAT"
        term["return_premium"] = r2(term["premium_net"])
        term["aggregate_limit_remaining"] = r2(ZERO)
        touch(term)
        for claim in all_of(db.claims):
            if claim["policy_term_id"] != term["id"]:
                continue
            if claim["coverage_status"] != "DENIED":
                claim["coverage_status"] = "DENIED"
                claim["denial_reason"] = "TERM_VOIDED"
                touch(claim)
            for negotiation in all_of(db.negotiations):
                if negotiation["claim_id"] != claim["id"]:
                    continue
                if negotiation["status"] not in ("PAID", "ABANDONED"):
                    negotiation["status"] = "ABANDONED"
                    touch(negotiation)
        for tail in rating.tails_of(policy["id"]):
            if tail["status"] == "ISSUED":
                tail["status"] = "VOID"
                tail["void_reason"] = C.VOID_REASON_FLAT_CANCEL
                touch(tail)
    else:
        term["status"] = "CANCELLED_PRO_RATA"
        whole_span = Decimal((expiration - effective).days)
        unearned = Decimal((expiration - stamp).days)
        term["return_premium"] = r2(term["premium_net"] * (unearned / whole_span))
        touch(term)

    rating.recompute_policy_money(policy)
    rating.derive_current_term(policy)
    rating.derive_policy_status(policy, driven_by="CANCELLED")
    touch(policy)
    return ok(term)


@bp.post("/policies/<record_id>/tail-endorsements")
@endpoint([C.R_UNDERWRITER])
def create_tail(record_id):
    policy = fetch_policy(record_id)

    payload = body()
    triggering_term_id = v_str(payload, "triggering_term_id")
    tail_type = v_enum(payload, "tail_type", C.TAIL_TYPES)
    trigger_reason = v_enum(payload, "trigger_reason", C.TRIGGER_REASONS)
    effective_date = v_date(payload, "effective_date")

    term = find(db.policy_terms, triggering_term_id)
    if term is None or term["policy_id"] != policy["id"]:
        raise ApiError("ERR_POLICY_TERM_NOT_FOUND")

    if term["status"] not in ("EXPIRED", "CANCELLED_PRO_RATA"):
        raise ApiError("ERR_TERM_STATE_INVALID")

    if term["status"] == "CANCELLED_PRO_RATA" and term["cancel_effective_date"]:
        window_opens_from = term["cancel_effective_date"]
    else:
        window_opens_from = term["expiration_date"]
    if d(effective_date) < d(window_opens_from):
        raise ApiError("ERR_TAIL_EFFECTIVE_DATE_INVALID")

    if tail_type == "ERP_5YR":
        window_end = add_years_minus_day(effective_date, C.ERP_5YR_WINDOW_YEARS)
    else:
        window_end = C.UNLIMITED_WINDOW_END

    for other in rating.tails_of(policy["id"]):
        if other["status"] != "ISSUED":
            continue
        if d(effective_date) <= d(other["reporting_window_end"]) and d(
            other["effective_date"]
        ) <= d(window_end):
            raise ApiError("ERR_TAIL_WINDOW_OVERLAP")

    if policy["coverage_form"] != "CLAIMS_MADE":
        raise ApiError("ERR_TAIL_NOT_APPLICABLE")

    insured = db.insureds[policy["insured_id"]]
    if tail_type == "DEATH_DISABILITY_RETIREMENT":
        if int(insured["years_in_practice"]) < C.DDR_MIN_YEARS_IN_PRACTICE:
            raise ApiError("ERR_DDR_NOT_ELIGIBLE")
        if int(term["claims_made_step_year"]) < C.DDR_MIN_STEP_YEAR:
            raise ApiError("ERR_DDR_NOT_ELIGIBLE")

    mature_basis = r2(Decimal(term["premium_manual"]) / Decimal(term["step_factor"]))
    tail_factor = C.TAIL_FACTOR[tail_type]
    record = new_record(
        {
            "policy_id": policy["id"],
            "triggering_term_id": term["id"],
            "tail_type": tail_type,
            "trigger_reason": trigger_reason,
            "effective_date": effective_date,
            "reporting_window_end": window_end,
            "mature_premium_basis": mature_basis,
            "tail_factor": tail_factor,
            "tail_premium": r2(mature_basis * tail_factor),
            "status": "QUOTED",
            "issued_at": None,
            "void_reason": None,
        }
    )
    db.tail_endorsements[record["id"]] = record
    return created(record)


@bp.get("/tail-endorsements/<record_id>")
@endpoint(C.CARRIER_AND_INSURED)
def get_tail(record_id):
    candidate = find(db.tail_endorsements, record_id)
    if candidate is not None:
        own_tail(candidate)
    return ok(tail_endorsement(record_id))


@bp.get("/tail-endorsements")
@endpoint(C.CARRIER_ROLES)
def list_tails():
    limit, offset = pagination()
    records = all_of(db.tail_endorsements)
    records = common.eq(records, "policy_id", common.arg("policy_id"))
    records = common.eq(records, "triggering_term_id", common.arg("triggering_term_id"))
    records = common.eq(records, "status", common.arg("status"))
    records = common.eq(records, "tail_type", common.arg("tail_type"))
    return listing(records, limit, offset)


@bp.post("/tail-endorsements/<record_id>/issuance")
@endpoint([C.R_UNDERWRITER])
def issue_tail(record_id):
    tail = tail_endorsement(record_id)
    if tail["status"] != "QUOTED":
        raise ApiError("ERR_TAIL_STATE_INVALID")
    for other in db.tail_endorsements.values():
        if other["id"] == tail["id"]:
            continue
        if other["triggering_term_id"] == tail["triggering_term_id"] and other[
            "status"
        ] == "ISSUED":
            raise ApiError("ERR_TAIL_ALREADY_ISSUED")
    tail["status"] = "ISSUED"
    tail["issued_at"] = db.logical_now()
    touch(tail)
    return ok(tail)
