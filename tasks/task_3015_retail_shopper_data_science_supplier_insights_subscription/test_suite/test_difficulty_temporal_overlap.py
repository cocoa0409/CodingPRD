"""Interval semantics: grant windows are half-open with adjacency allowed;
line-review cycles are closed windows demanding a seven-day buffer."""

from test_helpers import (
    account_with_contract,
    create_grant,
    get_success_data,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["category_manager_headers"]


def _grant_world(api):
    """Account + contract + an existing REQUESTED grant over [09-10, 09-20)."""
    world = account_with_contract(api, name="Nu Nectar")
    create_grant(
        api,
        world["account"]["id"],
        valid_from="2026-09-10T00:00:00Z",
        valid_until="2026-09-20T00:00:00Z",
    )
    return world


def test_overlapping_grant_window_rejected(api):
    """A window starting one day before the existing window ends is a true overlap.

    PRD: "any true overlap with an existing `REQUESTED` or `APPROVED` grant window for the same account is rejected with `ERR_WINDOW_OVERLAP`."
    Design: Difficulty/resource_temporal_overlap/grant_windows_half_open_adjacency
    """
    world = _grant_world(api)
    resp = api.create_grant(
        factories.grant_payload(
            world["account"]["id"],
            valid_from="2026-09-19T00:00:00Z",
            valid_until="2026-10-01T00:00:00Z",
        ),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.WINDOW_OVERLAP.value, 409)


def test_adjacent_grant_window_allowed(api):
    """A window starting exactly when the existing one ends is permitted by half-open semantics.

    PRD: "because windows are half-open, adjacency is permitted — a new window may start exactly when an existing one ends"
    Design: Difficulty/resource_temporal_overlap/grant_windows_half_open_adjacency
    """
    world = _grant_world(api)
    validate_error(
        api.create_grant(
            factories.grant_payload(
                world["account"]["id"],
                valid_from="2026-09-19T00:00:00Z",
                valid_until="2026-10-01T00:00:00Z",
            ),
            world["analyst_headers"],
        ),
        ApiErrorId.WINDOW_OVERLAP.value,
        409,
    )
    resp = api.create_grant(
        factories.grant_payload(
            world["account"]["id"],
            valid_from="2026-09-20T00:00:00Z",
            valid_until="2026-10-01T00:00:00Z",
        ),
        world["analyst_headers"],
    )
    adjacent = get_success_data(resp)
    assert adjacent["status"] == "REQUESTED"


def test_cycle_window_five_days_after_rejected(api):
    """A new SNACKS window opening five days after the existing closed window is too tight.

    PRD: "a new cycle whose window begins less than seven days after an existing non-`COMPLETED` cycle's closed window for the same category is rejected with `ERR_CYCLE_GAP_VIOLATION`."
    Design: Difficulty/resource_temporal_overlap/cycle_windows_require_seven_day_buffer
    """
    from test_helpers import create_cycle

    create_cycle(api, window_start="2026-10-01", window_end="2026-10-15")
    resp = api.create_cycle(
        factories.cycle_payload(category_code="SNACKS", window_start="2026-10-20", window_end="2026-10-25"),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.CYCLE_GAP_VIOLATION.value, 409)


def test_cycle_window_exactly_seven_days_after_allowed(api):
    """A window opening exactly seven days after the existing closed window clears the buffer.

    PRD: "a new cycle whose window begins less than seven days after an existing non-`COMPLETED` cycle's closed window for the same category is rejected with `ERR_CYCLE_GAP_VIOLATION`."
    PRD: "The cycle's `open_at` instant is computed as fourteen days before `window_start`, and the cycle is born `SCHEDULED`."
    Design: Difficulty/resource_temporal_overlap/cycle_windows_require_seven_day_buffer
    """
    from test_helpers import create_cycle

    create_cycle(api, window_start="2026-10-01", window_end="2026-10-15")
    validate_error(
        api.create_cycle(
            factories.cycle_payload(category_code="SNACKS", window_start="2026-10-20", window_end="2026-10-25"),
            MANAGER,
        ),
        ApiErrorId.CYCLE_GAP_VIOLATION.value,
        409,
    )
    resp = api.create_cycle(
        factories.cycle_payload(category_code="SNACKS", window_start="2026-10-22", window_end="2026-10-28"),
        MANAGER,
    )
    created = get_success_data(resp)
    assert created["status"] == "SCHEDULED"
