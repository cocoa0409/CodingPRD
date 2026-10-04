"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh server,
using get_success_data so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_date_avail_payload,
    create_engagement_payload,
    create_labor_call_payload,
    create_license_agreement_payload,
    create_rigging_allocation_payload,
    create_rigging_point_payload,
    create_safety_inspection_payload,
    create_ticket_scale_payload,
    create_tour_payload,
    create_truck_move_payload,
    create_venue_payload,
)
from .test_users import TEST_USERS

TM = TEST_USERS["tour_manager_headers"]
VB = TEST_USERS["venue_booker_headers"]
PE = TEST_USERS["production_engineer_headers"]
PE_B = TEST_USERS["production_engineer_b_headers"]
LS = TEST_USERS["labor_steward_headers"]
BOM = TEST_USERS["box_office_manager_headers"]
LM = TEST_USERS["licensing_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PA = TEST_USERS["platform_admin_headers"]


def set_clock(to_iso8601=DEFAULT_CLOCK):
    resp = api_client.set_clock(to_iso8601, PA)
    return get_success_data(resp)


def create_tour(open_routing=True, **overrides):
    resp = api_client.create_tour(create_tour_payload(**overrides), TM)
    tour = get_success_data(resp)
    if open_routing:
        tour = get_success_data(api_client.open_routing(tour["id"], TM))
    return tour


def create_venue(**overrides):
    resp = api_client.create_venue(create_venue_payload(**overrides), VB)
    return get_success_data(resp)


def create_date_avail(venue_id, **overrides):
    resp = api_client.create_date_avail(venue_id, create_date_avail_payload(**overrides), VB)
    return get_success_data(resp)


def create_rigging_point(venue_id, **overrides):
    resp = api_client.create_rigging_point(
        venue_id, create_rigging_point_payload(**overrides), VB
    )
    return get_success_data(resp)


def create_engagement(tour_id, venue_id, avail_id, avail_version, **overrides):
    payload = create_engagement_payload(venue_id, avail_id, avail_version, **overrides)
    resp = api_client.create_engagement(tour_id, payload, TM)
    return get_success_data(resp)


def confirm_engagement(tour_id, engagement_id):
    resp = api_client.confirm_engagement(tour_id, engagement_id, TM)
    return get_success_data(resp)


def setup_tour_and_venue(clock=DEFAULT_CLOCK, tour_overrides=None, venue_overrides=None):
    """Clock set + tour (ROUTING) + venue. Returns (tour, venue)."""
    set_clock(clock)
    tour = create_tour(**(tour_overrides or {}))
    venue = create_venue(**(venue_overrides or {}))
    return tour, venue


def setup_held_engagement(clock=DEFAULT_CLOCK, tour_overrides=None,
                          venue_overrides=None, avail_overrides=None,
                          engagement_overrides=None):
    """Tour (ROUTING) + venue + OPEN avail + engagement in HOLD.

    Returns dict with tour, venue, avail, engagement.
    """
    tour, venue = setup_tour_and_venue(clock, tour_overrides, venue_overrides)
    avail = create_date_avail(venue["id"], **(avail_overrides or {}))
    engagement = create_engagement(
        tour["id"], venue["id"], avail["id"], avail["version"],
        **(engagement_overrides or {}),
    )
    return {
        "tour": tour,
        "venue": venue,
        "avail": avail,
        "engagement": engagement,
    }


def setup_confirmed_engagement(clock=DEFAULT_CLOCK, tour_overrides=None,
                               venue_overrides=None, avail_overrides=None,
                               engagement_overrides=None):
    """Held engagement advanced to CONFIRMED. Same return shape."""
    ctx = setup_held_engagement(clock, tour_overrides, venue_overrides,
                                avail_overrides, engagement_overrides)
    ctx["engagement"] = confirm_engagement(
        ctx["tour"]["id"], ctx["engagement"]["id"]
    )
    return ctx


def advance_to_in_load(ctx, load_in_clock="2026-09-10T08:00:00Z"):
    """Advance the clock to load_in_at and tick the engagement into IN_LOAD."""
    set_clock(load_in_clock)
    resp = api_client.get_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
    ctx["engagement"] = get_success_data(resp)
    return ctx


def setup_rigging_plan(ctx, allocations=None, submit=False, approve=False,
                       approver_headers=None, point_overrides=None):
    """Create a rigging point (on ctx's venue) + plan + allocations.

    allocations: list of dict overrides for create_rigging_allocation_payload.
    Returns (point, plan).
    """
    point = create_rigging_point(ctx["venue"]["id"], **(point_overrides or {}))
    resp = api_client.create_rigging_plan(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
    plan = get_success_data(resp)
    for alloc_overrides in (allocations if allocations is not None else [{}]):
        payload = create_rigging_allocation_payload(point["id"], **alloc_overrides)
        get_success_data(
            api_client.create_rigging_allocation(
                ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], payload, PE
            )
        )
    if submit or approve:
        plan = get_success_data(
            api_client.submit_rigging_plan(
                ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"], PE
            )
        )
    if approve:
        plan = get_success_data(
            api_client.approve_rigging_plan(
                ctx["tour"]["id"], ctx["engagement"]["id"], plan["id"],
                approver_headers or PE_B,
            )
        )
    return point, plan


def create_ticket_scale(ctx, **overrides):
    resp = api_client.create_ticket_scale(
        ctx["tour"]["id"], ctx["engagement"]["id"],
        create_ticket_scale_payload(**overrides), BOM,
    )
    return get_success_data(resp)


def record_ticket_sale(ctx, scale_id, quantity):
    resp = api_client.create_ticket_sale(
        ctx["tour"]["id"], ctx["engagement"]["id"],
        {"ticket_scale_id": scale_id, "quantity": quantity}, BOM,
    )
    return get_success_data(resp)


def advance_to_in_performance(ctx, performance_clock=TEST_DEFAULTS["DURING_PERFORMANCE_CLOCK"]):
    """Advance the clock past first_show_at and tick the engagement.

    Only valid once the engagement is SHOW_READY.
    """
    set_clock(performance_clock)
    resp = api_client.get_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
    ctx["engagement"] = get_success_data(resp)
    return ctx


def setup_in_performance_engagement(clock=DEFAULT_CLOCK, tour_overrides=None,
                                    venue_overrides=None, avail_overrides=None,
                                    engagement_overrides=None,
                                    performance_clock=TEST_DEFAULTS["DURING_PERFORMANCE_CLOCK"],
                                    with_approved_plan=True, point_overrides=None):
    """Full chain to IN_PERFORMANCE: confirmed engagement, approved rigging plan,
    clock past first_show_at. Returns ctx dict with tour/venue/avail/engagement.

    The PRD show-ready gate (§3.7) unconditionally requires an APPROVED rigging
    plan before IN_LOAD → SHOW_READY, so the approved-plan chain always runs.
    ``with_approved_plan=False`` only omits ``point``/``plan`` from the returned
    ctx (for tests that do not reference them).
    """
    ctx = setup_confirmed_engagement(clock, tour_overrides, venue_overrides,
                                     avail_overrides, engagement_overrides)
    point, plan = setup_rigging_plan(
        ctx,
        allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 0}],
        approve=True,
        point_overrides=point_overrides,
    )
    if with_approved_plan:
        ctx["point"] = point
        ctx["plan"] = plan
    advance_to_in_load(ctx)
    ctx["engagement"] = get_success_data(
        api_client.mark_show_ready(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
    )
    advance_to_in_performance(ctx, performance_clock)
    return ctx


def reconcile_engagement(ctx):
    """Reconcile an IN_PERFORMANCE engagement; returns the Settlement."""
    resp = api_client.reconcile_settlement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
    settlement = get_success_data(resp)
    ctx["settlement"] = settlement
    ctx["engagement"] = get_success_data(
        api_client.get_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
    )
    return settlement


def setup_reconciled_settlement(clock=DEFAULT_CLOCK, gross_quantity=1000,
                                scale_overrides=None, tour_overrides=None,
                                venue_overrides=None, engagement_overrides=None,
                                performance_clock=TEST_DEFAULTS["DURING_PERFORMANCE_CLOCK"]):
    """Engagement IN_PERFORMANCE with ticket sales recorded, then reconciled.

    Returns ctx with tour/venue/avail/engagement/settlement/scale.
    """
    ctx = setup_in_performance_engagement(
        clock, tour_overrides=tour_overrides, venue_overrides=venue_overrides,
        engagement_overrides=engagement_overrides,
        performance_clock=performance_clock, with_approved_plan=False,
    )
    scale = create_ticket_scale(ctx, **(scale_overrides or {}))
    ctx["scale"] = scale
    if gross_quantity:
        record_ticket_sale(ctx, scale["id"], gross_quantity)
    reconcile_engagement(ctx)
    return ctx


def create_labor_call(ctx, **overrides):
    resp = api_client.create_labor_call(
        ctx["tour"]["id"], ctx["engagement"]["id"],
        create_labor_call_payload(**overrides), LS,
    )
    return get_success_data(resp)


def create_truck_move(ctx, **overrides):
    resp = api_client.create_truck_move(
        ctx["tour"]["id"], ctx["engagement"]["id"],
        create_truck_move_payload(**overrides), PE,
    )
    return get_success_data(resp)


def create_license_agreement(ctx, activate=False, **overrides):
    resp = api_client.create_license_agreement(
        ctx["tour"]["id"], create_license_agreement_payload(**overrides), LM
    )
    lic = get_success_data(resp)
    if activate:
        lic = get_success_data(
            api_client.activate_license_agreement(ctx["tour"]["id"], lic["id"], LM)
        )
    return lic


def create_safety_inspection(ctx, **overrides):
    resp = api_client.create_safety_inspection(
        ctx["tour"]["id"], ctx["engagement"]["id"],
        create_safety_inspection_payload(**overrides), CO,
    )
    return get_success_data(resp)
