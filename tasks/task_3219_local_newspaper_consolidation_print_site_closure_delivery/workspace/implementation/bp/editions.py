"""Editions: creation, allocation, dispatch, revert, delivery and correction."""
from flask import Blueprint

from core import DB, fail
from helpers import ok_list, ok_object, create
from guards import body, identity, path_one, require_row
from models import bump, touch
import calcs as C
import recompute as R
import logical_time as T

bp = Blueprint("editions", __name__)

READ_EDITION = ["PrintOperationsDirector", "Auditor", "PlatformAdmin"]


def slot_consumed(site_id):
    return int(DB.col("_slot_consumed").get(site_id, 0))


def bump_slot(site_id, delta):
    DB.col("_slot_consumed")[site_id] = max(0, slot_consumed(site_id) + delta)


def slot_open(site):
    return slot_consumed(site["id"]) < int(site.get("distinct_shifts_per_night") or 4)


def hub_print_consumption(hub):
    total = 0
    for site in C.sites_of_hub(hub["id"]):
        for (sid, _), charge in DB.volume.items():
            if sid == site["id"]:
                total += int(charge)
    return total


@bp.post("/regional-news-ops/print-markets/<market_id>/editions")
def create_edition(market_id):
    data = body()
    identity(["PrintOperationsDirector"])
    market = path_one("print_markets", market_id)
    hub = C.hub_for_market(market)
    # §2.11: lifecycle state is checked before the fiscal ceiling, and §2.9 records
    # that a withdrawn market "no longer receive[s] print", so an edition cannot be
    # created against one.
    if market.get("status") not in ("active", "consolidation_planned",
                                    "transfer_in_progress"):
        fail("ERR_INVALID_STATE")
    sp = require_row("print_sites", data.get("assigned_print_site_id"))
    if sp.get("status") == "closed":
        fail("ERR_PRESS_POSTURE_LOCKED")
    slugs = set()
    for other in C.editions_of_market(market["id"]):
        if other.get("slug") is not None:
            slugs.add(str(other.get("slug")))
    txt = data.get("slug")
    if txt is not None and str(txt) == "":
        fail("ERR_INVALID_REQUEST", "slug must not be empty.")
    if txt is not None and str(txt) in slugs:
        fail("ERR_DUPLICATE_HUB_CODE")
    edition = create("editions", data,
                     ["assigned_print_site_id", "slug", "page_count",
                      "requested_print_run_copies", "late_sports_engineering_flag",
                      "legal_notice_count"],
                     system={"print_market_id": market["id"]})
    if int(edition.get("page_count") or 0) < 1:
        DB.col("editions").pop(edition["id"], None)
        fail("ERR_INVALID_REQUEST", "page_count must be at least 1.")
    if int(edition.get("requested_print_run_copies") or 0) < 0:
        DB.col("editions").pop(edition["id"], None)
        fail("ERR_INVALID_REQUEST", "requested_print_run_copies must be non-negative.")
    remaining = C.capacity_remaining(sp)
    floor_copies = int(market.get("guaranteed_floor_copies") or 0)
    requested = int(edition["requested_print_run_copies"])
    if floor_copies > remaining:
        DB.col("editions").pop(edition["id"], None)
        fail("ERR_FLOOR_COPIES_EXCEED_CAPACITY")
    sibling_count = len(C.editions_of_site(sp["id"]))
    if max(requested, floor_copies) > remaining:
        DB.col("editions").pop(edition["id"], None)
        fail("ERR_PRESS_CAPACITY_EXCEEDED")
    siblings = C.editions_of_site(sp["id"])
    allocated = C.allocate_copies(sp, market, requested, siblings + [edition])
    # §3.5's tonnage ceiling guards the printed run, so the period charge is
    # measured on the run the market actually gets, not on what it asked for.
    billed = hub_print_consumption(hub) + max(allocated, floor_copies)
    if hub is not None and billed > int(hub.get("max_print_tonnage_budget_cents") or 0):
        DB.col("editions").pop(edition["id"], None)
        fail("ERR_PRINT_BUDGET_EXCEEDED")
    edition["allocated_print_run_copies"] = allocated
    edition["status"] = "in_production"
    edition["correction_open"] = False
    edition["next_edition_slot_taken"] = 0
    edition["second_edition_slot_open"] = slot_open(sp)
    route = DB.get("print_routes", market.get("selected_print_route_id"))
    if route is not None:
        C.recompute_edition_time(edition, market, sp, route)
    else:
        edition["press_run_hours"] = 0
        edition["press_ready_utc"] = None
        edition["latest_edition_ready_utc"] = None
        edition["minutes_late"] = 0
        edition["is_on_time"] = False
        edition["late_edition_penalty_cents"] = 0
    R.recompute_site(sp)
    R.recompute_market_print_routes(market)
    R.recompute_market_derived(market)
    touch(market)
    return ok_object(edition, 201)


@bp.get("/regional-news-ops/print-markets/<market_id>/editions")
def list_market_editions(market_id):
    identity(READ_EDITION)
    market = path_one("print_markets", market_id)
    rows = C.editions_of_market(market["id"])
    rows.sort(key=lambda e: (str(e.get("created_at") or ""), str(e.get("id") or "")))
    return ok_list(rows, None, None)


@bp.get("/regional-news-ops/editions/<edition_id>")
def get_edition(edition_id):
    identity(READ_EDITION)
    return ok_object(path_one("editions", edition_id))


@bp.post("/regional-news-ops/editions/<edition_id>/dispatch")
def dispatch(edition_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    edition = path_one("editions", edition_id)
    if edition.get("status") != "in_production":
        fail("ERR_INVALID_STATE")
    market = DB.get("print_markets", edition.get("print_market_id"))
    site = DB.get("print_sites", edition.get("assigned_print_site_id"))
    minutes_late = int(edition.get("minutes_late") or 0)
    if minutes_late > 0:
        if not slot_open(site):
            fail("ERR_INVALID_STATE", "No second-edition adjustment slot is open.")
        edition["status"] = "late_dispatch"
        edition["next_edition_slot_taken"] = 1
        edition["late_edition_penalty_cents"] = C.late_penalty(minutes_late, edition)
        bump_slot(site["id"], 1)
        consumed = slot_consumed(site["id"])
        for ed in C.editions_of_market(market["id"]):
            ed["second_edition_slot_open"] = consumed < int(
                site.get("distinct_shifts_per_night") or 4)
            touch(ed)
    elif edition.get("is_on_time"):
        edition["status"] = "on_time_dispatch"
    else:
        fail("ERR_INVALID_STATE")
    touch(edition)
    return ok_object(edition)


@bp.post("/regional-news-ops/editions/<edition_id>/deliver")
def deliver(edition_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    edition = path_one("editions", edition_id)
    if edition.get("status") not in ("late_dispatch", "on_time_dispatch"):
        fail("ERR_INVALID_STATE")
    was_late = edition.get("status") == "late_dispatch"
    edition["status"] = "delivered_market"
    touch(edition)
    if was_late:
        site = DB.get("print_sites", edition.get("assigned_print_site_id"))
        if site is not None:
            C.site_savings(site)
            touch(site)
    # §2.9: a delivery can change a market's on-time status, so re-examine its hub.
    market = DB.get("print_markets", edition.get("print_market_id"))
    hub = C.hub_for_market(market) if market else None
    if hub is not None:
        C.refresh_legal_notice_block(hub)
        bump(hub)
    return ok_object(edition)


@bp.post("/regional-news-ops/editions/<edition_id>/revert-to-digital")
def revert_to_digital(edition_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    edition = path_one("editions", edition_id)
    if edition.get("status") != "late_dispatch":
        fail("ERR_INVALID_STATE")
    if not edition.get("late_sports_engineering_flag"):
        fail("ERR_INVALID_STATE")
    market = DB.get("print_markets", edition.get("print_market_id"))
    for route in DB.all("print_routes"):
        if route.get("destination_market_id") != market["id"]:
            continue
        if route.get("status") == "orphaned":
            continue
        if C.route_clears_deadline(route, market, edition):
            fail("ERR_INVALID_STATE", "A route can still reach the market in time.")
    site = DB.get("print_sites", edition.get("assigned_print_site_id"))
    edition["status"] = "reverted_to_digital"
    edition["next_edition_slot_taken"] = 0
    edition["press_run_hours"] = 0
    edition["assigned_print_site_id"] = None
    touch(edition)
    if site is not None:
        R.recompute_site(site)
        touch(site)
    R.recompute_market_print_routes(market)
    R.recompute_market_derived(market)
    touch(market)
    for route in C.routes_into_market(market["id"]):
        route["printed_copies_surcharge_cents"] = 0
        R.recompute_delivery_route(route)
    return ok_object(edition)


@bp.post("/regional-news-ops/editions/<edition_id>/correct")
def correct(edition_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    edition = path_one("editions", edition_id)
    if edition.get("status") != "delivered_market":
        fail("ERR_INVALID_STATE")
    if int(edition.get("legal_notice_count") or 0) < 1:
        fail("ERR_INVALID_STATE")
    market = DB.get("print_markets", edition.get("print_market_id"))
    route = DB.get("print_routes", market.get("selected_print_route_id"))
    edition["correction_open"] = True
    edition["correction_redispatch_cost_cents"] = C.correction_redispatch_cost(edition, route)
    edition["status"] = "reverted_to_digital"
    touch(edition)
    hub = C.hub_for_market(market)
    if hub is not None:
        C.refresh_legal_notice_block(hub)
        bump(hub)
    R.recompute_market_derived(market)
    touch(market)
    return ok_object(edition)