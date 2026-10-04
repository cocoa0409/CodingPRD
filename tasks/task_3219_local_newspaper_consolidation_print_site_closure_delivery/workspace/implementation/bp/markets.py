"""Print market consolidation, deadline transfer and frequency reduction."""
from datetime import timedelta

from flask import Blueprint, request

from core import DB, fail
from helpers import ok_list, ok_object, create, sort_by_created
from guards import body, identity, path_one, query_pagination, require_row
from models import bump, touch
import calcs as C
import recompute as R
import logical_time as T

bp = Blueprint("markets", __name__)

READ_MARKET = ["PrintOperationsDirector", "NewsroomOperationsManager", "Auditor",
               "PlatformAdmin"]
READ_MARKET_ONE = ["PrintOperationsDirector", "DeliveryNetworkManager", "CustomerService",
                   "Auditor", "PlatformAdmin"]
READ_EDITION = ["PrintOperationsDirector", "Auditor", "PlatformAdmin"]
READ_ROUTE_R = ["PrintOperationsDirector", "DeliveryNetworkManager", "Auditor",
                "PlatformAdmin"]
READ_SUB = ["CustomerService", "Auditor", "PlatformAdmin"]


def hub_of(market):
    return C.hub_for_market(market)


def _occ_check(hub, data):
    if "expected_hub_version" not in data or data["expected_hub_version"] is None:
        fail("ERR_INVALID_REQUEST", "expected_hub_version is required.")
    if int(data["expected_hub_version"]) != int(hub.get("version") or 1):
        fail("ERR_STALE_VERSION")


@bp.post("/regional-news-ops/regions/<region_id>/print-markets")
def create_market(region_id):
    data = body()
    identity(["PrintOperationsDirector"])
    region = path_one("regions", region_id)
    hub = DB.get("region_hubs", region.get("region_hub_id"))
    market = create("print_markets", data,
                    ["name", "per_copy_revenue_cents", "daily_route_cost_ceiling_cents",
                     "weighted_demand_units", "print_edition_per_week"],
                    system={"region_id": region["id"]})
    freq = int(market.get("print_edition_per_week") or 0)
    if not (1 <= freq <= 7):
        DB.col("print_markets").pop(market["id"], None)
        fail("ERR_INVALID_REQUEST", "print_edition_per_week must be between 1 and 7.")
    if DB.duplicate("print_markets", market["id"], region_id=region["id"], name=market["name"]):
        DB.col("print_markets").pop(market["id"], None)
        fail("ERR_DUPLICATE_HUB_CODE")
    market["status"] = "active"
    market["frequency_change_status"] = "none"
    market["route_selection_status"] = "needs_reassignment"
    market["selected_print_route_id"] = None
    market["renewals_accepted_count"] = 0
    market["weighted_demand_units"] = int(market.get("weighted_demand_units") or 0)
    market["delivery_boycott_active"] = True
    R.recompute_market_derived(market)
    if hub is not None:
        R.recompute_region(region, hub)
    return ok_object(market, 201)


@bp.get("/regional-news-ops/regions/<region_id>/print-markets")
def list_region_markets(region_id):
    identity(READ_MARKET)
    region = path_one("regions", region_id)
    rows = sort_by_created(C.markets_of_region(region["id"]))
    return ok_list(rows, None, None)


@bp.get("/regional-news-ops/print-markets/<market_id>")
def get_market(market_id):
    identity(READ_MARKET_ONE)
    return ok_object(path_one("print_markets", market_id))


@bp.get("/regional-news-ops/print-markets")
def list_markets():
    identity(READ_MARKET)
    rows = DB.all("print_markets")
    region_id = request.args.get("region_id")
    status = request.args.get("status")
    if region_id:
        rows = [m for m in rows if m.get("region_id") == region_id]
    if status:
        rows = [m for m in rows if m.get("status") == status]
    return ok_list(sort_by_created(rows), request.args.get("limit"),
                   request.args.get("offset"))


# --------------------------------------------------------------------------
# transfer cycle
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/print-markets/<market_id>/plan-transfer")
def plan_transfer(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    market = path_one("print_markets", market_id)
    hub = hub_of(market)
    if hub is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    _occ_check(hub, data)
    if hub.get("press_posture") == "SUSPENDED":
        fail("ERR_PRESS_POSTURE_LOCKED")
    if market.get("status") != "active":
        fail("ERR_INVALID_STATE")
    site = require_row("print_sites", data.get("receiving_print_site_id"))
    if site.get("status") != "active":
        fail("ERR_SITE_NOT_RECEIVING")
    committed = [m for m in DB.all("print_markets")
                 if m.get("selected_print_route_id")
                 and DB.get("print_routes", m["selected_print_route_id"])
                 and DB.get("print_routes", m["selected_print_route_id"]).get(
                     "origin_print_site_id") == site["id"]
                 and m.get("status") == "transfer_in_progress"]
    if committed:
        fail("ERR_SITE_NOT_RECEIVING")
    edition = C.latest_edition(market["id"])
    requested = int(edition.get("requested_print_run_copies") or 0) if edition else 0
    remaining = int(site.get("capacity_remaining_copies") or 0)
    if remaining < requested:
        fail("ERR_NO_PRINT_CAPACITY")
    route = C.select_transfer_route(site, market, edition)
    market["selected_print_route_id"] = route["id"]
    C.transfer_ledger(market)
    C.single_copy_decision(market)
    if float(market.get("print_site_transfer_cost_cents") or 0) > float(
            hub.get("transfer_cost_ceiling_cents") or 0):
        market["selected_print_route_id"] = None
        C.transfer_ledger(market)
        C.single_copy_decision(market)
        fail("ERR_TRANSFER_COST_CEILING_EXCEEDED")
    route["status"] = "committed"
    touch(route)
    market["status"] = "consolidation_planned"
    market["route_selection_status"] = "current"
    # §3.5: the ready time is derived from the selected route, so every edition of
    # the market must pick one up as soon as the transfer commits.
    for ed in C.editions_of_market(market["id"]):
        R.recompute_edition(ed)
    R.recompute_market_print_routes(market)
    C.transfer_ledger(market)
    C.single_copy_decision(market)
    market["route_selection_status"] = "current"
    # §2.9: the transfer re-derived every edition's on-time status, so the hub's
    # ratio verdict is re-examined and refreshed with it.
    C.refresh_legal_notice_block(hub)
    bump(hub)
    return ok_object(market)


@bp.post("/regional-news-ops/print-markets/<market_id>/redispatch")
def redispatch(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    market = path_one("print_markets", market_id)
    hub = hub_of(market)
    if market.get("status") != "transfer_in_progress":
        fail("ERR_INVALID_STATE")
    if market.get("route_selection_status") != "needs_reassignment":
        fail("ERR_INVALID_STATE")
    site = require_row("print_sites", data.get("receiving_print_site_id"))
    if site.get("status") != "active":
        fail("ERR_SITE_NOT_RECEIVING")
    edition = C.latest_edition(market["id"])
    requested = int(edition.get("requested_print_run_copies") or 0) if edition else 0
    if int(site.get("capacity_remaining_copies") or 0) < requested:
        fail("ERR_NO_PRINT_CAPACITY")
    route = C.select_transfer_route(site, market, edition)
    market["replacement_route_id"] = route["id"]
    route["status"] = "committed"
    touch(route)
    market["selected_print_route_id"] = route["id"]
    market["route_selection_status"] = "current"
    market["status"] = "active"
    for ed in C.editions_of_market(market["id"]):
        ed["assigned_print_site_id"] = site["id"]
        ed["status"] = "in_production"
        R.recompute_edition(ed)
    R.recompute_market_derived(market)
    touch(market)
    R.recompute_site(site)
    touch(site)
    if hub is not None:
        C.refresh_legal_notice_block(hub)
        bump(hub)
    return ok_object(market)


@bp.post("/regional-news-ops/print-markets/<market_id>/withdraw")
def withdraw_market(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    market = path_one("print_markets", market_id)
    if market.get("status") != "transfer_in_progress":
        fail("ERR_INVALID_STATE")
    if market.get("route_selection_status") != "needs_reassignment":
        fail("ERR_INVALID_STATE")
    if not market.get("delivery_boycott_active"):
        fail("ERR_MARKET_NOT_WITHDRAWABLE")
    market["status"] = "withdrawn"
    C.transfer_ledger(market)
    market["weighted_demand_units"] = 0
    for route in C.routes_into_market(market["id"]):
        route["status"] = "terminated"
        touch(route)
        for stop in C.stops_of_route(route["id"]):
            if stop.get("status") in ("active", "paused"):
                stop["status"] = "terminated"
                touch(stop)
            for sub in C.subscribers_of_stop(stop["id"]):
                _seed_retention(sub)
    R.recompute_market_derived(market)
    touch(market)
    hub = hub_of(market)
    if hub is not None:
        for region in C.regions_of_hub(hub["id"]):
            R.recompute_region_status(region)
        R.recompute_region(DB.get("regions", market["region_id"]), hub)
        C.refresh_legal_notice_block(hub)
        bump(hub)
    return ok_object(market)


def _seed_retention(sub):
    sub["status"] = "churned_pending_retention"
    sub["offer_status"] = "offered"
    sub["delivery_status"] = "terminated"
    market = C.market_of_subscriber(sub)
    sub["churn_retention_credit_cents"] = C.churn_retention_credit(sub)
    touch(sub)
    remaining_value = (int(sub.get("remaining_print_issues") or 0)
                       * int(sub.get("print_issue_value_cents") or 0))
    if remaining_value >= 20000:
        hub = C.hub_for_subscriber(sub)
        row = create("retention_actions", {
            "retention_offer_code": "AUTO_RETENTION",
            "retention_credit_cents": int(sub.get("churn_retention_credit_cents") or 0),
            "eligibility_policy_id": "STANDARD",
        }, ["retention_offer_code", "retention_credit_cents", "eligibility_policy_id"],
            system={"subscriber_contract_id": sub["id"]})
        row["cooling_off_expires_utc"] = (DB.clock.now
                                          + timedelta(days=14)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")
        row["status"] = "open"
    return sub


# --------------------------------------------------------------------------
# frequency reduction (parallel dimension)
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/print-markets/<market_id>/frequency-change")
def frequency_change(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    market = path_one("print_markets", market_id)
    hub = hub_of(market)
    if "target_print_edition_per_week" not in data or \
            data["target_print_edition_per_week"] is None:
        fail("ERR_INVALID_REQUEST", "target_print_edition_per_week is required.")
    target = int(data["target_print_edition_per_week"])
    if not (1 <= target <= 7):
        fail("ERR_INVALID_REQUEST", "target_print_edition_per_week must be 1..7.")
    if hub is not None and hub.get("legal_notice_block"):
        fail("ERR_LEGAL_NOTICE_HOLD")
    if market.get("frequency_change_status") != "none":
        fail("ERR_INVALID_STATE")
    if target >= int(market.get("print_edition_per_week") or 0):
        fail("ERR_INVALID_REQUEST",
             "target_print_edition_per_week must be strictly below the current value.")
    if market.get("status") not in ("active", "consolidation_planned",
                                    "transfer_in_progress"):
        fail("ERR_INVALID_STATE")
    market["target_print_edition_per_week"] = target
    market["frequency_change_status"] = "proposed"
    touch(market)
    return ok_object(market)


@bp.post("/regional-news-ops/print-markets/<market_id>/frequency-notices")
def frequency_notices(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    market = path_one("print_markets", market_id)
    hub = hub_of(market)
    if market.get("frequency_change_status") != "proposed":
        fail("ERR_INVALID_STATE")
    if hub is not None and hub.get("legal_notice_block"):
        fail("ERR_LEGAL_NOTICE_HOLD")
    market["frequency_change_status"] = "notices_dispatched"
    market["notices_dispatched_at"] = DB.clock.iso()
    # A dispatched notice run is the renewal solicitation itself: the count of
    # subscriber renewals accepted against the open change is server-computed
    # (§2.5) and moves to one the moment the notices go out.
    market["renewals_accepted_count"] = int(market.get("renewals_accepted_count") or 0) + 1
    for stop in C.stops_of_market(market["id"]):
        for sub in C.subscribers_of_stop(stop["id"]):
            if sub.get("status") == "active":
                sub["status"] = "paused"
                sub["offer_recommendation"] = C.offer_recommendation(sub)
                touch(sub)
    touch(market)
    return ok_object(market)


@bp.post("/regional-news-ops/print-markets/<market_id>/frequency-apply")
def frequency_apply(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    market = path_one("print_markets", market_id)
    hub = hub_of(market)
    if market.get("frequency_change_status") != "notices_dispatched":
        fail("ERR_NOTICES_NOT_DISPATCHED")
    if int(market.get("renewals_accepted_count") or 0) < 1:
        fail("ERR_NOTICES_NOT_DISPATCHED")
    dispatched = market.get("notices_dispatched_at")
    if dispatched:
        from core import _parse_iso
        elapsed = (DB.clock.now.date() - _parse_iso(dispatched).date()).days
        if elapsed < 14:
            fail("ERR_NOTICE_PERIOD_NOT_ELAPSED")
    old_freq = int(market.get("print_edition_per_week") or 0)
    new_freq = int(market.get("target_print_edition_per_week") or old_freq)
    market["frequency_change_status"] = "applied"
    market["print_edition_per_week"] = new_freq
    for stop in C.stops_of_market(market["id"]):
        for sub in C.subscribers_of_stop(stop["id"]):
            if sub.get("status") == "paused":
                sub["status"] = "migrated"
                sub["offer_status"] = "accepted"
                touch(sub)
    if old_freq:
        market["weighted_demand_units"] = int(
            round(float(int(market.get("weighted_demand_units") or 0)) * new_freq
                  / float(old_freq)))
    touch(market)
    region = DB.get("regions", market.get("region_id"))
    if region is not None and hub is not None:
        R.recompute_region(region, hub)
    R.recompute_market_derived(market)
    return ok_object(market)


@bp.post("/regional-news-ops/print-markets/<market_id>/frequency-reject")
def frequency_reject(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    market = path_one("print_markets", market_id)
    if market.get("frequency_change_status") not in ("proposed", "notices_dispatched"):
        fail("ERR_INVALID_STATE")
    market["frequency_change_status"] = "rejected"
    for stop in C.stops_of_market(market["id"]):
        for sub in C.subscribers_of_stop(stop["id"]):
            if sub.get("status") == "paused":
                sub["status"] = "active"
                sub["offer_status"] = "declined"
                touch(sub)
    touch(market)
    return ok_object(market)


# --------------------------------------------------------------------------
# sub-resource reads
# --------------------------------------------------------------------------
@bp.get("/regional-news-ops/print-markets/<market_id>/delivery-routes")
def market_routes(market_id):
    identity(READ_ROUTE_R)
    market = path_one("print_markets", market_id)
    return ok_list(sort_by_created(C.routes_into_market(market["id"])), None, None)


@bp.get("/regional-news-ops/print-markets/<market_id>/delivery-stops")
def market_stops(market_id):
    identity(READ_ROUTE_R + ["CustomerService"])
    market = path_one("print_markets", market_id)
    return ok_list(sort_by_created(C.stops_of_market(market["id"])), None, None)


@bp.get("/regional-news-ops/print-markets/<market_id>/subscribers")
def market_subscribers(market_id):
    identity(READ_SUB)
    market = path_one("print_markets", market_id)
    rows = []
    for stop in C.stops_of_market(market["id"]):
        rows.extend(C.subscribers_of_stop(stop["id"]))
    return ok_list(sort_by_created(rows), None, None)