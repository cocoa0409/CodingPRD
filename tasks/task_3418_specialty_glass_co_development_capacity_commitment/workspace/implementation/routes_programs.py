"""Program endpoints: create, get, list, and the lifecycle actions."""
from flask import Blueprint, request

import cascades
import clock
import serializers
import store
from errors import (
    ApiError,
    ERR_DESIGN_FREEZE_PASSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NO_QUALIFIED_COMPOSITION,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_PROGRAM_MANAGER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_enum,
    as_datetime,
    pagination_args,
)

bp = Blueprint("programs", __name__)

MARKETS = {"CONSUMER_ELECTRONICS", "AUTOMOTIVE", "PHARMA_PACKAGING", "ARCHITECTURAL"}
CONF_TIERS = {"STANDARD_CONFIDENTIAL", "HIGH_CONFIDENTIAL"}
PROGRAM_STATUSES = {
    "DRAFT",
    "NDA_EXECUTED",
    "COMPOSITION_TUNING",
    "QUALIFICATION",
    "DESIGN_FROZEN",
    "CLOSED",
    "TERMINATED",
}
TERMINABLE = {"DRAFT", "NDA_EXECUTED", "COMPOSITION_TUNING", "QUALIFICATION", "DESIGN_FROZEN"}
OPEN_COMMITMENT_STATUSES = {"PROPOSED", "SIGNED", "COUNTERSIGNED", "SECURED", "BREACH_WATCH"}


def _get_program_or_404(program_id):
    program = store.programs.get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, "Program not found")
    return program


@bp.route("/glass/programs", methods=["POST"])
def create_program():
    authenticate({ROLE_PROGRAM_MANAGER})
    body = get_body()
    device_maker_id = as_str(req_field(body, "device_maker_id"), "device_maker_id")
    name = as_str(req_field(body, "name"), "name")
    primary_market = as_enum(req_field(body, "primary_market"), "primary_market", MARKETS)
    tier = body.get("confidentiality_tier")
    if tier is not None:
        tier = as_enum(tier, "confidentiality_tier", CONF_TIERS)
    else:
        tier = "STANDARD_CONFIDENTIAL"
    if device_maker_id not in store.device_makers:
        raise ApiError(ERR_NOT_FOUND, "Device maker not found")
    program = store.base_fields()
    program.update(
        {
            "device_maker_id": device_maker_id,
            "name": name,
            "primary_market": primary_market,
            "confidentiality_tier": tier,
            "status": "DRAFT",
            "nda_reference": None,
            "design_freeze_date": None,
        }
    )
    store.programs[program["id"]] = program
    return success_object(serializers.program(program), status=201)


@bp.route("/glass/programs/<programId>", methods=["GET"])
def get_program(programId):
    authenticate(ALL_ROLES)
    return success_object(serializers.program(_get_program_or_404(programId)))


@bp.route("/glass/programs", methods=["GET"])
def list_programs():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_maker = request.args.get("device_maker_id")
    f_status = request.args.get("status")
    items = list(store.programs.values())
    if f_maker is not None:
        items = [p for p in items if p["device_maker_id"] == f_maker]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.program(p) for p in page], limit, offset, total)


@bp.route("/glass/programs/<programId>/execute-nda", methods=["POST"])
def execute_nda(programId):
    authenticate({ROLE_PROGRAM_MANAGER})
    body = get_body()
    nda_reference = as_str(req_field(body, "nda_reference"), "nda_reference")
    program = _get_program_or_404(programId)
    if program["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "execute-nda requires DRAFT")
    program["status"] = "NDA_EXECUTED"
    program["nda_reference"] = nda_reference
    store.touch(program)
    return success_object(serializers.program(program))


@bp.route("/glass/programs/<programId>/begin-qualification", methods=["POST"])
def begin_qualification(programId):
    authenticate({ROLE_PROGRAM_MANAGER})
    body = get_body()
    freeze_date = as_datetime(req_field(body, "design_freeze_date"), "design_freeze_date")
    # Shape gate (PRD 2.8 row 3): the deadline must lie strictly in the future.
    if freeze_date <= clock.now():
        raise ApiError(
            ERR_INVALID_REQUEST, "design_freeze_date must lie strictly in the future"
        )
    program = _get_program_or_404(programId)
    if program["status"] != "COMPOSITION_TUNING":
        raise ApiError(ERR_INVALID_STATE, "begin-qualification requires COMPOSITION_TUNING")
    program["status"] = "QUALIFICATION"
    program["design_freeze_date"] = freeze_date
    store.touch(program)
    return success_object(serializers.program(program))


@bp.route("/glass/programs/<programId>/rework", methods=["POST"])
def rework(programId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()
    program = _get_program_or_404(programId)
    if program["status"] != "QUALIFICATION":
        raise ApiError(ERR_INVALID_STATE, "rework requires QUALIFICATION")
    program["status"] = "COMPOSITION_TUNING"
    program["design_freeze_date"] = None
    store.touch(program)
    return success_object(serializers.program(program))


@bp.route("/glass/programs/<programId>/freeze-design", methods=["POST"])
def freeze_design(programId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()
    program = _get_program_or_404(programId)
    if program["status"] != "QUALIFICATION":
        raise ApiError(ERR_INVALID_STATE, "freeze-design requires QUALIFICATION")
    # Priority 11: at or before the deadline is allowed (inclusive boundary).
    if clock.now() > program["design_freeze_date"]:
        raise ApiError(ERR_DESIGN_FREEZE_PASSED, "design_freeze_date has passed")
    qualified = any(
        c["program_id"] == program["id"] and c["status"] in ("QUALIFIED", "LOCKED")
        for c in store.compositions.values()
    )
    if not qualified:
        raise ApiError(
            ERR_NO_QUALIFIED_COMPOSITION,
            "freeze-design requires a QUALIFIED or LOCKED composition",
        )
    program["status"] = "DESIGN_FROZEN"
    store.touch(program)
    return success_object(serializers.program(program))


@bp.route("/glass/programs/<programId>/close", methods=["POST"])
def close_program(programId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()
    program = _get_program_or_404(programId)
    if program["status"] != "DESIGN_FROZEN":
        raise ApiError(ERR_INVALID_STATE, "close requires DESIGN_FROZEN")
    comp_ids = {
        c["id"] for c in store.compositions.values() if c["program_id"] == program["id"]
    }
    in_flight_campaign = any(
        c["composition_id"] in comp_ids and c["status"] in ("SCHEDULED", "RUNNING")
        for c in store.campaigns.values()
    )
    open_commitment = any(
        c["program_id"] == program["id"] and c["status"] in OPEN_COMMITMENT_STATUSES
        for c in store.commitments.values()
    )
    if in_flight_campaign or open_commitment:
        raise ApiError(
            ERR_INVALID_STATE, "close requires no in-flight campaigns or commitments"
        )
    program["status"] = "CLOSED"
    store.touch(program)
    return success_object(serializers.program(program))


@bp.route("/glass/programs/<programId>/terminate", methods=["POST"])
def terminate_program(programId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()  # optional reason; accepted but not persisted
    program = _get_program_or_404(programId)
    if program["status"] not in TERMINABLE:
        raise ApiError(ERR_INVALID_STATE, "terminate requires a non-terminal program")
    program["status"] = "TERMINATED"
    store.touch(program)
    # Cascade hop 1: release every non-terminal commitment (refund prepayment).
    for c in list(store.commitments.values()):
        if c["program_id"] == program["id"] and c["status"] in OPEN_COMMITMENT_STATUSES:
            cascades.release_commitment(c, release_allocations=False)
    # Cascade hop 1 (cont.): cancel every SCHEDULED campaign over the program's
    # compositions; hop 2 releases their RESERVED allocations. Commitments of
    # this program are all RELEASED by now, so the breach recompute finds none
    # still SECURED (scaffold note on terminate).
    comp_ids = {
        c["id"] for c in store.compositions.values() if c["program_id"] == program["id"]
    }
    to_cancel = [
        c
        for c in store.campaigns.values()
        if c["composition_id"] in comp_ids and c["status"] == "SCHEDULED"
    ]
    cascades.cancel_campaigns_batched(to_cancel)
    return success_object(serializers.program(program))
