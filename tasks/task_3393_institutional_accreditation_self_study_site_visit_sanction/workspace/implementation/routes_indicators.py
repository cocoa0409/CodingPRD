"""Indicator reports: open, list, submit (CFI/EMI), evaluate + cascade (§3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
from auth import authenticate, check_liaison_chain, require_liaison_owns, require_role
from calculations import (annual_dues_cents, cfi_band,
                          composite_financial_index,
                          enrollment_momentum_index)
from db import STORE, add_months, fmt_dt, parse_iso_date
from errors import (ERR_INDICATOR_REPORT_NOT_FOUND, ERR_INSTITUTION_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_REPORT_PERIOD_GAP,
                    ERR_REPORT_PERIOD_OVERLAP, ERR_VALIDATION, raise_err)
from helpers import (fetch_or_404, freeze_substantive_changes, get_body,
                     new_entity, opt_number, paginate, req_int, req_number,
                     req_string, serialize, touch)
from response import success_list, success_object

bp = Blueprint("indicators", __name__)


@bp.post("/accreditation/institutions/<inst_id>/indicator-reports")
def create_report(inst_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    body = get_body()
    start_raw = req_string(body, "period_start")
    end_raw = req_string(body, "period_end")
    start = parse_iso_date(start_raw)
    end = parse_iso_date(end_raw)
    if start is None or end is None or end <= start:
        raise_err(ERR_VALIDATION, "period_start/period_end must be YYYY-MM-DD with end after start")
    existing = [r for r in STORE.indicator_reports.values() if r["institution_id"] == inst_id]
    for r in existing:
        # Closed-interval intersection.
        if start <= r["_period_end"] and r["_period_start"] <= end:
            raise_err(ERR_REPORT_PERIOD_OVERLAP,
                      "The period intersects an existing report period")
    if existing:
        latest_end = max(r["_period_end"] for r in existing)
        if start != latest_end + timedelta(days=1):
            raise_err(ERR_REPORT_PERIOD_GAP,
                      "period_start must be exactly one day after the latest period_end")
    report = new_entity({
        "institution_id": inst_id,
        "period_start": start_raw,
        "period_end": end_raw,
        "_period_start": start,
        "_period_end": end,
        "status": "DUE",
        "primary_reserve_ratio": None,
        "viability_ratio": None,
        "net_operating_ratio": None,
        "state_appropriation_ratio": None,
        "enrollment_change_pct": None,
        "completion_rate": None,
        "retention_rate": None,
        "fte_enrollment": None,
        "cfi_value": None,
        "cfi_variant_used": None,
        "emi_value": None,
        "evaluated_at": None,
        "_evaluated_dt": None,
    })
    STORE.indicator_reports[report["id"]] = report
    return success_object(serialize(report), code=201)


@bp.get("/accreditation/institutions/<inst_id>/indicator-reports")
def list_reports(inst_id):
    actor = authenticate()
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, inst_id)
    fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    items = [r for r in STORE.indicator_reports.values() if r["institution_id"] == inst_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.post("/accreditation/indicator-reports/<report_id>/submit")
def submit_report(report_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    report = fetch_or_404(STORE.indicator_reports, report_id, ERR_INDICATOR_REPORT_NOT_FOUND)
    require_liaison_owns(actor, report["institution_id"])
    body = get_body()
    prr = req_number(body, "primary_reserve_ratio")
    viability = req_number(body, "viability_ratio")
    nor = req_number(body, "net_operating_ratio")
    sar = opt_number(body, "state_appropriation_ratio")
    ecp = req_number(body, "enrollment_change_pct")
    completion = req_number(body, "completion_rate", minimum=0, maximum=100)
    retention = req_number(body, "retention_rate", minimum=0, maximum=100)
    fte = req_int(body, "fte_enrollment", minimum=0)
    if report["status"] != "DUE":
        raise_err(ERR_INVALID_STATE, "Only a DUE report can be submitted")
    inst = STORE.institutions.get(report["institution_id"])
    cfi_value, variant = composite_financial_index(prr, viability, nor, sar, inst["legal_status"])
    emi_value = enrollment_momentum_index(ecp, completion, retention)
    report["primary_reserve_ratio"] = prr
    report["viability_ratio"] = viability
    report["net_operating_ratio"] = nor
    report["state_appropriation_ratio"] = sar
    report["enrollment_change_pct"] = ecp
    report["completion_rate"] = completion
    report["retention_rate"] = retention
    report["fte_enrollment"] = fte
    report["cfi_value"] = cfi_value
    report["cfi_variant_used"] = variant
    report["emi_value"] = emi_value
    report["status"] = "SUBMITTED"
    touch(report)
    # Submission refreshes the institution FTE and forces a dues recompute.
    inst["fte_enrollment"] = fte
    inst["current_annual_dues_cents"] = annual_dues_cents(
        inst["fte_enrollment"], inst["degree_levels_offered"])
    touch(inst)
    return success_object(serialize(report))


@bp.post("/accreditation/indicator-reports/<report_id>/evaluate")
def evaluate_report(report_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    report = fetch_or_404(STORE.indicator_reports, report_id, ERR_INDICATOR_REPORT_NOT_FOUND)
    if report["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED report can be evaluated")
    inst = STORE.institutions.get(report["institution_id"])
    band = cfi_band(report["cfi_value"])
    now = STORE.now()
    from decimal import Decimal
    if band == "PANEL":
        verdict = "FLAGGED_PANEL"
    elif band == "CLEAR" and Decimal(str(report["emi_value"])) >= C.EMI_FLAG_BELOW:
        verdict = "CLEARED"
    else:
        verdict = "FLAGGED_REVIEW"
    report["status"] = verdict
    report["evaluated_at"] = STORE.now_iso()
    report["_evaluated_dt"] = now
    touch(report)
    inst["latest_cfi_value"] = report["cfi_value"]
    inst["latest_cfi_band"] = band
    if verdict == "FLAGGED_PANEL":
        # Indicator cascade: an already-effective NOTICE sanction outcome (§3.9).
        outcome = new_entity({
            "review_cycle_id": None,
            "indicator_origin_institution_id": inst["id"],
            "origin": "INDICATOR_MONITOR",
            "action_type": "NOTICE",
            "status": "EFFECTIVE",
            "public_disclosure_text": None,
            "disclosed_at": None,
            "effective_at": STORE.now_iso(),
            "sanction_level": "NOTICE",
            "cure_status": "NONE",
            "cure_review_opened_at": None,
            "_cure_opened_dt": None,
            "cure_threshold_snapshot": None,
            "cure_deadline_at": fmt_dt(add_months(now, C.SANCTION_CURE_MONTHS["NOTICE"])),
        })
        STORE.action_outcomes[outcome["id"]] = outcome
        if inst["sanction_status"] == "NONE":
            inst["sanction_status"] = "NOTICE"
        freeze_substantive_changes(inst["id"])
    touch(inst)
    return success_object(serialize(report))
