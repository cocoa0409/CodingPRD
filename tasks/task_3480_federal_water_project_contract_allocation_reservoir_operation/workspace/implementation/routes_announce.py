"""AllocationAnnouncements and AllocationLines (PRD sections 2.7, 3.3).

Publish computes declared supply, shortage tier, allocation basis, per-contract
lines, supersedes sibling announcements, transitions the year, and runs the
revision curtailment cascade.
"""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, not_found
from routes_years import year_or_404
from serial import announcement_view, line_view
from store import DB, clock_now, new_record, touch
from validate import as_int, get_body, required

bp = Blueprint("announcements", __name__)


@bp.post("/water/water-years/<string:water_year_id>/allocation-announcements")
def create_announcement(water_year_id):
    authenticate(["ReclamationOperator"])
    body = get_body()
    expected = as_int(required(body, "expected_water_year_version"),
                      "expected_water_year_version")
    year = year_or_404(water_year_id)
    if year["status"] == "CLOSED":
        raise ApiError("ERR_YEAR_CLOSED", 409,
                       "announcements cannot be created in a CLOSED water year")
    # the API's single OCC-guarded write (PRD section 2.7)
    if expected != year["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_water_year_version does not match the current version")
    seq = 1 + max([a["sequence_number"] for a in DB["announcements"].values()
                   if a["water_year_id"] == year["id"]] + [0])
    rec = new_record()
    rec.update({
        "water_year_id": year["id"],
        "sequence_number": seq,
        "status": "DRAFT",
        "declared_supply_af": None,
        "shortage_tier": None,
        "allocation_basis": None,
        "published_at": None,
    })
    DB["announcements"][rec["id"]] = rec
    # each successful creation increments the year's version by one
    touch(year)
    return success(announcement_view(rec), 201)


@bp.get("/water/water-years/<string:water_year_id>/allocation-announcements")
def list_announcements(water_year_id):
    authenticate(ALL_ROLES)
    year = year_or_404(water_year_id)
    filters = {"status": request.args.get("status")}
    records = [a for a in DB["announcements"].values()
               if a["water_year_id"] == year["id"]]
    return list_response(records, announcement_view, filters)


@bp.post("/water/allocation-announcements/<string:announcement_id>/publish")
def publish_announcement(announcement_id):
    authenticate(["ReclamationOperator"])
    ann = DB["announcements"].get(announcement_id)
    if ann is None:
        not_found("AllocationAnnouncement")
    year = DB["water_years"][ann["water_year_id"]]
    if year["status"] == "CLOSED":
        raise ApiError("ERR_YEAR_CLOSED", 409,
                       "cannot publish into a CLOSED water year")
    if ann["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a DRAFT announcement can be published")

    # 1-2. declared supply, then shortage tier (pinned order)
    declared = calc.declared_supply(year)
    tier = calc.shortage_tier(declared)

    # 3. allocation basis: ACTIVATED shortage agreement covering this label
    agreement = None
    for ag in DB["agreements"].values():
        if (ag["status"] == "ACTIVATED"
                and ag["activated_water_year_label"] == year["label"]):
            agreement = ag
            break
    basis = "SHORTAGE_SHARING" if agreement is not None else "PRIORITY_WATERFALL"

    # 4. per-contract lines over ACTIVE contracts; revision carries forward
    #    delivered / transfer totals from the superseded announcement's lines
    contracts = calc.active_contracts()
    if basis == "SHORTAGE_SHARING":
        allocations = calc.sharing_allocations(contracts, declared, tier, agreement)
    else:
        allocations = calc.waterfall_allocations(contracts, declared)
    prev_lines = {}
    if year["current_announcement_id"] is not None:
        for l in calc.lines_of(year["current_announcement_id"]):
            prev_lines[l["contract_id"]] = l
    new_lines = {}
    for c in contracts:
        prev = prev_lines.get(c["id"])
        delivered = prev["delivered_af"] if prev else 0
        t_in = prev["transfer_in_af"] if prev else 0
        t_out = prev["transfer_out_af"] if prev else 0
        allocated = allocations[c["id"]]
        rec = new_record()
        rec.update({
            "announcement_id": ann["id"],
            "contract_id": c["id"],
            "allocated_af": allocated,
            "delivered_af": delivered,
            "transfer_in_af": t_in,
            "transfer_out_af": t_out,
            "remaining_af": allocated + t_in - t_out - delivered,
        })
        DB["allocation_lines"][rec["id"]] = rec
        new_lines[c["id"]] = rec

    # 5. supersede every other announcement of the year; transition the year
    for other in DB["announcements"].values():
        if (other["water_year_id"] == year["id"] and other["id"] != ann["id"]
                and other["status"] in ("DRAFT", "PUBLISHED")):
            other["status"] = "SUPERSEDED"
            touch(other)
    ann["declared_supply_af"] = declared
    ann["shortage_tier"] = tier
    ann["allocation_basis"] = basis
    ann["published_at"] = clock_now()
    ann["status"] = "PUBLISHED"
    touch(ann)
    year["status"] = "ANNOUNCED"
    year["current_announcement_id"] = ann["id"]
    touch(year)

    # 6. re-home delivery orders onto successor lines, then curtail, then
    #    recompute remaining balances last
    for o in DB["delivery_orders"].values():
        if o["water_year_id"] != year["id"]:
            continue
        new_line = new_lines.get(o["contract_id"])
        if new_line is not None and o["allocation_line_id"] != new_line["id"]:
            o["allocation_line_id"] = new_line["id"]
            touch(o)
    calc.curtailment_cascade(list(new_lines.values()))
    return success(announcement_view(ann), 200)


@bp.get("/water/allocation-lines")
def list_allocation_lines():
    authenticate(ALL_ROLES)
    filters = {
        "announcement_id": request.args.get("announcement_id"),
        "contract_id": request.args.get("contract_id"),
    }
    return list_response(list(DB["allocation_lines"].values()), line_view, filters)


@bp.get("/water/allocation-lines/<string:line_id>")
def get_allocation_line(line_id):
    authenticate(ALL_ROLES)
    line = DB["allocation_lines"].get(line_id)
    if line is None:
        not_found("AllocationLine")
    return success(line_view(line))
