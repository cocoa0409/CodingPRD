"""Room blocks, sub-block carving, cutoff and the attrition waiver."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from logic import *  # noqa: F401,F403
from serialize import block_json, night_json, reservation_json

bp = Blueprint("blocks", __name__)

BLOCK_READ_ROLES = [ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
                    ROLE_RESERVATIONS_AGENT, ROLE_ACCOUNTING_CLERK,
                    ROLE_GROUP_CONTACT]


@bp.route("/group-sales/room-blocks", methods=["POST"])
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_RESERVATIONS_AGENT])
def create_sub_block():
    body = body_json()
    parent_id = v_id(body, "parent_block_id")
    name = v_string(body, "name", min_len=1, max_len=60)
    entries = v_allotments(body)
    expected = v_int(body, "expected_parent_block_version", minimum=0)
    dates = [e["stay_date"] for e in entries]
    if len(set(dates)) != len(dates):
        fail("ERR_INVALID_REQUEST",
             "'nightly_allotments' carries a duplicate stay_date.")
    parent = need_block(parent_id)
    if expected != parent["version"]:
        fail("ERR_STALE_BLOCK_VERSION",
             "expected_parent_block_version %s does not match the parent's version %s."
             % (expected, parent["version"]))
    entries = sorted(entries, key=lambda e: e["stay_date"])
    # Two passes in ascending stay_date order, applied atomically (PRD §3.6).
    parent_nights = []
    for entry in entries:
        night = night_of_block(parent_id, iso_date(entry["stay_date"]))
        if night is None:
            fail("ERR_SUB_BLOCK_DATES_OUTSIDE_PARENT",
                 "The parent block holds no night for %s."
                 % iso_date(entry["stay_date"]))
        parent_nights.append(night)
    for entry, night in zip(entries, parent_nights):
        if entry["rooms"] > night_unallocated(night):
            fail("ERR_SUB_BLOCK_ALLOTMENT_EXCEEDED",
                 "The parent night %s has only %s unallocated rooms."
                 % (night["stay_date"], night_unallocated(night)))
    row = new_row({
        "contract_id": parent["contract_id"],
        "parent_block_id": parent["id"],
        "name": name,
        "inventory_status": "SETUP",
        "billing_status": "UNBILLED",
        "cutoff_date": parent["cutoff_date"],
        "waived_by_user_id": None,
        "waiver_reason": None,
    })
    store.blocks[row["id"]] = row
    for entry in entries:
        night = new_row({
            "block_id": row["id"],
            "stay_date": iso_date(entry["stay_date"]),
            "rooms_allotted": entry["rooms"],
            "rooms_released": 0,
        })
        store.nights[night["id"]] = night
    touch(parent)
    return ok(block_json(row), 201)


@bp.route("/group-sales/room-blocks/<block_id>", methods=["GET"])
@endpoint(BLOCK_READ_ROLES)
def read_block(block_id):
    block = need_block(block_id)
    require_owner(owner_of_block(block))
    return ok(block_json(block))


@bp.route("/group-sales/room-blocks", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
           ROLE_RESERVATIONS_AGENT, ROLE_ACCOUNTING_CLERK])
def list_blocks():
    limit, offset = q_pagination()
    contract_id = q_str("contract_id")
    parent_id = q_str("parent_block_id")
    is_master = q_bool("is_master")
    inventory_status = q_enum("inventory_status", INVENTORY_STATUSES)
    rows = in_order(list(store.blocks.values()))
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if parent_id is not None:
        rows = [r for r in rows if r["parent_block_id"] == parent_id]
    if is_master is not None:
        rows = [r for r in rows if (r["parent_block_id"] is None) == is_master]
    if inventory_status is not None:
        rows = [r for r in rows if r["inventory_status"] == inventory_status]
    page, total = paginate(rows, limit, offset)
    return ok_list([block_json(r) for r in page], limit, offset, total)


@bp.route("/group-sales/room-blocks/<block_id>/nights", methods=["GET"])
@endpoint(BLOCK_READ_ROLES)
def list_block_nights(block_id):
    limit, offset = q_pagination()
    from_date = q_date("from_date")
    to_date = q_date("to_date")
    block = need_block(block_id)
    require_owner(owner_of_block(block))
    rows = nights_of_block(block_id)
    if from_date is not None:
        rows = [r for r in rows if r["stay_date"] >= iso_date(from_date)]
    if to_date is not None:
        rows = [r for r in rows if r["stay_date"] < iso_date(to_date)]
    page, total = paginate(rows, limit, offset)
    return ok_list([night_json(r) for r in page], limit, offset, total)


@bp.route("/group-sales/room-blocks/<block_id>/reservations", methods=["GET"])
@endpoint(BLOCK_READ_ROLES)
def list_block_reservations(block_id):
    limit, offset = q_pagination()
    status = q_enum("status", RESERVATION_STATUSES)
    block = need_block(block_id)
    require_owner(owner_of_block(block))
    rows = reservations_of_block(block_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([reservation_json(r) for r in page], limit, offset, total)


@bp.route("/group-sales/room-blocks/<block_id>/pickup-summary", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
           ROLE_ACCOUNTING_CLERK])
def block_pickup_summary(block_id):
    block = need_block(block_id)
    contract = contract_of_block(block)
    payload = {
        "block_id": block["id"],
        "allotted_room_nights": block_allotted_room_nights(block),
        "picked_up_room_nights": block_picked_up_room_nights(block),
        "released_room_nights": block_released_room_nights(block),
        "peak_night_rooms": block_peak_night_rooms(block),
        "commitment_base_room_nights": commitment_base_room_nights(contract),
    }
    payload.update(both_attrition_projections(contract))
    return ok(payload)


@bp.route("/group-sales/room-blocks/<block_id>/open", methods=["POST"])
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_RESERVATIONS_AGENT])
def open_block(block_id):
    block = need_block(block_id)
    if block["inventory_status"] != "SETUP":
        fail("ERR_BLOCK_INVALID_STATE",
             "Open is declared only from SETUP; the block is %s."
             % block["inventory_status"])
    contract = contract_of_block(block)
    if contract is None or contract["status"] != "SIGNED":
        fail("ERR_CONTRACT_INVALID_STATE",
             "The block's contract must be SIGNED to open the block.")
    if store.today() > parse_date_str(block["cutoff_date"]):
        fail("ERR_BLOCK_INVALID_STATE",
             "The block's cutoff date of %s has already passed."
             % block["cutoff_date"])
    block["inventory_status"] = "OPEN"
    touch(block)
    return ok(block_json(block))


@bp.route("/group-sales/room-blocks/<block_id>/cutoff", methods=["POST"])
@endpoint([ROLE_RESERVATIONS_AGENT, ROLE_CONTRACT_ADMIN])
def cutoff_block(block_id):
    block = need_block(block_id)
    if block["inventory_status"] != "OPEN":
        fail("ERR_BLOCK_INVALID_STATE",
             "Cutoff is declared only from OPEN; the block is %s."
             % block["inventory_status"])
    if store.today() < parse_date_str(block["cutoff_date"]):
        fail("ERR_CUTOFF_DATE_NOT_REACHED",
             "The cutoff date of %s has not been reached." % block["cutoff_date"])
    cutoff_block_cascade(block)
    return ok(block_json(block))


@bp.route("/group-sales/room-blocks/<block_id>/waive-attrition", methods=["POST"])
@endpoint([ROLE_REVENUE_MANAGER])
def waive_attrition(block_id):
    body = body_json()
    reason = v_string(body, "waiver_reason", min_len=1, max_len=500)
    block = need_block(block_id)
    if block["billing_status"] in ("WAIVED", "SETTLED"):
        fail("ERR_BLOCK_ALREADY_BILLED",
             "The block's billing_status is already %s." % block["billing_status"])
    contract = contract_of_block(block)
    newest = newest_reconciliation(block["contract_id"])
    if block["billing_status"] == "UNBILLED":
        if newest is not None:
            fail("ERR_BLOCK_INVALID_STATE",
                 "A settlement already exists for the contract; the block must be "
                 "ATTRITION_ASSESSED to be waived.")
    else:
        if newest is None or newest["status"] != "DRAFT":
            fail("ERR_BLOCK_INVALID_STATE",
                 "The contract's newest settlement must still be DRAFT to waive.")
    block["billing_status"] = "WAIVED"
    block["waived_by_user_id"] = actor()
    block["waiver_reason"] = reason
    touch(block)
    if newest is not None and newest["status"] == "DRAFT":
        recompute_reconciliation(newest, contract)
        touch(newest)
    # PRD §2.7: "an attrition waiver ... bumps the contract's version".
    if contract is not None:
        touch(contract)
    return ok(block_json(block))
