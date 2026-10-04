"""Composite setup helpers for the storm-ready continuous-ops domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z until set).
"""
from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client as api
from .constants import CHECKLIST_KEYS, DEFAULT_CLOCK
from .factories import (
    create_allocation_payload,
    create_asset_payload,
    create_assignment_payload,
    create_condition_report_payload,
    create_crew_member_payload,
    create_lodging_booking_payload,
    create_relief_org_payload,
    create_relief_pledge_payload,
    create_storm_event_payload,
    create_unit_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
UM = TEST_USERS["unit_manager_headers"]
LP = TEST_USERS["logistics_planner_headers"]
FC = TEST_USERS["field_coordinator_headers"]
RC = TEST_USERS["relief_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: clock and basic entity setup
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Advance the server's logical clock (PRD §2.7)."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_storm(clock=DEFAULT_CLOCK, **overrides):
    """Set the logical clock, then declare a storm (starts WATCH)."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(api.create_storm_event(create_storm_event_payload(**overrides), ADMIN))


def create_unit_for(storm, clock=None, **overrides):
    if clock is not None:
        set_clock(clock)
    return get_success_data(api.create_unit(storm["id"], create_unit_payload(**overrides), ADMIN))


def setup_storm_with_unit(clock=DEFAULT_CLOCK, **unit_overrides):
    """Storm in WATCH + one registered unit. Returns dict(storm, unit)."""
    storm = create_storm(clock=clock)
    unit = create_unit_for(storm, **unit_overrides)
    return {"storm": storm, "unit": unit}


def file_condition_report(unit_id, clock=None, **axes):
    """File a condition report as UnitManager; cascades tier/cash-only."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(
        api.create_condition_report(unit_id, create_condition_report_payload(**axes), UM)
    )


def get_unit(unit_id):
    return get_success_data(api.get_unit(unit_id, ADMIN))


def get_storm(storm_id):
    return get_success_data(api.get_storm_event(storm_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1b: storm lifecycle walks
# ---------------------------------------------------------------------------

def activate_storm(storm):
    """WATCH -> ACTIVE. Returns the updated storm."""
    return get_success_data(
        api.activate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, ADMIN
        )
    )


def escalate_storm(storm):
    """WATCH -> WARNING. Returns the updated storm."""
    return get_success_data(
        api.escalate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, ADMIN
        )
    )


def deescalate_storm(storm):
    """WARNING -> WATCH or ACTIVE -> RECOVERY. Returns the updated storm."""
    return get_success_data(
        api.deescalate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, ADMIN
        )
    )


def setup_active_storm_tiered_unit(clock=DEFAULT_CLOCK, report_axes=None, **unit_overrides):
    """Storm activated to ACTIVE + unit degraded to a storm tier.

    Default report axes: power DOWN (menu_tier TIER1_NO_POWER).
    Returns dict(storm, unit).
    """
    ctx = setup_storm_with_unit(clock=clock, **unit_overrides)
    ctx["storm"] = activate_storm(ctx["storm"])
    if report_axes is None:
        report_axes = {"power": "DOWN", "water": "UP", "gas": "UP", "payment_network": "UP"}
    file_condition_report(ctx["unit"]["id"], clock=None, **report_axes)
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: checklist runs
# ---------------------------------------------------------------------------

def open_checklist(unit_id):
    return get_success_data(api.create_checklist(unit_id, None, UM))


def record_item(unit_id, run_id, key, result="PASS", **extra):
    payload = {"key": key, "result": result}
    payload.update(extra)
    return get_success_data(api.create_checklist_item(unit_id, run_id, payload, UM))


def record_all_pass_items(unit_id, run_id):
    for key in CHECKLIST_KEYS:
        record_item(unit_id, run_id, key, "PASS")


def submit_checklist(unit_id, run_id, user_id="um-1"):
    headers = build_user_headers(user_id, "UnitManager")
    return get_success_data(api.submit_checklist(unit_id, run_id, None, headers))


def setup_submittable_checklist(
    outage_at="2026-09-10T09:00:00Z",
    all_clear_at="2026-09-10T10:00:00Z",
    submit_clock="2026-09-10T12:00:00Z",
    submitter_id="um-1",
    outage_axes=None,
):
    """Full checklist setup ready to submit: storm ACTIVE; unit files an outage
    report at `outage_at` then an all-clear report at `all_clear_at`; a run is
    opened with all five items PASS; the clock rests at `submit_clock` (inside
    the four-hour cold-hold window of the all-clear report).

    Returns dict(storm, unit, run).
    """
    if outage_axes is None:
        outage_axes = {"power": "DOWN", "water": "UP", "gas": "UP", "payment_network": "UP"}
    ctx = setup_storm_with_unit(clock=outage_at)
    ctx["storm"] = activate_storm(ctx["storm"])
    file_condition_report(ctx["unit"]["id"], clock=None, **outage_axes)
    file_condition_report(
        ctx["unit"]["id"], clock=all_clear_at,
        power="UP", water="UP", gas="UP", payment_network="UP",
    )
    run = open_checklist(ctx["unit"]["id"])
    record_all_pass_items(ctx["unit"]["id"], run["id"])
    set_clock(submit_clock)
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    ctx["run"] = run
    ctx["submitter_id"] = submitter_id
    return ctx


def setup_submitted_checklist(**kwargs):
    """setup_submittable_checklist + submit. Returns dict(storm, unit, run, submitter_id)."""
    ctx = setup_submittable_checklist(**kwargs)
    ctx["run"] = submit_checklist(ctx["unit"]["id"], ctx["run"]["id"], ctx["submitter_id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: crew relocation and lodging
# ---------------------------------------------------------------------------

def create_crew_member(home_unit_id, **overrides):
    return get_success_data(
        api.create_crew_member(create_crew_member_payload(home_unit_id, **overrides), FC)
    )


def create_assignment(crew_member_id, unit_id, **overrides):
    return get_success_data(
        api.create_assignment(
            create_assignment_payload(crew_member_id, unit_id, **overrides), FC
        )
    )


def setup_crew_assignment(
    clock=DEFAULT_CLOCK,
    report_axes=None,
    assigned_from="2026-09-10T07:00:00Z",
    assigned_until="2026-09-12T00:00:00Z",
    is_jump_team=True,
    **member_overrides,
):
    """Storm ACTIVE + tiered unit + one crew member with a SCHEDULED assignment
    whose window has already begun relative to `clock` (when the default
    assigned_from predates it). Returns dict(storm, unit, member, assignment).
    """
    ctx = setup_active_storm_tiered_unit(clock=clock, report_axes=report_axes)
    member = create_crew_member(
        ctx["unit"]["id"], is_jump_team=is_jump_team, **member_overrides
    )
    assignment = create_assignment(
        member["id"], ctx["unit"]["id"],
        assigned_from=assigned_from, assigned_until=assigned_until,
    )
    ctx["member"] = member
    ctx["assignment"] = assignment
    return ctx


def setup_lodging_scenario(
    clock=DEFAULT_CLOCK,
    lodging_fund_cents=1000000,
    assigned_from="2026-09-10T08:00:00Z",
    assigned_until="2026-09-14T08:00:00Z",
):
    """Storm WATCH + unit with a lodging fund + member + SCHEDULED assignment.
    Returns dict(storm, unit, member, assignment).
    """
    ctx = setup_storm_with_unit(clock=clock, lodging_fund_cents=lodging_fund_cents)
    member = create_crew_member(ctx["unit"]["id"])
    assignment = create_assignment(
        member["id"], ctx["unit"]["id"],
        assigned_from=assigned_from, assigned_until=assigned_until,
    )
    ctx["member"] = member
    ctx["assignment"] = assignment
    return ctx


def book_lodging(assignment_id, unit_id, **overrides):
    return get_success_data(
        api.create_lodging_booking(
            create_lodging_booking_payload(assignment_id, unit_id, **overrides), FC
        )
    )


# ---------------------------------------------------------------------------
# Tier 3b: assets and allocations
# ---------------------------------------------------------------------------

def create_asset(home_unit_id, **overrides):
    return get_success_data(
        api.create_asset(create_asset_payload(home_unit_id, **overrides), LP)
    )


def create_allocation(asset_id, unit_id):
    return get_success_data(
        api.create_allocation(create_allocation_payload(asset_id, unit_id), LP)
    )


def setup_asset_scenario(clock=DEFAULT_CLOCK, kind="GENERATOR", report_axes=None):
    """Storm WATCH + tiered unit (default power DOWN) + one IDLE asset of the
    given kind staged at the unit. Returns dict(storm, unit, asset).
    """
    ctx = setup_storm_with_unit(clock=clock)
    if report_axes is None:
        report_axes = {"power": "DOWN", "water": "UP", "gas": "UP", "payment_network": "UP"}
    file_condition_report(ctx["unit"]["id"], clock=None, **report_axes)
    asset = create_asset(ctx["unit"]["id"], kind=kind)
    ctx["asset"] = asset
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: relief program
# ---------------------------------------------------------------------------

def create_relief_org(**overrides):
    return get_success_data(api.create_relief_org(create_relief_org_payload(**overrides), RC))


def setup_relief_scenario(
    clock=DEFAULT_CLOCK,
    meal_count=10,
    service_date="2026-09-10",
    report_axes=None,
):
    """Storm + tiered unit (default power DOWN, so the unit is storm-affected)
    + ACTIVE relief org + one PLEDGED pledge. Returns dict(storm, unit, org, pledge).
    """
    ctx = setup_storm_with_unit(clock=clock)
    if report_axes is None:
        report_axes = {"power": "DOWN", "water": "UP", "gas": "UP", "payment_network": "UP"}
    file_condition_report(ctx["unit"]["id"], clock=None, **report_axes)
    org = create_relief_org()
    pledge = get_success_data(
        api.create_relief_pledge(
            ctx["unit"]["id"],
            create_relief_pledge_payload(
                org["id"], meal_count=meal_count, service_date=service_date
            ),
            RC,
        )
    )
    ctx["org"] = org
    ctx["pledge"] = pledge
    return ctx


def confirm_pledge(unit_id, pledge_id, served_count):
    return get_success_data(
        api.confirm_relief_pledge(unit_id, pledge_id, {"served_count": served_count}, RC)
    )
