"""Commitment endpoints: propose (OCC + supersession), get, list, sign,
countersign, confirm-prepayment, apply-prepayment, release."""
from flask import Blueprint, request

import cascades
import clock
import constants as C
import serializers
import store
from calculations import coverage_snapshot
from errors import (
    ApiError,
    ERR_COMMITMENT_COVERAGE_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NDA_REQUIRED,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_PREPAYMENT_INSUFFICIENT,
    ERR_PREPAYMENT_OVERAPPLY,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_PROGRAM_VERSION,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_PROGRAM_MANAGER,
    ROLE_CAPACITY_PLANNER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_DEVICE_MAKER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_int,
    pagination_args,
)

bp = Blueprint("commitments", __name__)

NON_TERMINAL = {"PROPOSED", "SIGNED", "COUNTERSIGNED", "SECURED", "BREACH_WATCH"}


def _get_commitment_or_404(commitment_id):
    commitment = store.commitments.get(commitment_id)
    if commitment is None:
        raise ApiError(ERR_NOT_FOUND, "Commitment not found")
    return commitment


@bp.route("/glass/commitments", methods=["POST"])
def create_commitment():
    authenticate({ROLE_PROGRAM_MANAGER})
    body = get_body()
    program_id = as_str(req_field(body, "program_id"), "program_id")
    committed = as_int(req_field(body, "committed_units"), "committed_units")
    required = as_int(req_field(body, "required_units"), "required_units")
    prepayment = as_int(req_field(body, "prepayment_cents"), "prepayment_cents")
    expected = as_int(
        req_field(body, "expected_program_version"), "expected_program_version"
    )
    if committed <= 0 or required <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST, "committed_units and required_units must be positive"
        )
    program = store.programs.get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, "Program not found")
    # Priority 7: OCC on the parent Program version.
    if expected != program["version"]:
        raise ApiError(
            ERR_STALE_PROGRAM_VERSION,
            "expected_program_version does not match Program.version",
        )
    # Priority 8: confidentiality gate.
    if program["status"] == "DRAFT":
        raise ApiError(ERR_NDA_REQUIRED, "Program NDA must be executed first")
    # Priority 22: minimum prepayment (exactly the minimum is allowed).
    if prepayment < C.MIN_PREPAYMENT_CENTS:
        raise ApiError(
            ERR_PREPAYMENT_INSUFFICIENT,
            "prepayment_cents below the minimum of {}".format(C.MIN_PREPAYMENT_CENTS),
        )
    # Supersession: existing PROPOSED commitments of the same program are
    # released exactly as the release cascade describes.
    for c in list(store.commitments.values()):
        if c["program_id"] == program["id"] and c["status"] == "PROPOSED":
            cascades.release_commitment(c)
    commitment = store.base_fields()
    commitment.update(
        {
            "program_id": program["id"],
            "device_maker_id": program["device_maker_id"],
            "committed_units": committed,
            "required_units": required,
            "prepayment_cents": prepayment,
            "status": "PROPOSED",
            "coverage_tier": None,
            "effective_units": None,
            "fulfilled_units": 0,
            "supply_coverage": 0,
            "prepayment_applied_cents": 0,
            "prepayment_remaining_cents": prepayment,
            "prepayment_refunded_cents": 0,
            "breach_deadline": None,
            "countersigned_by": None,
            "signed_at": None,
        }
    )
    store.commitments[commitment["id"]] = commitment
    # Creation increments the parent Program.version by 1.
    store.touch(program)
    return success_object(serializers.commitment(commitment), status=201)


@bp.route("/glass/commitments/<commitmentId>", methods=["GET"])
def get_commitment(commitmentId):
    authenticate(ALL_ROLES)
    return success_object(serializers.commitment(_get_commitment_or_404(commitmentId)))


@bp.route("/glass/commitments", methods=["GET"])
def list_commitments():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_program = request.args.get("program_id")
    f_maker = request.args.get("device_maker_id")
    f_status = request.args.get("status")
    items = list(store.commitments.values())
    if f_program is not None:
        items = [c for c in items if c["program_id"] == f_program]
    if f_maker is not None:
        items = [c for c in items if c["device_maker_id"] == f_maker]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.commitment(c) for c in page], limit, offset, total)


@bp.route("/glass/commitments/<commitmentId>/sign", methods=["POST"])
def sign_commitment(commitmentId):
    user_id = authenticate({ROLE_DEVICE_MAKER})
    get_body()
    commitment = _get_commitment_or_404(commitmentId)
    if user_id != commitment["device_maker_id"]:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, "Caller is not the committing maker")
    if commitment["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "sign requires PROPOSED")
    commitment["status"] = "SIGNED"
    commitment["signed_at"] = clock.now()
    store.touch(commitment)
    return success_object(serializers.commitment(commitment))


@bp.route("/glass/commitments/<commitmentId>/countersign", methods=["POST"])
def countersign_commitment(commitmentId):
    user_id = authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    commitment = _get_commitment_or_404(commitmentId)
    if commitment["status"] != "SIGNED":
        raise ApiError(ERR_INVALID_STATE, "countersign requires SIGNED")
    commitment["status"] = "COUNTERSIGNED"
    commitment["countersigned_by"] = user_id
    store.touch(commitment)
    return success_object(serializers.commitment(commitment))


@bp.route("/glass/commitments/<commitmentId>/confirm-prepayment", methods=["POST"])
def confirm_prepayment(commitmentId):
    user_id = authenticate({ROLE_FINANCE_CONTROLLER})
    get_body()
    commitment = _get_commitment_or_404(commitmentId)
    if commitment["status"] != "COUNTERSIGNED":
        raise ApiError(ERR_INVALID_STATE, "confirm-prepayment requires COUNTERSIGNED")
    # Priority 10: segregation of duties.
    if user_id == commitment["countersigned_by"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Confirmer must differ from the countersigner",
        )
    # Priority 22: coverage gate on pre-bonus base coverage (exactly 1.0 passes).
    snap = coverage_snapshot(
        commitment["committed_units"],
        commitment["required_units"],
        commitment["prepayment_cents"],
    )
    if snap["base_coverage"] < C.TIER_B_COVERAGE_MIN:
        raise ApiError(
            ERR_COMMITMENT_COVERAGE_INSUFFICIENT, "base_coverage below the TIER_B gate"
        )
    commitment["status"] = "SECURED"
    commitment["coverage_tier"] = snap["tier"]
    commitment["effective_units"] = snap["effective_units"]
    store.touch(commitment)
    return success_object(serializers.commitment(commitment))


@bp.route("/glass/commitments/<commitmentId>/apply-prepayment", methods=["POST"])
def apply_prepayment(commitmentId):
    authenticate({ROLE_FINANCE_CONTROLLER})
    body = get_body()
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    if amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be strictly positive")
    commitment = _get_commitment_or_404(commitmentId)
    if commitment["status"] not in NON_TERMINAL:
        raise ApiError(
            ERR_INVALID_STATE, "apply-prepayment requires a non-terminal commitment"
        )
    if amount > commitment["prepayment_remaining_cents"]:
        raise ApiError(
            ERR_PREPAYMENT_OVERAPPLY, "amount_cents exceeds prepayment_remaining_cents"
        )
    commitment["prepayment_applied_cents"] += amount
    commitment["prepayment_remaining_cents"] -= amount
    store.touch(commitment)
    return success_object(serializers.commitment(commitment))


@bp.route("/glass/commitments/<commitmentId>/release", methods=["POST"])
def release_commitment_endpoint(commitmentId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()  # optional reason; accepted but not persisted
    commitment = _get_commitment_or_404(commitmentId)
    if commitment["status"] not in NON_TERMINAL:
        raise ApiError(ERR_INVALID_STATE, "release requires a non-terminal commitment")
    cascades.release_commitment(commitment)
    return success_object(serializers.commitment(commitment))
