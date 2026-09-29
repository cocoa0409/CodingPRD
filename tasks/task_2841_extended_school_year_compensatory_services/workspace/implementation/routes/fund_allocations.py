"""Budget codes and their lifecycle (PRD sections 2.9 / 3.5)."""
from flask import Blueprint

from auth import SPED_DIRECTOR, endpoint
from calcs import refresh_available
from envelope import created, ok
from errors import ApiError
from resolve import body_ref, path_ref
from serialize import allocation_public
from store import db, new_record, touch
from validate import body, req_enum, req_int, req_str

bp = Blueprint("fund_allocations", __name__)

FUND_SOURCES = ("IDEA_611_FEDERAL", "IDEA_619_FEDERAL", "LOCAL_GENERAL")
ALLOCATION_STATUSES = ("OPEN", "FROZEN", "CLOSED")


@bp.post("/esy/fund-allocations")
@endpoint((SPED_DIRECTOR,))
def create_fund_allocation():
    data = body()
    body_ref(data, "program_id", "program")
    program_id = req_str(data, "program_id", 1, None)
    fund_source = req_enum(data, "fund_source", FUND_SOURCES)
    budget_code = req_str(data, "budget_code", 1, 24)
    authorized = req_int(data, "authorized_amount_cents", 1, 100000000)

    for existing in db.allocations.values():
        if (existing["program_id"] == program_id
                and existing["budget_code"] == budget_code):
            raise ApiError("ERR_DUPLICATE_BUDGET_CODE")

    allocation = new_record("FundAllocation", {
        "program_id": program_id,
        "fund_source": fund_source,
        "budget_code": budget_code,
        "authorized_amount_cents": authorized,
        "encumbered_amount_cents": 0,
        "expended_amount_cents": 0,
        "compensatory_expended_cents": 0,
        "available_cents": authorized,
        "status": "OPEN",
    })
    refresh_available(allocation)
    db.allocations[allocation["id"]] = allocation
    return created(allocation_public(allocation))


@bp.patch("/esy/fund-allocations/<allocation_id>")
@endpoint((SPED_DIRECTOR,))
def update_fund_allocation(allocation_id):
    allocation = path_ref("allocation", allocation_id)
    data = body()
    target = req_enum(data, "status", ALLOCATION_STATUSES)
    current = allocation["status"]

    if target == "FROZEN":
        if current != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
    elif target == "OPEN":
        if current != "FROZEN":
            raise ApiError("ERR_INVALID_STATE")
    else:
        if current not in ("OPEN", "FROZEN"):
            raise ApiError("ERR_INVALID_STATE")
        if allocation["encumbered_amount_cents"] != 0:
            raise ApiError("ERR_INVALID_STATE")

    allocation["status"] = target
    touch(allocation)
    return ok(allocation_public(allocation))
