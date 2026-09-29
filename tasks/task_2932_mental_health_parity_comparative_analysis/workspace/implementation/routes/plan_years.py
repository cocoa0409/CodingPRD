"""Plan years and their benefit classifications (PRD 3.1, 3.2)."""

from datetime import timedelta

from flask import Blueprint

import recompute
import serialize
import shape
from auth import guard
from calc import MEASUREMENT_PERIOD_BUFFER_DAYS
from enums import (ALL_ROLES, BENEFIT_CATEGORIES, FUNDING_ARRANGEMENTS, NETWORK_TIERS,
                   SUB_CLASSIFICATIONS, TIERED_CATEGORIES)
from envelope import success
from errors import ApiError
from helpers import list_response
from store import db, lookup_path, new_row

bp = Blueprint("plan_years", __name__)


@bp.route("/plan-years", methods=["POST"])
@guard("PlanSponsor")
def create_plan_year():
    payload = shape.body()
    # Step 5: body foreign keys, in the order the fields are declared.
    raw_admin = shape.raw_fk(payload, "administrator_id")
    if raw_admin is not None and raw_admin not in db.administrators:
        raise ApiError("ERR_ADMINISTRATOR_NOT_FOUND")
    # Step 6: payload shape.
    plan_name = shape.req_string(payload, "plan_name", 1, 120)
    plan_year_label = shape.req_string(payload, "plan_year_label", 1, 16)
    administrator_id = shape.req_string(payload, "administrator_id", 1, None)
    funding_arrangement = shape.req_enum(payload, "funding_arrangement", FUNDING_ARRANGEMENTS)
    covered_participant_count = shape.req_int(payload, "covered_participant_count", 1, None)
    cap_cents = shape.req_int(payload, "remediation_liability_cap_cents", 0, None)

    row = new_row({
        "plan_name": plan_name,
        "plan_year_label": plan_year_label,
        "administrator_id": administrator_id,
        "funding_arrangement": funding_arrangement,
        "covered_participant_count": covered_participant_count,
        "remediation_liability_cap_cents": cap_cents,
        "status": "OPEN",
        "compliance_posture": "COMPLIANT",
        "open_violation_count": 0,
        "notified_violation_count": 0,
        "failing_parity_test_count": 0,
        "remediation_liability_cents": 0,
    })
    db.plan_years[row["id"]] = row
    # The posture is derived immediately, without counting as a further mutation.
    recompute.recompute_plan_year(row, bump=False)
    return success(serialize.plan_year(row), 201)


@bp.route("/plan-years/<plan_year_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_plan_year(plan_year_id):
    row = lookup_path(db.plan_years, plan_year_id, "ERR_PLAN_YEAR_NOT_FOUND")
    return success(serialize.plan_year(row))


@bp.route("/plan-years", methods=["GET"])
@guard(*ALL_ROLES)
def list_plan_years():
    return list_response(db.plan_years.values(), serialize.plan_year,
                         ("administrator_id", "status", "compliance_posture"))


@bp.route("/plan-years/<plan_year_id>/classifications", methods=["POST"])
@guard("PlanSponsor")
def create_classification(plan_year_id):
    plan_year = lookup_path(db.plan_years, plan_year_id, "ERR_PLAN_YEAR_NOT_FOUND")
    payload = shape.body()
    benefit_category = shape.req_enum(payload, "benefit_category", BENEFIT_CATEGORIES)
    network_tier = shape.req_enum(payload, "network_tier", NETWORK_TIERS)
    sub_classification = shape.opt_enum(payload, "sub_classification", SUB_CLASSIFICATIONS,
                                        "NONE")
    start_text, start_date = shape.req_date(payload, "measurement_period_start")
    end_text, end_date = shape.req_date(payload, "measurement_period_end")
    mh_covered = shape.opt_bool(payload, "mh_su_benefits_covered", True)

    # Step 7: network tiering applies exactly to the two categories that have a network.
    if benefit_category in TIERED_CATEGORIES:
        if network_tier not in ("IN_NETWORK", "OUT_OF_NETWORK"):
            raise ApiError("ERR_NETWORK_TIER_MISMATCH")
    elif network_tier != "NOT_APPLICABLE":
        raise ApiError("ERR_NETWORK_TIER_MISMATCH")
    # Step 8: the outpatient split is only meaningful for outpatient benefits.
    if sub_classification != "NONE" and benefit_category != "OUTPATIENT":
        raise ApiError("ERR_SUB_CLASSIFICATION_MISMATCH")
    # Step 9: the period must make sense on its own terms.
    if end_date < start_date:
        raise ApiError("ERR_MEASUREMENT_PERIOD_INVALID")
    # Steps 14 and 15.
    recompute.gate_not_closed(plan_year)
    recompute.gate_open(plan_year)
    # Step 28: closed intervals separated by at least one full day.
    _reject_period_overlap(plan_year_id, benefit_category, network_tier, sub_classification,
                           start_date, end_date)

    row = new_row({
        "plan_year_id": plan_year_id,
        "benefit_category": benefit_category,
        "network_tier": network_tier,
        "sub_classification": sub_classification,
        "measurement_period_start": start_text,
        "measurement_period_end": end_text,
        "mh_su_benefits_covered": mh_covered,
        "_period_start": start_date,
        "_period_end": end_date,
    })
    db.classifications[row["id"]] = row
    return success(serialize.classification(row), 201)


def _reject_period_overlap(plan_year_id, benefit_category, network_tier, sub_classification,
                           start_date, end_date):
    buffer_days = timedelta(days=MEASUREMENT_PERIOD_BUFFER_DAYS)
    for existing in db.classifications.values():
        if (existing["plan_year_id"] != plan_year_id
                or existing["benefit_category"] != benefit_category
                or existing["network_tier"] != network_tier
                or existing["sub_classification"] != sub_classification):
            continue
        if (start_date <= existing["_period_end"] + buffer_days
                and end_date >= existing["_period_start"] - buffer_days):
            raise ApiError("ERR_MEASUREMENT_PERIOD_OVERLAP")


@bp.route("/plan-years/<plan_year_id>/classifications", methods=["GET"])
@guard(*ALL_ROLES)
def list_classifications(plan_year_id):
    lookup_path(db.plan_years, plan_year_id, "ERR_PLAN_YEAR_NOT_FOUND")
    rows = [c for c in db.classifications.values() if c["plan_year_id"] == plan_year_id]
    return list_response(rows, serialize.classification,
                         ("benefit_category", "network_tier"))
