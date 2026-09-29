"""QualificationItem endpoints and the allowance ledger (PRD 3.3)."""
from flask import Blueprint

import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, sorted_rows, touch
from errors import ApiError, bad_request
from money import MONEY_ZERO, RATIO_ZERO, q2, q4
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROGRAM_ADMIN,
    endpoint,
)

bp = Blueprint("qualification_items", __name__)

ITEM_TYPES = ("ASSUMPTION", "ALLOWANCE", "CLARIFICATION", "EXCLUSION")
ITEM_STATUSES = ("OPEN", "PARTIALLY_RECONCILED", "FULLY_RECONCILED")
ALLOWANCE_ONLY_FIELDS = ("allowance_amount", "allocated_units", "unit_of_measure")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


@bp.route("/qualification-items", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_qualification_item():
    body = v.json_body()
    gmp_proposal_id = v.get_id(body, "gmp_proposal_id", required=True)
    item_type = v.get_enum(body, "item_type", ITEM_TYPES, required=True)
    text = v.get_str(body, "text", required=True, min_len=1, max_len=1000)

    if item_type == "ALLOWANCE":
        allowance_amount = v.get_money(
            body, "allowance_amount", required=True, positive=True
        )
        allocated_units = v.get_units(
            body, "allocated_units", required=True, positive=True
        )
        unit_of_measure = v.get_str(
            body, "unit_of_measure", required=True, min_len=1, max_len=200
        )
        allowance_unit_rate = q4(allowance_amount / allocated_units)
        remaining_units = allocated_units
    else:
        for name in ALLOWANCE_ONLY_FIELDS:
            if v.present(body, name):
                raise bad_request(
                    "field '%s' is only permitted when item_type is ALLOWANCE" % name
                )
        allowance_amount = None
        allocated_units = None
        unit_of_measure = None
        allowance_unit_rate = RATIO_ZERO
        remaining_units = MONEY_ZERO

    proposal = lookups.proposal(gmp_proposal_id)
    if proposal["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError(
            "ERR_PROPOSAL_STATE_INVALID",
            "parent proposal status is %s; qualification items may only be added "
            "while it is DRAFT or RETURNED_FOR_REVISION" % proposal["status"],
        )

    item = new_record({
        "gmp_proposal_id": proposal["id"],
        "item_type": item_type,
        "text": text,
        "allowance_amount": allowance_amount,
        "allocated_units": allocated_units,
        "unit_of_measure": unit_of_measure,
        "allowance_unit_rate": allowance_unit_rate,
        "remaining_units": remaining_units,
        "reconciled_units": MONEY_ZERO,
        "reconciled_amount": MONEY_ZERO,
        "variance_amount": MONEY_ZERO,
        "reconciliation_seq": 0,
        "last_action": "NONE",
        "status": "OPEN",
        "_bookings": [],
    })
    db.qualification_items[item["id"]] = item
    return resp.created(serializers.qualification_item(item))


def _rederive_status(item):
    if item["allocated_units"] is None:
        item["status"] = "OPEN"
        return
    if item["reconciled_units"] == MONEY_ZERO:
        item["status"] = "OPEN"
    elif item["reconciled_units"] == item["allocated_units"]:
        item["status"] = "FULLY_RECONCILED"
    else:
        item["status"] = "PARTIALLY_RECONCILED"


def _rederive_variance(item):
    item["variance_amount"] = q2(
        item["reconciled_amount"]
        - q2(item["reconciled_units"] * item["allowance_unit_rate"])
    )


@bp.route("/qualification-items/<qid>/allowance-reconciliation", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def allowance_reconciliation(qid):
    body = v.json_body()
    action = v.get_enum(body, "action", ("RECONCILE", "REVERSE"), required=True)
    units = None
    actual_unit_cost = None
    overrun_authorized = False
    if action == "RECONCILE":
        units = v.get_units(body, "units", required=True)
        actual_unit_cost = v.get_unit_rate(body, "actual_unit_cost", required=True)
        overrun_authorized = v.get_bool(
            body, "overrun_authorized", required=False, default=False
        )

    item = lookups.qualification_item(qid)

    if action == "RECONCILE":
        if units > item["remaining_units"]:
            raise ApiError(
                "ERR_ALLOWANCE_UNITS_EXCEEDED",
                "requested units %s exceed remaining_units %s"
                % (units, item["remaining_units"]),
            )
        if actual_unit_cost > item["allowance_unit_rate"] and not overrun_authorized:
            raise ApiError(
                "ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED",
                "actual_unit_cost %s exceeds allowance_unit_rate %s without "
                "overrun_authorized" % (actual_unit_cost, item["allowance_unit_rate"]),
            )
        booked = q2(units * actual_unit_cost)
        item["reconciled_units"] = q2(item["reconciled_units"] + units)
        item["remaining_units"] = q2(item["remaining_units"] - units)
        item["reconciled_amount"] = q2(item["reconciled_amount"] + booked)
        item["reconciliation_seq"] = item["reconciliation_seq"] + 1
        item["last_action"] = "RECONCILE"
        item["_bookings"].append({"units": units, "amount": booked})
    else:
        if item["last_action"] != "RECONCILE" or item["reconciliation_seq"] < 1 \
                or not item["_bookings"]:
            raise ApiError(
                "ERR_ALLOWANCE_REVERSAL_INVALID",
                "there is no immediately preceding RECONCILE booking to reverse",
            )
        booking = item["_bookings"].pop()
        item["reconciled_units"] = q2(item["reconciled_units"] - booking["units"])
        item["remaining_units"] = q2(item["remaining_units"] + booking["units"])
        item["reconciled_amount"] = q2(item["reconciled_amount"] - booking["amount"])
        item["last_action"] = "REVERSE"

    _rederive_variance(item)
    _rederive_status(item)
    touch(item)
    return resp.ok(serializers.qualification_item(item))


@bp.route("/qualification-items", methods=["GET"])
@endpoint(*READ_ROLES)
def list_qualification_items():
    limit, offset = v.pagination()
    proposal_id = v.query_filter("gmp_proposal_id")
    item_type = v.query_filter("item_type", ITEM_TYPES)
    status = v.query_filter("status", ITEM_STATUSES)
    rows = []
    for row in db.qualification_items.values():
        if proposal_id is not None and row["gmp_proposal_id"] != proposal_id:
            continue
        if item_type is not None and row["item_type"] != item_type:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing(
        [serializers.qualification_item(r) for r in page], limit, offset, total
    )


@bp.route("/qualification-items/<qid>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_qualification_item(qid):
    return resp.ok(serializers.qualification_item(lookups.qualification_item(qid)))
