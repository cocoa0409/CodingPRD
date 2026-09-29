"""Capacity blocks (PRD 3.2): a half-open date window of run hours."""
from flask import Blueprint

from auth import (ROLE_EXECUTIVE_SPONSOR, ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER,
                  endpoint, find_or_404)
from calcs import CHANGEOVER_BUFFER_DAYS
from envelope import respond_list, respond_object
from errors import ApiError, bad_request
from store import new_row, ordered, public, public_all, store
from util import D, month_of_date, shift_date
from validators import (get_body, paginate, pagination, query_str, req_date,
                        req_number, req_string)

bp = Blueprint("capacity", __name__)

BLOCK_READ_ROLES = [ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]


@bp.post("/sop/capacity-blocks")
@endpoint([ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER])
def create_block():
    body = get_body()
    family_id = req_string(body, "family_id")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    if end_date <= start_date:
        raise bad_request("end_date must be strictly later than start_date")
    available_hours = req_number(body, "available_hours", exclusive_min=0)

    family = find_or_404("families", family_id, "ERR_FAMILY_NOT_FOUND")

    existing = [b for b in ordered(store.capacity_blocks.values())
                if b["family_id"] == family["id"]]

    # changeover buffer: two clear days in one direction or the other
    for other in existing:
        clears = (start_date >= shift_date(other["end_date"], CHANGEOVER_BUFFER_DAYS)
                  or other["start_date"] >= shift_date(end_date, CHANGEOVER_BUFFER_DAYS))
        if not clears:
            raise ApiError("ERR_CAPACITY_BLOCK_OVERLAP",
                           "The block comes within %d days of an existing block"
                           % CHANGEOVER_BUFFER_DAYS)

    # monthly ceiling: blocks bucket by start_date alone
    bucket = month_of_date(start_date)
    total = D(available_hours)
    for other in existing:
        if month_of_date(other["start_date"]) == bucket:
            total += D(other["available_hours"])
    if total > D(family["max_monthly_hours"]):
        raise ApiError("ERR_FAMILY_MONTHLY_HOURS_EXCEEDED",
                       "The family's monthly hour ceiling would be exceeded")

    row = new_row()
    row.update({
        "family_id": family["id"],
        "start_date": start_date,
        "end_date": end_date,
        "available_hours": available_hours,
    })
    store.capacity_blocks[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/sop/capacity-blocks/<block_id>")
@endpoint(BLOCK_READ_ROLES)
def get_block(block_id):
    row = find_or_404("capacity_blocks", block_id, "ERR_CAPACITY_BLOCK_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/capacity-blocks")
@endpoint(BLOCK_READ_ROLES)
def list_blocks():
    limit, offset = pagination()
    family_id = query_str("family_id")
    rows = ordered(store.capacity_blocks.values())
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)
