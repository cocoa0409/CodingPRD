"""Vineyards, blocks, the two block-nested event collections, and contracts."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import derive
import service
import store
from common import (ApiError, ZERO, dec_out, invalid, respond_list,
                    respond_object, r2, r3)
from validate import ALL_ROLES, F, auth, pagination, parse_payload

bp = Blueprint("core", __name__)

VARIETIES = ("CABERNET_SAUVIGNON", "CHARDONNAY", "PINOT_NOIR", "ZINFANDEL", "SYRAH")
ROOTSTOCKS = ("ROOTSTOCK_1103P", "ROOTSTOCK_110R", "ROOTSTOCK_SO4",
              "RIPARIA_GLOIRE", "ST_GEORGE")
TRELLISES = ("VSP", "SPRAWL", "QUADRILATERAL_CORDON", "HEAD_TRAINED", "GDC")
FARMING_STATUSES = ("ESTABLISHING", "BEARING", "REMOVED")
PEST_CODES = ("POWDERY_MILDEW", "VINE_MEALYBUG", "BOTRYTIS", "LEAFHOPPER")
YIELD_METHODS = ("CLUSTER_COUNT", "BERRY_SAMPLE")
CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")
SETTLEMENT_MODES = ("PROVISIONAL", "FINAL")


# --------------------------------------------------------------------------
# Vineyard
# --------------------------------------------------------------------------

VINEYARD_SCHEMA = [
    F("name", "string", min_len=1, max_len=120),
    F("owner_legal_name", "string", min_len=1, max_len=160),
    F("ava_region", "string", min_len=1, max_len=80),
    F("client_contact_email", "email", min_len=1),
]


@bp.route("/vineyards", methods=["POST"])
def create_vineyard():
    auth(["VineyardManager"])
    body = parse_payload(VINEYARD_SCHEMA)
    row = store.new_row()
    row.update({
        "name": body["name"],
        "owner_legal_name": body["owner_legal_name"],
        "ava_region": body["ava_region"],
        "client_contact_email": body["client_contact_email"],
    })
    store.vineyards[row["id"]] = row
    return respond_object(derive.serialize_vineyard(row), 201)


@bp.route("/vineyards/<vineyard_id>", methods=["GET"])
def read_vineyard(vineyard_id):
    user_id, role = auth(["VineyardManager", "Controller", "ClientOwner"])
    vineyard = service.get_vineyard(vineyard_id)
    service.require_vineyard_owner(role, user_id, vineyard["id"])
    return respond_object(derive.serialize_vineyard(vineyard))


# --------------------------------------------------------------------------
# Block
# --------------------------------------------------------------------------

BLOCK_SCHEMA = [
    F("vineyard_id", "id", min_len=1),
    F("block_code", "string", min_len=1, max_len=24),
    F("variety", "enum", values=VARIETIES),
    F("clone", "string", min_len=1, max_len=24),
    F("rootstock", "enum", values=ROOTSTOCKS),
    F("trellis_system", "enum", values=TRELLISES),
    F("planting_year", "integer", ge=1900, le=2100),
    F("vine_spacing_ft", "number", gt=0),
    F("row_spacing_ft", "number", gt=0),
    F("acres", "number", gt=0),
    F("replaces_block_id", "id", required=False, nullable=True, min_len=1),
]


@bp.route("/blocks", methods=["POST"])
def create_block():
    auth(["VineyardManager"])
    body = parse_payload(BLOCK_SCHEMA)

    # rung 10 — body references in the fixed order of PRD 2.5
    vineyard = service.get_vineyard(body["vineyard_id"])
    predecessor = None
    if "replaces_block_id" in body:
        predecessor = service.get_block(body["replaces_block_id"])

    # rung 15
    if predecessor is not None:
        service.require_block_live(predecessor)

    # rung 19 — duplicate code precedes ranch mismatch
    for other in store.blocks.values():
        if other["vineyard_id"] == vineyard["id"] and other["block_code"] == body["block_code"]:
            raise ApiError("ERR_DUPLICATE_BLOCK_CODE", 409)
    if predecessor is not None and predecessor["vineyard_id"] != vineyard["id"]:
        raise ApiError("ERR_VINEYARD_MISMATCH", 409)

    vines_per_acre, vine_count = calc.vine_geometry(
        body["vine_spacing_ft"], body["row_spacing_ft"], body["acres"])

    row = store.new_row()
    row.update({
        "vineyard_id": vineyard["id"],
        "contract_id": None,
        "replaces_block_id": predecessor["id"] if predecessor is not None else None,
        "block_code": body["block_code"],
        "variety": body["variety"],
        "clone": body["clone"],
        "rootstock": body["rootstock"],
        "trellis_system": body["trellis_system"],
        "planting_year": body["planting_year"],
        "vine_spacing_ft": body["vine_spacing_ft"],
        "row_spacing_ft": body["row_spacing_ft"],
        "acres": body["acres"],
        "contracted_acres": None,
        "per_acre_fee_override": None,
        "vines_per_acre": vines_per_acre,
        "vine_count": vine_count,
        "farming_status": "ESTABLISHING",
    })
    store.blocks[row["id"]] = row

    if predecessor is not None:
        predecessor["farming_status"] = "REMOVED"
        store.touch(predecessor)

    return respond_object(derive.serialize_block(row), 201)


BLOCK_READ_ROLES = ["VineyardManager", "Agronomist", "Applicator",
                    "ComplianceOfficer", "Controller", "CrewSupervisor"]


@bp.route("/blocks/<block_id>", methods=["GET"])
def read_block(block_id):
    auth(BLOCK_READ_ROLES)
    block = service.get_block(block_id)
    return respond_object(derive.serialize_block(block))


@bp.route("/blocks", methods=["GET"])
def list_blocks():
    auth(BLOCK_READ_ROLES)
    rows = service.filtered(store.blocks, (
        ("vineyard_id", "vineyard_id"),
        ("contract_id", "contract_id"),
        ("replaces_block_id", "replaces_block_id"),
        ("farming_status", "farming_status"),
    ))
    items, limit, offset, total = service.page(rows, derive.serialize_block)
    return respond_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# PestObservation (block-nested)
# --------------------------------------------------------------------------

OBSERVATION_SCHEMA = [
    F("pest_code", "enum", values=PEST_CODES),
    F("incidence_pct", "number", ge=0, le=100),
    F("severity_index", "integer", ge=0, le=5),
    F("scouting_note", "string", required=False, nullable=True,
      max_len=500, blank_ok=True),
]


@bp.route("/blocks/<block_id>/pest-observations", methods=["POST"])
def create_observation(block_id):
    user_id, _role = auth(["Agronomist"])
    body = parse_payload(OBSERVATION_SCHEMA)
    block = service.get_block(block_id)
    service.require_block_live(block)

    threshold = calc.ACTION_THRESHOLD_PCT[body["pest_code"]]
    row = store.new_row(versioned=False)
    row.update({
        "block_id": block["id"],
        "pest_code": body["pest_code"],
        "incidence_pct": body["incidence_pct"],
        "severity_index": body["severity_index"],
        "scouting_note": body.get("scouting_note"),
        "observed_at": store.now_utc(),
        "scout_user_id": user_id,
        "action_threshold_pct": threshold,
        "exceeds_threshold": body["incidence_pct"] >= threshold,
    })
    store.pest_observations[row["id"]] = row
    return respond_object(derive.serialize_observation(row), 201)


@bp.route("/blocks/<block_id>/pest-observations", methods=["GET"])
def list_observations(block_id):
    auth(["VineyardManager", "Agronomist", "Applicator", "ComplianceOfficer"])
    limit, offset = pagination()
    block = service.get_block(block_id)
    rows = [o for o in store.pest_observations.values() if o["block_id"] == block["id"]]
    items, limit, offset, total = service.page_rows(
        rows, derive.serialize_observation, limit, offset,
        key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]), reverse=True)
    return respond_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# YieldEstimate (block-nested)
# --------------------------------------------------------------------------

ESTIMATE_SCHEMA = [
    F("method", "enum", values=YIELD_METHODS),
    F("sample_date", "date"),
    F("avg_clusters_per_vine", "number", ge=0),
    F("avg_cluster_weight_lb", "number", required=False, gt=0),
    F("berries_per_cluster", "integer", required=False, gt=0),
    F("avg_berry_weight_g", "number", required=False, gt=0),
    F("days_to_harvest", "integer", required=False, ge=0),
]

BERRY_FIELDS = ("berries_per_cluster", "avg_berry_weight_g", "days_to_harvest")


@bp.route("/blocks/<block_id>/yield-estimates", methods=["POST"])
def create_estimate(block_id):
    auth(["VineyardManager", "Agronomist"])
    body = parse_payload(ESTIMATE_SCHEMA)

    # rung 5 — method-conditional field coherence
    if body["method"] == "CLUSTER_COUNT":
        if "avg_cluster_weight_lb" not in body:
            raise invalid("avg_cluster_weight_lb is required for a CLUSTER_COUNT estimate.")
        for name in BERRY_FIELDS:
            if name in body:
                raise invalid("Field '%s' must be absent for a CLUSTER_COUNT estimate." % name)
    else:
        for name in BERRY_FIELDS:
            if name not in body:
                raise invalid("Field '%s' is required for a BERRY_SAMPLE estimate." % name)
        if "avg_cluster_weight_lb" in body:
            raise invalid("avg_cluster_weight_lb must be absent for a BERRY_SAMPLE estimate.")

    block = service.get_block(block_id)
    service.require_block_live(block)

    frozen_vines = block["vine_count"]
    estimated_tons, per_acre = calc.yield_estimate_tons(body, frozen_vines, block["acres"])

    row = store.new_row(versioned=False)
    row.update({
        "block_id": block["id"],
        "method": body["method"],
        "sample_date": body["sample_date"],
        "avg_clusters_per_vine": body["avg_clusters_per_vine"],
        "avg_cluster_weight_lb": body.get("avg_cluster_weight_lb"),
        "berries_per_cluster": body.get("berries_per_cluster"),
        "avg_berry_weight_g": body.get("avg_berry_weight_g"),
        "days_to_harvest": body.get("days_to_harvest"),
        "vine_count_at_estimate": frozen_vines,
        "estimated_tons": estimated_tons,
        "estimated_tons_per_acre": per_acre,
    })
    store.yield_estimates[row["id"]] = row
    store.touch(block)
    return respond_object(derive.serialize_estimate(row), 201)


@bp.route("/blocks/<block_id>/yield-estimates", methods=["GET"])
def list_estimates(block_id):
    auth(["VineyardManager", "Agronomist", "Controller"])
    limit, offset = pagination()
    block = service.get_block(block_id)
    rows = [e for e in store.yield_estimates.values() if e["block_id"] == block["id"]]
    items, limit, offset, total = service.page_rows(
        rows, derive.serialize_estimate, limit, offset,
        key=lambda e: (e["sample_date"], e["created_at"], e["_seq"]), reverse=True)
    return respond_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# CustomFarmingContract
# --------------------------------------------------------------------------

CONTRACT_SCHEMA = [
    F("vineyard_id", "id", min_len=1),
    F("per_acre_annual_fee", "number", ge=0),
    F("cost_pass_through_pct", "number", ge=0, le=1),
    F("quality_incentive_per_ton", "number", ge=0),
    F("quality_brix_threshold", "number", gt=0),
    F("period_overhead_pool", "number", ge=0),
    F("period_start", "date"),
    F("period_end", "date"),
]


@bp.route("/contracts", methods=["POST"])
def create_contract():
    auth(["VineyardManager"])
    body = parse_payload(CONTRACT_SCHEMA)
    if body["period_end"] < body["period_start"]:
        raise invalid("period_end must be the same as or later than period_start.")
    vineyard = service.get_vineyard(body["vineyard_id"])

    row = store.new_row()
    row.update({
        "vineyard_id": vineyard["id"],
        "per_acre_annual_fee": body["per_acre_annual_fee"],
        "cost_pass_through_pct": body["cost_pass_through_pct"],
        "quality_incentive_per_ton": body["quality_incentive_per_ton"],
        "quality_brix_threshold": body["quality_brix_threshold"],
        "period_overhead_pool": body["period_overhead_pool"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "contract_status": "DRAFT",
        "client_signature_name": None,
        "settled_period_count": 0,
        "last_settlement_total": None,
    })
    store.contracts[row["id"]] = row
    return respond_object(derive.serialize_contract(row), 201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    user_id, role = auth(["VineyardManager", "Controller", "ClientOwner"])
    contract = service.get_contract(contract_id)
    service.require_vineyard_owner(role, user_id, contract["vineyard_id"])
    return respond_object(derive.serialize_contract(contract))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    user_id, role = auth(["VineyardManager", "Controller", "ClientOwner"])
    limit, offset = pagination()
    rows = list(store.contracts.values())
    wanted_vineyard = request.args.get("vineyard_id")
    if role == "ClientOwner":
        if wanted_vineyard is not None and wanted_vineyard != user_id:
            raise ApiError("ERR_VINEYARD_OWNERSHIP_REQUIRED", 403)
        wanted_vineyard = user_id
    if wanted_vineyard is not None:
        rows = [c for c in rows if c["vineyard_id"] == wanted_vineyard]
    wanted_status = request.args.get("contract_status")
    if wanted_status is not None:
        rows = [c for c in rows if c["contract_status"] == wanted_status]
    items, limit, offset, total = service.page_rows(
        rows, derive.serialize_contract, limit, offset)
    return respond_list(items, limit, offset, total)


ENROLL_SCHEMA = [
    F("block_id", "id", min_len=1),
    F("contracted_acres", "number", ge=0),
    F("per_acre_fee_override", "number", required=False, nullable=True, ge=0),
]


@bp.route("/contracts/<contract_id>/enroll-block", methods=["POST"])
def enroll_block(contract_id):
    auth(["VineyardManager"])
    body = parse_payload(ENROLL_SCHEMA)
    contract = service.get_contract(contract_id)
    block = service.get_block(body["block_id"])

    if contract["contract_status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT", 409)
    if block["vineyard_id"] != contract["vineyard_id"]:
        raise ApiError("ERR_VINEYARD_MISMATCH", 409)
    if block["contract_id"] is not None:
        raise ApiError("ERR_BLOCK_ALREADY_ENROLLED", 409)

    block["contract_id"] = contract["id"]
    block["contracted_acres"] = body["contracted_acres"]
    block["per_acre_fee_override"] = body.get("per_acre_fee_override")
    store.touch(block)
    store.touch(contract)
    return respond_object(derive.serialize_block(block))


ACTIVATE_SCHEMA = [F("client_signature_name", "string", min_len=1, max_len=160)]


@bp.route("/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    user_id, role = auth(["ClientOwner"])
    body = parse_payload(ACTIVATE_SCHEMA)
    contract = service.get_contract(contract_id)
    service.require_vineyard_owner(role, user_id, contract["vineyard_id"])

    if contract["contract_status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT", 409)
    if len(derive.contract_blocks(contract["id"])) < 1:
        raise ApiError("ERR_NO_ENROLLED_BLOCKS", 409)

    contract["contract_status"] = "ACTIVE"
    contract["client_signature_name"] = body["client_signature_name"]
    store.touch(contract)
    return respond_object(derive.serialize_contract(contract))


SETTLE_SCHEMA = [
    F("settlement_mode", "enum", values=SETTLEMENT_MODES),
    F("period_end_date", "date"),
]


@bp.route("/contracts/<contract_id>/settle-period", methods=["POST"])
def settle_period(contract_id):
    auth(["Controller"])
    body = parse_payload(SETTLE_SCHEMA)
    contract = service.get_contract(contract_id)
    if contract["contract_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)

    figures = service.settlement_statement(
        contract, body["settlement_mode"], body["period_end_date"])
    statement = {
        "contract_id": contract["id"],
        "settlement_mode": body["settlement_mode"],
        "period_end_date": body["period_end_date"],
        "direct_cost_total": dec_out(figures["direct_cost_total"]),
        "management_fee_base": dec_out(figures["management_fee_base"]),
        "pass_through": dec_out(figures["pass_through"]),
        "tier_basis": dec_out(figures["tier_basis"]),
        "volume_discount_pct": dec_out(figures["volume_discount_pct"]),
        "volume_discount": dec_out(figures["volume_discount"]),
        "quality_incentive": dec_out(figures["quality_incentive"]),
        "total_billable": dec_out(figures["total_billable"]),
        "contract_status": contract["contract_status"],
    }
    return respond_object(statement)
