"""§1.3 calculation rules, implemented from PRD §3."""
import math
from decimal import Decimal

from core import DB, D, rhu, fail
from logical_time import (add_hours, cutoff_dt, days_between_floor, deadline_dt,
                          now, today, whole_minutes_between)

FIXED_PRESS_AVOIDED_CENTS = 180000
SAVINGS_WINDOW_DAYS = 30
ACTIVE_CONTRACT_CAP_CENTS = 5000
CARRIER_LABOR_CENTS = 85
PER_ISSUE_HANDLING_CENTS = 40


# --------------------------------------------------------------------------
# small accessors
# --------------------------------------------------------------------------
def hub_of(row):
    for key in ("region_hub_id", "print_site_hub_id", "contractor_hub_id", "title_hub_id"):
        if row.get(key):
            return DB.get("region_hubs", row[key])
    return None


def hub_for_market(market):
    region = DB.get("regions", market.get("region_id"))
    return DB.get("region_hubs", region.get("region_hub_id")) if region else None


def hub_for_site(site):
    return DB.get("region_hubs", site.get("print_site_hub_id"))


def hub_for_route(route):
    site = DB.get("print_sites", route.get("origin_print_site_id"))
    return hub_for_site(site) if site else None


def hub_for_stop(stop):
    route = DB.get("delivery_routes", stop.get("delivery_route_id"))
    contractor = DB.get("delivery_contractors", route.get("delivery_contractor_id")) \
        if route else None
    return DB.get("region_hubs", contractor.get("contractor_hub_id")) if contractor else None


def hub_for_subscriber(sub):
    stop = DB.get("delivery_stops", sub.get("delivery_stop_id"))
    return hub_for_stop(stop) if stop else None


def market_of_subscriber(sub):
    stop = DB.get("delivery_stops", sub.get("delivery_stop_id"))
    return DB.get("print_markets", stop.get("print_market_id")) if stop else None


def market_of_stop(stop):
    return DB.get("print_markets", stop.get("print_market_id"))


def market_of_route(route):
    return DB.get("print_markets", route.get("destination_market_id"))


def site_of_market(market):
    route = DB.get("print_routes", market.get("selected_print_route_id"))
    return DB.get("print_sites", route.get("origin_print_site_id")) if route else None


def editions_of_market(market_id):
    return [e for e in DB.all("editions") if e.get("print_market_id") == market_id]


def latest_edition(market_id):
    eds = sorted(editions_of_market(market_id), key=lambda e: str(e.get("slug")))
    return eds[-1] if eds else None


def editions_of_site(site_id):
    return [e for e in DB.all("editions") if e.get("assigned_print_site_id") == site_id]


def routes_of_site(site_id):
    return [r for r in DB.all("print_routes") if r.get("origin_print_site_id") == site_id]


def routes_of_contractor(contractor_id):
    return [r for r in DB.all("delivery_routes")
            if r.get("delivery_contractor_id") == contractor_id]


def stops_of_route(route_id):
    return [s for s in DB.all("delivery_stops") if s.get("delivery_route_id") == route_id]


def stops_of_market(market_id):
    return [s for s in DB.all("delivery_stops") if s.get("print_market_id") == market_id]


def routes_into_market(market_id):
    return [r for r in DB.all("delivery_routes") if r.get("print_market_id") == market_id]


def subscribers_of_stop(stop_id):
    return [s for s in DB.all("subscribers") if s.get("delivery_stop_id") == stop_id]


def regions_of_hub(hub_id):
    return [r for r in DB.all("regions") if r.get("region_hub_id") == hub_id]


def sites_of_hub(hub_id):
    return [s for s in DB.all("print_sites") if s.get("print_site_hub_id") == hub_id]


def markets_of_hub(hub_id):
    out = []
    for region in regions_of_hub(hub_id):
        out.extend([m for m in DB.all("print_markets") if m.get("region_id") == region["id"]])
    return out


def contractors_of_hub(hub_id):
    return [c for c in DB.all("delivery_contractors")
            if c.get("contractor_hub_id") == hub_id]


def markets_of_region(region_id):
    return [m for m in DB.all("print_markets") if m.get("region_id") == region_id]


COUNTED_MARKET_STATUSES = ("active", "consolidation_planned", "transfer_in_progress")


# --------------------------------------------------------------------------
# §3.3 route transport cost
# --------------------------------------------------------------------------
def stops_per_night(route):
    market_id = route.get("destination_market_id")
    return len([s for s in DB.all("delivery_stops")
                if s.get("print_market_id") == market_id
                and s.get("status") in ("active", "paused")])


def total_copies_allocated(route):
    total = 0
    for ed in editions_of_market(route.get("destination_market_id")):
        total += int(ed.get("allocated_print_run_copies") or 0)
    return total


def compute_route_transport(route):
    distance = rhu(D(route.get("transit_minutes") or 0) / 60 * 55, 2)
    band1 = min(distance, 50) * 0.90
    band2 = min(max(distance - 50, 0), 100) * 0.75
    band3 = max(distance - 150, 0) * 0.60
    marginal = rhu(band1 + band2 + band3, 2)
    spn = stops_per_night(route)
    transport = rhu(marginal + spn * 1.25, 2)
    copies = total_copies_allocated(route)
    if copies == 0:
        per_copy = 0
    else:
        per_copy = rhu(D(transport) / copies, 4)
    route["distance_miles"] = distance
    route["marginal_mileage_cost"] = marginal
    route["stops_per_night"] = spn
    route["total_copies_allocated"] = copies
    route["route_transport_cost"] = transport
    route["marginal_cost_per_copy_cents"] = per_copy
    return route


# --------------------------------------------------------------------------
# §3.5 press runs and readiness
# --------------------------------------------------------------------------
def speed_factor(page_count):
    pc = int(page_count or 0)
    if pc <= 8:
        return 1.00
    if pc <= 16:
        return 0.85
    return 0.70


def ceil_quarter(raw):
    """Round a raw duration up to the next quarter hour."""
    quarters = int(D(raw) * 4)
    if D(quarters) / 4 < D(raw) - D("0.000000001"):
        quarters += 1
    return quarters * 0.25


def press_run_hours(edition, site):
    """PRD §3.5: the raw duration is formed by the division chain and rounded
    once, to the next quarter hour; press_run_hours is a floor of that rounding."""
    speed = speed_factor(edition.get("page_count"))
    raw = float(D(edition.get("requested_print_run_copies") or 0)
                / D(site.get("press_units") or 1)
                / D(site.get("shifts_per_night") or 1)
                / D(site.get("copies_per_hour_per_press") or 1)
                / D(speed))
    return ceil_quarter(raw)


def late_penalty(minutes_late, edition):
    minutes_late = int(minutes_late or 0)
    if minutes_late == 0:
        return 0
    if edition.get("correction_open"):
        mult = 3
    elif edition.get("late_sports_engineering_flag"):
        mult = 2
    else:
        mult = 1
    return int(minutes_late * 45 * mult)


def _iso_ts(dt):
    """§2.5: ISO 8601 UTC timestamp with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def recompute_edition_time(edition, market, site, route):
    """Recompute press hours, ready times, lateness and the penalty."""
    if route is None:
        edition["press_run_hours"] = 0
        edition["press_ready_utc"] = None
        edition["latest_edition_ready_utc"] = None
        edition["minutes_late"] = 0
        edition["is_on_time"] = False
        edition["late_edition_penalty_cents"] = 0
        return edition
    hours = press_run_hours(edition, site)
    edition["press_run_hours"] = hours
    press_ready = add_hours(cutoff_dt(route), 1.0)
    press_ready = add_hours(press_ready, hours)
    ready = add_hours(press_ready, (int(route.get("transit_minutes") or 0)
                                    + int(route.get("buffer_minutes") or 0)) / 60.0)
    edition["press_ready_utc"] = _iso_ts(press_ready)
    edition["latest_edition_ready_utc"] = _iso_ts(ready)
    dl = deadline_dt(market)
    minutes_late = max(0, whole_minutes_between(dl, ready))
    edition["minutes_late"] = minutes_late
    margin = (dl - ready).total_seconds() / 60.0
    edition["is_on_time"] = margin >= int(market.get("on_time_margin_minutes") or 0)
    edition["late_edition_penalty_cents"] = late_penalty(minutes_late, edition)
    return edition


def route_clears_deadline(route, market, edition):
    hours = press_run_hours(edition, DB.get("print_sites", route.get("origin_print_site_id"))) \
        if edition else 0
    ready = add_hours(cutoff_dt(route), 1.0)
    ready = add_hours(ready, hours)
    ready = add_hours(ready, (int(route.get("transit_minutes") or 0)
                              + int(route.get("buffer_minutes") or 0)) / 60.0)
    return ready <= deadline_dt(market)


def select_transfer_route(site, market, edition):
    candidates = [r for r in routes_of_site(site["id"])
                  if r.get("status") == "eligible" and r.get("is_direct_hop")]
    ok = [r for r in candidates if route_clears_deadline(r, market, edition)]
    if not ok:
        fail("ERR_NO_ROUTE_IN_TIME")
    ok.sort(key=lambda r: (int(r.get("transit_minutes") or 0),
                           str(r.get("dispatch_cutoff_utc") or ""),
                           str(r.get("created_at") or "")))
    return ok[0]


# --------------------------------------------------------------------------
# §3.5 copy allocation
# --------------------------------------------------------------------------
def capacity_remaining(site, extra_allocated=0):
    cap = int(site.get("capacity_copies") or 0)
    used = sum(int(e.get("allocated_print_run_copies") or 0)
               for e in editions_of_site(site["id"]))
    return max(0, cap - used - extra_allocated)


def allocate_copies(site, market, requested, edition_rows=None):
    remaining = capacity_remaining(site)
    floor_copies = int(market.get("guaranteed_floor_copies") or 0)
    if floor_copies > remaining:
        fail("ERR_FLOOR_COPIES_EXCEED_CAPACITY")
    eff_requested = max(int(requested or 0), floor_copies)
    if site.get("allocation_method") == "PRIORITY":
        return min(eff_requested, remaining)
    rows = edition_rows if edition_rows is not None else editions_of_site(site["id"])
    total_requested = sum(int(e.get("requested_print_run_copies") or 0) for e in rows)
    if total_requested == 0:
        return 0
    allocated = int(int(eff_requested) * remaining // total_requested)
    allocated = max(allocated, floor_copies)
    allocated = min(allocated, eff_requested)
    allocated = min(allocated, remaining)
    return allocated


# --------------------------------------------------------------------------
# §3.5 transfer ledger
# --------------------------------------------------------------------------
def transfer_ledger(market):
    route = DB.get("print_routes", market.get("selected_print_route_id"))
    edition = latest_edition(market["id"])
    alloc = int(edition.get("allocated_print_run_copies") or 0) if edition else 0
    per_copy = D(route.get("marginal_cost_per_copy_cents") or 0) if route else D(0)
    cost = rhu(alloc * per_copy, 2)
    if market.get("status") == "withdrawn" or (edition and edition.get("correction_open")):
        # step 2 runs before the credit is stored, and the stored cost is the
        # rounded value the credit negates exactly.
        cost = market.get("print_site_transfer_cost_cents")
        if cost is None:
            cost = rhu(alloc * per_copy, 2)
        credit = -float(cost)
        if credit == 0:
            credit = 0
    else:
        credit = 0
    market["print_site_transfer_cost_cents"] = cost
    market["print_site_transfer_credit_cents"] = credit
    net = rhu(cost + credit, 2)
    market["net_print_site_transfer_cost_cents"] = 0 if net == 0 else net
    return market


# --------------------------------------------------------------------------
# §3.3 single-copy assortment decision
# --------------------------------------------------------------------------
def single_copy_decision(market):
    route = DB.get("print_routes", market.get("selected_print_route_id"))
    edition = latest_edition(market["id"])
    alloc = int(edition.get("allocated_print_run_copies") or 0) if edition else 0
    if market.get("status") == "withdrawn":
        market["newsstand_contribution_cents"] = None
        market["carrier_contribution_cents"] = None
        market["keeps_print_single_copy"] = False
        return market
    transport = D(route.get("route_transport_cost") or 0) if route else D(0)
    per_copy = D(route.get("marginal_cost_per_copy_cents") or 0) if route else D(0)
    revenue = int(market.get("per_copy_revenue_cents") or 0)
    sold = int(math.floor(alloc * 0.65))
    newsstand = rhu(sold * revenue - transport, 2)
    carrier = rhu(alloc * revenue - alloc * per_copy, 2)
    market["newsstand_contribution_cents"] = newsstand
    market["carrier_contribution_cents"] = carrier
    if market.get("single_copy_market_rule") == "newsstand":
        market["keeps_print_single_copy"] = newsstand >= 0
    else:
        market["keeps_print_single_copy"] = carrier >= 0
    return market


# --------------------------------------------------------------------------
# §3.6 subscriber economics
# --------------------------------------------------------------------------
def migration_credit(sub, market):
    per_issue_cost = CARRIER_LABOR_CENTS + PER_ISSUE_HANDLING_CENTS
    revenue = int(market.get("per_copy_revenue_cents") or 0) if market else 0
    value = int(sub.get("remaining_print_issues") or 0) * (per_issue_cost - revenue)
    return int(value)


def churn_retention_credit(sub):
    paid_through = sub.get("paid_through_utc")
    days_remaining = days_between_floor(now(), _parse_dt(paid_through))
    base = int(sub.get("remaining_print_issues") or 0) * int(sub.get("print_issue_value_cents") or 0)
    if days_remaining < 30:
        credit = int(base * 0.5)
    elif days_remaining <= 89:
        credit = int(base * 0.7)
    else:
        credit = int(base * 0.9)
    credit = max(credit, 0)
    if credit >= ACTIVE_CONTRACT_CAP_CENTS:
        credit = ACTIVE_CONTRACT_CAP_CENTS
    return credit


def offer_recommendation(sub):
    remaining_value = rhu(int(sub.get("remaining_print_issues") or 0)
                          * int(sub.get("print_issue_value_cents") or 0), 2)
    days_remaining = days_between_floor(now(), _parse_dt(sub.get("paid_through_utc")))
    if remaining_value < 5000:
        return "PRINT_CREDIT"
    if days_remaining >= 180:
        return "DIGITAL_UPGRADE"
    return "FULL_REFUND"


def _parse_dt(text):
    from core import _parse_iso
    return _parse_iso(text) if text else now()


# --------------------------------------------------------------------------
# §3.3 delivery route night cost
# --------------------------------------------------------------------------
def copies_carried_night(route):
    total = 0
    for ed in editions_of_market(route.get("print_market_id")):
        if ed.get("status") in ("in_production", "on_time_dispatch", "late_dispatch",
                                "delivered_market"):
            total += int(ed.get("allocated_print_run_copies") or 0)
    return total


def counted_stop_count(route):
    return len([s for s in stops_of_route(route["id"])
                if s.get("status") in ("active", "paused")])


def route_night_cost(route):
    contractor = DB.get("delivery_contractors", route.get("delivery_contractor_id"))
    copies = copies_carried_night(route)
    copy_term = D(0)
    if contractor and contractor.get("pay_basis") == "PER_COPY":
        copy_term = D(copies) * D(contractor.get("per_copy_rate_cents") or 0)
    billed = max(counted_stop_count(route), int(contractor.get("min_stop_guarantee") or 1)
                 if contractor else 1)
    base = rhu(copy_term + D(billed) * D(route.get("per_stop_fee_cents") or 0), 2)
    if copies <= 7500:
        tier = 0.00
    elif copies <= 15000:
        tier = 0.05
    elif copies <= 30000:
        tier = 0.10
    else:
        tier = 0.15
    factor = 0.85 if (contractor and contractor.get("status") == "terminated") else 1.00
    night = rhu(D(base) * (1 + D(tier)) * D(factor)
                + D(route.get("printed_copies_surcharge_cents") or 0), 2)
    per_copy = rhu(D(night) / copies, 4) if copies else 0
    route["base_cost_cents"] = base
    route["copy_volume_tier_pct"] = tier
    route["contractor_status_factor"] = factor
    route["copies_carried_night"] = copies
    route["route_night_cost"] = night
    route["cost_per_copy_cents"] = per_copy
    return route


# --------------------------------------------------------------------------
# §3.1 print-site savings ledger
# --------------------------------------------------------------------------
def site_savings(site):
    from datetime import timedelta
    current = today()
    window = [current - timedelta(days=k) for k in range(1, SAVINGS_WINDOW_DAYS + 1)]
    observed = []
    for day in window:
        key = (site["id"], day.isoformat())
        if key in DB.volume:
            observed.append((day, int(DB.volume[key])))
    total = sum(c for _, c in observed)
    flat = (D(total) / len(observed)) if observed else D(0)
    annualized = rhu(FIXED_PRESS_AVOIDED_CENTS + flat * SAVINGS_WINDOW_DAYS, 2)
    realized = rhu(FIXED_PRESS_AVOIDED_CENTS
                   + sum(c for d, c in observed if d <= current), 2)
    site["annualized_savings_cents"] = annualized
    site["realized_savings_cents"] = realized
    site["savings_divergence_cents"] = rhu(abs(D(annualized) - D(realized)), 2)
    return site


# --------------------------------------------------------------------------
# §3.5 correction re-run
# --------------------------------------------------------------------------
def correction_redispatch_cost(edition, route):
    transport = D(route.get("route_transport_cost") or 0) if route else D(0)
    return rhu(D(edition.get("press_run_hours") or 0) * D("2500.00")
               + transport * D("1.40"), 2)


# --------------------------------------------------------------------------
# §3.9 / §2.9 hub posture and legal-notice ratio
# --------------------------------------------------------------------------
def recompute_press_posture(hub):
    sites = sites_of_hub(hub["id"])
    statuses = [s.get("status") for s in sites]
    if statuses and all(s == "closed" for s in statuses):
        hub["press_posture"] = "SUSPENDED"
    elif any(s == "closing" for s in statuses):
        hub["press_posture"] = "RESTRICTED"
    else:
        hub["press_posture"] = "OPEN"
    return hub


def market_is_on_time(market):
    """§2.9 counted-market numerator: a market is on time when its latest edition
    is on time *and* the market is still receiving print.

    §3.4 states that "a paused stop stops taking copies, a pause can push a market
    off time", and §3.2 relies on a withdrawal's stop termination moving the hub's
    ratio, so a market whose stops are not all active is not receiving print; a
    market with no delivery stops at all is judged on its edition alone. §3.5's
    reverted edition contributes no press hours "to any downstream figure", so a
    reverted or corrected edition no longer carries the market either.
    """
    ed = latest_edition(market["id"])
    if ed is None or not ed.get("is_on_time"):
        return False
    if ed.get("correction_open") or ed.get("status") == "reverted_to_digital":
        return False
    for stop in stops_of_market(market["id"]):
        if stop.get("status") != "active":
            return False
    return True


def legal_notice_verdict(hub):
    counted = [m for m in markets_of_hub(hub["id"])
               if m.get("status") in COUNTED_MARKET_STATUSES]
    on_time = 0
    for m in counted:
        if market_is_on_time(m):
            on_time += 1
    denominator = len(counted)
    if denominator == 0:
        compliant = False
    else:
        compliant = on_time * 100 >= int(hub.get("min_on_time_ratio_pct") or 90) * denominator
    return compliant, on_time, denominator


def refresh_legal_notice_block(hub):
    compliant, _, _ = legal_notice_verdict(hub)
    hub["legal_notice_block"] = not compliant
    return hub


def delivery_boycott_active(market):
    stops = stops_of_market(market["id"])
    return not any(s.get("status") == "active" for s in stops)


# --------------------------------------------------------------------------
# §3.8 newsroom allocation
# --------------------------------------------------------------------------
def region_need_score(region):
    total = 0
    for m in markets_of_region(region["id"]):
        if m.get("status") in COUNTED_MARKET_STATUSES:
            total += int(m.get("weighted_demand_units") or 0)
    return rhu(D(total) / 1000, 2)


def recompute_hub_allocation(hub):
    regions = sorted(regions_of_hub(hub["id"]),
                     key=lambda r: (int(r.get("allocation_priority") or 0),
                                    str(r.get("name") or "")))
    pool = int(hub.get("total_newsroom_headcount") or 0)
    guaranteed = {}
    for r in regions:
        score = region_need_score(r)
        r["region_need_score"] = score
        cap = r.get("daily_headcount_cap")
        r["daily_headcount_cap"] = cap if cap is not None else int(r.get("daily_headcount_floor") or 0)
        r["member_market_count"] = len(markets_of_region(r["id"]))
        guaranteed[r["id"]] = min(int(math.floor(score)),
                                  int(r.get("daily_headcount_floor") or 0))
        r["guaranteed_headcount"] = guaranteed[r["id"]]
    residual = pool - sum(guaranteed.values())
    for r in regions:
        cap = int(r.get("daily_headcount_cap") or 0)
        headroom = cap - guaranteed[r["id"]]
        grant = max(0, min(residual, headroom))
        allocated = guaranteed[r["id"]] + grant
        residual -= grant
        r["allocated_newsroom_headcount"] = allocated
    total_allocated = sum(int(r.get("allocated_newsroom_headcount") or 0) for r in regions)
    hub["unassigned_headcount"] = pool - total_allocated
    return hub


def recompute_region_allocated(region, hub):
    positions = [p for p in DB.all("newsroom_positions")
                 if p.get("region_id") == region["id"]]
    total = 0
    for p in positions:
        total += int(p.get("allocated_headcount") or 0)
    region["allocated_newsroom_headcount"] = total
    return region


def severance_cost(change, position):
    severed = int(change.get("requested_slots") or 0) - int(change.get("allocated_slots") or 0)
    monthly = D(position.get("monthly_cost_cents") or 0) if position else D(0)
    if severed <= 0:
        return 0
    if severed <= 2:
        return rhu(D(severed) * D("2.1500") * D("1.6500") * monthly, 2)
    return rhu(D(severed) * D("2.1500") * D("0.2500") * monthly * D("1.6500"), 2)


def residual_pass(hub):
    """Residual headcount left to each sibling change, in residual pass order."""
    changes = [c for c in DB.all("newsroom_changes") if _change_hub(c) is not None
               and _change_hub(c)["id"] == hub["id"]]
    changes.sort(key=lambda c: (str(c.get("created_at") or ""),
                                int(c.get("layoff_order_index") or 0),
                                str(c.get("id") or "")))
    running = int(hub.get("unassigned_headcount") or 0)
    for c in changes:
        available = max(0, running)
        c["residual_headcount"] = available
        c["allocated_slots"] = min(int(c.get("requested_slots") or 0), available)
        running = available - int(c.get("allocated_slots") or 0)
    return changes


def _change_hub(change):
    position = DB.get("newsroom_positions", change.get("newsroom_position_id"))
    region = DB.get("regions", position.get("region_id")) if position else None
    return DB.get("region_hubs", region.get("region_hub_id")) if region else None


# --------------------------------------------------------------------------
# §3.3 sanction policy selector
# --------------------------------------------------------------------------
def select_active_sanction_policy(hub):
    eligible = [c for c in contractors_of_hub(hub["id"])
                if c.get("status") in ("active", "suspended")
                and c.get("net_60_available") is True
                and c.get("sanction_reason_code") != "RESIDUAL_PROGRAMME"]
    if not eligible:
        return None, "NO_ELIGIBLE_CONTRACTOR"
    eligible.sort(key=lambda c: (int(c.get("per_copy_rate_cents") or 0),
                                 str(c.get("name") or "")))
    return eligible[0], None