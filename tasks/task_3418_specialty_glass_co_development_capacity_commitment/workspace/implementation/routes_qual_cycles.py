"""QualCycle endpoints: submit, get, list, begin-testing, record-result, resubmit."""
from flask import Blueprint, request

import clock
import constants as C
import serializers
import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_MAX_QUAL_ATTEMPTS,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_PROGRAM_MANAGER,
    ROLE_DEVICE_MAKER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_enum,
    pagination_args,
)

bp = Blueprint("qual_cycles", __name__)

QUAL_STATUSES = {"SUBMITTED", "IN_TESTING", "PASSED", "FAILED"}


def _get_cycle_or_404(cycle_id):
    cycle = store.qual_cycles.get(cycle_id)
    if cycle is None:
        raise ApiError(ERR_NOT_FOUND, "Qualification cycle not found")
    return cycle


def _owning_maker_id(cycle):
    composition = store.compositions[cycle["composition_id"]]
    program = store.programs[composition["program_id"]]
    return program["device_maker_id"], composition


@bp.route("/glass/qual-cycles", methods=["POST"])
def create_qual_cycle():
    authenticate({ROLE_PROGRAM_MANAGER})
    body = get_body()
    composition_id = as_str(req_field(body, "composition_id"), "composition_id")
    test_plan_ref = as_str(req_field(body, "test_plan_ref"), "test_plan_ref")
    if composition_id not in store.compositions:
        raise ApiError(ERR_NOT_FOUND, "Composition not found")
    cycle = store.base_fields()
    cycle.update(
        {
            "composition_id": composition_id,
            "test_plan_ref": test_plan_ref,
            "attempt_number": 1,
            "status": "SUBMITTED",
            "result_recorded_at": None,
        }
    )
    store.qual_cycles[cycle["id"]] = cycle
    return success_object(serializers.qual_cycle(cycle), status=201)


@bp.route("/glass/qual-cycles/<qualCycleId>", methods=["GET"])
def get_qual_cycle(qualCycleId):
    authenticate(ALL_ROLES)
    return success_object(serializers.qual_cycle(_get_cycle_or_404(qualCycleId)))


@bp.route("/glass/qual-cycles", methods=["GET"])
def list_qual_cycles():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_comp = request.args.get("composition_id")
    f_status = request.args.get("status")
    items = list(store.qual_cycles.values())
    if f_comp is not None:
        items = [c for c in items if c["composition_id"] == f_comp]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.qual_cycle(c) for c in page], limit, offset, total)


@bp.route("/glass/qual-cycles/<qualCycleId>/begin-testing", methods=["POST"])
def begin_testing(qualCycleId):
    user_id = authenticate({ROLE_DEVICE_MAKER})
    get_body()
    cycle = _get_cycle_or_404(qualCycleId)
    owner_id, composition = _owning_maker_id(cycle)
    if user_id != owner_id:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, "Caller is not the owning device maker")
    if cycle["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "begin-testing requires SUBMITTED")
    cycle["status"] = "IN_TESTING"
    store.touch(cycle)
    # First contact with the test bench tunes an EXPERIMENTAL composition.
    if composition["status"] == "EXPERIMENTAL":
        composition["status"] = "TUNED"
        store.touch(composition)
    return success_object(serializers.qual_cycle(cycle))


@bp.route("/glass/qual-cycles/<qualCycleId>/record-result", methods=["POST"])
def record_result(qualCycleId):
    user_id = authenticate({ROLE_DEVICE_MAKER})
    body = get_body()
    outcome = as_enum(req_field(body, "outcome"), "outcome", {"PASSED", "FAILED"})
    cycle = _get_cycle_or_404(qualCycleId)
    owner_id, composition = _owning_maker_id(cycle)
    if user_id != owner_id:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, "Caller is not the owning device maker")
    if cycle["status"] != "IN_TESTING":
        raise ApiError(ERR_INVALID_STATE, "record-result requires IN_TESTING")
    cycle["status"] = outcome
    cycle["result_recorded_at"] = clock.now()
    store.touch(cycle)
    # A PASSED outcome qualifies a TUNED composition.
    if outcome == "PASSED" and composition["status"] == "TUNED":
        composition["status"] = "QUALIFIED"
        store.touch(composition)
    return success_object(serializers.qual_cycle(cycle))


@bp.route("/glass/qual-cycles/<qualCycleId>/resubmit", methods=["POST"])
def resubmit(qualCycleId):
    authenticate({ROLE_PROGRAM_MANAGER})
    get_body()
    cycle = _get_cycle_or_404(qualCycleId)
    if cycle["status"] != "FAILED":
        raise ApiError(ERR_INVALID_STATE, "resubmit requires FAILED")
    if cycle["attempt_number"] >= C.MAX_QUAL_ATTEMPTS:
        raise ApiError(ERR_MAX_QUAL_ATTEMPTS, "Qualification attempt cap reached")
    cycle["status"] = "SUBMITTED"
    cycle["attempt_number"] += 1
    store.touch(cycle)
    return success_object(serializers.qual_cycle(cycle))
