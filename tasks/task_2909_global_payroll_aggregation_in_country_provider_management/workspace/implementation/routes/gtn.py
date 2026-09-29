"""Gross-to-net results, variance analysis and review."""
from flask import Blueprint, g

import calc
import serial
import services
import store
import validate as v
from auth import require
from common import (
    ALL_ROLES,
    GTN_STATUSES,
    PAYROLL_CONTROLLER,
    PROVIDER_USER,
    ApiError,
)
from response import created, object_response, page_response
from store import new_row, touch

bp = Blueprint("gtn", __name__)

SUPERSEDABLE = ("SUBMITTED", "CLEARED", "ESCALATED", "RETURNED")


def _baseline_run(cycle):
    prior_id = cycle["prior_cycle_id"]
    if prior_id is None or prior_id not in store.cycles:
        return None
    return store.approved_run_of_cycle(prior_id)


def _apply_variance(run, cycle, engagement, country):
    outcome = calc.compute_variance(run, _baseline_run(cycle), country)
    run.update(outcome)
    if outcome["variance_material"]:
        run["status"] = "ESCALATED"
        variance = outcome["variance_pct"]
        if variance is not None and abs(variance) >= country["materiality_pct"] * 2:
            services.raise_incident(
                engagement["id"], cycle["id"], "VARIANCE_ESCALATION", "SEV3"
            )
    else:
        run["status"] = "CLEARED"


@bp.post("/payroll/gross-to-net-runs")
@require(PROVIDER_USER)
def create_run():
    body = v.json_body()
    cycle_id = v.req_id(body, "cycle_id")
    input_file_id = v.req_id(body, "input_file_id")
    gross = v.req_int(body, "gross_minor", 1)
    net = v.req_int(body, "net_minor", 1)
    employer_cost = v.req_int(body, "employer_cost_minor", 0)
    provider_fee = v.req_int(body, "provider_fee_minor", 0)
    employee_count = v.req_int(body, "employee_count", 1)
    expected = v.req_int(body, "expected_cycle_version")

    cycle = store.get_cycle(cycle_id)
    extract = store.get_input_file(input_file_id)
    engagement = store.engagement_of_cycle(cycle)
    provider = store.provider_of_engagement(engagement)

    if g.user_id != engagement["provider_id"]:
        raise ApiError(
            "ERR_PROVIDER_SCOPE_VIOLATION",
            "A provider may only submit results for its own engagement.",
        )
    if cycle["status"] != "INPUTS_LOCKED":
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE",
            "Results may only be submitted for a cycle in INPUTS_LOCKED.",
        )
    if provider["status"] == "SUSPENDED":
        raise ApiError(
            "ERR_PROVIDER_SUSPENDED",
            "A suspended provider may not produce new payroll results.",
        )
    if expected != cycle["version"]:
        raise ApiError(
            "ERR_STALE_CYCLE_VERSION",
            "The expected cycle version does not match the stored version.",
        )
    if extract["cycle_id"] != cycle["id"] or extract["status"] != "VALIDATED":
        raise ApiError(
            "ERR_INPUT_FILE_CYCLE_MISMATCH",
            "The backing extract must be a VALIDATED extract of this cycle.",
        )
    if abs(gross - extract["gross_declared_minor"]) * 10 > extract["gross_declared_minor"]:
        raise ApiError(
            "ERR_GROSS_TOTAL_OUT_OF_TOLERANCE",
            "The reported gross is outside one tenth of the declared gross.",
        )
    if net > gross:
        raise ApiError(
            "ERR_GTN_TOTALS_INCONSISTENT",
            "net_minor may not exceed gross_minor.",
        )

    for earlier in store.runs_of_cycle(cycle["id"]):
        if earlier["status"] in SUPERSEDABLE:
            earlier["status"] = "SUPERSEDED"
            touch(earlier)

    row = new_row(
        {
            "cycle_id": cycle["id"],
            "input_file_id": extract["id"],
            "gross_minor": gross,
            "net_minor": net,
            "employer_cost_minor": employer_cost,
            "provider_fee_minor": provider_fee,
            "employee_count": employee_count,
            "status": "SUBMITTED",
            "variance_pct": None,
            "variance_basis": None,
            "headcount_drift_pct": None,
            "variance_material": False,
            "variance_justification": None,
            "return_reason": None,
        }
    )
    store.gtn_runs[row["id"]] = row
    touch(cycle)

    country = store.country_of_engagement(engagement)
    _apply_variance(row, cycle, engagement, country)
    return created(serial.gtn_run(row))


@bp.get("/payroll/gross-to-net-runs/<ident>")
@require(*ALL_ROLES)
def read_run(ident):
    return object_response(serial.gtn_run(store.get_run(ident)))


@bp.get("/payroll/gross-to-net-runs")
@require(*ALL_ROLES)
def list_runs():
    limit, offset = v.pagination()
    status = v.query_enum("status", GTN_STATUSES)
    cycle_id = v.query_value("cycle_id")
    input_file_id = v.query_value("input_file_id")

    rows = list(store.gtn_runs.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if input_file_id is not None:
        rows = [r for r in rows if r["input_file_id"] == input_file_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_response(store.ordered(rows), serial.gtn_run, limit, offset)


@bp.post("/payroll/gross-to-net-runs/<ident>/review")
@require(PAYROLL_CONTROLLER)
def review_run(ident):
    body = v.json_body()
    decision = v.req_enum(body, "decision", ["APPROVE", "RETURN"])
    justification = v.opt_str(body, "variance_justification", 1, None)
    if decision == "RETURN":
        return_reason = v.req_str(body, "return_reason", 10, None)
    else:
        return_reason = v.opt_str(body, "return_reason", 1, None)

    run = store.get_run(ident)
    cycle = store.get_cycle(run["cycle_id"])
    engagement = store.engagement_of_cycle(cycle)

    if cycle["input_submitter_user_id"] is not None and (
        g.user_id == cycle["input_submitter_user_id"]
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The principal that supplied the inputs may not review the results.",
        )
    if run["status"] not in ("CLEARED", "ESCALATED"):
        raise ApiError(
            "ERR_GTN_RUN_INVALID_STATE",
            "Only a CLEARED or ESCALATED run can be reviewed.",
        )
    if decision == "APPROVE" and run["status"] == "ESCALATED":
        if justification is None or len(justification) < 10:
            raise ApiError(
                "ERR_VARIANCE_JUSTIFICATION_REQUIRED",
                "Approving an escalated run requires a variance justification of at least 10 characters.",
            )

    if decision == "APPROVE":
        if justification is not None:
            run["variance_justification"] = justification
        run["status"] = "APPROVED"
        touch(run)
        cycle["status"] = "RESULTS_APPROVED"
        cycle["gross_total_minor"] = run["gross_minor"]
        touch(cycle)
        services.mint_system_evidence(cycle["id"], "CTRL_VARIANCE_REVIEW")
    else:
        run["return_reason"] = return_reason
        run["status"] = "RETURNED"
        touch(run)
        services.raise_incident(
            engagement["id"], cycle["id"], "LATE_GTN_DELIVERY", "SEV2"
        )
    return object_response(serial.gtn_run(run))


@bp.post("/payroll/gross-to-net-runs/<ident>/resubmit")
@require(PROVIDER_USER)
def resubmit_run(ident):
    body = v.json_body()
    gross = v.req_int(body, "gross_minor", 1)
    net = v.req_int(body, "net_minor", 1)
    employer_cost = v.req_int(body, "employer_cost_minor", 0)
    provider_fee = v.req_int(body, "provider_fee_minor", 0)
    employee_count = v.req_int(body, "employee_count", 1)
    expected = v.req_int(body, "expected_cycle_version")

    run = store.get_run(ident)
    cycle = store.get_cycle(run["cycle_id"])
    engagement = store.engagement_of_cycle(cycle)

    if g.user_id != engagement["provider_id"]:
        raise ApiError(
            "ERR_PROVIDER_SCOPE_VIOLATION",
            "A provider may only resubmit results for its own engagement.",
        )
    if run["status"] != "RETURNED":
        raise ApiError(
            "ERR_GTN_RUN_INVALID_STATE",
            "Only a RETURNED run can be resubmitted.",
        )
    if cycle["status"] != "INPUTS_LOCKED":
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE",
            "The owning cycle must still be in INPUTS_LOCKED.",
        )
    if expected != cycle["version"]:
        raise ApiError(
            "ERR_STALE_CYCLE_VERSION",
            "The expected cycle version does not match the stored version.",
        )

    run["gross_minor"] = gross
    run["net_minor"] = net
    run["employer_cost_minor"] = employer_cost
    run["provider_fee_minor"] = provider_fee
    run["employee_count"] = employee_count
    run["status"] = "SUBMITTED"
    run["return_reason"] = None
    touch(cycle)

    country = store.country_of_engagement(engagement)
    _apply_variance(run, cycle, engagement, country)
    touch(run)
    return object_response(serial.gtn_run(run))
