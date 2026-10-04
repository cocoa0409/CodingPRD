"""Composite setup helpers.

Every test starts against a freshly restarted server with an empty database and
the logical clock at its boot default of 2026-09-01T00:00:00Z. These fixtures
build multi-step preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_asset_payload,
    create_campaign_payload,
    create_maintenance_window_payload,
    create_production_payload,
    create_render_batch_payload,
    create_show_payload,
    create_sponsor_payload,
    create_venue_system_payload,
)
from .test_users import TEST_USERS

PD = TEST_USERS["production_director_headers"]
CP = TEST_USERS["content_producer_headers"]
VS = TEST_USERS["venue_scheduler_headers"]
VO = TEST_USERS["venue_ops_engineer_headers"]
SM = TEST_USERS["sponsorship_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]
GU = TEST_USERS["guest_headers"]


# ---------------------------------------------------------------- clock


def set_clock(to_iso8601: str):
    """Advance the logical clock (ProductionDirector test-driving capability)."""
    resp = api_client.set_clock(to_iso8601, PD)
    assert resp.status_code == 200, f"clock set failed: {resp.text}"


# ---------------------------------------------------------------- productions


def create_production(**overrides) -> dict:
    """Create a production (lands in DRAFT with gain_cents 0)."""
    data = get_success_data(api_client.create_production(create_production_payload(**overrides), PD))
    return data


def create_active_production(**overrides) -> dict:
    """Create a production and activate it. Returns the activated production."""
    prod = create_production(**overrides)
    return get_success_data(api_client.activate_production(prod["id"], PD))


# ---------------------------------------------------------------- assets & render pipeline


def capture_asset(production_id, **overrides) -> dict:
    """Capture an asset under a production (lands in CAPTURED)."""
    return get_success_data(api_client.create_asset(create_asset_payload(production_id, **overrides), CP))


def render_asset_to_qc(asset_id, dispatch_mode="STANDARD", settle_clock="2026-09-01T03:00:00Z"):
    """Create a batch holding the asset, dispatch it, advance the clock past the
    projected render duration, and settle. Returns (asset_in_qc, batch)."""
    batch = get_success_data(
        api_client.create_render_batch(create_render_batch_payload([asset_id], dispatch_mode=dispatch_mode), CP)
    )
    get_success_data(api_client.dispatch_render_batch(batch["id"], CP))
    set_clock(settle_clock)
    batch = get_success_data(api_client.settle_render_batch(batch["id"], CP))
    asset = get_success_data(api_client.get_asset(asset_id, CP))
    return asset, batch


def create_approved_asset(production_id, settle_clock="2026-09-01T03:00:00Z", **asset_overrides) -> dict:
    """Capture an asset and run the full render pipeline to APPROVED."""
    asset = capture_asset(production_id, **asset_overrides)
    render_asset_to_qc(asset["id"], settle_clock=settle_clock)
    return get_success_data(api_client.qc_approve_asset(asset["id"], CP))


def setup_active_production_with_approved_asset(
    base_price_cents=10000, is_haptic_capable=False, settle_clock="2026-09-01T03:00:00Z", **prod_overrides
):
    """Active production + one APPROVED asset. Returns (production, asset)."""
    prod = create_active_production(base_price_cents=base_price_cents, is_haptic_capable=is_haptic_capable, **prod_overrides)
    if is_haptic_capable:
        asset = create_approved_asset(prod["id"], settle_clock=settle_clock, capture_format="WRAP_16K")
    else:
        asset = create_approved_asset(prod["id"], settle_clock=settle_clock)
    return prod, asset


# ---------------------------------------------------------------- shows


def create_show(production_id, **overrides) -> dict:
    """Create a show (lands in TENTATIVE)."""
    return get_success_data(api_client.create_show(create_show_payload(production_id, **overrides), VS))


def create_show_in_rehearsal(production_id, **overrides) -> dict:
    """Create a show and schedule its rehearsal (lands in REHEARSAL with
    rehearsal_minutes and changeover_minutes computed)."""
    show = create_show(production_id, **overrides)
    return get_success_data(api_client.schedule_rehearsal(show["id"], VS))


def setup_show_in_rehearsal(
    base_price_cents=10000,
    is_haptic_capable=False,
    show_overrides=None,
    settle_clock="2026-09-01T03:00:00Z",
):
    """Active production + APPROVED asset + one show in REHEARSAL.
    Returns (production, asset, show)."""
    prod, asset = setup_active_production_with_approved_asset(
        base_price_cents=base_price_cents,
        is_haptic_capable=is_haptic_capable,
        settle_clock=settle_clock,
    )
    show = create_show_in_rehearsal(prod["id"], **(show_overrides or {}))
    return prod, asset, show


def confirm_show_with_occ(show_id, production_id) -> dict:
    """Read the production's current version and confirm the show with it."""
    prod = get_success_data(api_client.get_production(production_id, PD))
    return get_success_data(
        api_client.confirm_show(show_id, {"expected_production_version": prod["version"]}, VS)
    )


def setup_confirmed_show(
    base_price_cents=10000,
    is_haptic_capable=False,
    show_overrides=None,
    settle_clock="2026-09-01T03:00:00Z",
):
    """Active production + APPROVED asset + one CONFIRMED show.
    Returns (production, asset, show)."""
    prod, asset, show = setup_show_in_rehearsal(
        base_price_cents=base_price_cents,
        is_haptic_capable=is_haptic_capable,
        show_overrides=show_overrides,
        settle_clock=settle_clock,
    )
    show = confirm_show_with_occ(show["id"], prod["id"])
    return prod, asset, show


# ---------------------------------------------------------------- sponsors & campaigns


def create_sponsor(**overrides) -> dict:
    """Register a sponsor (active_campaign_count starts at 0)."""
    return get_success_data(api_client.create_sponsor(create_sponsor_payload(**overrides), SM))


def create_campaign(sponsor_id, **overrides) -> dict:
    """Create a campaign under a sponsor (lands in DRAFT)."""
    return get_success_data(api_client.create_campaign(create_campaign_payload(sponsor_id, **overrides), SM))


def create_active_campaign(brand_tier="STANDARD", sponsor=None, **campaign_overrides):
    """Sponsor + campaign activated (flight window covers the logical clock).
    Returns (sponsor, campaign)."""
    if sponsor is None:
        sponsor = create_sponsor(brand_tier=brand_tier)
    campaign = create_campaign(sponsor["id"], **campaign_overrides)
    campaign = get_success_data(
        api_client.activate_campaign(campaign["id"], {"expected_sponsor_version": sponsor["version"]}, SM)
    )
    sponsor = get_success_data(api_client.get_sponsor(sponsor["id"], SM))
    return sponsor, campaign


# ---------------------------------------------------------------- venue systems & maintenance


def create_venue_system(**overrides) -> dict:
    """Register a venue system (comes up ONLINE with consecutive_failed_windows 0)."""
    return get_success_data(api_client.create_venue_system(create_venue_system_payload(**overrides), VO))


def fail_one_window(system_id, window_start, window_end, fail_clock, buffer_minutes=15) -> dict:
    """Schedule a maintenance window, advance the clock into it (window becomes
    ACTIVE), and mark it FAILED. Returns the failed window."""
    window = get_success_data(
        api_client.create_maintenance_window(
            create_maintenance_window_payload(
                system_id, start_time=window_start, end_time=window_end, buffer_minutes=buffer_minutes
            ),
            VO,
        )
    )
    set_clock(fail_clock)
    return get_success_data(api_client.fail_maintenance_window(window["id"], VO))


def degrade_venue_system(kind="AUDIO_BEAM") -> dict:
    """Create a venue system and drive it to DEGRADED via two consecutive failed
    maintenance windows. Returns the DEGRADED system."""
    system = create_venue_system(kind=kind, name=f"{kind}-degraded")
    fail_one_window(
        system["id"],
        "2026-09-01T03:30:00Z",
        "2026-09-01T04:00:00Z",
        fail_clock="2026-09-01T03:45:00Z",
    )
    fail_one_window(
        system["id"],
        "2026-09-01T04:30:00Z",
        "2026-09-01T05:00:00Z",
        fail_clock="2026-09-01T04:45:00Z",
    )
    return get_success_data(api_client.get_venue_system(system["id"], VO))
