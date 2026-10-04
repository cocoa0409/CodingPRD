"""Composition endpoints: create, get, list, lock, retire (+ cascade)."""
from flask import Blueprint, request

import cascades
import serializers
import store
from errors import (
    ApiError,
    ERR_COMPOSITION_CODE_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NDA_REQUIRED,
    ERR_NOT_FOUND,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_PROGRAM_MANAGER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_number,
    pagination_args,
)

bp = Blueprint("compositions", __name__)

COMPOSITION_STATUSES = {"EXPERIMENTAL", "TUNED", "QUALIFIED", "LOCKED", "RETIRED"}
RETIRABLE = {"EXPERIMENTAL", "TUNED", "QUALIFIED"}


def _get_composition_or_404(composition_id):
    composition = store.compositions.get(composition_id)
    if composition is None:
        raise ApiError(ERR_NOT_FOUND, "Composition not found")
    return composition


@bp.route("/glass/compositions", methods=["POST"])
def create_composition():
    authenticate({ROLE_PROGRAM_MANAGER})
    body = get_body()
    program_id = as_str(req_field(body, "program_id"), "program_id")
    code = as_str(req_field(body, "composition_code"), "composition_code")
    multiplier = as_number(
        req_field(body, "complexity_multiplier"), "complexity_multiplier"
    )
    if multiplier < 1.0 or multiplier > 2.5:
        raise ApiError(
            ERR_INVALID_REQUEST, "complexity_multiplier must lie within [1.0, 2.5]"
        )
    program = store.programs.get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, "Program not found")
    # Confidentiality gate (priority 8): program must be past DRAFT.
    if program["status"] == "DRAFT":
        raise ApiError(ERR_NDA_REQUIRED, "Program NDA must be executed first")
    # composition_code unique within the program (priority 21).
    for c in store.compositions.values():
        if c["program_id"] == program["id"] and c["composition_code"] == code:
            raise ApiError(
                ERR_COMPOSITION_CODE_CONFLICT,
                "composition_code already used within this program",
            )
    composition = store.base_fields()
    composition.update(
        {
            "program_id": program["id"],
            "composition_code": code,
            "complexity_multiplier": multiplier,
            "status": "EXPERIMENTAL",
        }
    )
    store.compositions[composition["id"]] = composition
    # System transition: the first composition advances NDA_EXECUTED ->
    # COMPOSITION_TUNING (increments Program.version).
    if program["status"] == "NDA_EXECUTED":
        program["status"] = "COMPOSITION_TUNING"
        store.touch(program)
    return success_object(serializers.composition(composition), status=201)


@bp.route("/glass/compositions/<compositionId>", methods=["GET"])
def get_composition(compositionId):
    authenticate(ALL_ROLES)
    return success_object(serializers.composition(_get_composition_or_404(compositionId)))


@bp.route("/glass/compositions", methods=["GET"])
def list_compositions():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_program = request.args.get("program_id")
    f_status = request.args.get("status")
    items = list(store.compositions.values())
    if f_program is not None:
        items = [c for c in items if c["program_id"] == f_program]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.composition(c) for c in page], limit, offset, total)


@bp.route("/glass/compositions/<compositionId>/lock", methods=["POST"])
def lock_composition(compositionId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()
    composition = _get_composition_or_404(compositionId)
    if composition["status"] != "QUALIFIED":
        raise ApiError(ERR_INVALID_STATE, "lock requires QUALIFIED")
    composition["status"] = "LOCKED"
    store.touch(composition)
    return success_object(serializers.composition(composition))


@bp.route("/glass/compositions/<compositionId>/retire", methods=["POST"])
def retire_composition(compositionId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()
    composition = _get_composition_or_404(compositionId)
    # A LOCKED composition is immutable and can never be retired.
    if composition["status"] not in RETIRABLE:
        raise ApiError(
            ERR_INVALID_STATE,
            "retire requires EXPERIMENTAL, TUNED, or QUALIFIED",
        )
    composition["status"] = "RETIRED"
    store.touch(composition)
    # Cascade: cancel SCHEDULED campaigns (RUNNING untouched), release their
    # RESERVED allocations, breach-watch recomputation, standing demotion.
    to_cancel = [
        c
        for c in store.campaigns.values()
        if c["composition_id"] == composition["id"] and c["status"] == "SCHEDULED"
    ]
    cascades.cancel_campaigns_batched(to_cancel)
    return success_object(serializers.composition(composition))
