"""Practice-management agreements and the fee statement."""

import db
from decimal import Decimal
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers, management
from services.helpers import as_dt, as_enum, as_int, as_num, as_str
from utils import fmt_ts, parse_iso, utc_now_dt

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "NetworkAnalyst",
    "PlatformAdmin",
]

SERVICE_LINES = ("REVENUE_CYCLE", "STAFFING", "TECHNOLOGY")
FEE_BASES = ("PERCENT_OF_NET_COLLECTIONS", "FIXED_MONTHLY", "PER_FTE", "PER_CLAIM")
BLACKOUT_DAYS = 30


@route("POST", "/networks/practice-management-agreements", roles=["NetworkAdmin"], status=201, write=True)
def create_management(ctx):
    practice = helpers.practice_or_404(as_str(ctx.body, "practice_id"))
    service_line = as_enum(ctx.body, "service_line", SERVICE_LINES, required_=True)
    fee_basis = as_enum(ctx.body, "fee_basis", FEE_BASES, required_=True)
    if service_line == "REVENUE_CYCLE" and fee_basis != "PERCENT_OF_NET_COLLECTIONS":
        raise ApiError("ERR_INVALID_FEE_BASIS")
    rate = as_num(ctx.body, "fee_rate", default=Decimal(0))
    if rate is not None and rate < 0:
        raise ApiError("ERR_INVALID_REQUEST", "fee_rate may not be negative")
    if rate is not None and rate > Decimal("0.15"):
        raise ApiError("ERR_INVALID_REQUEST", "fee_rate must not exceed 0.15")

    agreement = db.create(
        "management_agreements",
        {
            "practice_id": practice["id"],
            "service_line": service_line,
            "fee_basis": fee_basis,
            "fee_rate": float(rate or 0),
            "fixed_fee_cents": as_int(ctx.body, "fixed_fee_cents", default=0),
            "per_fte_fee_cents": as_int(ctx.body, "per_fte_fee_cents", default=0),
            "per_claim_fee_cents": as_int(ctx.body, "per_claim_fee_cents", default=0),
            "fte_count": as_int(ctx.body, "fte_count", default=0),
            "term_start": fmt_ts(as_dt(ctx.body, "term_start", required_=True)),
            "term_end": fmt_ts(as_dt(ctx.body, "term_end", required_=True)),
            "accrued_fee_cents": 0,
            "active_month_count": 0,
            "tier_level": practice.get("tier_level"),
            "status": "DRAFT",
        },
    )
    return serial(agreement), 201


@route("GET", "/networks/practice-management-agreements", roles=READ_ROLES)
def list_management(ctx):
    rows = filtered(
        db.all_records("management_agreements"),
        ctx,
        {"practice_id": "practice_id", "status": "status", "service_line": "service_line"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/practice-management-agreements/{agreementId}", roles=READ_ROLES)
def get_management(ctx):
    return serial(helpers.management_or_404(ctx.path_id("agreementId")))


@route(
    "GET", "/networks/practice-management-agreements/{agreementId}/statement", roles=READ_ROLES
)
def management_statement(ctx):
    agreement = helpers.management_or_404(ctx.path_id("agreementId"))
    practice = helpers.practice_or_404(agreement["practice_id"])
    as_of = ctx.q_dt("as_of") or utc_now_dt()
    return management.statement(agreement, practice, as_of)


@route(
    "POST",
    "/networks/practice-management-agreements/{agreementId}/activate",
    roles=["NetworkAdmin"],
    write=True,
)
def activate_management(ctx):
    agreement = helpers.management_or_404(ctx.path_id("agreementId"))
    practice = helpers.practice_or_404(agreement["practice_id"])
    if agreement["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError("ERR_MANAGEMENT_AGREEMENT_NOT_DRAFT")
    if practice["affiliation_status"] not in ("AFFILIATED", "SUSPENDED"):
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")

    start = parse_iso(agreement.get("term_start"))
    end = parse_iso(agreement.get("term_end"))
    if start is None or end is None or end < start:
        raise ApiError("ERR_INVALID_MANAGEMENT_TERM")
    _check_blackout(agreement)
    if agreement.get("service_line") == "REVENUE_CYCLE" and agreement.get("fee_basis") != (
        "PERCENT_OF_NET_COLLECTIONS"
    ):
        raise ApiError("ERR_INVALID_FEE_BASIS")

    if agreement.get("tier_level") is None:
        agreement["tier_level"] = practice.get("tier_level")
    agreement["status"] = "ACTIVE"
    management.accrue(agreement, practice)
    db.touch(agreement)
    return serial(agreement)


def _check_blackout(agreement):
    """Closed-inclusive terms: adjacency is a conflict, and a shorter separation
    than 30 days is refused."""
    from datetime import timedelta

    start = parse_iso(agreement.get("term_start"))
    if start is None:
        return
    for other in db.where("management_agreements", practice_id=agreement["practice_id"]):
        if other["id"] == agreement["id"]:
            continue
        if other.get("service_line") != agreement.get("service_line"):
            continue
        other_end = parse_iso(other.get("term_end"))
        other_start = parse_iso(other.get("term_start"))
        if other_end is None or other_start is None:
            continue
        if start < other_end + timedelta(days=BLACKOUT_DAYS):
            raise ApiError("ERR_MANAGEMENT_TERM_OVERLAP")


@route(
    "POST",
    "/networks/practice-management-agreements/{agreementId}/suspend",
    roles=["NetworkAdmin"],
    write=True,
)
def suspend_management(ctx):
    agreement = helpers.management_or_404(ctx.path_id("agreementId"))
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_MANAGEMENT_AGREEMENT_NOT_ACTIVE")
    agreement["status"] = "SUSPENDED"
    db.touch(agreement)
    return serial(agreement)


@route(
    "POST",
    "/networks/practice-management-agreements/{agreementId}/terminate",
    roles=["NetworkAdmin"],
    write=True,
)
def terminate_management(ctx):
    agreement = helpers.management_or_404(ctx.path_id("agreementId"))
    practice = helpers.practice_or_404(agreement["practice_id"])
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_MANAGEMENT_AGREEMENT_NOT_ACTIVE")
    agreement["status"] = "TERMINATED"
    # The fee liability survives termination.
    practice["unsettled_balance_cents"] = int(practice.get("unsettled_balance_cents") or 0) + int(
        agreement.get("accrued_fee_cents") or 0
    )
    db.touch(practice)
    db.touch(agreement)
    return serial(agreement)