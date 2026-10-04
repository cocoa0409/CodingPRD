"""Logical clock control, subscription reach reporting and the periodic research cycle."""
from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses

bp = Blueprint("reports", __name__, url_prefix="/data-research")

GLOBAL_ALL_ROLLUP_BPS = 5000


# ---------------------------------------------------------------------------
# Logical clock (declared outside the /data-research prefix)
# ---------------------------------------------------------------------------
clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.authorize(["PlatformAdmin"])
    payload = core.body_of(request)
    current_utc = core.require_datetime(payload, "current_utc")
    core.clock.set(core.fmt_dt(current_utc))
    apply_renewed_activations()
    return responses.ok_object({}, 200)


def apply_renewed_activations():
    """system: a RENEWED contract returns to ACTIVE once its new term start arrives."""
    for contract in core.contracts.values():
        if contract["status"] != "RENEWED":
            continue
        if core.clock.now() >= core.parse_dt(contract["term_start"]):
            contract["status"] = "ACTIVE"
            core.touch(contract)
            org = core.organizations.get(contract["subscriber_organization_id"])
            if org is not None:
                lookups.recompute_organization_counters(org)


# ---------------------------------------------------------------------------
# Subscription reach report
# ---------------------------------------------------------------------------
@bp.post("/reports/subscription-reach")
def subscription_reach():
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    contract_id = core.require_string(payload, "contract_id")
    contract = lookups.get_contract(contract_id)
    org = lookups.get_organization(contract["subscriber_organization_id"])

    total_sqft = sum(p["rentable_sqft"] for p in core.properties.values())
    licensed = set(contract["licensed_markets"])
    contract_sqft = sum(
        p["rentable_sqft"] for p in core.properties.values() if p["market"] in licensed)

    if total_sqft > 0:
        occupy_bps = core.as_int(
            core.round_half_up(core.Decimal(10000) * core.Decimal(contract_sqft)
                               / core.Decimal(total_sqft), 0))
    else:
        occupy_bps = 0
    # The subscription's occupy-limit share may not exceed the GLOBAL_ALL roll-up
    # share it is entitled to.
    rollup_bps = GLOBAL_ALL_ROLLUP_BPS
    reach_ok = occupy_bps <= rollup_bps

    lookups.recompute_organization_counters(org)
    if not reach_ok:
        raise core.ApiError("ERR_SUBSCRIPTION_REACH_EXCEEDED")
    return responses.ok_object({
        "occupy_limit_share_bps": occupy_bps,
        "rollup_share_bps": rollup_bps,
        "reach_ok": reach_ok,
    })


# ---------------------------------------------------------------------------
# Periodic research cycle
# ---------------------------------------------------------------------------
@bp.post("/run_research_cycle")
def run_research_cycle():
    auth.authorize(["PlatformAdmin"])
    core.body_of(request)

    # 1. Age the corpus: recompute stale_source_count for every property.
    stale_source_properties = 0
    for prop in list(core.properties.values()):
        before = prop["stale_source_count"]
        after = calc.property_stale_source_count(prop)
        prop["stale_source_count"] = after
        if after != before:
            prop["completeness_pct"] = calc.weighted_completeness_score(prop, "PROVISIONAL")
            prop["land_posture"] = calc.derive_land_posture(prop)
            core.touch(prop)
            stale_source_properties += 1

    # 1b. Renewed contracts whose new term start has arrived.
    apply_renewed_activations()

    # 2. Renewal lapse scan (ordered by renewal_due_at then created_at).
    lapsed_contracts = calc.renewal_lapse_scan()

    # 3. Listing expiry.
    expired_listings = 0
    for listing in list(core.listings.values()):
        if listing["status"] == "PUBLISHED" and listing["expires_at"] is not None:
            if core.clock.now() >= core.parse_dt(listing["expires_at"]):
                listing["status"] = "EXPIRED"
                core.touch(listing)
                expired_listings += 1

    # 4. Sale subordination deadlines.
    for txn in list(core.sale_transactions.values()):
        if txn["subordination_status"] == "PENDING":
            if core.clock.now() >= core.parse_dt(txn["subordination_deadline"]):
                txn["subordination_status"] = "LAPSED"
                core.touch(txn)
                prop = core.properties.get(txn["property_id"])
                if prop is not None:
                    lookups.recompute_verified_sale_value(prop)
                    core.touch(prop)

    # 5. Seat metering refresh.
    by_contract = {}
    for seat in list(core.seats.values()):
        contract = core.contracts.get(seat["contract_id"])
        if contract is None:
            continue
        seat["overage_fee_cents"] = calc.seat_overage_fee(seat, contract)
        _owner, share = calc.seat_owner_attribution(seat, "monthly_cycle")
        seat["billed_owner_share_pct"] = share
        core.touch(seat)
        entry = by_contract.setdefault(contract["id"], {
            "seat_count": 0,
            "overage_fee_cents": 0,
            "billed_owner_share_pct": 0.0,
            "status": contract["status"],
        })
        entry["seat_count"] += 1
        entry["overage_fee_cents"] += seat["overage_fee_cents"]
        entry["billed_owner_share_pct"] = round(
            entry["billed_owner_share_pct"] + seat["billed_owner_share_pct"], 2)

    # 6. Re-derive market index values for every market holding an index run.
    markets = {}
    for run in core.analytics_runs.values():
        if run["run_type"] != "INDEX" or run["index_value"] is None:
            continue
        markets.setdefault(run["market"], []).append(run)
    for runs in markets.values():
        for run in runs:
            window_start = core.parse_dt(run["window_start"])
            window_end = core.parse_dt(run["window_end"])
            refreshed = calc.market_index_value(
                run["market"], window_start, window_end, run["adjustment_mode"], [])
            if refreshed["comp_count"] == 0:
                continue
            run["index_value"] = refreshed["index_value"]
            run["comp_count"] = refreshed["comp_count"]
            run["mean_effective_rent_psf"] = refreshed["mean_effective_rent_psf"]
            run["median_effective_rent_psf"] = refreshed["median_effective_rent_psf"]
            if run["attribution_status"] == "ATTRIBUTED":
                run["attributed_records_delta"] = refreshed["comp_count"]
            core.touch(run)

    # 7. Advance the cycle index.
    core.cycle_index["value"] += 1

    return responses.ok_object({
        "cycle_index": core.cycle_index["value"],
        "aged_source_count": stale_source_properties,
        "expired_listing_count": expired_listings,
        "lapsed_contract_count": lapsed_contracts,
        "expired_listings": expired_listings,
        "lapsed_contracts": lapsed_contracts,
        "stale_source_properties": stale_source_properties,
    })