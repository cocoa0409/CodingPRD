"""Precondition builders. Every one of them builds its state through the public API only."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    make_corporate_lead_headers,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
)

# ---------------------------------------------------------------------------
# Tier 0: the logical clock
# ---------------------------------------------------------------------------


def set_clock(current_utc: str) -> Dict[str, Any]:
    """Advance the logical clock, which is the only operation that resolves an ACTIVE target."""
    return get_success_data(api_client.set_clock(current_utc))


# ---------------------------------------------------------------------------
# Tier 1: single-step state progression
# ---------------------------------------------------------------------------


def create_site(**overrides: Any) -> Dict[str, Any]:
    payload = factories.create_site_payload(**overrides)
    return get_success_data(api_client.create_site(payload, make_platform_admin_headers()))


def create_food_type(**overrides: Any) -> Dict[str, Any]:
    payload = factories.create_food_type_payload(**overrides)
    return get_success_data(api_client.create_food_type(payload, make_platform_admin_headers()))


def create_recipe(ingredients: Optional[List[Dict[str, Any]]] = None, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_recipe_payload(ingredients=ingredients, **overrides)
    return get_success_data(api_client.create_recipe(payload, make_platform_admin_headers()))


def publish_recipe(recipe_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_recipe(recipe_id, make_platform_admin_headers()))


def create_published_recipe(ingredients: Optional[List[Dict[str, Any]]] = None, **overrides: Any) -> Dict[str, Any]:
    recipe = create_recipe(ingredients=ingredients, **overrides)
    return publish_recipe(recipe["id"])


def create_station(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_tracking_station_payload(site_id, **overrides)
    return get_success_data(api_client.create_tracking_station(payload, make_platform_admin_headers()))


def set_station_status(site_id: str, station_id: str, status: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.station_status_payload(status, **overrides)
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.set_station_status(station_id, payload, headers))


def open_shift(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_shift_payload(site_id, **overrides)
    return get_success_data(api_client.create_shift(payload, make_shift_lead_headers()))


def close_shift(shift_id: str, user_id: str = "sl-1") -> Dict[str, Any]:
    return get_success_data(api_client.close_shift(shift_id, make_shift_lead_headers(user_id)))


def capture_entry(
    station_id: str, shift_id: str, food_type_id: str, as_kitchen_staff: bool = True, user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.create_waste_entry_payload(station_id, shift_id, food_type_id, **overrides)
    if as_kitchen_staff:
        headers = make_kitchen_staff_headers(user_id or "ks-1")
    else:
        headers = make_shift_lead_headers(user_id or "sl-1")
    return get_success_data(api_client.create_waste_entry(payload, headers))


def flag_entry(entry_id: str, user_id: str = "sl-1", **overrides: Any) -> Dict[str, Any]:
    payload = factories.flag_payload(**overrides)
    return get_success_data(api_client.flag_waste_entry(entry_id, payload, make_shift_lead_headers(user_id)))


def clear_entry_flag(entry_id: str, user_id: str = "sl-1") -> Dict[str, Any]:
    return get_success_data(api_client.clear_waste_entry_flag(entry_id, make_shift_lead_headers(user_id)))


def void_entry(entry_id: str, user_id: str = "sl-2", **overrides: Any) -> Dict[str, Any]:
    """Voids as a second ShiftLead identity, because a lead may not void their own capture."""
    payload = factories.void_payload(**overrides)
    return get_success_data(api_client.void_waste_entry(entry_id, payload, make_shift_lead_headers(user_id)))


def correct_entry(entry_id: str, expected_entry_version: int, user_id: str = "sl-1", **overrides: Any) -> Dict[str, Any]:
    payload = factories.correction_payload(expected_entry_version, **overrides)
    return get_success_data(api_client.correct_waste_entry(entry_id, payload, make_shift_lead_headers(user_id)))


def open_baseline(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_baseline_period_payload(site_id, **overrides)
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.create_baseline_period(payload, headers))


def submit_baseline(site_id: str, baseline_id: str) -> Dict[str, Any]:
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.submit_baseline_period(baseline_id, headers))


def certify_baseline(baseline_id: str, user_id: str = "csl-1") -> Dict[str, Any]:
    return get_success_data(api_client.certify_baseline_period(baseline_id, make_corporate_lead_headers(user_id)))


def reject_baseline(baseline_id: str, user_id: str = "csl-1", **overrides: Any) -> Dict[str, Any]:
    payload = factories.reject_baseline_payload(**overrides)
    return get_success_data(api_client.reject_baseline_period(baseline_id, payload, make_corporate_lead_headers(user_id)))


def propose_target(
    site_id: str, baseline_period_id: str, expected_site_version: int, user_id: str = "csl-1", **overrides: Any
) -> Dict[str, Any]:
    payload = factories.create_reduction_target_payload(
        site_id, baseline_period_id, expected_site_version, **overrides
    )
    return get_success_data(api_client.create_reduction_target(payload, make_corporate_lead_headers(user_id)))


def activate_target(target_id: str, user_id: str = "csl-1") -> Dict[str, Any]:
    return get_success_data(api_client.activate_reduction_target(target_id, make_corporate_lead_headers(user_id)))


def create_hauler(**overrides: Any) -> Dict[str, Any]:
    payload = factories.create_hauler_payload(**overrides)
    return get_success_data(api_client.create_hauler(payload, make_platform_admin_headers()))


def approve_hauler(hauler_id: str, user_id: str = "csl-1") -> Dict[str, Any]:
    return get_success_data(api_client.approve_hauler(hauler_id, make_corporate_lead_headers(user_id)))


def create_approved_hauler(**overrides: Any) -> Dict[str, Any]:
    hauler = create_hauler(**overrides)
    return approve_hauler(hauler["id"])


def open_consignment(site_id: str, hauler_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_consignment_payload(site_id, hauler_id, **overrides)
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.create_consignment(payload, headers))


def add_line(
    site_id: str, consignment_id: str, waste_entry_id: str, allocated_weight_grams: int, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.create_consignment_line_payload(
        consignment_id, waste_entry_id, allocated_weight_grams, **overrides
    )
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.create_consignment_line(payload, headers))


def delete_line(site_id: str, line_id: str) -> Dict[str, Any]:
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.delete_consignment_line(line_id, headers))


def stage_consignment(site_id: str, consignment_id: str) -> Dict[str, Any]:
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.stage_consignment(consignment_id, headers))


def dispatch_consignment(site_id: str, consignment_id: str) -> Dict[str, Any]:
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.dispatch_consignment(consignment_id, headers))


def cancel_consignment(site_id: str, consignment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.cancel_consignment_payload(**overrides)
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.cancel_consignment(consignment_id, payload, headers))


def submit_ticket(hauler_id: str, consignment_id: str, gross_weight_grams: int, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_hauler_ticket_payload(consignment_id, gross_weight_grams, **overrides)
    headers = make_hauler_operator_headers(hauler_id)
    return get_success_data(api_client.create_hauler_ticket(payload, headers))


def accept_ticket(site_id: str, ticket_id: str) -> Dict[str, Any]:
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.accept_hauler_ticket(ticket_id, headers))


def dispute_ticket(site_id: str, ticket_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.dispute_ticket_payload(**overrides)
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.dispute_hauler_ticket(ticket_id, payload, headers))


def acknowledge_alert(alert_id: str, user_id: str = "ks-1") -> Dict[str, Any]:
    return get_success_data(api_client.acknowledge_alert(alert_id, make_kitchen_staff_headers(user_id)))


def resolve_alert(alert_id: str, user_id: str = "sl-1", **overrides: Any) -> Dict[str, Any]:
    payload = factories.resolve_alert_payload(**overrides)
    return get_success_data(api_client.resolve_alert(alert_id, payload, make_shift_lead_headers(user_id)))


def run_scan(site_id: str, scan_date: str, **overrides: Any) -> List[Dict[str, Any]]:
    payload = factories.create_data_quality_scan_payload(site_id, scan_date, **overrides)
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.create_data_quality_scan(payload, headers))


def resolve_finding(site_id: str, finding_id: str, resolution: str = "CONFIRMED", **overrides: Any) -> Dict[str, Any]:
    payload = factories.resolve_finding_payload(resolution, **overrides)
    headers = make_site_sustainability_manager_headers(site_id)
    return get_success_data(api_client.resolve_finding(finding_id, payload, headers))


def prepare_rollup(site_ids: List[str], user_id: str = "csl-1", **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_rollup_payload(site_ids, **overrides)
    return get_success_data(api_client.create_rollup(payload, make_corporate_lead_headers(user_id)))


def publish_rollup(rollup_id: str, user_id: str = "csl-2") -> Dict[str, Any]:
    """Publishes as a second corporate identity, because the preparer may never publish."""
    return get_success_data(api_client.publish_rollup(rollup_id, make_corporate_lead_headers(user_id)))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchies
# ---------------------------------------------------------------------------


def catalog_with_prep_station(**site_overrides: Any) -> Dict[str, Any]:
    """A site, a PREP station and one catalog food type — the minimum a capture needs."""
    site = create_site(**site_overrides)
    station = create_station(site["id"], station_code="PREP-1", station_kind="PREP")
    food_type = create_food_type()
    return {"site": site, "station": station, "food_type": food_type}


def catalog_with_prep_and_dish_stations(**site_overrides: Any) -> Dict[str, Any]:
    """Both station kinds at one site, which is what a compliance denominator of two needs."""
    site = create_site(**site_overrides)
    prep = create_station(site["id"], station_code="PREP-1", station_kind="PREP")
    dish = create_station(site["id"], station_code="DISH-1", station_kind="DISH_RETURN")
    food_type = create_food_type()
    return {"site": site, "prep_station": prep, "dish_station": dish, "food_type": food_type}


def site_with_open_shift(shift_overrides: Optional[Dict[str, Any]] = None, **site_overrides: Any) -> Dict[str, Any]:
    """A site with one PREP station, one food type and one OPEN service period."""
    world = catalog_with_prep_station(**site_overrides)
    world["shift"] = open_shift(world["site"]["id"], **(shift_overrides or {}))
    return world


def site_with_one_capture(
    entry_overrides: Optional[Dict[str, Any]] = None,
    shift_overrides: Optional[Dict[str, Any]] = None,
    **site_overrides: Any,
) -> Dict[str, Any]:
    """One site, one OPEN period, one RECORDED capture."""
    world = site_with_open_shift(shift_overrides=shift_overrides, **site_overrides)
    world["entry"] = capture_entry(
        world["station"]["id"], world["shift"]["id"], world["food_type"]["id"], **(entry_overrides or {})
    )
    return world


def site_with_draft_consignment(
    entry_overrides: Optional[Dict[str, Any]] = None,
    hauler_overrides: Optional[Dict[str, Any]] = None,
    consignment_overrides: Optional[Dict[str, Any]] = None,
    **site_overrides: Any,
) -> Dict[str, Any]:
    """A capture and a DRAFT consignment on an APPROVED hauler, ready for allocation lines."""
    world = site_with_one_capture(entry_overrides=entry_overrides, **site_overrides)
    world["hauler"] = create_approved_hauler(**(hauler_overrides or {}))
    world["consignment"] = open_consignment(
        world["site"]["id"], world["hauler"]["id"], **(consignment_overrides or {})
    )
    return world


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------


def staged_consignment(allocated_weight_grams: int = 1000, **kwargs: Any) -> Dict[str, Any]:
    """A consignment carrying one line and locked at STAGED."""
    world = site_with_draft_consignment(**kwargs)
    world["line"] = add_line(
        world["site"]["id"], world["consignment"]["id"], world["entry"]["id"], allocated_weight_grams
    )
    world["consignment"] = stage_consignment(world["site"]["id"], world["consignment"]["id"])
    return world


def dispatched_consignment(allocated_weight_grams: int = 1000, **kwargs: Any) -> Dict[str, Any]:
    """A consignment collected at pickup and therefore ticket-eligible on the settlement axis."""
    world = staged_consignment(allocated_weight_grams=allocated_weight_grams, **kwargs)
    world["consignment"] = dispatch_consignment(world["site"]["id"], world["consignment"]["id"])
    return world


def ticketed_consignment(
    gross_weight_grams: int = 1000, allocated_weight_grams: int = 1000, **kwargs: Any
) -> Dict[str, Any]:
    """A dispatched consignment carrying one SUBMITTED weigh ticket."""
    world = dispatched_consignment(allocated_weight_grams=allocated_weight_grams, **kwargs)
    world["ticket"] = submit_ticket(world["hauler"]["id"], world["consignment"]["id"], gross_weight_grams)
    return world


def settled_consignment(
    gross_weight_grams: int = 1000, allocated_weight_grams: int = 1000, **kwargs: Any
) -> Dict[str, Any]:
    """A consignment whose ticket has been accepted, so its grams are settled diversion."""
    world = ticketed_consignment(
        gross_weight_grams=gross_weight_grams, allocated_weight_grams=allocated_weight_grams, **kwargs
    )
    world["ticket"] = accept_ticket(world["site"]["id"], world["ticket"]["id"])
    return world


def certified_baseline(
    baseline_overrides: Optional[Dict[str, Any]] = None,
    entry_overrides: Optional[Dict[str, Any]] = None,
    shift_overrides: Optional[Dict[str, Any]] = None,
    **site_overrides: Any,
) -> Dict[str, Any]:
    """A CERTIFIED baseline period: capture in the window, period closed for meals, then certified."""
    world = site_with_one_capture(
        entry_overrides=entry_overrides, shift_overrides=shift_overrides, **site_overrides
    )
    world["shift"] = close_shift(world["shift"]["id"])
    world["baseline"] = open_baseline(world["site"]["id"], **(baseline_overrides or {}))
    world["baseline"] = submit_baseline(world["site"]["id"], world["baseline"]["id"])
    world["baseline"] = certify_baseline(world["baseline"]["id"])
    return world


def active_target(target_overrides: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    """A reduction target bound to a certified baseline and advanced to ACTIVE."""
    world = certified_baseline(**kwargs)
    site = get_success_data(api_client.get_site(world["site"]["id"], make_platform_admin_headers()))
    world["site"] = site
    world["target"] = propose_target(
        site["id"], world["baseline"]["id"], site["version"], **(target_overrides or {})
    )
    world["target"] = activate_target(world["target"]["id"])
    return world


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------


def shift_at_intensity(grams: int, meals_served: int, **site_overrides: Any) -> Dict[str, Any]:
    """One capture of exactly ``grams`` on a period of ``meals_served`` covers."""
    world = site_with_open_shift(shift_overrides={"meals_served": meals_served}, **site_overrides)
    world["entry"] = capture_entry(
        world["station"]["id"], world["shift"]["id"], world["food_type"]["id"], weight_grams=grams
    )
    return world


def site_with_open_alerts(alert_count: int, **site_overrides: Any) -> Dict[str, Any]:
    """Raise ``alert_count`` distinct alerts by walking one period per alert to the same breach."""
    world = catalog_with_prep_station(**site_overrides)
    shift_codes = ["AM", "PM", "NIGHT"]
    shifts: List[Dict[str, Any]] = []
    for index in range(alert_count):
        shift_date = f"2026-08-{1 + index // 3:02d}"
        shift = open_shift(
            world["site"]["id"], shift_date=shift_date, shift_code=shift_codes[index % 3], meals_served=100
        )
        capture_entry(
            world["station"]["id"],
            shift["id"],
            world["food_type"]["id"],
            weight_grams=6000,
            loss_reason="OVERPRODUCTION",
            captured_at=f"{shift_date}T00:00:00Z",
        )
        shifts.append(shift)
    world["shifts"] = shifts
    world["site"] = get_success_data(api_client.get_site(world["site"]["id"], make_platform_admin_headers()))
    return world


# ---------------------------------------------------------------------------
# Tier 5: finalization and terminal states
# ---------------------------------------------------------------------------


def closed_shift_with_capture(
    entry_overrides: Optional[Dict[str, Any]] = None,
    shift_overrides: Optional[Dict[str, Any]] = None,
    **site_overrides: Any,
) -> Dict[str, Any]:
    """A period carried through the final valuation pass and the leaderboard scoring."""
    world = site_with_one_capture(
        entry_overrides=entry_overrides, shift_overrides=shift_overrides, **site_overrides
    )
    world["shift"] = close_shift(world["shift"]["id"])
    world["entry"] = get_success_data(
        api_client.get_waste_entry(world["entry"]["id"], make_platform_admin_headers())
    )
    return world


def draft_rollup_over_one_site(
    rollup_overrides: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Dict[str, Any]:
    """A DRAFT rollup scoped to a single site holding one capture."""
    world = site_with_one_capture(**kwargs)
    world["rollup"] = prepare_rollup([world["site"]["id"]], **(rollup_overrides or {}))
    return world


def published_rollup(**kwargs: Any) -> Dict[str, Any]:
    """A rollup signed off by a second corporate identity, freezing its metrics."""
    world = draft_rollup_over_one_site(**kwargs)
    world["rollup"] = publish_rollup(world["rollup"]["id"])
    return world


# ---------------------------------------------------------------------------
# Read-through helpers
# ---------------------------------------------------------------------------


def read_site(site_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_site(site_id, make_platform_admin_headers()))


def read_shift(shift_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_shift(shift_id, make_platform_admin_headers()))


def read_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_waste_entry(entry_id, make_platform_admin_headers()))


def read_consignment(consignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_consignment(consignment_id, make_platform_admin_headers()))


def read_line(line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_consignment_line(line_id, make_platform_admin_headers()))


def read_ticket(ticket_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_hauler_ticket(ticket_id, make_platform_admin_headers()))


def read_alert(alert_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_alert(alert_id, make_platform_admin_headers()))


def read_finding(finding_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_finding(finding_id, make_platform_admin_headers()))


def read_baseline(baseline_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_baseline_period(baseline_id, make_platform_admin_headers()))


def read_target(target_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_reduction_target(target_id, make_platform_admin_headers()))


def read_attainment(target_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_target_attainment(target_id, make_platform_admin_headers()))


def read_rollup(rollup_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_rollup(rollup_id, make_platform_admin_headers()))


def read_recipe(recipe_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_recipe(recipe_id, make_platform_admin_headers()))


def read_station(station_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_tracking_station(station_id, make_platform_admin_headers()))


def read_hauler(hauler_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_hauler(hauler_id, make_platform_admin_headers()))
