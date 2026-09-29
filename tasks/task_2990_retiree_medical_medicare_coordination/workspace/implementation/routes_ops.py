"""Operator capabilities: the logical clock and the nightly administration
sweep (PRD 2.4, 3.9)."""

from flask import Blueprint

import calc
from auth import ROLE_BENEFITS_ADMIN, require_caller
from domain import (adjust_enrolled_count, apply_msp, freeze_account_for,
                   invoices_of_enrollment, terminate_coverage,
                   write_off_invoices)
from envelope import object_response
from store import db, iso, now, order_asc, set_clock, touch
from validate import read_body

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_caller((ROLE_BENEFITS_ADMIN,))
    body = read_body()
    to_iso8601 = body.instant("to_iso8601")
    current = set_clock(to_iso8601)
    return object_response({"current_utc": iso(current)})


@bp.post("/_ops/daily-run")
def daily_run():
    require_caller((ROLE_BENEFITS_ADMIN,))

    counters = {
        "processed_invoice_count": 0,
        "activated_enrollment_count": 0,
        "suspended_enrollment_count": 0,
        "lapsed_enrollment_count": 0,
        "applied_plan_change_count": 0,
        "recomputed_msp_count": 0,
    }

    _phase_activation(counters)
    _phase_past_due(counters)
    _phase_plan_changes(counters)
    _phase_msp_refresh(counters)

    return object_response(counters)


def _phase_activation(counters):
    clock = now()
    for enrollment in order_asc(list(db.enrollments.values())):
        if enrollment["coverage_status"] != "PENDING":
            continue
        if enrollment["coverage_effective_date"] > clock:
            continue
        enrollment["coverage_status"] = "ACTIVE"
        touch(enrollment)
        counters["activated_enrollment_count"] += 1


def _phase_past_due(counters):
    clock = now()
    due = [i for i in order_asc(list(db.invoices.values()))
           if i["status"] in ("ISSUED", "PARTIALLY_PAID")
           and i["past_due_at"] is not None
           and i["past_due_at"] <= clock]

    for invoice in due:
        counters["processed_invoice_count"] += 1

        # Hop one: the invoice itself ages.
        invoice["status"] = "PAST_DUE"
        touch(invoice)

        enrollment = db.enrollments.get(invoice["enrollment_id"])
        if enrollment is None:
            continue

        # Hop two: caused by hop one.
        enrollment["consecutive_unpaid_periods"] += 1
        if enrollment["delinquency_first_unpaid_period_start"] is None:
            enrollment["delinquency_first_unpaid_period_start"] = \
                invoice["billing_period_start"]
        if enrollment["billing_status"] in ("CURRENT", "REINSTATED"):
            enrollment["billing_status"] = "DELINQUENT"

        # Hop three: caused by hop two.
        if enrollment["coverage_status"] == "ACTIVE":
            enrollment["coverage_status"] = "SUSPENDED"
            counters["suspended_enrollment_count"] += 1

        # Hop four: only once three consecutive periods have gone unpaid.
        if enrollment["consecutive_unpaid_periods"] >= calc.LAPSE_THRESHOLD_PERIODS \
                and enrollment["billing_status"] != "LAPSED":
            _lapse(enrollment, counters)

        touch(enrollment)


def _lapse(enrollment, counters):
    clock = now()
    plan_year = db.plan_years.get(enrollment["plan_year_id"])
    window_days = plan_year["reinstatement_window_days"] if plan_year else 0

    enrollment["billing_status"] = "LAPSED"
    enrollment["lapse_date"] = clock
    enrollment["reinstatement_deadline"] = calc.plus_days(clock, window_days)
    terminate_coverage(enrollment, "PREMIUM_LAPSE")

    adjust_enrolled_count(enrollment["plan_option_id"], -1)
    write_off_invoices(enrollment["id"], ("PAST_DUE",))

    # Hop five, and hop six chained from it.
    freeze_account_for(enrollment["retiree_id"], enrollment["plan_year_id"])

    counters["lapsed_enrollment_count"] += 1


def _phase_plan_changes(counters):
    clock = now()
    for option in order_asc(list(db.plan_options.values())):
        if option["change_notice_issued_at"] is None:
            continue
        effective = option["pending_change_effective_date"]
        if effective is None or effective > clock:
            continue

        counters["applied_plan_change_count"] += 1

        if option["pending_change_type"] == "PREMIUM_INCREASE":
            if option["pending_new_monthly_premium_cents"] is not None:
                option["monthly_premium_cents"] = \
                    option["pending_new_monthly_premium_cents"]
        elif option["pending_change_type"] == "PLAN_TERMINATION":
            option["status"] = "RETIRED"
            covered = [e for e in order_asc(list(db.enrollments.values()))
                       if e["plan_option_id"] == option["id"]
                       and e["coverage_status"] in calc.ACTIVE_COVERAGE_STATUSES]
            for enrollment in covered:
                terminate_coverage(enrollment, "PLAN_TERMINATION")
                touch(enrollment)
            option["enrolled_count"] = 0

        option["pending_change_type"] = None
        option["pending_change_effective_date"] = None
        option["pending_new_monthly_premium_cents"] = None
        touch(option)


def _phase_msp_refresh(counters):
    for enrollment in order_asc(list(db.enrollments.values())):
        if enrollment["coverage_status"] not in calc.ACTIVE_COVERAGE_STATUSES:
            continue
        retiree = db.retirees.get(enrollment["retiree_id"])
        if retiree is None:
            continue
        payer_order, basis = calc.msp_determination(retiree, now())
        if (enrollment["payer_order"] == payer_order
                and enrollment["msp_basis_code"] == basis):
            continue
        enrollment["payer_order"] = payer_order
        enrollment["msp_basis_code"] = basis
        touch(enrollment)
        counters["recomputed_msp_count"] += 1
