"""Subrogation recovery demands."""

from flask import Blueprint

import calc
import serializers
from auth import require, SUBRO_READ
from common import filtered, lookup, paginate
from envelope import ok, created
from errors import fail
from shape import MISSING, f, filters, given, present, read_body
from store import base_row, db, touch

bp = Blueprint("subrogation", __name__)


@bp.post("/claims/<entity_id>/subrogation-demands")
def create_subrogation(entity_id):
    require("ClaimsManager", "ClaimsAdjuster")
    values = read_body([
        f("third_party_name", "string", required=True),
        f("at_fault_percentage", "int", required=True, minimum=1, maximum=100),
        f("basis_note", "string", required=True),
    ])
    claim = lookup("claims", entity_id)
    crash = db.crashes[claim["crash_id"]]
    if not crash["third_party_at_fault"]:
        fail("ERR_NO_THIRD_PARTY_AT_FAULT",
             "The underlying crash alleges no third-party fault")
    row = base_row()
    row["claim_id"] = claim["id"]
    row["third_party_name"] = values["third_party_name"]
    row["at_fault_percentage"] = values["at_fault_percentage"]
    row["basis_note"] = values["basis_note"]
    row["status"] = "DRAFT"
    row["recoverable_base_cents"] = None
    row["max_recoverable_cents"] = None
    row["recovered_amount_cents"] = None
    row["resolution_note"] = None
    row["resolved_at"] = None
    db.subrogation_demands[row["id"]] = row
    return created(serializers.subrogation_demand(row))


@bp.get("/claims/<entity_id>/subrogation-demands")
def list_claim_subrogations(entity_id):
    require(*SUBRO_READ)
    claim = lookup("claims", entity_id)
    criteria = filters({"status": calc.SUBRO_STATUSES})
    criteria["claim_id"] = claim["id"]
    return paginate(filtered("subrogation_demands", criteria),
                    serializers.subrogation_demand)


@bp.get("/subrogation-demands/<entity_id>")
def read_subrogation(entity_id):
    require(*SUBRO_READ)
    return ok(serializers.subrogation_demand(
        lookup("subrogation_demands", entity_id)))


@bp.get("/subrogation-demands")
def list_subrogations():
    require(*SUBRO_READ)
    criteria = filters({"claim_id": None, "status": calc.SUBRO_STATUSES})
    return paginate(filtered("subrogation_demands", criteria),
                    serializers.subrogation_demand)


@bp.post("/subrogation-demands/<entity_id>/resolve")
def resolve_subrogation(entity_id):
    require("ClaimsManager")
    values = read_body([
        f("resolution", "string", required=True, enum=calc.RESOLUTIONS),
        f("recovered_amount_cents", "int"),
        f("resolution_note", "string", required=True),
    ])
    resolution = values["resolution"]
    has_amount = present(values, "recovered_amount_cents")
    if resolution == "RECOVERED" and not has_amount:
        fail("ERR_INVALID_REQUEST",
             "recovered_amount_cents is required for a RECOVERED resolution")
    if resolution != "RECOVERED" and has_amount:
        fail("ERR_INVALID_REQUEST",
             "recovered_amount_cents must be absent for a %s resolution"
             % resolution)
    subro = lookup("subrogation_demands", entity_id)
    if subro["status"] != "READY_TO_PURSUE":
        fail("ERR_SUBROGATION_DEMAND_STATE_INVALID",
             "Only a READY_TO_PURSUE subrogation demand may be resolved")
    amount = given(values, "recovered_amount_cents")
    if resolution == "RECOVERED":
        if amount <= 0 or amount > subro["max_recoverable_cents"]:
            fail("ERR_RECOVERY_EXCEEDS_BASE",
                 "recovered_amount_cents must be positive and within the frozen "
                 "recovery ceiling")
    subro["status"] = resolution
    subro["recovered_amount_cents"] = amount if resolution == "RECOVERED" else None
    subro["resolution_note"] = values["resolution_note"]
    subro["resolved_at"] = db.now
    touch(subro)
    if resolution == "RECOVERED":
        claim = db.claims[subro["claim_id"]]
        claim["subrogation_recovered_cents"] += amount
        touch(claim)
    return ok(serializers.subrogation_demand(subro))
