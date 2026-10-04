"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data so a
setup failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_ad_campaign_payload,
    create_ad_slot_payload,
    create_capacity_pool_payload,
    create_partner_payload,
    create_property_payload,
    create_reservation_payload,
    create_territory_rule_payload,
    create_viewer_payload,
    create_window_payload,
)
from .test_users import TEST_USERS, make_viewer_headers

RM = TEST_USERS["rights_manager_headers"]
AD = TEST_USERS["ad_ops_headers"]
SO = TEST_USERS["stream_ops_headers"]
PM = TEST_USERS["partner_manager_headers"]

REGION = TEST_DEFAULTS["REGION"]


def set_clock(iso: str):
    """Advance the logical clock (PRD §2.8)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, SO))


def create_property(**overrides):
    """Create a property (NEGOTIATION). Returns the property dict."""
    return get_success_data(api_client.create_property(create_property_payload(**overrides), RM))


def create_active_property(**overrides):
    """Create + activate a property. Returns the ACTIVE property dict."""
    prop = create_property(**overrides)
    return get_success_data(api_client.activate_property(prop["id"], RM))


def current_property_version(property_id) -> int:
    return get_success_data(api_client.get_property(property_id, RM))["version"]


def create_window(property_id, **overrides):
    """Create a window against the property, threading the current property
    version into expected_property_version. Returns the window dict."""
    version = current_property_version(property_id)
    payload = create_window_payload(property_id, version, **overrides)
    return get_success_data(api_client.create_window(payload, RM))


def create_pool(**overrides):
    return get_success_data(api_client.create_capacity_pool(create_capacity_pool_payload(**overrides), SO))


def hold_reservation(pool_id, window_id, units=1):
    payload = create_reservation_payload(pool_id, window_id, units=units)
    return get_success_data(api_client.create_capacity_reservation(payload, SO))


def confirm_reservation(reservation_id):
    return get_success_data(api_client.confirm_capacity_reservation(reservation_id, SO))


def hold_and_confirm(pool_id, window_id, units=1):
    res = hold_reservation(pool_id, window_id, units=units)
    confirm_reservation(res["id"])
    return get_success_data(api_client.get_capacity_reservation(res["id"], SO))


def provision_window_capacity(window_id, units, pool=None):
    """Hold + confirm `units` of capacity for the window. Returns (pool, reservation)."""
    if pool is None:
        pool = create_pool(total_units=max(units, 100))
    res = hold_and_confirm(pool["id"], window_id, units=units)
    return pool, res


def create_booked_campaign(**overrides):
    campaign = get_success_data(api_client.create_ad_campaign(create_ad_campaign_payload(**overrides), AD))
    return get_success_data(api_client.book_ad_campaign(campaign["id"], AD))


def create_slot(window_id, **overrides):
    return get_success_data(api_client.create_ad_slot(create_ad_slot_payload(window_id, **overrides), AD))


def fill_slot(slot_id, campaign_id):
    """Fill a slot one leg (OPEN -> RESERVED), threading the current window
    version. Returns the slot dict after the leg."""
    window_id = get_success_data(api_client.get_ad_slot(slot_id, AD))["window_id"]
    wv = get_success_data(api_client.get_window(window_id, RM))["version"]
    return get_success_data(
        api_client.fill_ad_slot(slot_id, {"campaign_id": campaign_id, "expected_window_version": wv}, AD)
    )


def fill_slot_twice(slot_id, campaign_id):
    """Both fill legs (OPEN -> RESERVED -> FILLED). Returns final slot."""
    fill_slot(slot_id, campaign_id)
    return fill_slot(slot_id, campaign_id)


def create_viewer(**overrides):
    """Register a viewer. Registration is open to the Viewer role; the shared
    header is fine here because no Viewer entity exists yet to own."""
    return get_success_data(
        api_client.create_viewer(create_viewer_payload(**overrides), TEST_USERS["viewer_headers"])
    )


def make_live_window(property_overrides=None, window_overrides=None, capacity_units=None,
                     live_at=None, required_local_breaks=0):
    """Full pipeline: ACTIVE property + SCHEDULED window + confirmed capacity
    meeting the capacity gate + go-live. Returns (property, window).

    If required_local_breaks > 0, also creates and double-fills that many
    LOCAL slots so the local-break gate passes.
    """
    property_overrides = dict(property_overrides or {})
    window_overrides = dict(window_overrides or {})
    property_overrides.setdefault("required_local_breaks_per_event", required_local_breaks)
    prop = create_active_property(**property_overrides)
    window = create_window(prop["id"], **window_overrides)
    units = capacity_units if capacity_units is not None else window["capacity_required_units"]
    provision_window_capacity(window["id"], units)
    if required_local_breaks > 0:
        campaign = create_booked_campaign(region_target=window.get("territory_scope", [REGION]))
        for i in range(required_local_breaks):
            slot = create_slot(
                window["id"],
                break_index=1,
                pod_index=i + 1,
                duration_seconds=15,
                slot_scope="LOCAL",
                region_code=window["territory_scope"][0],
            )
            fill_slot_twice(slot["id"], campaign["id"])
    if live_at is None:
        live_at = window["scheduled_start"]
    set_clock(live_at)
    window = get_success_data(api_client.go_live_window(window["id"], RM))
    return prop, window


def make_completed_window(property_overrides=None, window_overrides=None, capacity_units=None,
                          live_at=None):
    """make_live_window + complete. Returns (property, window)."""
    prop, window = make_live_window(property_overrides, window_overrides, capacity_units, live_at)
    window = get_success_data(api_client.complete_window(window["id"], RM))
    return prop, window


def create_partner(**overrides):
    return get_success_data(api_client.create_partner(create_partner_payload(**overrides), PM))


def issue_promo_code(partner_id):
    return get_success_data(api_client.issue_promo_code(partner_id, PM))


def viewer_with_bundle_entitlement(**viewer_overrides):
    """Partner + one ISSUED code + viewer + redeem. Returns
    (partner, promo_code, viewer, entitlement)."""
    partner = create_partner()
    code = issue_promo_code(partner["id"])
    viewer = create_viewer(**viewer_overrides)
    headers = make_viewer_headers(viewer["id"])
    entitlement = get_success_data(
        api_client.redeem_promo_code({"code": code["code"], "viewer_id": viewer["id"]}, headers)
    )
    viewer = get_success_data(api_client.get_viewer(viewer["id"], PM))
    return partner, code, viewer, entitlement
