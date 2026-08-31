"""PipelineNomination endpoints."""

from decimal import Decimal

from flask import Blueprint

import calc
import derived
import store
from auth import authenticate, deny_role, require_owner, require_role
from common import r2, r4
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import nomination_out
from validation import Field, parse_body, peek_body, validate

bp = Blueprint("nominations", __name__)

ZERO = Decimal("0")

NOMINATION_FIELDS = [
    Field("contract_id", "string", required=True),
    Field("plant_id", "string", required=True),
    Field("gas_day_start", "datetime", required=True),
    Field("gas_day_end", "datetime", required=True),
    Field("nominated_dth", "number", required=True, gt=0),
    Field("expected_contract_version", "integer", required=True),
]


@bp.post("/pipeline-nominations")
def create_nomination():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler"])
    body = parse_body()
    data = validate(body, NOMINATION_FIELDS)

    # Priority 50 - body foreign keys, left to right.
    contract = must_find("contract", data["contract_id"])
    plant = must_find("plant", data["plant_id"])

    # Priority 57 - interval direction.
    if data["gas_day_end"] <= data["gas_day_start"]:
        fail("ERR_INTERVAL_INVALID", "gas_day_end must be strictly after gas_day_start.")

    # Priority 70 - optimistic concurrency on the parent contract.
    if data["expected_contract_version"] != contract["version"]:
        fail(
            "ERR_STALE_CONTRACT_VERSION",
            "expected_contract_version does not match the contract's current version.",
        )

    # Priority 80 - the contract must be active.
    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The offtake contract is not ACTIVE.")

    # Priority 110 - the window must lie inside the contract term.
    if data["gas_day_start"] < contract["term_start"] or data["gas_day_end"] > contract["term_end"]:
        fail(
            "ERR_CONTRACT_TERM_WINDOW",
            "The nominated window escapes the contract term.",
        )

    # Priority 130 - contract MDQ, then pooled receipt-point capacity.
    if data["nominated_dth"] > contract["contract_mdq_dth_per_day"]:
        fail("ERR_CONTRACT_MDQ_EXCEEDED", "nominated_dth exceeds the contract's daily quantity.")

    rate = calc.hourly_rate(data["nominated_dth"], data["gas_day_start"], data["gas_day_end"])
    committed = ZERO
    for other in store.nominations.values():
        if other["plant_id"] != plant["id"]:
            continue
        if other["status"] not in ("DRAFT", "CONFIRMED", "SCHEDULED"):
            continue
        # Half-open intersection.
        if other["gas_day_start"] < data["gas_day_end"] and data["gas_day_start"] < other["gas_day_end"]:
            committed += other["hourly_rate_dth"]

    cap = plant["receipt_point_mdq_dth_per_day"] / Decimal("24")
    if r4(committed + rate) > r4(cap):
        fail(
            "ERR_RECEIPT_POINT_CAPACITY_EXCEEDED",
            "The pooled receipt-point hourly rate would be exceeded.",
        )

    row = store.new_row(
        contract_id=contract["id"],
        plant_id=plant["id"],
        gas_day_start=data["gas_day_start"],
        gas_day_end=data["gas_day_end"],
        nominated_dth=data["nominated_dth"],
        hourly_rate_dth=rate,
        status="DRAFT",
        committed_dth=r2(ZERO),
        delivered_dth=r2(ZERO),
        curtail_reason=None,
    )
    store.nominations[row["id"]] = row

    store.touch(contract)
    return object_response(nomination_out(row), 201)


@bp.get("/pipeline-nominations/<nomination_id>")
def read_nomination(nomination_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler", "PlantOperator", "Offtaker"])
    row = must_find("nomination", nomination_id)
    if caller.role == "Offtaker":
        require_owner(caller, row["contract_id"])
    return object_response(nomination_out(row))


@bp.get("/pipeline-nominations")
def list_nominations():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler", "PlantOperator"])
    limit, offset = pagination()
    rows = store.ordered(store.nominations.values())
    rows = filter_equal(rows, "contract_id", arg("contract_id"))
    rows = filter_equal(rows, "plant_id", arg("plant_id"))
    rows = filter_equal(rows, "status", arg("status"))
    return paginate(rows, limit, offset, nomination_out)


NOMINATION_STATUS_FIELDS = [
    Field(
        "to_status",
        "enum",
        required=True,
        values=("DRAFT", "CONFIRMED", "SCHEDULED", "DELIVERED", "CURTAILED", "CANCELLED"),
    ),
    Field("curtail_reason", "string", max_len=500),
]

NOMINATION_TRANSITIONS = {
    ("DRAFT", "CONFIRMED"),
    ("CONFIRMED", "CURTAILED"),
    ("SCHEDULED", "CURTAILED"),
    ("DRAFT", "CANCELLED"),
}


@bp.post("/pipeline-nominations/<nomination_id>/status")
def nomination_status(nomination_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler", "Offtaker"])

    requested = peek_body().get("to_status")
    if caller.role == "Offtaker" and requested is not None and requested != "CONFIRMED":
        deny_role("An Offtaker may only confirm a nomination.")
    if caller.role == "ProjectAdmin" and requested in ("CURTAILED", "CANCELLED"):
        deny_role("Curtailment and cancellation are CommercialScheduler prerogatives.")

    nomination = must_find("nomination", nomination_id)
    body = parse_body()
    data = validate(body, NOMINATION_STATUS_FIELDS)

    # Priority 60 - resource ownership.
    if caller.role == "Offtaker":
        require_owner(caller, nomination["contract_id"])

    target = data["to_status"]
    current = nomination["status"]

    # Priority 80 - state legality.
    if (current, target) not in NOMINATION_TRANSITIONS:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not a declared transition." % (current, target))

    if target == "CONFIRMED":
        contract = store.contracts.get(nomination["contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            fail("ERR_CONTRACT_NOT_ACTIVE", "The offtake contract is not ACTIVE.")
        derived.apply_changes(nomination, {"status": "CONFIRMED"})
    elif target == "CURTAILED":
        derived.apply_changes(
            nomination, {"status": "CURTAILED", "curtail_reason": data["curtail_reason"]}
        )
    else:  # CANCELLED
        derived.apply_changes(nomination, {"status": "CANCELLED"})

    return object_response(nomination_out(nomination))
