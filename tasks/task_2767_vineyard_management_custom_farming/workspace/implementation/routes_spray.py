"""Spray records: recommendation, application (the deepest cascade) and
compliance countersignature."""

from datetime import timedelta

from flask import Blueprint

import calc
import derive
import service
import store
from common import ApiError, respond_list, respond_object
from validate import F, auth, parse_payload

bp = Blueprint("spray", __name__)

SPRAY_ROLES = ["VineyardManager", "Agronomist", "Applicator", "ComplianceOfficer"]

SPRAY_SCHEMA = [
    F("block_id", "id", min_len=1),
    F("farming_plan_id", "id", min_len=1),
    F("pest_observation_id", "id", min_len=1),
    F("product_name", "string", min_len=1, max_len=120),
    F("active_ingredient", "string", min_len=1, max_len=120),
    F("rei_hours", "integer", ge=0),
    F("phi_days", "integer", ge=0),
    F("rate_per_acre", "number", gt=0),
    F("material_cost", "number", ge=0),
]


@bp.route("/spray-records", methods=["POST"])
def create_spray():
    user_id, _role = auth(["Agronomist"])
    body = parse_payload(SPRAY_SCHEMA)

    block = service.get_block(body["block_id"])
    plan = service.get_plan(body["farming_plan_id"])
    observation = service.get_observation(body["pest_observation_id"])

    service.require_plan_approved(plan)
    service.require_block_live(block)

    # rung 17 — the pest action threshold behind the recommendation
    if not observation["exceeds_threshold"]:
        raise ApiError("ERR_ACTION_THRESHOLD_NOT_MET", 409)

    # rung 19
    if plan["block_id"] != block["id"]:
        raise ApiError("ERR_PLAN_BLOCK_MISMATCH", 409)

    row = store.new_row()
    row.update({
        "block_id": block["id"],
        "farming_plan_id": plan["id"],
        "pest_observation_id": observation["id"],
        "product_name": body["product_name"],
        "active_ingredient": body["active_ingredient"],
        "rei_hours": body["rei_hours"],
        "phi_days": body["phi_days"],
        "rate_per_acre": body["rate_per_acre"],
        "material_cost": body["material_cost"],
        "spray_status": "RECOMMENDED",
        "recommended_by_user_id": user_id,
        "applied_by_user_id": None,
        "verified_by_user_id": None,
        "applicator_license_no": None,
        "wind_speed_mph": None,
        "applied_at": None,
        "rei_clear_at": None,
        "phi_clear_at": None,
    })
    store.spray_records[row["id"]] = row
    return respond_object(derive.serialize_spray(row), 201)


@bp.route("/spray-records/<spray_id>", methods=["GET"])
def read_spray(spray_id):
    auth(SPRAY_ROLES)
    spray = service.get_spray(spray_id)
    return respond_object(derive.serialize_spray(spray))


@bp.route("/spray-records", methods=["GET"])
def list_sprays():
    auth(SPRAY_ROLES)
    rows = service.filtered(store.spray_records, (
        ("block_id", "block_id"),
        ("farming_plan_id", "farming_plan_id"),
        ("pest_observation_id", "pest_observation_id"),
        ("spray_status", "spray_status"),
    ))
    items, limit, offset, total = service.page(rows, derive.serialize_spray)
    return respond_list(items, limit, offset, total)


APPLY_SCHEMA = [
    F("applicator_license_no", "string", min_len=1, max_len=120),
    F("wind_speed_mph", "number", ge=0),
    F("expected_block_version", "integer", ge=1),
]


@bp.route("/spray-records/<spray_id>/apply", methods=["POST"])
def apply_spray(spray_id):
    user_id, _role = auth(["Applicator"])
    body = parse_payload(APPLY_SCHEMA)
    spray = service.get_spray(spray_id)
    block = store.blocks[spray["block_id"]]

    # rung 13 — optimistic concurrency on the block
    if body["expected_block_version"] != block["version"]:
        raise ApiError("ERR_STALE_BLOCK_VERSION", 412)

    # rung 15
    service.require_block_live(block)
    if spray["spray_status"] != "RECOMMENDED":
        raise ApiError("ERR_SPRAY_NOT_RECOMMENDED", 409)

    # rung 16
    service.require_distinct(user_id, [spray["recommended_by_user_id"]])

    applied_at = store.now_utc()
    spray["spray_status"] = "APPLIED"
    spray["applied_by_user_id"] = user_id
    spray["applicator_license_no"] = body["applicator_license_no"]
    spray["wind_speed_mph"] = body["wind_speed_mph"]
    spray["applied_at"] = applied_at
    spray["rei_clear_at"] = applied_at + timedelta(hours=spray["rei_hours"])
    spray["phi_clear_at"] = applied_at + timedelta(hours=spray["phi_days"] * 24)
    store.touch(spray)

    service.cascade_spray_applied(spray, block)
    return respond_object(derive.serialize_spray(spray))


VERIFY_SCHEMA = [F("verification_note", "string", required=False, nullable=True,
                   max_len=1000, blank_ok=True)]


@bp.route("/spray-records/<spray_id>/verify", methods=["POST"])
def verify_spray(spray_id):
    user_id, _role = auth(["ComplianceOfficer"])
    parse_payload(VERIFY_SCHEMA)
    spray = service.get_spray(spray_id)

    if spray["spray_status"] != "APPLIED":
        raise ApiError("ERR_SPRAY_NOT_APPLIED", 409)
    service.require_distinct(
        user_id, [spray["recommended_by_user_id"], spray["applied_by_user_id"]])

    spray["spray_status"] = "VERIFIED"
    spray["verified_by_user_id"] = user_id
    store.touch(spray)
    return respond_object(derive.serialize_spray(spray))
