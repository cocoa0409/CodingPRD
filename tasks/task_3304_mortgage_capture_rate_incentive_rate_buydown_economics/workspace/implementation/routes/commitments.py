"""ForwardCommitment endpoints."""

from flask import Blueprint, request

from db import db, parse_iso
from errors import fail
from response import ok, ok_list, paginate
from checks import (
    authenticate, body, require_fields, int_field, string_field, iso_field,
    get_community, get_commitment, require_state,
)
from services import common, calc

bp = Blueprint("commitments", __name__)

FINANCE_ROLES = ["PlatformAdmin", "MortgageBanker", "ComplianceOfficer"]
DETAIL_ROLES = ["PlatformAdmin", "MortgageBanker", "ClosingOfficer", "ComplianceOfficer"]
CREATE_ROLES = ["MortgageBanker", "PlatformAdmin"]


@bp.post("/housing/communities/<community_id>/forward-commitments")
def create_commitment(community_id):
    authenticate(CREATE_ROLES)
    get_community(community_id)
    payload = body()
    require_fields(
        payload,
        [
            "commitment_code",
            "investor_name",
            "committed_rate_bps",
            "committed_units",
            "commitment_start_iso",
            "commitment_end_iso",
        ],
    )
    code = string_field(payload, "commitment_code")
    investor = string_field(payload, "investor_name")
    rate_bps = int_field(payload, "committed_rate_bps", minimum=0, maximum=2000)
    units = int_field(payload, "committed_units", minimum=1, maximum=500)
    start_iso = iso_field(payload, "commitment_start_iso")
    end_iso = iso_field(payload, "commitment_end_iso")
    if parse_iso(end_iso) < parse_iso(start_iso):
        fail("ERR_INVALID_ENUM_VALUE", "commitment_end_iso must not precede the start")

    # Uniqueness of the code among live commitments of the same community.
    for existing in db.forward_commitments.values():
        if (
            existing.get("community_id") == community_id
            and existing.get("commitment_code") == code
            and existing.get("commitment_status") in ("OPEN", "EXHAUSTED")
        ):
            fail(
                "ERR_COMMITMENT_WINDOW_OVERLAP",
                "commitment_code collides with a live commitment of this community",
            )

    # Priority 16: closed-open window overlap against OPEN or EXHAUSTED commitments.
    new_start = parse_iso(start_iso)
    new_end = parse_iso(end_iso)
    for existing in db.forward_commitments.values():
        if existing.get("community_id") != community_id:
            continue
        if existing.get("commitment_status") not in ("OPEN", "EXHAUSTED"):
            continue
        old_start = parse_iso(existing.get("commitment_start_iso"))
        old_end = parse_iso(existing.get("commitment_end_iso"))
        if new_start < old_end and old_start < new_end:
            fail(
                "ERR_COMMITMENT_WINDOW_OVERLAP",
                "the commitment window overlaps a live commitment of this community",
            )

    row = {
        "id": db.new_id(),
        "community_id": community_id,
        "commitment_code": code,
        "investor_name": investor,
        "committed_rate_bps": rate_bps,
        "committed_units": units,
        "units_drawn": 0,
        "units_released": 0,
        "units_available": units,
        "commitment_start_iso": start_iso,
        "commitment_end_iso": end_iso,
        "pair_off_fee_cents": 0,
        "commitment_status": "OPEN",
    }
    common.stamp_new(row)
    db.forward_commitments[row["id"]] = row
    _refresh_community(community_id)
    return ok(common.dump(row), 201)


def _refresh_community(community_id):
    community = db.communities.get(community_id)
    if community is not None:
        calc.capture_rate_realization(community)
        common.touch(community)
    return community


@bp.get("/housing/forward-commitments/<commitment_id>")
def get_commitment_detail(commitment_id):
    authenticate(FINANCE_ROLES)
    commitment = get_commitment(commitment_id)
    common.recompute_commitment_counters(commitment)
    return ok(common.dump(commitment), 200)


@bp.post("/housing/forward-commitments/<commitment_id>/close")
def close_commitment(commitment_id):
    authenticate(["ComplianceOfficer"])
    commitment = get_commitment(commitment_id)
    status = commitment.get("commitment_status")
    common.recompute_commitment_counters(commitment)
    if status == "EXPIRED":
        commitment["commitment_status"] = "CLOSED"
        common.touch(commitment)
    elif status in ("OPEN", "EXHAUSTED"):
        if commitment.get("units_available") != 0:
            fail(
                "ERR_INVALID_STATE",
                "a commitment may only be sealed once no units remain available",
            )
        commitment["commitment_status"] = "CLOSED"
        commitment["pair_off_fee_cents"] = 0
        common.touch(commitment)
    else:
        fail("ERR_INVALID_STATE", "the commitment is already CLOSED")
    _refresh_community(commitment.get("community_id"))
    return ok(common.dump(commitment), 200)


@bp.get("/housing/forward-commitments/<commitment_id>/rate-locks")
def list_commitment_locks(commitment_id):
    authenticate(DETAIL_ROLES)
    get_commitment(commitment_id)
    rows = [l for l in db.rate_locks.values() if l.get("commitment_id") == commitment_id]
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)