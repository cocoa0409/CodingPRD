"""Rebate programs and the qualification lifecycle."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers, rebates
from services.helpers import as_int, as_num, as_str
from utils import utc_now_dt
from decimal import Decimal

READ_ROLES = ["NetworkAdmin", "PracticeAdmin", "NetworkAnalyst", "PlatformAdmin"]


# ---------------------------------------------------------------------------
# Programs


@route("POST", "/networks/{networkId}/rebate-programs", roles=["NetworkAdmin"], status=201, write=True)
def create_program(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    data = ctx.body
    rebound_pct = as_num(data, "rebate_pct", required_=True)
    if rebound_pct < 0 or rebound_pct > Decimal("0.10"):
        raise ApiError("ERR_INVALID_REQUEST", "rebate_pct must be between 0 and 0.10")
    program = db.create(
        "rebate_programs",
        {
            "network_id": network["id"],
            "program_name": as_str(data, "program_name"),
            "drug_ndc_scope": as_str(data, "drug_ndc_scope"),
            "market_share_threshold_pct": float(as_num(data, "market_share_threshold_pct", required_=True)),
            "rebate_pct": float(rebound_pct),
            "compliance_min_score": float(as_num(data, "compliance_min_score", required_=True)),
            "period_epoch_index": as_int(data, "period_epoch_index", required_=True),
            "weight_reporting_compliance": as_int(data, "weight_reporting_compliance", default=1),
            "weight_adherence_steering": as_int(data, "weight_adherence_steering", default=1),
            "weight_transparency": as_int(data, "weight_transparency", default=1),
            "status": "DRAFT",
        },
    )
    return serial(program), 201


@route("GET", "/networks/rebate-programs", roles=READ_ROLES)
def list_programs(ctx):
    rows = filtered(
        db.all_records("rebate_programs"),
        ctx,
        {"network_id": "network_id", "status": "status"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/rebate-programs/{programId}", roles=READ_ROLES)
def get_program(ctx):
    return serial(helpers.program_or_404(ctx.path_id("programId")))


@route("GET", "/networks/rebate-programs/{programId}/qualifications", roles=READ_ROLES)
def program_qualifications(ctx):
    program = helpers.program_or_404(ctx.path_id("programId"))
    rows = filtered(
        db.where("rebate_qualifications", rebate_program_id=program["id"]),
        ctx,
        {"status": "status"},
    )
    return paginate(ctx, rows)


@route("POST", "/networks/rebate-programs/{programId}/activate", roles=["NetworkAdmin"], write=True)
def activate_program(ctx):
    program = helpers.program_or_404(ctx.path_id("programId"))
    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    program["status"] = "ACTIVE"
    db.touch(program)
    return serial(program)


@route("POST", "/networks/rebate-programs/{programId}/close", roles=["NetworkAdmin"], write=True)
def close_program(ctx):
    program = helpers.program_or_404(ctx.path_id("programId"))
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    pending = [
        q
        for q in db.where("rebate_qualifications", rebate_program_id=program["id"])
        if q["status"] == "PENDING"
    ]
    if pending:
        raise ApiError("ERR_OPEN_REBATE_CLAIMS_EXIST")
    program["status"] = "CLOSED"
    db.touch(program)
    return serial(program)


# ---------------------------------------------------------------------------
# Qualifications


@route(
    "POST",
    "/networks/rebate-qualifications",
    roles=["PracticeAdmin", "NetworkAdmin"],
    status=201,
    write=True,
)
def create_qualification(ctx):
    practice = helpers.practice_or_404(as_str(ctx.body, "practice_id"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    program = helpers.program_or_404(as_str(ctx.body, "rebate_program_id"))
    if program["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    if program.get("network_id") != practice.get("network_id"):
        raise ApiError("ERR_CROSS_NETWORK_REFERENCE")

    qualification = db.create(
        "rebate_qualifications",
        {
            "practice_id": practice["id"],
            "rebate_program_id": program["id"],
            "period_epoch_index": program.get("period_epoch_index"),
            "market_share_pct": 0.0,
            "compliance_score": 0.0,
            "is_qualified": False,
            "rebate_amount_cents": 0,
            "holdback_cents": 0,
            "compliance_report_submitted_at": None,
            "compact_discount_credit_cents": 0,
            "compliance_report_verified": False,
            "status": "PENDING",
        },
    )
    rebates.refresh_qualification(qualification)
    qualification["is_qualified"] = rebates.qualified_test(qualification)
    db.touch(qualification)
    rebates.mark_practice_mirror(practice)
    db.touch(practice)
    return serial(qualification), 201


@route("GET", "/networks/rebate-qualifications", roles=READ_ROLES)
def list_qualifications(ctx):
    rows = filtered(
        db.all_records("rebate_qualifications"),
        ctx,
        {
            "practice_id": "practice_id",
            "rebate_program_id": "rebate_program_id",
            "status": "status",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/rebate-qualifications/{qualificationId}", roles=READ_ROLES)
def get_qualification(ctx):
    return serial(helpers.qualification_or_404(ctx.path_id("qualificationId")))


@route(
    "POST",
    "/networks/rebate-qualifications/{qualificationId}/report",
    roles=["PracticeAdmin"],
    write=True,
)
def report_compliance(ctx):
    qualification = helpers.qualification_or_404(ctx.path_id("qualificationId"))
    practice = helpers.practice_or_404(qualification["practice_id"])
    helpers.may_edit_practice(ctx.principal, practice["id"])
    if qualification["status"] != "PENDING":
        raise ApiError("ERR_QUALIFICATION_NOT_PENDING")
    if qualification.get("compliance_report_submitted_at"):
        raise ApiError("ERR_INVALID_STATE")

    network = db.get("networks", practice["network_id"])
    closed_at = helpers.epoch_closed_at(network, qualification.get("period_epoch_index"))
    grace_days = int(network.get("compliance_report_grace_days") or 0)
    from datetime import timedelta

    deadline = closed_at + timedelta(days=grace_days)
    instant = utc_now_dt()
    if instant > deadline:
        raise ApiError("ERR_COMPLIANCE_REPORT_LATE")

    if not ctx.body.get("compliance_attestation"):
        raise ApiError("ERR_INVALID_REQUEST", "compliance_attestation is required")

    from utils import fmt_ts

    qualification["compliance_report_submitted_at"] = fmt_ts(instant)
    rebates.refresh_qualification(qualification)
    qualification["is_qualified"] = rebates.qualified_test(qualification)
    db.touch(qualification)
    return serial(qualification)


@route(
    "POST",
    "/networks/rebate-qualifications/{qualificationId}/verify-report",
    roles=["NetworkAdmin"],
    write=True,
)
def verify_report(ctx):
    qualification = helpers.qualification_or_404(ctx.path_id("qualificationId"))
    qualification["compliance_report_verified"] = True
    db.touch(qualification)
    return serial(qualification)


@route(
    "POST",
    "/networks/rebate-qualifications/{qualificationId}/evaluate",
    roles=["NetworkAdmin"],
    write=True,
)
def evaluate_qualification(ctx):
    qualification = helpers.qualification_or_404(ctx.path_id("qualificationId"))
    practice = helpers.practice_or_404(qualification["practice_id"])
    if qualification["status"] != "PENDING":
        raise ApiError("ERR_QUALIFICATION_NOT_PENDING")
    network = db.get("networks", practice["network_id"])
    period = int(qualification.get("period_epoch_index") or 0)
    if period > int(network.get("allocation_epoch_index") or 0):
        raise ApiError("ERR_QUALIFICATION_PERIOD_NOT_ELAPSED")

    rebates.refresh_qualification(qualification)
    qualified = rebates.qualified_test(qualification)
    qualification["is_qualified"] = qualified
    qualification["status"] = "QUALIFIED" if qualified else "DISQUALIFIED"
    if not qualified:
        qualification["rebate_amount_cents"] = 0
    rebates.mark_practice_mirror(practice)
    db.touch(practice)
    db.touch(qualification)
    return serial(qualification)


@route("POST", "/networks/rebate-qualifications/{qualificationId}/pay", roles=["NetworkAdmin"], write=True)
def pay_qualification(ctx):
    qualification = helpers.qualification_or_404(ctx.path_id("qualificationId"))
    if qualification["status"] != "QUALIFIED":
        raise ApiError("ERR_QUALIFICATION_NOT_QUALIFIED")
    if not qualification.get("compliance_report_verified"):
        raise ApiError("ERR_COMPLIANCE_REPORT_NOT_VERIFIED")
    if int(qualification.get("holdback_cents") or 0) != 0:
        raise ApiError("ERR_REBATE_ON_HOLDBACK")
    qualification["status"] = "PAID"
    db.touch(qualification)
    return serial(qualification)


@route(
    "POST",
    "/networks/rebate-qualifications/{qualificationId}/reclaim",
    roles=["NetworkAdmin"],
    write=True,
)
def reclaim_qualification(ctx):
    qualification = helpers.qualification_or_404(ctx.path_id("qualificationId"))
    practice = helpers.practice_or_404(qualification["practice_id"])
    if qualification["status"] != "QUALIFIED":
        raise ApiError("ERR_QUALIFICATION_NOT_QUALIFIED")
    amount = int(qualification.get("rebate_amount_cents") or 0)
    qualification["status"] = "RECLAIMED"
    qualification["holdback_cents"] = amount
    qualification["rebate_amount_cents"] = 0
    qualification["is_qualified"] = False
    practice["unsettled_balance_cents"] = int(practice.get("unsettled_balance_cents") or 0) + amount
    rebates.mark_practice_mirror(practice)
    db.touch(practice)
    db.touch(qualification)
    return serial(qualification)