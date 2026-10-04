"""Affiliation contracts: activation, termination and the departure unwind."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services import shortage as shortage_service
from services.helpers import as_dt, as_enum, as_int
from utils import fmt_ts, parse_iso

READ_ROLES = ["NetworkAdmin", "PracticeAdmin", "NetworkAnalyst", "PlatformAdmin"]


@route(
    "POST",
    "/networks/practices/{practiceId}/affiliation-contracts",
    roles=["NetworkAdmin"],
    status=201,
    write=True,
)
def create_contract(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    data = ctx.body
    contract = db.create(
        "affiliation_contracts",
        {
            "practice_id": practice["id"],
            "contract_type": as_enum(
                data,
                "contract_type",
                ("FULL_AFFILIATION", "MANAGEMENT_SERVICES_ONLY", "PURCHASING_ONLY"),
                required_=True,
            ),
            "term_start": fmt_ts(as_dt(data, "term_start", required_=True)),
            "term_end": fmt_ts(as_dt(data, "term_end", required_=True)),
            "notice_period_days": as_int(data, "notice_period_days", required_=True),
            "pricing_agreements_unwound": False,
            "open_orders_closed": False,
            "rebate_holdback_cents": 0,
            "research_hold": False,
            "status": "DRAFT",
        },
    )
    return serial(contract), 201


@route("GET", "/networks/affiliation-contracts", roles=READ_ROLES)
def list_contracts(ctx):
    rows = filtered(
        db.all_records("affiliation_contracts"),
        ctx,
        {"practice_id": "practice_id", "status": "status"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/affiliation-contracts/{contractId}", roles=READ_ROLES)
def get_contract(ctx):
    return serial(helpers.contract_or_404(ctx.path_id("contractId")))


@route("POST", "/networks/affiliation-contracts/{contractId}/activate", roles=["NetworkAdmin"], write=True)
def activate_contract(ctx):
    contract = helpers.contract_or_404(ctx.path_id("contractId"))
    practice = helpers.practice_or_404(contract["practice_id"])
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT")
    if practice["affiliation_status"] not in ("PROSPECTIVE", "AFFILIATED"):
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATABLE")
    start = parse_iso(contract.get("term_start"))
    end = parse_iso(contract.get("term_end"))
    if start is None or end is None or end < start:
        raise ApiError("ERR_INVALID_CONTRACT_TERM")
    if int(contract.get("notice_period_days") or 0) < 0:
        raise ApiError("ERR_INVALID_REQUEST", "notice_period_days may not be negative")

    contract["status"] = "ACTIVE"
    if practice["affiliation_status"] == "PROSPECTIVE":
        practice["affiliation_status"] = "AFFILIATED"
        helpers.recompute_tier(practice)
        db.touch(practice)
    db.touch(contract)
    return serial(contract)


@route(
    "POST",
    "/networks/affiliation-contracts/{contractId}/complete-unwind",
    roles=["NetworkAdmin"],
    write=True,
)
def complete_unwind(ctx):
    contract = helpers.contract_or_404(ctx.path_id("contractId"))
    practice = helpers.practice_or_404(contract["practice_id"])
    if contract["status"] != "UNWIND_IN_PROGRESS":
        raise ApiError("ERR_CONTRACT_NOT_UNWINDING")

    for order in db.where("purchase_orders", practice_id=practice["id"]):
        if order["status"] in ("SUBMITTED", "CONFIRMED", "BACKORDERED", "SHIPPED"):
            raise ApiError("ERR_OPEN_ORDERS_EXIST")
    for agreement in db.where("management_agreements", practice_id=practice["id"]):
        if agreement["status"] in ("DRAFT", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_OPEN_MANAGEMENT_AGREEMENT")
    for participation in db.where("research_participations", practice_id=practice["id"]):
        if participation["site_status"] in (
            "APPLIED",
            "FEASIBILITY_REVIEW",
            "ACTIVATED",
            "SUSPENDED",
        ):
            raise ApiError("ERR_OPEN_RESEARCH_SITE")

    contract["status"] = "TERMINATED"
    # RECLAIMED rows keep the holdback they recorded; a QUALIFIED row with a
    # zero holdback is left untouched — the sweep is not a second confiscation.
    contract["pricing_agreements_unwound"] = all(
        a["status"] == "SUPERSEDED"
        for a in db.where("pricing_agreements", practice_id=practice["id"])
    )
    contract["open_orders_closed"] = True
    for grant in db.where("shortage_allocations", practice_id=practice["id"]):
        if grant["status"] in ("GRANTED", "PARTIALLY_COMMITTED"):
            shortage_service.revoke(grant)
    db.touch(contract)
    return serial(contract)


@route("POST", "/networks/affiliation-contracts/{contractId}/terminate", roles=["NetworkAdmin"], write=True)
def terminate_contract(ctx):
    contract = helpers.contract_or_404(ctx.path_id("contractId"))
    practice = helpers.practice_or_404(contract["practice_id"])
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    if practice["affiliation_status"] != "PROSPECTIVE":
        raise ApiError("ERR_CONTRACT_NOT_TERMINABLE_WHILE_AFFILIATED")
    contract["status"] = "TERMINATED"
    db.touch(contract)
    return serial(contract)