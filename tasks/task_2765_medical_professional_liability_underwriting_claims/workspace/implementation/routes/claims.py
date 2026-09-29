"""Claim intake, coverage position, reserving, expense payment and disposition."""
from decimal import Decimal

from flask import Blueprint, g

import constants as C
from auth import claim as fetch_claim, counsel_assignment, endpoint, find
from auth import insured as fetch_insured, own_claim
from envelope import created, listing, ok, pagination
from errors import ApiError
from routes import common
from store import all_of, db, new_record, touch
from val import ZERO, body, d, parse_instant, r2, v_date, v_enum, v_money, v_int, v_str
from services import claims as claims_svc, rating

bp = Blueprint("claims", __name__, url_prefix=C.API_PREFIX)


@bp.post("/claims")
@endpoint([C.R_ADJUSTER])
def create_claim():
    payload = body()
    insured_id = v_str(payload, "insured_id")
    incident_date = v_date(payload, "incident_date")
    report_date = v_date(payload, "report_date")
    venue_code = v_enum(payload, "venue_code", C.VENUE_CODES)
    allegation_category = v_enum(
        payload, "allegation_category", C.ALLEGATION_CATEGORIES
    )
    demand_amount = v_money(payload, "demand_amount", minimum=ZERO)

    insured = fetch_insured(insured_id)

    if d(report_date) < d(incident_date):
        raise ApiError("ERR_REPORT_DATE_BEFORE_INCIDENT")

    band, band_factor = claims_svc.severity_band(demand_amount)
    record = new_record(
        {
            "insured_id": insured_id,
            "incident_date": incident_date,
            "report_date": report_date,
            "venue_code": venue_code,
            "allegation_category": allegation_category,
            "demand_amount": demand_amount,
            "claim_status": "INTAKE",
            "coverage_status": "UNDER_REVIEW",
            "denial_reason": None,
            "policy_term_id": None,
            "tail_endorsement_id": None,
            "severity_band": band,
            "severity_band_factor": band_factor,
            "indemnity_reserve": r2(ZERO),
            "expense_reserve": r2(ZERO),
            "paid_indemnity": r2(ZERO),
            "paid_expense": r2(ZERO),
            "case_incurred": r2(ZERO),
            "actuarial_incurred": r2(ZERO),
            "insured_share_receivable": r2(ZERO),
            "reserve_method_current": None,
            "counsel_reassignment_required": False,
            "excluded_counsel_firm_ids": [],
            "disposition": None,
            "verdict_amount": None,
            "suit_filed_on": None,
            "resolved_on": None,
            "closed_on": None,
            "reserved_rights_reason": None,
        }
    )
    claims_svc.resolve_coverage(record)
    db.claims[record["id"]] = record
    rating.recompute_claim_counters(insured)
    rating.rerate_drafts(insured_id, "RENEWAL_PROSPECTIVE")
    return created(record)


@bp.get("/claims/<record_id>")
@endpoint(C.CARRIER_AND_INSURED)
def get_claim(record_id):
    candidate = find(db.claims, record_id)
    if candidate is not None:
        own_claim(candidate)
    return ok(fetch_claim(record_id))


@bp.get("/claims")
@endpoint(C.CARRIER_ROLES)
def list_claims():
    limit, offset = pagination()
    records = all_of(db.claims)
    records = common.eq(records, "insured_id", common.arg("insured_id"))
    records = common.eq(records, "policy_term_id", common.arg("policy_term_id"))
    records = common.eq(records, "tail_endorsement_id", common.arg("tail_endorsement_id"))
    records = common.eq(records, "claim_status", common.arg("claim_status"))
    records = common.eq(records, "coverage_status", common.arg("coverage_status"))
    records = common.eq(records, "venue_code", common.arg("venue_code"))
    records = common.eq(records, "allegation_category", common.arg("allegation_category"))
    return listing(records, limit, offset)


@bp.post("/claims/<record_id>/coverage-decision")
@endpoint([C.R_ADJUSTER])
def coverage_decision(record_id):
    payload = body()
    position = v_enum(payload, "coverage_status", C.COVERAGE_DECISION_VALUES)
    reserved_rights_reason = v_str(payload, "reserved_rights_reason", required=False)

    claim = fetch_claim(record_id)
    if claim["claim_status"] != "INTAKE":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if claim["coverage_status"] not in ("UNDER_REVIEW", "RESERVED_RIGHTS"):
        raise ApiError("ERR_COVERAGE_ALREADY_DECIDED")

    claim["coverage_status"] = position
    if position == "RESERVED_RIGHTS":
        claim["reserved_rights_reason"] = reserved_rights_reason
    if position == "DENIED":
        claim["denial_reason"] = "ADJUSTER_DENIAL"
    claim["claim_status"] = "INVESTIGATION"
    touch(claim)
    if position == "DENIED":
        rating.recompute_claim_counters(db.insureds[claim["insured_id"]])
    return ok(claim)


RESERVE_OPEN_STATUSES = ("INTAKE", "INVESTIGATION", "LITIGATION")


@bp.post("/claims/<record_id>/reserve-entries")
@endpoint([C.R_ADJUSTER])
def create_reserve_entry(record_id):
    claim = fetch_claim(record_id)

    payload = body()
    method = v_enum(payload, "method", C.RESERVE_METHODS)
    effective_at = payload.get("effective_at")
    effective_dt = parse_instant(effective_at, "ERR_VALIDATION", "effective_at") if (
        "effective_at" in payload and payload["effective_at"] is not None
    ) else None
    if effective_dt is None:
        raise ApiError("ERR_VALIDATION", "effective_at is required.")
    rationale = v_str(payload, "rationale")
    expected_version = v_int(payload, "expected_claim_version")
    indemnity_amount = v_money(payload, "indemnity_amount", required=False, minimum=ZERO)
    expense_amount = v_money(payload, "expense_amount", required=False, minimum=ZERO)

    if method == "CASE_BASIS":
        if indemnity_amount is None or expense_amount is None:
            raise ApiError("ERR_RESERVE_METHOD_INPUT_MISMATCH")
    else:
        if indemnity_amount is not None or expense_amount is not None:
            raise ApiError("ERR_RESERVE_METHOD_INPUT_MISMATCH")

    if expected_version != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION")

    if claim["claim_status"] not in RESERVE_OPEN_STATUSES:
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    if method == "CASE_BASIS":
        computed_indemnity = r2(indemnity_amount)
        computed_expense = r2(expense_amount)
    else:
        computed_indemnity, computed_expense = claims_svc.formula_reserve(claim)

    entry = new_record(
        {
            "claim_id": claim["id"],
            "method": method,
            "effective_at": effective_at,
            "rationale": rationale,
            "indemnity_amount": indemnity_amount,
            "expense_amount": expense_amount,
            "computed_indemnity_amount": computed_indemnity,
            "computed_expense_amount": computed_expense,
            "set_by_user_id": g.user_id,
            "_effective_dt": effective_dt,
        },
        versioned=False,
    )
    db.reserve_entries[entry["id"]] = entry
    claims_svc.apply_reserve_of_record(claim)
    return created(entry)


@bp.get("/claims/<record_id>/reserve-entries")
@endpoint(C.CARRIER_ROLES)
def list_reserve_entries(record_id):
    claim = fetch_claim(record_id)
    limit, offset = pagination()
    records = claims_svc.reserve_entries_of(claim["id"])
    records = common.eq(records, "method", common.arg("method"))
    return listing(records, limit, offset)


@bp.post("/claims/<record_id>/litigation")
@endpoint([C.R_ADJUSTER])
def record_litigation(record_id):
    payload = body()
    suit_filed_on = v_date(payload, "suit_filed_on")

    claim = fetch_claim(record_id)
    if claim["claim_status"] != "INVESTIGATION":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if d(suit_filed_on) < d(claim["report_date"]):
        raise ApiError(
            "ERR_VALIDATION", "suit_filed_on may not precede the claim's report_date."
        )

    claim["suit_filed_on"] = suit_filed_on
    claim["claim_status"] = "LITIGATION"
    touch(claim)
    return ok(claim)


@bp.post("/claims/<record_id>/expense-payments")
@endpoint([C.R_ADJUSTER])
def pay_expense(record_id):
    claim = fetch_claim(record_id)

    payload = body()
    amount = v_money(payload, "amount", minimum=ZERO)
    invoice_reference = v_str(payload, "invoice_reference")
    assignment_id = v_str(payload, "counsel_assignment_id")

    assignment = counsel_assignment(assignment_id)

    if claim["claim_status"] not in ("INVESTIGATION", "LITIGATION"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if assignment["assignment_status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")
    if assignment["claim_id"] != claim["id"]:
        raise ApiError("ERR_ASSIGNMENT_CLAIM_MISMATCH")

    claim["paid_expense"] = r2(claim["paid_expense"] + amount)
    assignment["billed_expense_amount"] = r2(
        assignment["billed_expense_amount"] + amount
    )
    touch(assignment)
    firm = db.counsel_firms.get(assignment["counsel_firm_id"])
    if firm is not None:
        firm["billed_expense_total"] = r2(firm["billed_expense_total"] + amount)
        touch(firm)
    claims_svc.recompute_incurred(claim)
    return ok(claim)


@bp.post("/claims/<record_id>/disposition")
@endpoint([C.R_ADJUSTER])
def record_disposition(record_id):
    payload = body()
    disposition = v_enum(payload, "disposition", C.DISPOSITIONS)
    if disposition == "SETTLED":
        raise ApiError(
            "ERR_VALIDATION",
            "A settlement is recorded by disbursing a negotiation, not by disposition.",
        )
    resolved_on = v_date(payload, "resolved_on")
    verdict_amount = v_money(
        payload,
        "verdict_amount",
        required=(disposition == "PLAINTIFF_VERDICT"),
        minimum=ZERO,
    )

    claim = fetch_claim(record_id)
    if claim["claim_status"] not in ("INVESTIGATION", "LITIGATION"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if d(resolved_on) < d(claim["report_date"]):
        raise ApiError(
            "ERR_VALIDATION", "resolved_on may not precede the claim's report_date."
        )

    claims_svc.resolve_claim(
        claim, disposition, resolved_on, verdict_amount=verdict_amount
    )
    return ok(claim)
