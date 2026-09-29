"""Asset library endpoints (PRD section 3.7)."""

from flask import Blueprint

import calc
import envelope
import governance as gov
import listing
import serialize
import validate as v
from auth import ROLE_BRAND, ROLE_LEGAL, ROLE_MANAGING_EDITOR, endpoint
from errors import ApiError
from store import store, touch, new_row, by_created

bp = Blueprint("assets", __name__)

ASSET_READERS = (ROLE_MANAGING_EDITOR, ROLE_LEGAL, ROLE_BRAND)


@bp.post("/editorial/assets")
@endpoint(ROLE_MANAGING_EDITOR)
def create_asset():
    body = v.body()
    name = v.v_str(body, "name", minlen=1, maxlen=120)
    asset_type = v.v_enum(body, "asset_type", v.ASSET_TYPES)
    license_start = v.v_instant(body, "license_start")
    license_end = v.v_instant(body, "license_end")
    channels = v.v_enum_list(body, "licensed_channels", v.CHANNELS,
                             min_items=1, max_items=3)
    max_uses = v.v_int(body, "max_licensed_uses", minimum=1, maximum=50)
    if license_end <= license_start:
        v.fail("license_end must be strictly after license_start")

    row = new_row("assets", {
        "name": name,
        "asset_type": asset_type,
        "license_start": license_start,
        "license_end": license_end,
        "licensed_channels": channels,
        "max_licensed_uses": max_uses,
        "active_use_count": 0,
        "remaining_licensed_uses": max_uses,
        "status": calc.asset_status(license_end, store.clock),
    })
    store.assets[row["id"]] = row
    return envelope.created(serialize.asset(row))


@bp.post("/editorial/assets/<aid>/renew")
@endpoint(ROLE_MANAGING_EDITOR)
def renew_asset(aid):
    asset = gov.get_asset(aid)
    body = v.body()
    new_end = v.v_instant(body, "new_license_end")

    if asset["status"] not in ("EXPIRING", "EXPIRED"):
        raise ApiError("ERR_ASSET_STATE_INVALID",
                       "renewal is declared only from EXPIRING and EXPIRED")
    if new_end <= store.clock or new_end <= asset["license_end"]:
        raise ApiError("ERR_ASSET_RENEWAL_NOT_EXTENDING",
                       "new_license_end must extend past both the clock and the "
                       "current license_end")

    # Step 1 -- status is stamped LICENSED unconditionally, never re-derived.
    asset["license_end"] = new_end
    asset["status"] = "LICENSED"
    touch(asset)
    # Step 2 -- revive the lapsed usages.
    revived = []
    for usage in by_created(gov.usages_of_asset(asset["id"])):
        if usage["usage_state"] == "RIGHTS_LAPSED":
            usage["usage_state"] = "ACTIVE"
            usage["released_at"] = None
            touch(usage)
            revived.append(usage)
    gov.refresh_asset_counts(asset, derive_status=False)
    # Step 3 -- restore the reach of the rows suppressed for lapsed asset rights.
    campaigns = []
    for usage in revived:
        for dist in gov.sort_distributions(
                gov.distributions_of_item(usage["content_item_id"])):
            if dist["channel"] != usage["channel"]:
                continue
            if dist["state"] != "SUPPRESSED" \
                    or dist["suppression_reason"] != "ASSET_RIGHTS_LAPSED":
                continue
            if dist["scheduled_at"] <= store.clock:
                dist["state"] = "LIVE"
                dist["went_live_at"] = store.clock
            else:
                dist["state"] = "SCHEDULED"
            dist["suppression_reason"] = None
            dist["suppressed_at"] = None
            touch(dist)
        item = store.items.get(usage["content_item_id"])
        if item is not None and item["campaign_id"] not in campaigns:
            campaigns.append(item["campaign_id"])
    # Step 4.
    for campaign_id in campaigns:
        campaign = store.campaigns.get(campaign_id)
        if campaign is not None:
            gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.asset(asset))


@bp.get("/editorial/assets")
@endpoint(*ASSET_READERS)
def list_assets():
    rows = listing.apply_filters(list(store.assets.values()),
                                 [("asset_type", "asset_type"),
                                  ("status", "status")])
    rows = listing.sort_by(rows, ["license_end"])
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.asset(r) for r in window], pagination)


@bp.get("/editorial/assets/<aid>")
@endpoint(*ASSET_READERS)
def read_asset(aid):
    return envelope.ok(serialize.asset(gov.get_asset(aid)))


@bp.get("/editorial/assets/<aid>/usages")
@endpoint(*ASSET_READERS)
def list_asset_usages(aid):
    asset = gov.get_asset(aid)
    rows = listing.apply_filters(gov.usages_of_asset(asset["id"]),
                                 [("usage_state", "usage_state")])
    rows = listing.sort_by(rows, ["attached_at"])
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.usage(r) for r in window], pagination)
