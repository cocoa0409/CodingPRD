"""CustodyTransfer endpoints (PRD §3.2): scheduling with contiguous window
chaining, completion mapping destination kind onto the asset custody track.
"""

from flask import Blueprint

import errors
import store
from constants import LOCATION_KINDS, CONDITION_GRADES
from middleware import require_roles, require_business_role
from response import ok_object, ok_list
from routes_assets import load_asset
from serialize import ser_transfer
from util import get_body, req_str, req_enum, req_dt, parse_pagination, sort_and_page

bp = Blueprint("transfers", __name__)

# to_location_kind -> resulting Asset.custody_state on completion.
_CUSTODY_ON_COMPLETE = {
    "STORAGE": "IN_STORAGE",
    "MAINTENANCE_SHOP": "IN_MAINTENANCE",
    "OTHER": "SECURED",
    "CLAIMANT_PREMISES": "TRANSFERRED_OUT",
}


@bp.route("/custody/custody-transfers", methods=["POST"])
def create_transfer():
    require_roles("AssetCustodian")
    # Tier 3: request shape (half-open window: end strictly after start).
    data = get_body()
    asset_id = req_str(data, "asset_id")
    from_location_ref = req_str(data, "from_location_ref")
    to_location_ref = req_str(data, "to_location_ref")
    to_location_kind = req_enum(data, "to_location_kind", LOCATION_KINDS)
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    if window_end <= window_start:
        raise errors.invalid_request("window_end must be later than window_start")
    # Tier 4: asset must exist.
    asset = load_asset(asset_id)
    # Tier 6: custody gate — CLAIMANT_PREMISES only while RELEASED_FOR_RETURN;
    # every other kind requires custody not in {TRANSFERRED_OUT, RELEASED_FOR_RETURN}.
    if to_location_kind == "CLAIMANT_PREMISES":
        if asset["custody_state"] != "RELEASED_FOR_RETURN":
            raise errors.invalid_state(
                "CLAIMANT_PREMISES transfers require custody_state == "
                "RELEASED_FOR_RETURN (custody_state=%s)" % asset["custody_state"]
            )
    else:
        if asset["custody_state"] in ("TRANSFERRED_OUT", "RELEASED_FOR_RETURN"):
            raise errors.invalid_state(
                "Cannot schedule a %s transfer while custody_state == %s"
                % (to_location_kind, asset["custody_state"])
            )
    # Tier 8: contiguous window chaining — window_start must equal the
    # greatest window_end among the asset's non-CANCELLED transfers; the
    # asset's very first (non-cancelled) transfer is exempt.
    chain = [
        t for t in store.transfers_of_asset(asset["id"]) if t["status"] != "CANCELLED"
    ]
    if chain:
        max_end = max(t["window_end"] for t in chain)
        if window_start != max_end:
            raise errors.ApiError(
                errors.ERR_CUSTODY_WINDOW_BREAK,
                409,
                "window_start must equal the greatest window_end of the "
                "asset's non-CANCELLED transfers",
            )
    transfer = store.new_entity(
        {
            "asset_id": asset["id"],
            "from_location_ref": from_location_ref,
            "to_location_ref": to_location_ref,
            "to_location_kind": to_location_kind,
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
            "condition_on_arrival": None,
        }
    )
    store.TRANSFERS[transfer["id"]] = transfer
    return ok_object(ser_transfer(transfer), status=201)


@bp.route("/custody/custody-transfers/<transfer_id>/complete", methods=["POST"])
def complete_transfer(transfer_id):
    require_roles("AssetCustodian")
    data = get_body()
    condition_on_arrival = req_enum(data, "condition_on_arrival", CONDITION_GRADES)
    transfer = store.TRANSFERS.get(transfer_id)
    if transfer is None:
        raise errors.not_found("CustodyTransfer not found: %s" % transfer_id)
    # Tier 6: only a SCHEDULED transfer can complete.
    if transfer["status"] != "SCHEDULED":
        raise errors.invalid_state(
            "Only a SCHEDULED transfer can be completed (status=%s)"
            % transfer["status"]
        )
    transfer["status"] = "COMPLETED"
    transfer["condition_on_arrival"] = condition_on_arrival
    store.touch(transfer)
    # Cascade onto the asset: custody mapping + condition refresh.
    asset = store.ASSETS.get(transfer["asset_id"])
    if asset is not None:
        asset["custody_state"] = _CUSTODY_ON_COMPLETE[transfer["to_location_kind"]]
        asset["current_condition_grade"] = condition_on_arrival
        store.touch(asset)
    return ok_object(ser_transfer(transfer))


@bp.route("/custody/assets/<asset_id>/custody-transfers", methods=["GET"])
def list_asset_transfers(asset_id):
    require_business_role()
    asset = load_asset(asset_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.transfers_of_asset(asset["id"]), limit, offset)
    return ok_list([ser_transfer(t) for t in page], total, limit, offset)
