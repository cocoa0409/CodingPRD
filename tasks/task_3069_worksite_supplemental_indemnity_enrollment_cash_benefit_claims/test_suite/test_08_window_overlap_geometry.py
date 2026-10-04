"""Window overlap geometry: half-open within a group, closed across a counselor."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.test_users import make_carrier_admin_headers, make_counselor_headers


def _group_with_open_campaign(client):
    """One ACTIVE group with an OPEN campaign covering 2026-09-01..2026-09-15."""
    group = fixtures.create_active_group(client)
    counselor_a = fixtures.create_counselor(client)
    campaign_a = fixtures.create_campaign(
        client, group["id"], counselor_a,
        window_start="2026-09-01T00:00:00Z", window_end="2026-09-15T00:00:00Z",
    )
    fixtures.open_campaign(client, campaign_a["id"], counselor_a)
    return fixtures.Bundle(group=group, counselor_a=counselor_a, campaign_a=campaign_a)


def test_touching_windows_do_not_overlap_within_a_group(client):
    """A campaign starting exactly at the OPEN campaign's window_end opens cleanly.

    "Within the group, no other `OPEN` campaign may have a window overlapping this
    one under half-open semantics — an existing window that ends exactly at this
    campaign's `window_start` does not overlap; a violation is
    `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/group_campaign_window_half_open_adjacency_allowed
    """
    base = _group_with_open_campaign(client)
    counselor_b = fixtures.create_counselor(client)
    adjacent = fixtures.create_campaign(
        client, base.group["id"], counselor_b,
        window_start="2026-09-15T00:00:00Z", window_end="2026-10-01T00:00:00Z",
    )

    opened = validate_success(
        client.open_enrollment_campaign(adjacent["id"], make_counselor_headers(counselor_b["id"])),
        200,
    )
    assert opened["status"] == "OPEN"


def test_a_one_second_earlier_start_overlaps_and_is_rejected(client):
    """A window beginning one second before the OPEN campaign's end conflicts.

    "Within the group, no other `OPEN` campaign may have a window overlapping this
    one under half-open semantics — an existing window that ends exactly at this
    campaign's `window_start` does not overlap; a violation is
    `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/group_campaign_window_half_open_adjacency_allowed
    """
    base = _group_with_open_campaign(client)
    counselor_b = fixtures.create_counselor(client)
    overlapping = fixtures.create_campaign(
        client, base.group["id"], counselor_b,
        window_start="2026-09-14T23:59:59Z", window_end="2026-10-01T00:00:00Z",
    )

    response = client.open_enrollment_campaign(
        overlapping["id"], make_counselor_headers(counselor_b["id"])
    )

    validate_error(response, api_errors.ERR_CAMPAIGN_WINDOW_OVERLAP, 409)
    campaign = validate_success(
        client.get_enrollment_campaign(overlapping["id"],
                                       make_carrier_admin_headers()),
        200,
    )
    assert campaign["status"] == "DRAFT"


def _same_counselor_touching_campaigns(client):
    """One counselor with an OPEN campaign 09-01..09-15 and a DRAFT campaign whose
    window starts exactly at 09-15."""
    group = fixtures.create_active_group(client)
    counselor = fixtures.create_counselor(client)
    first = fixtures.create_campaign(
        client, group["id"], counselor,
        window_start="2026-09-01T00:00:00Z", window_end="2026-09-15T00:00:00Z",
    )
    fixtures.open_campaign(client, first["id"], counselor)
    second = fixtures.create_campaign(
        client, group["id"], counselor,
        window_start="2026-09-15T00:00:00Z", window_end="2026-10-01T00:00:00Z",
    )
    return fixtures.Bundle(group=group, counselor=counselor, first=first, second=second)


def test_touching_windows_double_book_the_counselor(client):
    """The counselor rule is closed-interval: touching windows still conflict.

    "Across the counselor's own book, the rule is stricter: the counselor must not
    already lead an `OPEN` campaign whose window intersects this one under
    closed-interval semantics, so a window whose start equals this campaign's
    `window_end` — or vice versa — does conflict; a violation is
    `ERR_COUNSELOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/counselor_double_booked_closed_interval_touching_conflicts
    """
    base = _same_counselor_touching_campaigns(client)

    response = client.open_enrollment_campaign(
        base.second["id"], make_counselor_headers(base.counselor["id"])
    )

    validate_error(response, api_errors.ERR_COUNSELOR_DOUBLE_BOOKED, 409)


def test_a_double_booking_rejection_leaves_the_campaign_in_draft(client):
    """The refused open mutates nothing; the second campaign stays DRAFT.

    "Across the counselor's own book, the rule is stricter: the counselor must not
    already lead an `OPEN` campaign whose window intersects this one under
    closed-interval semantics, so a window whose start equals this campaign's
    `window_end` — or vice versa — does conflict; a violation is
    `ERR_COUNSELOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/counselor_double_booked_closed_interval_touching_conflicts
    """
    base = _same_counselor_touching_campaigns(client)

    validate_error(
        client.open_enrollment_campaign(
            base.second["id"], make_counselor_headers(base.counselor["id"])
        ),
        api_errors.ERR_COUNSELOR_DOUBLE_BOOKED,
        409,
    )

    campaign = validate_success(
        client.get_enrollment_campaign(base.second["id"],
                                       make_carrier_admin_headers()),
        200,
    )
    assert campaign["status"] == "DRAFT"
    first = validate_success(
        client.get_enrollment_campaign(base.first["id"],
                                       make_carrier_admin_headers()),
        200,
    )
    assert first["status"] == "OPEN"
