"""911 fee assessment and voiding (PRD 3.9)."""
from flask import Blueprint

import lookup
import store
import util
import validate as v
from common import (auth_for, body_or_error, bump, enum_filter, guard_account_owner,
                    list_response, object_response, optional_body, pagination,
                    paginate, period_filter, sort_created_asc, str_filter)
from errors import ApiError
from services import derive, fees

bp = Blueprint("fees", __name__)

ASSESSMENT_STATUSES = ("ASSESSED", "VOIDED", "REMITTED")
ASSESSMENT_VARIANTS = ("PROVISIONAL", "FINAL")


@bp.route("/voip/fee-assessments", methods=["POST"])
def create_assessment():
    user_id, _role = auth_for(("BillingAdmin",))
    body = body_or_error()
    account_id = v.req_id(body, "account_id")
    jurisdiction_id = v.req_id(body, "jurisdiction_id")
    period_month = v.req_period(body, "period_month")

    account = lookup.account(account_id)
    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    lookup.require_active(account)

    existing = fees.assessments_for(account["id"], jurisdiction["id"], period_month)
    if any(a["status"] == "ASSESSED" for a in existing):
        raise ApiError("ERR_DUPLICATE_PROVISIONAL_ASSESSMENT",
                       "An ASSESSED assessment already stands for that period.")
    if any(a["status"] == "REMITTED" for a in existing):
        raise ApiError("ERR_ASSESSMENT_PERIOD_ALREADY_REMITTED",
                       "That period has already been remitted for this account.")

    year, month = util.parse_period(period_month)
    period_start, period_end, days_in_month = util.period_bounds(year, month)
    registrations = fees.eligible_registrations(
        account["id"], jurisdiction["id"], period_end, effective_cutoff=store.now())
    units = fees.build_units(registrations, jurisdiction["fee_type"])
    if not units:
        raise ApiError("ERR_NO_BILLABLE_UNITS",
                       "No billable unit is selected for that period.")
    breakdown = fees.provisional_breakdown(units, jurisdiction["monthly_fee_cents"],
                                           period_start, days_in_month)
    row = fees.new_assessment(account["id"], jurisdiction, period_month, "PROVISIONAL",
                              breakdown, user_id)
    derive.recompute_ledger(jurisdiction, [account["id"]])
    return object_response(row, 201)


@bp.route("/voip/fee-assessments/<assessment_id>/void", methods=["POST"])
def void_assessment(assessment_id):
    user_id, _role = auth_for(("BillingAdmin",))
    body = optional_body()
    v.opt_free_text(body, "void_note")
    row = lookup.assessment(assessment_id)
    if row["status"] != "ASSESSED":
        raise ApiError("ERR_ASSESSMENT_NOT_VOIDABLE",
                       "Only an ASSESSED assessment can be voided.")
    if user_id == row["assessed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                       "The assessing principal may not void the assessment.")
    row["status"] = "VOIDED"
    row["voided_by_user_id"] = user_id
    bump(row)
    derive.recompute_ledger(store.jurisdictions.get(row["jurisdiction_id"]),
                            [row["account_id"]])
    return object_response(row)


@bp.route("/voip/fee-assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    user_id, role = auth_for(("BillingAdmin", "PlatformAdmin", "AccountAdmin"))
    row = lookup.assessment(assessment_id)
    guard_account_owner(role, user_id, row["account_id"])
    return object_response(row)


@bp.route("/voip/fee-assessments", methods=["GET"])
def list_assessments():
    auth_for(("BillingAdmin", "PlatformAdmin"))
    limit, offset = pagination()
    account_id = str_filter("account_id")
    jurisdiction_id = str_filter("jurisdiction_id")
    period_month = period_filter("period_month")
    status = enum_filter("status", ASSESSMENT_STATUSES)
    variant = enum_filter("variant", ASSESSMENT_VARIANTS)
    rows = list(store.fee_assessments.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if period_month is not None:
        rows = [r for r in rows if r["period_month"] == period_month]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
