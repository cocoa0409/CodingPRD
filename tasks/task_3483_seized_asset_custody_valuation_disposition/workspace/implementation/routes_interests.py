"""ThirdPartyInterest endpoints (PRD §3.5): lien/innocent-owner filings,
kind-compatible adjudication, the return cascade, and the appeal loop.
"""

from flask import Blueprint

import errors
import store
from constants import (
    TPI_KINDS,
    LIEN_KINDS,
    KIND_INNOCENT_OWNER,
    TPI_OUTCOMES,
    APPEAL_LIMIT,
)
from middleware import require_roles, require_business_role
from response import ok_object, ok_list
from routes_assets import load_asset
from serialize import ser_interest
from util import get_body, req_str, req_enum, opt_int, parse_pagination, sort_and_page

bp = Blueprint("interests", __name__)

# Legal states in which filings are blocked.
_FILING_BLOCKED_STATES = ("SOLD", "RETURN_PENDING", "RETURNED", "DISPUTED", "RESOLVED")

# Legal states the innocent-owner grant cascade moves to RETURN_PENDING.
_GRANT_CASCADE_STATES = (
    "SEIZED",
    "VALUATION_PENDING",
    "VALUED",
    "DISPOSITION_REVIEW",
    "SALE_AUTHORIZED",
)

# Statuses that hold a lien priority position.
_POSITION_HOLDING_STATES = ("FILED", "VERIFIED", "APPEALED")


def _fire_innocent_owner_grant_cascade(asset):
    """Links 1-2 of innocent_owner_grant_cascade (no-op off the from-states)."""
    if asset["legal_state"] not in _GRANT_CASCADE_STATES:
        return
    asset["legal_state"] = "RETURN_PENDING"
    for sale in store.sales_of_asset(asset["id"]):
        if sale["status"] in ("OPEN_FOR_BIDS", "CLOSED_PENDING_SETTLEMENT"):
            sale["status"] = "CANCELLED"
            store.touch(sale)
    store.touch(asset)


@bp.route("/custody/third-party-interests", methods=["POST"])
def create_interest():
    user_id, _ = require_roles("Claimant")
    data = get_body()
    # Tier 2 identity: petitioner_ref must equal the caller's X-User-ID.
    petitioner_ref = data.get("petitioner_ref")
    if petitioner_ref is not None and petitioner_ref != user_id:
        raise errors.forbidden(
            "petitioner_ref must equal the caller's X-User-ID"
        )
    # Tier 3: request shape, including kind/field consistency.
    asset_id = req_str(data, "asset_id")
    kind = req_enum(data, "kind", TPI_KINDS)
    petitioner_ref = req_str(data, "petitioner_ref")
    lienholder_name = data.get("lienholder_name")
    amount_cents = data.get("amount_cents")
    priority_position = data.get("priority_position")
    if kind in LIEN_KINDS:
        if lienholder_name is None or not isinstance(lienholder_name, str):
            raise errors.invalid_request(
                "LIEN_* filings require a non-null lienholder_name"
            )
        amount_cents = opt_int(data, "amount_cents", min_value=1)
        if amount_cents is None:
            raise errors.invalid_request(
                "LIEN_* filings require a non-null amount_cents"
            )
        priority_position = opt_int(data, "priority_position", min_value=1)
        if priority_position is None:
            raise errors.invalid_request(
                "LIEN_* filings require a non-null priority_position"
            )
    else:  # INNOCENT_OWNER: all three lien fields must be null.
        if (
            lienholder_name is not None
            or amount_cents is not None
            or priority_position is not None
        ):
            raise errors.invalid_request(
                "INNOCENT_OWNER filings must carry null lienholder_name, "
                "amount_cents, and priority_position"
            )
        lienholder_name = None
        amount_cents = None
        priority_position = None
    # Tier 4: asset must exist.
    asset = load_asset(asset_id)
    # Tier 6: filings blocked once the asset is on the sold/return tracks.
    if asset["legal_state"] in _FILING_BLOCKED_STATES:
        raise errors.invalid_state(
            "Interests may not be filed while legal_state == %s"
            % asset["legal_state"]
        )
    # Tier 8: at most one active lien per (asset, priority_position).
    if kind in LIEN_KINDS:
        for other in store.interests_of_asset(asset["id"]):
            if (
                other["kind"] in LIEN_KINDS
                and other["status"] in _POSITION_HOLDING_STATES
                and other["priority_position"] == priority_position
            ):
                raise errors.ApiError(
                    errors.ERR_PRIORITY_POSITION_CONFLICT,
                    409,
                    "priority_position %d is already held by an active lien "
                    "on this asset" % priority_position,
                )
    interest = store.new_entity(
        {
            "asset_id": asset["id"],
            "kind": kind,
            "petitioner_ref": petitioner_ref,
            "lienholder_name": lienholder_name,
            "amount_cents": amount_cents,
            "priority_position": priority_position,
            "status": "FILED",
            "appeal_count": 0,
            "satisfied_amount_cents": None,
            "adjudicated_by_user_id": None,
        }
    )
    store.INTERESTS[interest["id"]] = interest
    return ok_object(ser_interest(interest), status=201)


@bp.route("/custody/third-party-interests/<interest_id>/adjudicate", methods=["POST"])
def adjudicate_interest(interest_id):
    user_id, _ = require_roles("CourtOfficial")
    data = get_body()
    outcome = req_enum(data, "outcome", TPI_OUTCOMES)
    interest = store.INTERESTS.get(interest_id)
    if interest is None:
        raise errors.not_found("ThirdPartyInterest not found: %s" % interest_id)
    # Tier 6: only FILED or APPEALED interests can be adjudicated.
    if interest["status"] not in ("FILED", "APPEALED"):
        raise errors.invalid_state(
            "Only a FILED or APPEALED interest can be adjudicated (status=%s)"
            % interest["status"]
        )
    # Tier 8: outcome/kind compatibility (VERIFY: liens only; GRANT:
    # innocent-owner only; DENY: any kind).
    if outcome == "VERIFY" and interest["kind"] not in LIEN_KINDS:
        raise errors.ApiError(
            errors.ERR_OUTCOME_KIND_MISMATCH,
            422,
            "VERIFY applies only to LIEN_* kinds",
        )
    if outcome == "GRANT" and interest["kind"] != KIND_INNOCENT_OWNER:
        raise errors.ApiError(
            errors.ERR_OUTCOME_KIND_MISMATCH,
            422,
            "GRANT applies only to INNOCENT_OWNER",
        )
    interest["adjudicated_by_user_id"] = user_id
    if outcome == "VERIFY":
        interest["status"] = "VERIFIED"
    elif outcome == "DENY":
        interest["status"] = "DENIED"
    else:  # GRANT
        interest["status"] = "GRANTED"
        asset = store.ASSETS.get(interest["asset_id"])
        if asset is not None:
            _fire_innocent_owner_grant_cascade(asset)
    store.touch(interest)
    return ok_object(ser_interest(interest))


@bp.route("/custody/third-party-interests/<interest_id>/appeal", methods=["POST"])
def appeal_interest(interest_id):
    user_id, _ = require_roles("Claimant")
    get_body()
    interest = store.INTERESTS.get(interest_id)
    if interest is None:
        raise errors.not_found("ThirdPartyInterest not found: %s" % interest_id)
    # Tier 2 identity: only the petitioner may appeal.
    if interest["petitioner_ref"] != user_id:
        raise errors.forbidden(
            "Only the petitioner may appeal this interest"
        )
    # Tier 6: DENIED from-state, then the appeal budget.
    if interest["status"] != "DENIED":
        raise errors.invalid_state(
            "Only a DENIED interest can be appealed (status=%s)" % interest["status"]
        )
    if interest["appeal_count"] >= APPEAL_LIMIT:
        raise errors.appeal_exhausted(
            "appeal_count has reached the appeal limit of %d" % APPEAL_LIMIT
        )
    interest["status"] = "APPEALED"
    interest["appeal_count"] += 1
    store.touch(interest)
    return ok_object(ser_interest(interest))


@bp.route("/custody/assets/<asset_id>/third-party-interests", methods=["GET"])
def list_asset_interests(asset_id):
    require_business_role()
    asset = load_asset(asset_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.interests_of_asset(asset["id"]), limit, offset)
    return ok_list([ser_interest(t) for t in page], total, limit, offset)
