"""Allocation endpoints: create (OCC), get, list, release, fulfill."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import serializers
import store
from calculations import allocated_units, supply_coverage_value
from errors import (
    ApiError,
    ERR_COMMITMENT_UNITS_EXCEEDED,
    ERR_INSUFFICIENT_CAMPAIGN_HEADROOM,
    ERR_INVALID_STATE,
    ERR_IP_LITIGATION_HOLD,
    ERR_NONPOSITIVE_UNITS,
    ERR_NOT_FOUND,
    ERR_PROGRAM_MISMATCH,
    ERR_STALE_COMMITMENT_VERSION,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_CAPACITY_PLANNER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_int,
    pagination_args,
)
from cascades import demote_maker

bp = Blueprint("allocations", __name__)


def _get_allocation_or_404(allocation_id):
    allocation = store.allocations.get(allocation_id)
    if allocation is None:
        raise ApiError(ERR_NOT_FOUND, "Allocation not found")
    return allocation


def _recover_if_healed(commitment):
    """BREACH_WATCH -> SECURED once recomputed coverage reaches the minimum."""
    if (
        commitment["status"] == "BREACH_WATCH"
        and commitment["supply_coverage"] >= C.SUPPLY_COVERAGE_MIN
    ):
        commitment["status"] = "SECURED"
        commitment["breach_deadline"] = None


@bp.route("/glass/allocations", methods=["POST"])
def create_allocation():
    authenticate({ROLE_CAPACITY_PLANNER})
    body = get_body()
    commitment_id = as_str(req_field(body, "commitment_id"), "commitment_id")
    campaign_id = as_str(req_field(body, "campaign_id"), "campaign_id")
    units = as_int(req_field(body, "units"), "units")
    expected = as_int(
        req_field(body, "expected_commitment_version"), "expected_commitment_version"
    )
    commitment = store.commitments.get(commitment_id)
    if commitment is None:
        raise ApiError(ERR_NOT_FOUND, "Commitment not found")
    campaign = store.campaigns.get(campaign_id)
    if campaign is None:
        raise ApiError(ERR_NOT_FOUND, "Campaign not found")
    # Priority 6: creation-time state gates on the referenced entities.
    if commitment["status"] not in ("SECURED", "BREACH_WATCH"):
        raise ApiError(
            ERR_INVALID_STATE, "Commitment must be SECURED or BREACH_WATCH"
        )
    if campaign["status"] not in ("SCHEDULED", "RUNNING"):
        raise ApiError(ERR_INVALID_STATE, "Campaign must be SCHEDULED or RUNNING")
    # Priority 7: OCC on the parent Commitment version.
    if expected != commitment["version"]:
        raise ApiError(
            ERR_STALE_COMMITMENT_VERSION,
            "expected_commitment_version does not match Commitment.version",
        )
    # Priority 9: IP litigation hold on the commitment's maker.
    maker = store.device_makers.get(commitment["device_maker_id"])
    if maker is not None and maker["ip_review_status"] == "CONFIRMED_INFRINGEMENT":
        raise ApiError(ERR_IP_LITIGATION_HOLD, "Device maker under IP litigation hold")
    # Priority 19: campaign and commitment must belong to the same program.
    composition = store.compositions[campaign["composition_id"]]
    if composition["program_id"] != commitment["program_id"]:
        raise ApiError(ERR_PROGRAM_MISMATCH, "Allocation spans two programs")
    # Priority 21: strictly positive units.
    if units <= 0:
        raise ApiError(ERR_NONPOSITIVE_UNITS, "units must be strictly positive")
    # Priority 22: remaining need first, then campaign headroom (equal allowed).
    remaining_need = commitment["committed_units"] - allocated_units(
        commitment["id"], store.allocations.values()
    )
    if units > remaining_need:
        raise ApiError(
            ERR_COMMITMENT_UNITS_EXCEEDED, "units exceed the commitment's remaining need"
        )
    if units > campaign["unallocated_units"]:
        raise ApiError(
            ERR_INSUFFICIENT_CAMPAIGN_HEADROOM, "units exceed campaign unallocated_units"
        )
    allocation = store.base_fields()
    allocation.update(
        {
            "commitment_id": commitment["id"],
            "campaign_id": campaign["id"],
            "units": units,
            "status": "RESERVED",
        }
    )
    store.allocations[allocation["id"]] = allocation
    campaign["unallocated_units"] -= units
    store.touch(campaign)
    commitment["supply_coverage"] = supply_coverage_value(
        commitment, store.allocations.values()
    )
    store.touch(commitment)
    _recover_if_healed(commitment)
    return success_object(serializers.allocation(allocation), status=201)


@bp.route("/glass/allocations/<allocationId>", methods=["GET"])
def get_allocation(allocationId):
    authenticate(ALL_ROLES)
    return success_object(serializers.allocation(_get_allocation_or_404(allocationId)))


@bp.route("/glass/allocations", methods=["GET"])
def list_allocations():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_commitment = request.args.get("commitment_id")
    f_campaign = request.args.get("campaign_id")
    f_status = request.args.get("status")
    items = list(store.allocations.values())
    if f_commitment is not None:
        items = [a for a in items if a["commitment_id"] == f_commitment]
    if f_campaign is not None:
        items = [a for a in items if a["campaign_id"] == f_campaign]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.allocation(a) for a in page], limit, offset, total)


@bp.route("/glass/allocations/<allocationId>/release", methods=["POST"])
def release_allocation_endpoint(allocationId):
    authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    allocation = _get_allocation_or_404(allocationId)
    if allocation["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "release requires RESERVED")
    allocation["status"] = "RELEASED"
    store.touch(allocation)
    campaign = store.campaigns[allocation["campaign_id"]]
    campaign["unallocated_units"] += allocation["units"]
    store.touch(campaign)
    commitment = store.commitments[allocation["commitment_id"]]
    if commitment["status"] in ("SECURED", "BREACH_WATCH"):
        commitment["supply_coverage"] = supply_coverage_value(
            commitment, store.allocations.values()
        )
        store.touch(commitment)
        if (
            commitment["status"] == "SECURED"
            and commitment["supply_coverage"] < C.SUPPLY_COVERAGE_MIN
        ):
            commitment["status"] = "BREACH_WATCH"
            commitment["breach_deadline"] = clock.now() + timedelta(
                days=C.BREACH_GRACE_DAYS
            )
            maker = store.device_makers.get(commitment["device_maker_id"])
            if maker is not None:
                demote_maker(maker)
    return success_object(serializers.allocation(allocation))


@bp.route("/glass/allocations/<allocationId>/fulfill", methods=["POST"])
def fulfill_allocation(allocationId):
    authenticate({ROLE_CAPACITY_PLANNER})
    get_body()
    allocation = _get_allocation_or_404(allocationId)
    if allocation["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "fulfill requires RESERVED")
    campaign = store.campaigns[allocation["campaign_id"]]
    commitment = store.commitments[allocation["commitment_id"]]
    if campaign["status"] not in ("RUNNING", "COMPLETED"):
        raise ApiError(ERR_INVALID_STATE, "Campaign must be RUNNING or COMPLETED")
    if commitment["status"] not in ("SECURED", "BREACH_WATCH"):
        raise ApiError(ERR_INVALID_STATE, "Commitment must be SECURED or BREACH_WATCH")
    allocation["status"] = "FULFILLED"
    store.touch(allocation)
    commitment["fulfilled_units"] += allocation["units"]
    commitment["supply_coverage"] = supply_coverage_value(
        commitment, store.allocations.values()
    )
    store.touch(commitment)
    _recover_if_healed(commitment)
    return success_object(serializers.allocation(allocation))
