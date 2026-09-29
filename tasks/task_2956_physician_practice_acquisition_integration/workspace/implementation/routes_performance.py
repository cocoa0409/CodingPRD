"""POST /performance-reports and the compensation true-up (PRD section 3.11)."""

import calc
import clock
import enums
import services
import store
import validate
from errors import ApiError
from store import set_field

REPORTABLE_PLAN_STATES = ("EXECUTED", "COMPLIANCE_HOLD")


def create_report():
    validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    physician_id = validate.req_id(body, "physician_id")
    plan_id = validate.req_id(body, "applied_comp_plan_id")
    period_start_on = validate.req_date(body, "period_start_on")
    period_end_on = validate.req_date(body, "period_end_on")
    actual_wrvu = validate.req_int(body, "actual_wrvu", minimum=0)
    actual_collections = validate.req_int(body, "actual_collections_cents",
                                          minimum=0)

    # Rank 5: every foreign key resolves.
    acquisition = store.require("acquisitions", acquisition_id)
    physician = store.require("physicians", physician_id)
    plan = store.require("compensation_plans", plan_id)

    # Rank 6: the three references agree with one another.
    if physician["acquisition_id"] != acquisition_id:
        raise services.scope_mismatch(
            "Physician '%s' does not belong to acquisition '%s'."
            % (physician_id, acquisition_id))
    if plan["acquisition_id"] != acquisition_id:
        raise services.scope_mismatch(
            "CompensationPlan '%s' does not belong to acquisition '%s'."
            % (plan_id, acquisition_id))
    if plan["physician_id"] != physician_id:
        raise services.scope_mismatch(
            "CompensationPlan '%s' does not belong to physician '%s'."
            % (plan_id, physician_id))

    # Rank 11: one report per physician per period.
    start_str = clock.format_date(period_start_on)
    for peer in store.where("performance_reports", physician_id=physician_id,
                            period_start_on=start_str):
        raise ApiError("ERR_DUPLICATE_REPORT_PERIOD",
                       "A report already exists for this physician and period.")

    # Rank 15.
    services.check_freeze(acquisition)

    # Rank 29: one whole calendar month, at or after the close date.
    _check_period(acquisition, period_start_on, period_end_on)

    # Rank 39, then rank 44.
    if plan["status"] not in REPORTABLE_PLAN_STATES:
        raise ApiError("ERR_NO_EXECUTED_COMP_PLAN",
                       "CompensationPlan '%s' is in %s." % (plan_id, plan["status"]))
    if acquisition["deal_status"] != "CLOSED":
        raise ApiError("ERR_ACQUISITION_NOT_CLOSED",
                       "The acquisition is in %s." % acquisition["deal_status"])

    row = {
        "acquisition_id": acquisition_id,
        "physician_id": physician_id,
        "applied_comp_plan_id": plan_id,
        "period_start_on": start_str,
        "period_end_on": clock.format_date(period_end_on),
        "actual_wrvu": actual_wrvu,
        "actual_collections_cents": actual_collections,
        "true_up_applied_cents": 0,
        "benchmark_percentile_after": None,
    }
    store.insert("performance_reports", row, versioned=False)

    _fold_into_plan(acquisition, physician, plan, row)
    store.commit()
    import envelope
    import serialize
    return envelope.object_response(serialize.dump(row), 201)


def _check_period(acquisition, period_start_on, period_end_on):
    if period_start_on.day != 1:
        raise ApiError("ERR_INVALID_REPORT_PERIOD",
                       "period_start_on must be the first day of a month.")
    if period_end_on != calc.last_day_of_month(period_start_on):
        raise ApiError("ERR_INVALID_REPORT_PERIOD",
                       "period_end_on must be the last day of the same month.")
    closed_at = acquisition["closed_at"]
    if closed_at is not None:
        closed_on = clock.parse_instant(closed_at).date()
        if period_start_on < closed_on:
            raise ApiError("ERR_INVALID_REPORT_PERIOD",
                           "period_start_on precedes the close date %s."
                           % clock.format_date(closed_on))


def _fold_into_plan(acquisition, physician, plan, report):
    """Aggregate every report filed against the plan, then re-run the true-up."""
    reports = store.where("performance_reports",
                          applied_comp_plan_id=plan["id"])
    actual_ytd_wrvu = sum(r["actual_wrvu"] for r in reports)
    months_elapsed = len(reports)

    outcome = calc.comp_true_up(plan, actual_ytd_wrvu, months_elapsed)
    basis = plan["benchmark_basis"]
    compared = (outcome["annualized_comp_per_wrvu_cents"]
                if basis == "COMP_PER_WRVU"
                else outcome["annualized_total_cash_comp_cents"])
    percentile = calc.compensation_benchmark_percentile(
        compared, basis, physician["specialty"])

    set_field(plan, "actual_ytd_wrvu", actual_ytd_wrvu)
    set_field(plan, "months_elapsed", months_elapsed)
    set_field(plan, "comp_true_up_cents", outcome["comp_true_up_cents"])
    set_field(plan, "benchmark_percentile", percentile)

    report["true_up_applied_cents"] = plan["comp_true_up_cents"]
    report["benchmark_percentile_after"] = plan["benchmark_percentile"]

    # The safe-harbour trip.
    if (percentile > calc.FMV_SAFE_HARBOR_PERCENTILE
            and not plan["fmv_justification_on_file"]
            and plan["status"] == "EXECUTED"):
        set_field(plan, "status", "COMPLIANCE_HOLD")
        services.recompute_employment_status(physician)
        if acquisition["compliance_clearance"] == "CLEARED":
            services.flag_clearance(acquisition)


def register(app):
    app.add_url_rule("/performance-reports", "create_report", create_report,
                     methods=["POST"])
