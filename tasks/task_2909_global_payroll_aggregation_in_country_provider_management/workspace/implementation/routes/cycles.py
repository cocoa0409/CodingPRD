"""The payroll calendar: cycles, cutoffs, holds, closure and cancellation."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import serial
import services
import store
import validate as v
from auth import require
from common import (
    ALL_ROLES,
    CONTROL_REFS,
    CYCLE_STATUSES,
    GLOBAL_PAYROLL_OPS,
    INPUT_FILE_STATUSES,
    PAYROLL_CONTROLLER,
    ApiError,
    date_str,
    now,
    parse_date,
)
from response import object_response, created, page_response
from store import new_row, touch

bp = Blueprint("cycles", __name__)

LIVE_ENGAGEMENT_STATUSES = (
    "ACTIVE",
    "REMEDIATION_REQUIRED",
    "TRANSITION_PLANNED",
    "TRANSITION_IN_PROGRESS",
)
MANDATORY_CLOSURE_CONTROLS = (
    "CTRL_INPUT_INTEGRITY",
    "CTRL_VARIANCE_REVIEW",
    "CTRL_FUNDING_DUAL_AUTH",
    "CTRL_FILING_CONFIRMATION",
)


@bp.post("/payroll/cycles")
@require(GLOBAL_PAYROLL_OPS)
def create_cycle():
    body = v.json_body()
    engagement_id = v.req_id(body, "engagement_id")
    label = v.req_str(body, "period_label", 1, 20)
    period_start = v.req_date(body, "period_start_date")
    period_end = v.req_date(body, "period_end_date")
    pay_date = v.req_date(body, "pay_date")
    lead_days = v.req_int(body, "cutoff_lead_working_days", 1, 15)
    prior_id = v.opt_id(body, "prior_cycle_id")

    engagement = store.get_engagement(engagement_id)
    prior = store.get_cycle(prior_id) if prior_id is not None else None

    if engagement["status"] not in LIVE_ENGAGEMENT_STATUSES:
        raise ApiError(
            "ERR_ENGAGEMENT_NOT_ACTIVE",
            "The engagement is not in a live state.",
        )
    if pay_date < period_start or pay_date > period_end + timedelta(days=30):
        raise ApiError(
            "ERR_PAY_DATE_OUT_OF_RANGE",
            "pay_date must fall between period_start_date and period_end_date plus 30 days.",
        )
    for other in store.cycles_of_engagement(engagement_id):
        if other["status"] == "CANCELLED":
            continue
        other_start = parse_date(other["period_start_date"])
        other_end = parse_date(other["period_end_date"])
        if period_start < other_end and other_start < period_end:
            raise ApiError(
                "ERR_PAY_PERIOD_OVERLAP",
                "The period overlaps another cycle of the same engagement.",
            )
    if prior is not None:
        if prior["engagement_id"] != engagement_id or parse_date(
            prior["period_end_date"]
        ) > period_start:
            raise ApiError(
                "ERR_PRIOR_CYCLE_ENGAGEMENT_MISMATCH",
                "prior_cycle_id must name a chronologically earlier cycle of the same engagement.",
            )
    days = calc.period_days(period_start, period_end)
    if not calc.frequency_ok(engagement["pay_frequency"], days):
        raise ApiError(
            "ERR_PERIOD_FREQUENCY_MISMATCH",
            "The period length does not match the engagement's pay frequency.",
        )
    for other in store.cycles_of_engagement(engagement_id):
        if other["period_label"] == label:
            raise ApiError(
                "ERR_DUPLICATE_PERIOD_LABEL",
                "This period_label is already used by another cycle of the engagement.",
            )

    country = store.country_of_engagement(engagement)
    cutoff = calc.resolve_input_cutoff(pay_date, lead_days, country["local_holidays"])

    row = new_row(
        {
            "engagement_id": engagement_id,
            "prior_cycle_id": prior_id,
            "period_label": label,
            "period_start_date": date_str(period_start),
            "period_end_date": date_str(period_end),
            "pay_date": date_str(pay_date),
            "cutoff_lead_working_days": lead_days,
            "input_cutoff_at": cutoff,
            "status": "DRAFT",
            "hold_reason": None,
            "gross_total_minor": 0,
            "funded_total_minor": 0,
            "input_submitter_user_id": None,
            "filings_confirmed_count": 0,
        }
    )
    store.cycles[row["id"]] = row
    return created(serial.cycle(row))


@bp.get("/payroll/cycles/<ident>")
@require(*ALL_ROLES)
def read_cycle(ident):
    return object_response(serial.cycle(store.get_cycle(ident)))


@bp.get("/payroll/cycles")
@require(*ALL_ROLES)
def list_cycles():
    limit, offset = v.pagination()
    status = v.query_enum("status", CYCLE_STATUSES)
    engagement_id = v.query_value("engagement_id")
    prior_id = v.query_value("prior_cycle_id")

    rows = list(store.cycles.values())
    if engagement_id is not None:
        rows = [r for r in rows if r["engagement_id"] == engagement_id]
    if prior_id is not None:
        rows = [r for r in rows if r["prior_cycle_id"] == prior_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_response(store.ordered(rows), serial.cycle, limit, offset)


# ---------------------------------------------------------------------------
# Lock inputs
# ---------------------------------------------------------------------------
@bp.post("/payroll/cycles/<ident>/lock-inputs")
@require(GLOBAL_PAYROLL_OPS)
def lock_inputs(ident):
    cycle = store.get_cycle(ident)
    engagement = store.engagement_of_cycle(cycle)
    if cycle["status"] != "DRAFT":
        raise ApiError("ERR_CYCLE_INVALID_STATE", "Only a DRAFT cycle can lock its inputs.")
    if engagement["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "The owning engagement is not ACTIVE.")
    files = store.input_files_of_cycle(cycle["id"])
    validated = [f for f in files if f["status"] == "VALIDATED"]
    if not validated:
        raise ApiError("ERR_NO_VALIDATED_INPUT", "The cycle has no validated HR extract.")

    country = store.country_of_engagement(engagement)
    minted = 0
    for filing_type in country["required_filing_types"]:
        row = new_row(
            {
                "cycle_id": cycle["id"],
                "filing_type": filing_type,
                "responsibility": engagement["filing_responsibility"],
                "due_at": calc.statutory_due_at(
                    parse_date(cycle["pay_date"]), country["statutory_filing_deadline_days"]
                ),
                "status": "PENDING",
                "filed_at": None,
                "submission_ref": None,
                "confirmation_ref": None,
                "late_days": 0,
                "penalty_status": "NONE",
                "base_penalty_minor": 0,
                "surcharge_minor": 0,
                "total_penalty_minor": 0,
                "provider_share_minor": 0,
                "client_share_minor": 0,
                "penalty_owner": "NONE",
                "dispute_round": 0,
                "dispute_reason": None,
            }
        )
        store.filings[row["id"]] = row
        minted += 1
    if minted:
        country["open_filing_obligation_count"] += minted
        touch(country)
    for extract in files:
        if extract["status"] == "RECEIVED":
            extract["status"] = "SUPERSEDED"
            touch(extract)

    cycle["status"] = "INPUTS_LOCKED"
    touch(cycle)
    return object_response(serial.cycle(cycle))


# ---------------------------------------------------------------------------
# Release hold
# ---------------------------------------------------------------------------
@bp.post("/payroll/cycles/<ident>/release-hold")
@require(GLOBAL_PAYROLL_OPS, PAYROLL_CONTROLLER)
def release_hold(ident):
    cycle = store.get_cycle(ident)
    if cycle["status"] != "ON_HOLD":
        raise ApiError("ERR_CYCLE_INVALID_STATE", "Only an ON_HOLD cycle can be released.")
    engagement = store.engagement_of_cycle(cycle)
    provider = store.provider_of_engagement(engagement)
    if provider["status"] != "ACTIVE" or engagement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_HOLD_CAUSE_ACTIVE",
            "The provider and the engagement must both be ACTIVE before the hold is released.",
        )
    cycle["status"] = "DRAFT"
    cycle["hold_reason"] = None
    touch(cycle)
    return object_response(serial.cycle(cycle))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/payroll/cycles/<ident>/cancel")
@require(GLOBAL_PAYROLL_OPS)
def cancel_cycle(ident):
    body = v.json_body()
    v.req_str(body, "cancel_reason", 1, None)

    cycle = store.get_cycle(ident)
    if cycle["status"] not in ("DRAFT", "ON_HOLD", "INPUTS_LOCKED"):
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE",
            "The cycle has progressed beyond the point where it can be cancelled.",
        )
    for instruction in store.funding_of_cycle(cycle["id"]):
        if instruction["status"] == "RELEASED":
            raise ApiError(
                "ERR_CYCLE_INVALID_STATE",
                "A released funding instruction prevents cancellation.",
            )
    for filing in store.filings_of_cycle(cycle["id"]):
        if filing["status"] in ("FILED", "FILED_LATE", "CONFIRMED"):
            raise ApiError(
                "ERR_CYCLE_INVALID_STATE",
                "A lodged statutory filing prevents cancellation.",
            )

    cycle["status"] = "CANCELLED"
    cycle["hold_reason"] = None
    touch(cycle)

    voided = 0
    for filing in store.filings_of_cycle(cycle["id"]):
        if filing["status"] in ("PENDING", "LATE"):
            filing["status"] = "VOIDED"
            touch(filing)
            voided += 1
    if voided:
        country = store.country_of_engagement(store.engagement_of_cycle(cycle))
        country["open_filing_obligation_count"] -= voided
        if country["open_filing_obligation_count"] < 0:
            country["open_filing_obligation_count"] = 0
        touch(country)
    for instruction in store.funding_of_cycle(cycle["id"]):
        if instruction["status"] in ("DRAFT", "APPROVED"):
            instruction["status"] = "VOIDED"
            touch(instruction)
    for run in store.runs_of_cycle(cycle["id"]):
        if run["status"] in ("SUBMITTED", "CLEARED", "ESCALATED", "RETURNED"):
            run["status"] = "SUPERSEDED"
            touch(run)
    return object_response(serial.cycle(cycle))


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------
@bp.post("/payroll/cycles/<ident>/close")
@require(PAYROLL_CONTROLLER)
def close_cycle(ident):
    cycle = store.get_cycle(ident)
    if cycle["status"] != "FUNDED":
        raise ApiError("ERR_CYCLE_INVALID_STATE", "Only a FUNDED cycle can be closed.")
    filings = store.filings_of_cycle(cycle["id"])
    live = [f for f in filings if f["status"] != "VOIDED"]
    if not filings or any(f["status"] != "CONFIRMED" for f in live):
        raise ApiError(
            "ERR_FILINGS_NOT_CONFIRMED",
            "Every non-voided statutory filing of the cycle must be CONFIRMED.",
        )
    recorded = {item["control_ref"] for item in store.evidence_of_cycle(cycle["id"])}
    for control in MANDATORY_CLOSURE_CONTROLS:
        if control not in recorded:
            raise ApiError(
                "ERR_AUDIT_EVIDENCE_INCOMPLETE",
                "The cycle is missing mandatory control evidence.",
            )

    cycle["status"] = "CLOSED"
    touch(cycle)
    engagement = store.engagement_of_cycle(cycle)
    engagement["closed_cycle_count"] += 1
    touch(engagement)
    services.recompute_provider_score(store.provider_of_engagement(engagement))
    return object_response(serial.cycle(cycle))


# ---------------------------------------------------------------------------
# Filing sweep
# ---------------------------------------------------------------------------
@bp.post("/payroll/cycles/<ident>/filing-sweep")
@require(GLOBAL_PAYROLL_OPS, PAYROLL_CONTROLLER)
def filing_sweep(ident):
    limit, offset = v.pagination()
    cycle = store.get_cycle(ident)
    if cycle["status"] not in ("RESULTS_APPROVED", "FUNDED"):
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE",
            "A filing sweep requires a cycle in RESULTS_APPROVED or FUNDED.",
        )
    engagement = store.engagement_of_cycle(cycle)
    country = store.country_of_engagement(engagement)
    provider = store.provider_of_engagement(engagement)
    moment = now()

    for filing in store.filings_of_cycle(cycle["id"]):
        if filing["status"] != "PENDING" or not filing["due_at"] < moment:
            continue
        late_days = calc.late_days_between(filing["due_at"], moment)
        allocation = calc.allocate_penalty(
            late_days, country, provider, filing["responsibility"]
        )
        filing["status"] = "LATE"
        filing["late_days"] = late_days
        filing["penalty_status"] = "ASSESSED"
        filing.update(allocation)
        touch(filing)

        if allocation["provider_share_minor"]:
            provider["open_penalty_minor"] += allocation["provider_share_minor"]
            touch(provider)
            if (
                provider["open_penalty_minor"] > services.PENALTY_PROBATION_THRESHOLD
                and provider["status"] == "ACTIVE"
            ):
                services.apply_provider_status(provider, "PROBATION")
        if filing["responsibility"] == "PROVIDER":
            services.raise_incident(
                engagement["id"], cycle["id"], "FILING_MISS", "SEV2"
            )

    rows = store.filings_of_cycle(cycle["id"])
    return page_response(rows, serial.filing, limit, offset)


# ---------------------------------------------------------------------------
# Nested reads
# ---------------------------------------------------------------------------
@bp.get("/payroll/cycles/<ident>/audit-evidence")
@require(*ALL_ROLES)
def list_cycle_evidence(ident):
    limit, offset = v.pagination()
    control_ref = v.query_enum("control_ref", CONTROL_REFS)
    cycle = store.get_cycle(ident)
    rows = store.evidence_of_cycle(cycle["id"])
    if control_ref is not None:
        rows = [r for r in rows if r["control_ref"] == control_ref]
    return page_response(rows, serial.evidence, limit, offset)


@bp.get("/payroll/cycles/<ident>/input-files")
@require(*ALL_ROLES)
def list_cycle_input_files(ident):
    limit, offset = v.pagination()
    status = v.query_enum("status", INPUT_FILE_STATUSES)
    cycle = store.get_cycle(ident)
    rows = store.input_files_of_cycle(cycle["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_response(rows, serial.input_file, limit, offset)
