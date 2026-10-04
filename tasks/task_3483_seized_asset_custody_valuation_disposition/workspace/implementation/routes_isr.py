"""InterlocutorySaleRequest endpoints (PRD §3.4): OCC-guarded request with
the eligibility-ratio gate, and the SoD-guarded adjudication cascade.
"""

from flask import Blueprint

import calc
import errors
import store
from constants import ISR_OUTCOMES
from middleware import require_roles, require_business_role
from response import ok_object, ok_list
from routes_assets import load_asset, cancel_scheduled_transfers
from serialize import ser_isr
from util import get_body, req_str, req_enum, req_int, parse_pagination, sort_and_page

bp = Blueprint("isr", __name__)

# Legal states from which an interlocutory sale may be requested.
_REQUESTABLE_STATES = ("VALUED", "DISPOSITION_REVIEW")


@bp.route("/custody/interlocutory-sale-requests", methods=["POST"])
def create_isr():
    user_id, _ = require_roles("AssetManager")
    # Tier 3: request shape.
    data = get_body()
    asset_id = req_str(data, "asset_id")
    justification = req_str(data, "justification")
    expected_asset_version = req_int(data, "expected_asset_version")
    # Tier 4: asset must exist.
    asset = load_asset(asset_id)
    # Tier 5: optimistic concurrency on the asset.
    if expected_asset_version != asset["version"]:
        raise errors.stale_version(
            "expected_asset_version %s does not match current asset version %s"
            % (expected_asset_version, asset["version"])
        )
    # Tier 6: legal-state gate.
    if asset["legal_state"] not in _REQUESTABLE_STATES:
        raise errors.invalid_state(
            "Interlocutory sale requires legal_state VALUED or "
            "DISPOSITION_REVIEW (legal_state=%s)" % asset["legal_state"]
        )
    # Tier 9: eligibility ratio (integer form, boundary inclusive).
    projected_burden = calc.projected_burden_cents(asset)
    if not calc.interlocutory_eligible(asset):
        raise errors.ApiError(
            errors.ERR_RATIO_BELOW_THRESHOLD,
            422,
            "Projected holding-cost burden is below 30%% of appraised value",
        )
    isr = store.new_entity(
        {
            "asset_id": asset["id"],
            "justification": justification,
            "requested_by_user_id": user_id,
            "status": "PENDING",
            "adjudicated_by_user_id": None,
            "accumulated_costs_snapshot_cents": asset[
                "accumulated_net_holding_cost_cents"
            ],
            "projected_burden_cents": projected_burden,
            "appraised_value_snapshot_cents": asset["appraised_value_cents"],
        }
    )
    store.ISRS[isr["id"]] = isr
    # Filing an interlocutory request mutates the asset's OCC view.
    store.touch(asset)
    return ok_object(ser_isr(isr), status=201)


@bp.route(
    "/custody/interlocutory-sale-requests/<isr_id>/adjudicate", methods=["POST"]
)
def adjudicate_isr(isr_id):
    user_id, _ = require_roles("CourtOfficial")
    data = get_body()
    outcome = req_enum(data, "outcome", ISR_OUTCOMES)
    isr = store.ISRS.get(isr_id)
    if isr is None:
        raise errors.not_found("InterlocutorySaleRequest not found: %s" % isr_id)
    # Tier 6: only a PENDING request can be adjudicated (fires before SoD).
    if isr["status"] != "PENDING":
        raise errors.invalid_state(
            "Only a PENDING request can be adjudicated (status=%s)" % isr["status"]
        )
    # Tier 7: segregation of duties — adjudicator must differ from requester.
    if user_id == isr["requested_by_user_id"]:
        raise errors.sod_violation(
            "The adjudicator must differ from the requesting AssetManager"
        )
    isr["adjudicated_by_user_id"] = user_id
    if outcome == "DENY":
        isr["status"] = "DENIED"
        store.touch(isr)
        return ok_object(ser_isr(isr))
    # APPROVE: fire isr_approval_cascade on the asset.
    isr["status"] = "APPROVED"
    store.touch(isr)
    asset = store.ASSETS.get(isr["asset_id"])
    if asset is not None and asset["legal_state"] in _REQUESTABLE_STATES:
        # Link 1: legal -> SALE_AUTHORIZED, custody -> RELEASED_FOR_SALE,
        # retention_decision -> SELL.
        asset["legal_state"] = "SALE_AUTHORIZED"
        asset["custody_state"] = "RELEASED_FOR_SALE"
        asset["retention_decision"] = "SELL"
        # Link 2: cancel every SCHEDULED custody transfer of the asset.
        cancel_scheduled_transfers(asset)
        # Link 3: the SALE_AUTHORIZED legal state excludes the asset from the
        # run-holding-review sweep's input set (enforced at sweep time).
        store.touch(asset)
    return ok_object(ser_isr(isr))


@bp.route("/custody/assets/<asset_id>/interlocutory-sale-requests", methods=["GET"])
def list_asset_isrs(asset_id):
    require_business_role()
    asset = load_asset(asset_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.isrs_of_asset(asset["id"]), limit, offset)
    return ok_list([ser_isr(i) for i in page], total, limit, offset)
