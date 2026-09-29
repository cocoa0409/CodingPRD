"""PlanYear endpoints (PRD 3.1) and the accounting liability valuation (3.9)."""

from flask import Blueprint, request

import calc
import errors
from auth import ALL_ROLES, ROLE_ACTUARY, ROLE_BENEFITS_ADMIN, require_caller
from domain import get_plan_year
from envelope import object_response, paginate
from errors import fail
from store import base_record, db, now, order_asc, touch
from validate import read_body, require_interval

bp = Blueprint("plan_years", __name__)

PLAN_YEAR_STATUSES = ("DRAFT", "OPEN", "CLOSED", "ARCHIVED")
PLAN_YEAR_SUCCESSOR = {"DRAFT": "OPEN", "OPEN": "CLOSED", "CLOSED": "ARCHIVED"}
LIABILITY_METHODS = ("PROJECTED_UNIT_CREDIT", "ATTRIBUTION_TO_FULL_ELIGIBILITY")

DEFAULT_PREMIUM_GRACE_PERIOD_DAYS = 31
DEFAULT_REINSTATEMENT_WINDOW_DAYS = 60
DEFAULT_NOTICE_LEAD_DAYS = 60


@bp.post("/retiree-benefits/plan-years")
def create_plan_year():
    require_caller((ROLE_BENEFITS_ADMIN,))
    body = read_body()

    year = body.integer("year", minimum=2024, maximum=2099)
    open_start = body.instant("open_enrollment_start")
    open_end = body.instant("open_enrollment_end")
    coverage_start = body.instant("coverage_start")
    credit_pre = body.cents("hra_credit_pre_medicare_cents")
    credit_medicare = body.cents("hra_credit_medicare_cents")
    carryover_cap_pct = body.number("carryover_cap_pct", minimum=0, maximum=1)
    discount_rate_bps = body.integer("discount_rate_bps", minimum=0, maximum=5000)
    assumed_subsidy = body.cents("assumed_annual_subsidy_cents")
    assumed_years = body.integer("assumed_payment_years", minimum=1)
    grace_days = body.integer("premium_grace_period_days", required=False,
                              minimum=0, default=DEFAULT_PREMIUM_GRACE_PERIOD_DAYS)
    reinstatement_days = body.integer("reinstatement_window_days", required=False,
                                      minimum=0,
                                      default=DEFAULT_REINSTATEMENT_WINDOW_DAYS)
    notice_days = body.integer("notice_lead_days", required=False, minimum=0,
                               default=DEFAULT_NOTICE_LEAD_DAYS)
    require_interval(open_start, open_end,
                     "open_enrollment_start", "open_enrollment_end")

    for existing in db.plan_years.values():
        if existing["year"] == year:
            fail(errors.ERR_DUPLICATE_PLAN_YEAR)

    record = base_record()
    record.update({
        "year": year,
        "status": "DRAFT",
        "open_enrollment_start": open_start,
        "open_enrollment_end": open_end,
        "coverage_start": coverage_start,
        "hra_credit_pre_medicare_cents": credit_pre,
        "hra_credit_medicare_cents": credit_medicare,
        "carryover_cap_pct": carryover_cap_pct,
        "premium_grace_period_days": grace_days,
        "reinstatement_window_days": reinstatement_days,
        "notice_lead_days": notice_days,
        "discount_rate_bps": discount_rate_bps,
        "assumed_annual_subsidy_cents": assumed_subsidy,
        "assumed_payment_years": assumed_years,
        "liability_method": None,
        "measured_retiree_count": 0,
        "epbo_total_cents": 0,
        "apbo_total_cents": 0,
        "service_cost_total_cents": 0,
        "liability_valued_at": None,
    })
    db.plan_years[record["id"]] = record
    return object_response(record, 201)


@bp.get("/retiree-benefits/plan-years/<plan_year_id>")
def read_plan_year(plan_year_id):
    require_caller(ALL_ROLES)
    return object_response(get_plan_year(plan_year_id))


@bp.get("/retiree-benefits/plan-years")
def list_plan_years():
    require_caller(ALL_ROLES)
    rows = list(db.plan_years.values())

    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    year = request.args.get("year")
    if year is not None:
        rows = [r for r in rows if str(r["year"]) == year.strip()]

    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/plan-years/<plan_year_id>/status")
def advance_plan_year(plan_year_id):
    require_caller((ROLE_BENEFITS_ADMIN,))
    plan_year = get_plan_year(plan_year_id)
    body = read_body()
    to_status = body.enum("to_status", PLAN_YEAR_STATUSES)

    if PLAN_YEAR_SUCCESSOR.get(plan_year["status"]) != to_status:
        fail(errors.ERR_INVALID_PLAN_YEAR_TRANSITION)

    if to_status == "ARCHIVED":
        for account in db.hra_accounts.values():
            if account["plan_year_id"] == plan_year["id"] and account["status"] == "OPEN":
                fail(errors.ERR_INVALID_PLAN_YEAR_TRANSITION,
                     "A reimbursement account of this plan year is still OPEN.")

    plan_year["status"] = to_status

    if to_status == "CLOSED":
        _close_catalogue(plan_year)

    touch(plan_year)
    return object_response(plan_year)


def _close_catalogue(plan_year):
    """Hop one closes the catalogue; hop two is caused by hop one."""
    options = order_asc([o for o in db.plan_options.values()
                         if o["plan_year_id"] == plan_year["id"]
                         and o["status"] == "ACTIVE"])
    for option in options:
        option["status"] = "CLOSED_TO_NEW"
        touch(option)

        events = order_asc([e for e in db.election_events.values()
                            if e["requested_plan_option_id"] == option["id"]
                            and e["status"] in ("SUBMITTED", "UNDER_REVIEW")])
        for event in events:
            event["status"] = "DENIED"
            event["denial_reason_code"] = "PLAN_CLOSED"
            touch(event)


@bp.post("/retiree-benefits/plan-years/<plan_year_id>/liability-valuation")
def run_liability_valuation(plan_year_id):
    require_caller((ROLE_ACTUARY,))
    plan_year = get_plan_year(plan_year_id)
    body = read_body()
    method = body.enum("method", LIABILITY_METHODS)

    cohort_ids = set()
    for determination in db.determinations.values():
        if (determination["plan_year_id"] == plan_year["id"]
                and determination["status"] == "CERTIFIED"
                and determination["outcome"] == "ELIGIBLE"):
            cohort_ids.add(determination["retiree_id"])

    cohort = [r for r in order_asc(list(db.retirees.values()))
              if r["id"] in cohort_ids]

    epbo_total = 0
    apbo_total = 0
    service_cost_total = 0
    for retiree in cohort:
        epbo, apbo, service_cost = calc.per_retiree_valuation(
            plan_year, retiree, method)
        epbo_total += epbo
        apbo_total += apbo
        service_cost_total += service_cost

    plan_year["liability_method"] = method
    plan_year["measured_retiree_count"] = len(cohort)
    plan_year["epbo_total_cents"] = epbo_total
    plan_year["apbo_total_cents"] = apbo_total
    plan_year["service_cost_total_cents"] = service_cost_total
    plan_year["liability_valued_at"] = now()
    touch(plan_year)
    return object_response(plan_year)
