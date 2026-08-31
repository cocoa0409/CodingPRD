"""Sampling, extrapolation and undercharge recovery (PRD section 3.9)."""

from datetime import timedelta

from flask import Blueprint

from calculations import (AUDIT_TIME_BAR_DAYS, close_extrapolation,
                          derive_audit_population, recompute_net_position,
                          select_rate_scaled)
from errors import ApiError
from responses import ok, ok_list
from store import db, fmt_dt, must_find, new_row, serialize, touch
import validation as V

bp = Blueprint("audits", __name__)


@bp.route("/interline/audit-samples", methods=["POST"])
def draw_sample():
    user_id, role = V.require([V.ROLE_AUDITOR])
    data = V.body()
    auditing_carrier_id = V.req_str(data, "auditing_carrier_id")
    audited_carrier_id = V.req_str(data, "audited_carrier_id")
    period_id = V.req_str(data, "settlement_period_id")
    claim_currency = V.req_enum(data, "claim_currency", V.CURRENCIES)
    sample_coupon_ids = V.req_id_list(data, "sample_coupon_ids", min_len=1,
                                      max_len=50, no_duplicates=True)

    auditing = must_find("carrier", auditing_carrier_id)
    audited = must_find("carrier", audited_carrier_id)
    period = must_find("period", period_id)
    sampled = [must_find("coupon", cid) for cid in sample_coupon_ids]

    V.require_ownership(user_id, role, auditing["id"])

    if period["status"] not in ("CLOSED", "SETTLED"):
        raise ApiError("ERR_PERIOD_NOT_CLOSED")

    population = derive_audit_population(audited["id"], period, claim_currency)

    bar = db.clock - timedelta(days=AUDIT_TIME_BAR_DAYS)
    for coupon in population:
        if coupon["_flown_at"] < bar:
            raise ApiError("ERR_AUDIT_TIME_BARRED")

    for coupon in sampled:
        ticket = db.tickets.get(coupon["ticket_id"])
        if ticket is None or ticket["sale_currency"] != claim_currency:
            raise ApiError("ERR_CURRENCY_MISMATCH")

    if not population:
        raise ApiError("ERR_EMPTY_AUDIT_POPULATION")

    population_ids = {c["id"] for c in population}
    for coupon in sampled:
        if coupon["id"] not in population_ids:
            raise ApiError("ERR_COUPON_NOT_IN_POPULATION")

    sample = new_row({
        "auditing_carrier_id": auditing["id"],
        "audited_carrier_id": audited["id"],
        "settlement_period_id": period["id"],
        "claim_currency": claim_currency,
        "sample_coupon_ids": list(sample_coupon_ids),
        "status": "DRAWN",
        "population_coupon_count": len(population),
        "population_allocated_minor": sum(
            c["allocated_amount_minor"] for c in population),
        "sampled_coupon_count": len(sample_coupon_ids),
        "sampled_allocated_minor": sum(
            c["allocated_amount_minor"] for c in sampled),
        "sampled_undercharge_minor": 0,
        "findings_count": 0,
        "undercharge_ratio_bp": 0,
        "coverage_bp": 0,
        "haircut_bp": 0,
        "extrapolated_gross_minor": 0,
        "claim_amount_minor": 0,
        "claim_settlement_minor": 0,
        "closed_at": None,
    })
    db.samples[sample["id"]] = sample
    return ok(serialize(sample), 201)


@bp.route("/interline/audit-samples/<sample_id>", methods=["GET"])
def get_sample(sample_id):
    V.require(V.ALL_ROLES)
    sample = must_find("sample", sample_id)
    return ok(serialize(sample))


@bp.route("/interline/audit-samples", methods=["GET"])
def list_samples():
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    auditing_carrier_id = V.filter_str("auditing_carrier_id")
    audited_carrier_id = V.filter_str("audited_carrier_id")
    period_id = V.filter_str("settlement_period_id")
    status = V.filter_enum("status", V.SAMPLE_STATUSES)
    rows = list(db.samples.values())
    if auditing_carrier_id is not None:
        rows = [r for r in rows
                if r["auditing_carrier_id"] == auditing_carrier_id]
    if audited_carrier_id is not None:
        rows = [r for r in rows if r["audited_carrier_id"] == audited_carrier_id]
    if period_id is not None:
        rows = [r for r in rows if r["settlement_period_id"] == period_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/audit-samples/<sample_id>/record-finding",
          methods=["POST"])
def record_finding(sample_id):
    user_id, role = V.require([V.ROLE_AUDITOR])
    data = V.body()
    coupon_id = V.req_str(data, "coupon_id")
    correct_amount = V.req_int(data, "correct_amount_minor", minimum=0)

    sample = must_find("sample", sample_id)
    coupon = must_find("coupon", coupon_id)

    V.require_ownership(user_id, role, sample["auditing_carrier_id"])

    if sample["status"] not in ("DRAWN", "IN_REVIEW"):
        raise ApiError("ERR_SAMPLE_STATE_INVALID")

    if coupon["id"] not in sample["sample_coupon_ids"]:
        raise ApiError("ERR_COUPON_NOT_IN_SAMPLE")

    shortfall = max(0, correct_amount - coupon["allocated_amount_minor"])
    sample["sampled_undercharge_minor"] += shortfall
    sample["findings_count"] += 1
    sample["status"] = "IN_REVIEW"
    touch(sample)
    return ok(serialize(sample))


@bp.route("/interline/audit-samples/<sample_id>/close", methods=["POST"])
def close_sample(sample_id):
    user_id, role = V.require([V.ROLE_AUDITOR])
    V.body()
    sample = must_find("sample", sample_id)

    V.require_ownership(user_id, role, sample["auditing_carrier_id"])

    if sample["status"] != "IN_REVIEW":
        raise ApiError("ERR_SAMPLE_STATE_INVALID")

    period = db.periods.get(sample["settlement_period_id"])
    if period is None:
        raise ApiError("ERR_PERIOD_NOT_FOUND")

    if select_rate_scaled(sample["claim_currency"], period["settlement_currency"],
                          period["_rate_fixing_date"]) is None:
        raise ApiError("ERR_NO_EXCHANGE_RATE")

    result = close_extrapolation(sample, period)
    sample.update(result)
    sample["closed_at"] = fmt_dt(db.clock)
    sample["_closed_at"] = db.clock
    touch(sample)
    return ok(serialize(sample))


@bp.route("/interline/audit-samples/<sample_id>/claim-decision",
          methods=["POST"])
def claim_decision(sample_id):
    user_id, role = V.require([V.ROLE_BILLING])
    data = V.body()
    decision = V.req_enum(data, "decision", ("ACCEPT", "DENY"))

    sample = must_find("sample", sample_id)

    V.require_ownership(user_id, role, sample["audited_carrier_id"])

    if sample["status"] != "CLAIM_RAISED":
        raise ApiError("ERR_SAMPLE_STATE_INVALID")

    if decision == "ACCEPT":
        amount = sample["claim_settlement_minor"]
        auditing = db.carriers.get(sample["auditing_carrier_id"])
        audited = db.carriers.get(sample["audited_carrier_id"])
        if auditing is not None:
            auditing["settled_receivable_minor"] += amount
            recompute_net_position(auditing)
            touch(auditing)
        if audited is not None:
            audited["settled_payable_minor"] += amount
            recompute_net_position(audited)
            touch(audited)
        sample["status"] = "CLAIM_ACCEPTED"
    else:
        sample["status"] = "CLAIM_DENIED"
    touch(sample)
    return ok(serialize(sample))
