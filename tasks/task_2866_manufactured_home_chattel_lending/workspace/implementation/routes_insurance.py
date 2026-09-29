"""Hazard coverage: the requirement matrix, force-placement and refunds (PRD 3.6)."""

from flask import Blueprint, request

import constants as K
import core
import domain
import envelope
import security
import shape
import store
from errors import ApiError
from routes_units import query_enum

bp = Blueprint("insurance", __name__)

POLICY_READ_ROLES = security.STAFF + (security.BORROWER,)


def _intersects(a_start, a_end, b_start, b_end):
    """Half-open intervals; touching endpoints do not intersect."""
    return a_start < b_end and b_start < a_end


@bp.post("/insurance-policies")
def create_policy():
    security.require(security.SERVICER, security.CLOSING_AGENT)
    data = shape.body()

    loan = store.get_loan(shape.req_id(data, "loan_id"))
    carrier_name = shape.req_string(data, "carrier_name")
    policy_number = shape.req_string(data, "policy_number")
    dwelling_coverage_cents = shape.req_int(data, "dwelling_coverage_cents", minimum=0)
    wind_deductible_cents = shape.req_int(data, "wind_deductible_cents", minimum=0)
    wind_endorsement = shape.req_bool(data, "wind_endorsement")
    effective_date = shape.req_instant(data, "effective_date")
    expiry_date = shape.req_instant(data, "expiry_date")
    expected_loan_version = shape.req_int(data, "expected_loan_version")

    if expected_loan_version != loan["version"]:
        raise ApiError("ERR_STALE_LOAN_VERSION")

    if expiry_date <= effective_date:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expiry_date must be strictly after effective_date.")

    for other in store.policies_of_loan(loan["id"]):
        if other["status"] != "ACTIVE" or other["source"] != "BORROWER_PROVIDED":
            continue
        if _intersects(effective_date, expiry_date,
                       other["effective_date"], other["expiry_date"]):
            raise ApiError("ERR_COVERAGE_PERIOD_OVERLAP")

    unit = store.units.get(loan["unit_id"])
    required = domain.required_coverage_cents(loan)
    record = {
        "id": core.new_id(),
        "loan_id": loan["id"],
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "dwelling_coverage_cents": dwelling_coverage_cents,
        "wind_deductible_cents": wind_deductible_cents,
        "wind_endorsement": wind_endorsement,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "coverage_days": core.calendar_days(effective_date, expiry_date),
        "premium_cents": 0,
        "required_coverage_cents": required,
        "compliance_state": domain.score_compliance(
            required, domain.wind_required(unit), wind_endorsement, dwelling_coverage_cents),
        "source": "BORROWER_PROVIDED",
        "status": "ACTIVE",
        "unearned_premium_refund_cents": 0,
    }
    store.stamp_new(record)
    store.policies[record["id"]] = record

    # the new policy retires the prior active borrower-provided policy
    for other in store.policies_of_loan(loan["id"]):
        if (other["id"] != record["id"] and other["status"] == "ACTIVE"
                and other["source"] == "BORROWER_PROVIDED"):
            other["status"] = "SUPERSEDED"
            store.touch(other)

    # real coverage displaces lender-placed coverage and earns a pro-rata refund
    if record["compliance_state"] == "COMPLIANT":
        for other in store.policies_of_loan(loan["id"]):
            if other["status"] == "ACTIVE" and other["source"] == "FORCE_PLACED":
                refund = domain.unearned_premium_refund_cents(other)
                other["status"] = "CANCELLED"
                other["unearned_premium_refund_cents"] = refund
                store.touch(other)
                loan["force_placed_premium_outstanding_cents"] = max(
                    0, loan["force_placed_premium_outstanding_cents"] - refund)

    domain.recompute_insurance_compliance(loan)
    store.touch(loan)
    return envelope.created(store.serialize(record))


@bp.get("/insurance-policies/<policy_id>")
def read_policy(policy_id):
    actor = security.require(*POLICY_READ_ROLES)
    policy = store.get_policy(policy_id)
    loan = store.loans.get(policy["loan_id"])
    if loan is not None:
        security.check_loan_scope(actor, loan)
    return envelope.ok(store.serialize(policy))


@bp.get("/insurance-policies")
def list_policies():
    actor = security.require(*POLICY_READ_ROLES)
    loan_id = request.args.get("loan_id")
    status = query_enum("status", K.POLICY_STATUSES)
    source = query_enum("source", K.POLICY_SOURCES)

    rows = store.ordered(list(store.policies.values()))
    if loan_id:
        rows = [p for p in rows if p["loan_id"] == loan_id]
    if status:
        rows = [p for p in rows if p["status"] == status]
    if source:
        rows = [p for p in rows if p["source"] == source]
    rows = security.narrow_by_loan(actor, rows)
    return envelope.paginate(rows, store.serialize)


@bp.post("/loans/<loan_id>/force-place-insurance")
def force_place(loan_id):
    security.require(security.SERVICER)
    loan = store.get_loan(loan_id)
    data = shape.body()
    carrier_name = shape.req_string(data, "carrier_name")
    policy_number = shape.req_string(data, "policy_number")
    effective_date = shape.req_instant(data, "effective_date")
    expiry_date = shape.req_instant(data, "expiry_date")

    if loan["servicing_state"] not in ("CURRENT", "DELINQUENT"):
        raise ApiError("ERR_LOAN_SERVICING_INVALID_STATE")

    if expiry_date <= effective_date:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expiry_date must be strictly after effective_date.")

    if loan["insurance_compliance"] != "NON_COMPLIANT":
        raise ApiError("ERR_INSURANCE_ALREADY_COMPLIANT")

    unit = store.units.get(loan["unit_id"])
    required = domain.required_coverage_cents(loan)
    coverage_days = core.calendar_days(effective_date, expiry_date)
    annual_premium, premium = domain.force_placed_premium_cents(
        required, unit["wind_zone"], coverage_days)

    record = {
        "id": core.new_id(),
        "loan_id": loan["id"],
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "dwelling_coverage_cents": required,
        "wind_deductible_cents": 0,
        "wind_endorsement": True,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "coverage_days": coverage_days,
        "premium_cents": premium,
        "required_coverage_cents": required,
        "compliance_state": domain.score_compliance(
            required, domain.wind_required(unit), True, required),
        "source": "FORCE_PLACED",
        "status": "ACTIVE",
        "unearned_premium_refund_cents": 0,
    }
    store.stamp_new(record)
    store.policies[record["id"]] = record

    loan["force_placed_premium_outstanding_cents"] += premium
    loan["insurance_compliance"] = "COMPLIANT"
    store.touch(loan)
    return envelope.created(store.serialize(record))
