"""
Composite setup helpers — newsroom allocation, positions, changes, severance
and title closures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_newsroom_change_payload,
    create_title_closure_payload,
)
from .test_users import (
    PRINT_OPS,
    NEWSROOM_MANAGER,
    NEWSROOM_MANAGER_ALT,
    make_newsroom_manager_headers,
)
from .constants import CLOCK_2026_09_01


# ─── Newsroom changes ────────────────────────────────────────────────

def create_newsroom_change(position_id, to_region_id, from_region_id,
                           expected_hub_version, **overrides):
    """Propose a headcount movement. Returns the change dict."""
    return get_success_data(api_client.create_newsroom_change(
        create_newsroom_change_payload(
            position_id, to_region_id, from_region_id, expected_hub_version,
            **overrides),
        NEWSROOM_MANAGER))


def create_newsroom_change_response(position_id, to_region_id, from_region_id,
                                    expected_hub_version, headers=None, **overrides):
    """Propose a change and return the raw Response (for error paths)."""
    return api_client.create_newsroom_change(
        create_newsroom_change_payload(
            position_id, to_region_id, from_region_id, expected_hub_version,
            **overrides),
        headers or NEWSROOM_MANAGER)


def get_newsroom_change(change_id):
    """Read one newsroom change."""
    return get_success_data(api_client.get_newsroom_change(change_id, NEWSROOM_MANAGER))


def approve_newsroom_change(change_id, headers=None):
    """Approve a proposed change. Defaults to a second operator, satisfying SoD."""
    return get_success_data(api_client.approve_newsroom_change(
        change_id, headers or NEWSROOM_MANAGER_ALT))


def approve_newsroom_change_response(change_id, headers=None):
    """Approve a change and return the raw Response (for SoD paths)."""
    return api_client.approve_newsroom_change(change_id, headers or NEWSROOM_MANAGER_ALT)


def apply_newsroom_change(change_id):
    """Apply an approved change on its effective date."""
    return get_success_data(api_client.apply_newsroom_change(change_id, NEWSROOM_MANAGER))


def apply_newsroom_change_response(change_id):
    """Apply a change and return the raw Response."""
    return api_client.apply_newsroom_change(change_id, NEWSROOM_MANAGER)


def reject_newsroom_change(change_id):
    """Reject a proposed change."""
    return get_success_data(api_client.reject_newsroom_change(change_id, NEWSROOM_MANAGER))


def reopen_newsroom_change(change_id):
    """Return an approved but unapplied change to proposed."""
    return get_success_data(api_client.reopen_newsroom_change(change_id, NEWSROOM_MANAGER))


def reopen_newsroom_change_response(change_id):
    """Reopen a change and return the raw Response."""
    return api_client.reopen_newsroom_change(change_id, NEWSROOM_MANAGER)


def list_newsroom_changes(params=None):
    """List newsroom changes, optionally filtered."""
    return get_success_data(api_client.list_newsroom_changes(NEWSROOM_MANAGER, params))


def list_position_changes(position_id):
    """List the changes recorded against one position."""
    return get_success_data(api_client.list_position_changes(position_id, NEWSROOM_MANAGER))


def list_region_positions(region_id):
    """List a region's newsroom positions."""
    return get_success_data(api_client.list_region_positions(region_id, NEWSROOM_MANAGER))


def get_newsroom_position(position_id):
    """Read one newsroom position."""
    return get_success_data(api_client.get_newsroom_position(position_id, NEWSROOM_MANAGER))


# ─── Composite: position + proposed change ───────────────────────────

def setup_position_with_change(region_id, hub_id, change_overrides=None,
                               position_overrides=None, clock=CLOCK_2026_09_01,
                               operator_id=None, change_from_region_id=None):
    """Hub/region already created: add a position and one proposed change.

    Returns (position, change). operator_id, when given, is the creating
    operator's id so segregation-of-duties tests can act as that same operator.
    """
    from .fixtures import create_position, hub_version

    position = create_position(region_id, **(position_overrides or {}))
    version = hub_version(hub_id)
    headers = make_newsroom_manager_headers(operator_id) if operator_id else None
    change = create_newsroom_change_response(
        position["id"], region_id,
        change_from_region_id or region_id,
        version, headers=headers, **(change_overrides or {}))
    return position, get_success_data(change)


def setup_approved_change(region_id, hub_id, change_overrides=None,
                          position_overrides=None, clock=CLOCK_2026_09_01):
    """Position + change walked to approved. Returns (position, change)."""
    position, change = setup_position_with_change(
        region_id, hub_id,
        change_overrides=change_overrides,
        position_overrides=position_overrides,
        clock=clock)
    change = approve_newsroom_change(change["id"])
    return position, change


def setup_applied_change(region_id, hub_id, clock="2026-09-01T00:00:00Z",
                         effective_date="2026-09-11",
                         change_overrides=None, position_overrides=None):
    """Position + change created, approved, and applied on its effective date.

    Returns (position, change). The clock is advanced past effective_date
    before the apply so the temporal precondition holds.
    """
    from .fixtures import set_clock

    position, change = setup_position_with_change(
        region_id, hub_id,
        change_overrides={"effective_date": effective_date, **(change_overrides or {})},
        position_overrides=position_overrides,
        clock=clock)
    change = approve_newsroom_change(change["id"])
    set_clock("2026-09-12T00:00:00Z")
    change = apply_newsroom_change(change["id"])
    return position, change


# ─── Title closures ──────────────────────────────────────────────────

def create_title_closure(hub_id, **overrides):
    """Announce a title closure in a hub. Returns the closure dict."""
    return get_success_data(api_client.create_title_closure(
        hub_id, create_title_closure_payload(**overrides), PRINT_OPS))


def create_title_closure_response(hub_id, **overrides):
    """Announce a title closure and return the raw Response (for error paths)."""
    return api_client.create_title_closure(
        hub_id, create_title_closure_payload(**overrides), PRINT_OPS)


def get_title_closure(title_id):
    """Read one title closure."""
    return get_success_data(api_client.get_title_closure(title_id, PRINT_OPS))


def publish_title_notice(title_id):
    """Publish the statutory closure notice."""
    return get_success_data(api_client.publish_title_notice(title_id, PRINT_OPS))


def publish_title_notice_response(title_id):
    """Publish the notice and return the raw Response (for hold paths)."""
    return api_client.publish_title_notice(title_id, PRINT_OPS)


def suspend_title_closure(title_id):
    """Suspend a published closure while the hub is under a hold."""
    return get_success_data(api_client.suspend_title_closure(title_id, PRINT_OPS))


def resume_title_closure(title_id):
    """Resume a suspended closure once the hold clears."""
    return get_success_data(api_client.resume_title_closure(title_id, PRINT_OPS))


def merge_title_closure(title_id, survivor_title_id):
    """Fold a title into its digital replacement title."""
    return get_success_data(api_client.merge_title_closure(
        title_id, {"survivor_title_id": survivor_title_id}, PRINT_OPS))


def merge_title_closure_response(title_id, survivor_title_id):
    """Merge a title and return the raw Response (for error paths)."""
    return api_client.merge_title_closure(
        title_id, {"survivor_title_id": survivor_title_id}, PRINT_OPS)


def archive_title_closure(title_id):
    """Complete the archive handoff for a merged title."""
    return get_success_data(api_client.archive_title_closure(title_id, PRINT_OPS))


def setup_title_closure_chain(hub_id, title_overrides=None):
    """Announce + publish + merge + archive a title closure.

    Requires the hub to be ratio-compliant for the publish step.
    Returns (closure_after_archive, merged_closure).
    """
    closure = create_title_closure(hub_id, **(title_overrides or {}))
    closure = publish_title_notice(closure["id"])
    return closure