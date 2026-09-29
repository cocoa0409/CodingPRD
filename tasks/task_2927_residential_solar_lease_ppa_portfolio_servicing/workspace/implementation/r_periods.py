"""Metered months: recording, reconciliation and reopening (PRD §3.3)."""
from flask import Blueprint

import calc
from calc import LATE_FEE_PCT
from core import (
    ApiError, D, clock, fmt_date, parse_date, rhu_int, sorted_rows, stamp_new,
    store, touch,
)
from guards import (
    homeowner_agreement_ids, homeowner_scope, lookup, require_child_write_allowed,
    require_not_decommissioned,
)
from serialize import period_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("period_routes", __name__)

PERIOD_STATUSES = ("RECORDED", "RECONCILED", "CREDIT_ISSUED")
RECONCILABLE_LIFECYCLE = ("ACTIVE", "TRANSFER_PENDING", "END_OF_TERM_PENDING")

PERIOD_SPECS = [
    {"name": "agreement_id", "kind": "id", "required": True},
    {"name": "period_year", "kind": "int", "required": True, "min": 2020, "max": 2099},
    {"name": "period_month", "kind": "int", "required": True, "min": 1, "max": 12},
    {"name": "metered_kwh", "kind": "int", "required": True, "min": 0},
    {"name": "auto_reconcile", "kind": "bool", "default": False},
    {"name": "auto_issue_credit", "kind": "bool", "default": False},
]


def month_elapsed(period_year, period_month):
    from core import month_start_instant, next_month
    ny, nm = next_month(period_year, period_month)
    return clock.now() >= month_start_instant(ny, nm)


def reconcile(period, ag, issue_credit):
    """The six-step waterfall in its pinned order (PRD §3.3)."""
    tariff = store.tariffs.get(ag["tariff_id"])
    cy = period["contract_year"]

    gross_expected, excused_days, adjusted = calc.monthly_expected(
        ag, period["period_year"], period["period_month"])
    period["gross_expected_kwh"] = gross_expected
    period["excused_days"] = excused_days
    period["adjusted_expected_kwh"] = adjusted

    floor, shortfall, credit_rate, credit_cents = calc.shortfall_credit(
        ag, tariff, adjusted, period["metered_kwh"], cy)
    period["guarantee_floor_kwh"] = floor
    period["shortfall_kwh"] = shortfall
    period["credit_rate_millicents"] = credit_rate
    period["credit_cents"] = credit_cents

    period["escalated_rate_millicents"] = calc.escalated_rate_millicents(ag, cy)
    period["escalated_monthly_rent_cents"] = calc.escalated_monthly_rent_cents(ag, cy)

    # step 1
    if ag["product_type"] == "PPA":
        gross_due = rhu_int(D(period["escalated_rate_millicents"])
                            * D(period["metered_kwh"]) / D(1000))
    else:
        gross_due = period["escalated_monthly_rent_cents"]
    # step 2 — balance BEFORE this month issues any credit of its own
    available_credit = ag["credit_balance_cents"]
    # step 3
    applied = min(gross_due, available_credit)
    # step 4
    net_due = gross_due - applied
    # step 5 — a percentage of the NET amount, only when past due
    if clock.today() > parse_date(period["due_date"]):
        late_fee = rhu_int(D(net_due) * LATE_FEE_PCT)
    else:
        late_fee = 0
    # step 6
    period["gross_due_cents"] = gross_due
    period["credit_applied_cents"] = applied
    period["net_due_cents"] = net_due
    period["late_fee_cents"] = late_fee
    period["total_invoiced_cents"] = net_due + late_fee

    ag["credit_applied_cents"] += applied
    ag["credit_balance_cents"] -= applied

    if issue_credit and credit_cents > 0:
        period["status"] = "CREDIT_ISSUED"
        ag["credit_earned_cents"] += credit_cents
        ag["credit_balance_cents"] += credit_cents
    else:
        period["status"] = "RECONCILED"

    touch(period)
    touch(ag)


@bp.post("/servicing/production-periods")
def create_period():
    authenticate(("PortfolioAdmin", "ServicingAgent"))
    body = validate_body(PERIOD_SPECS)
    ag = lookup("agreements", body["agreement_id"])
    require_child_write_allowed(ag)
    require_not_decommissioned(ag)
    for existing in store.periods.values():
        if (existing["agreement_id"] == ag["id"]
                and existing["period_year"] == body["period_year"]
                and existing["period_month"] == body["period_month"]):
            raise ApiError("ERR_DUPLICATE_PERIOD",
                           "A metered month already exists for that agreement and "
                           "calendar month.")

    start = parse_date(ag["contract_start_date"])
    contract_year = calc.contract_year_raw(start, body["period_year"],
                                           body["period_month"])
    gross_expected, excused_days, adjusted = calc.monthly_expected(
        ag, body["period_year"], body["period_month"])
    period = {
        "agreement_id": ag["id"],
        "period_year": body["period_year"],
        "period_month": body["period_month"],
        "metered_kwh": body["metered_kwh"],
        "contract_year": contract_year,
        "due_date": fmt_date(calc.period_due_date(body["period_year"],
                                                 body["period_month"])),
        "gross_expected_kwh": gross_expected,
        "excused_days": excused_days,
        "adjusted_expected_kwh": adjusted,
        "guarantee_floor_kwh": 0,
        "shortfall_kwh": 0,
        "escalated_rate_millicents": 0,
        "escalated_monthly_rent_cents": 0,
        "credit_rate_millicents": 0,
        "credit_cents": 0,
        "gross_due_cents": 0,
        "credit_applied_cents": 0,
        "net_due_cents": 0,
        "late_fee_cents": 0,
        "total_invoiced_cents": 0,
        "status": "RECORDED",
    }
    stamp_new(period)
    store.periods[period["id"]] = period

    if body["auto_reconcile"]:
        if not month_elapsed(period["period_year"], period["period_month"]):
            raise ApiError("ERR_PERIOD_NOT_ELAPSED",
                           "The period month has not fully elapsed.")
        reconcile(period, ag, body["auto_issue_credit"])
    return created(period_view(period))


@bp.get("/servicing/production-periods/<period_id>")
def get_period(period_id):
    user_id, role = authenticate(("PortfolioAdmin", "ServicingAgent", "Homeowner"))
    period = lookup("periods", period_id)
    homeowner_scope(role, user_id, store.agreements.get(period["agreement_id"]))
    return ok(period_view(period))


@bp.get("/servicing/production-periods")
def list_periods():
    user_id, role = authenticate(("PortfolioAdmin", "ServicingAgent", "Homeowner"))
    limit, offset = pagination()
    flt = filters([
        ("agreement_id", "str", None),
        ("contract_year", "int", None),
        ("period_year", "int", None),
        ("period_month", "int", None),
        ("status", "enum", PERIOD_STATUSES),
    ])
    rows = list(store.periods.values())
    if role == "Homeowner":
        if "agreement_id" in flt:
            homeowner_scope(role, user_id, store.agreements.get(flt["agreement_id"]))
        owned = homeowner_agreement_ids(user_id)
        rows = [r for r in rows if r["agreement_id"] in owned]
    rows = apply_filters(rows, flt)
    if "agreement_id" in flt:
        rows = sorted(rows, key=lambda r: (r["period_year"], r["period_month"], r["_seq"]))
    else:
        rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([period_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/production-periods/<period_id>/reconcile")
def reconcile_period(period_id):
    authenticate(("ServicingAgent",))
    body = validate_body([{"name": "issue_credit", "kind": "bool", "default": False}])
    period = lookup("periods", period_id)
    ag = store.agreements[period["agreement_id"]]
    if period["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a RECORDED month may be reconciled.")
    require_child_write_allowed(ag)
    require_not_decommissioned(ag)
    if ag["lifecycle_state"] not in RECONCILABLE_LIFECYCLE:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The agreement's lifecycle_state is %s."
                       % ag["lifecycle_state"])
    if not month_elapsed(period["period_year"], period["period_month"]):
        raise ApiError("ERR_PERIOD_NOT_ELAPSED",
                       "The period month has not fully elapsed.")
    reconcile(period, ag, body["issue_credit"])
    return ok(period_view(period))


@bp.post("/servicing/production-periods/<period_id>/reopen")
def reopen_period(period_id):
    authenticate(("PortfolioAdmin",))
    validate_body([])
    period = lookup("periods", period_id)
    ag = store.agreements[period["agreement_id"]]
    for tu in store.true_ups.values():
        if tu["status"] == "POSTED" and period["id"] in (tu.get("covered_period_ids") or []):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A POSTED guarantee true-up covers this month.")
    if period["status"] not in ("RECONCILED", "CREDIT_ISSUED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a settled month may be reopened.")

    applied = period["credit_applied_cents"]
    ag["credit_applied_cents"] -= applied
    ag["credit_balance_cents"] += applied
    if period["status"] == "CREDIT_ISSUED":
        ag["credit_earned_cents"] -= period["credit_cents"]
        ag["credit_balance_cents"] -= period["credit_cents"]
        period["credit_cents"] = 0
    period["gross_due_cents"] = 0
    period["credit_applied_cents"] = 0
    period["net_due_cents"] = 0
    period["late_fee_cents"] = 0
    period["total_invoiced_cents"] = 0
    period["status"] = "RECORDED"
    touch(period)
    touch(ag)
    return ok(period_view(period))
