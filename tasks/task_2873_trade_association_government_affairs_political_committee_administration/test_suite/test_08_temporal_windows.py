"""Windows on the same resource: closed-closed prior approvals, half-open
registration coverage, and the alert cooling period."""
from test_helpers import (
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import DEFAULT_CLOCK_INSTANT
from test_helpers.factories import create_prior_approval_payload, dispatch_alert_payload
from test_helpers.fixtures import (
    COMPLIANCE,
    DIRECTOR,
    draft_registration,
    file_registration,
    read_campaign,
    read_member,
    read_registration,
    set_clock,
    setup_granted_prior_approval,
    setup_live_campaign,
)

REGISTRANT = "National Manufacturers Association"


def _member_with_a_granted_first_half_window():
    set_clock("2026-06-01T00:00:00Z")
    return setup_granted_prior_approval(
        member_overrides={"restricted_class_size": 25},
        authorized_by_name="R. Okafor, Treasurer",
        solicitable_class_size=10,
        effective_date="2026-01-01",
        expires_at_date="2026-06-30",
    )


def test_prior_approval_windows_that_touch_on_one_day_collide():
    """Closed-closed windows sharing a single date do overlap.

    PRD 3.8: "The collision test compares the requested window against the
    member's existing approvals in `REQUESTED` or `GRANTED` status under
    **closed-closed** semantics: both endpoints count as covered days, so two
    windows that merely touch at a single shared date do collide, and the request
    is refused with `ERR_PRIOR_APPROVAL_WINDOW_CONFLICT`."
    PRD 3.1: "`pac_solicitable` is not a stored decision but a derived one: it
    reads true exactly when some prior approval of this member sits in `GRANTED`
    status and the logical clock's date falls on or after that approval's
    `effective_date` and on or before its `expires_at_date`."

    Design: Difficulty/resource_temporal_overlap/prior_approval_closed_closed_windows_touching_at_one_endpoint_collide
    """
    state = _member_with_a_granted_first_half_window()
    member_id = state["member"]["id"]
    assert state["approval"]["status"] == "GRANTED"
    assert read_member(member_id)["pac_solicitable"] is True

    response = api_client.create_prior_approval(
        create_prior_approval_payload(
            member_id, solicitable_class_size=10,
            effective_date="2026-06-30", expires_at_date="2026-12-31",
        ),
        COMPLIANCE,
    )
    validate_error(response, "ERR_PRIOR_APPROVAL_WINDOW_CONFLICT", 409)

    rows, meta = validate_paginated(
        api_client.list_member_prior_approvals(member_id, COMPLIANCE)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == state["approval"]["id"]
    assert read_member(member_id)["pac_solicitable"] is True


def test_the_day_after_is_accepted_while_a_malformed_window_reports_its_shape():
    """One day later there is no shared date, and shape errors are their own.

    PRD 3.8: "The shape test then requires that `effective_date` is not after
    `expires_at_date`, that both dates fall inside the stated `calendar_year`, and
    that the window spans no more than 365 days; a violation is refused with
    `ERR_PRIOR_APPROVAL_WINDOW_INVALID`."
    PRD 3.8: "A new approval is written in `REQUESTED` status with
    `authorized_by_name`, `granted_at`, `granted_by_user_id` and `revoked_at` all
    null."

    Design: Difficulty/resource_temporal_overlap/prior_approval_closed_closed_windows_touching_at_one_endpoint_collide
    """
    state = _member_with_a_granted_first_half_window()
    member_id = state["member"]["id"]

    inverted = api_client.create_prior_approval(
        create_prior_approval_payload(
            member_id, solicitable_class_size=10,
            effective_date="2026-12-31", expires_at_date="2026-07-01",
        ),
        COMPLIANCE,
    )
    validate_error(inverted, "ERR_PRIOR_APPROVAL_WINDOW_INVALID", 422)

    accepted = validate_success(
        api_client.create_prior_approval(
            create_prior_approval_payload(
                member_id, solicitable_class_size=10,
                effective_date="2026-07-01", expires_at_date="2026-12-31",
            ),
            COMPLIANCE,
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["effective_date"] == "2026-07-01"
    assert accepted["authorized_by_name"] is None
    assert accepted["granted_at"] is None


def test_abutting_registration_coverage_windows_may_both_be_live():
    """Half-open coverage lets one window end where the next begins.

    PRD 3.5: "The comparison treats each coverage window as **half-open**: it
    includes `coverage_start_date` and excludes `coverage_end_date`."
    PRD 3.5: "The practical consequence is that abutting windows are legal — a
    registration ending on the very day the next one starts does not collide —
    while any genuine overlap of covered days is refused with
    `ERR_REGISTRATION_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/registration_coverage_half_open_windows_may_abut_but_not_overlap
    """
    first = draft_registration(
        registrant_name=REGISTRANT,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-07-01",
    )
    first = file_registration(first["id"])
    assert first["status"] == "ACTIVE"

    second = draft_registration(
        registrant_name=REGISTRANT,
        coverage_start_date="2026-07-01",
        coverage_end_date="2026-12-31",
    )
    filed = validate_success(api_client.file_registration(second["id"], COMPLIANCE))

    assert filed["status"] == "ACTIVE"
    assert_instant_equals(filed["filed_at"], DEFAULT_CLOCK_INSTANT, "filed_at")
    assert read_registration(first["id"])["status"] == "ACTIVE"


def test_a_genuine_coverage_overlap_is_refused_but_another_registrant_is_not():
    """The overlap key is the jurisdiction and the registrant name together.

    PRD 3.5: "Two registrations that share the same `jurisdiction_code` and the
    same `registrant_name` may not both be live over the same days, where "live"
    means a status of `ACTIVE` or `AMENDMENT_PENDING`."
    PRD 3.5: "Filing moves the registration `DRAFT → ACTIVE`, stamps `filed_at`
    with the logical clock instant, and is the moment the overlap rule bites."

    Design: Difficulty/resource_temporal_overlap/registration_coverage_half_open_windows_may_abut_but_not_overlap
    """
    first = draft_registration(registrant_name=REGISTRANT,
                               coverage_start_date="2026-01-01",
                               coverage_end_date="2026-07-01")
    file_registration(first["id"])
    second = draft_registration(registrant_name=REGISTRANT,
                                coverage_start_date="2026-07-01",
                                coverage_end_date="2026-12-31")
    file_registration(second["id"])
    third = draft_registration(registrant_name=REGISTRANT,
                               coverage_start_date="2026-12-01",
                               coverage_end_date="2026-12-31")

    validate_error(
        api_client.file_registration(third["id"], COMPLIANCE),
        "ERR_REGISTRATION_COVERAGE_OVERLAP",
        409,
    )
    blocked = read_registration(third["id"])
    assert blocked["status"] == "DRAFT"
    assert blocked["filed_at"] is None
    assert read_registration(first["id"])["status"] == "ACTIVE"
    assert read_registration(second["id"])["status"] == "ACTIVE"

    other_registrant = draft_registration(registrant_name="NMA Political Fund",
                                          coverage_start_date="2026-12-01",
                                          coverage_end_date="2026-12-31")
    filed = validate_success(api_client.file_registration(other_registrant["id"], COMPLIANCE))
    assert filed["status"] == "ACTIVE"


ALERT = {
    "target_district_code": "CA-12",
    "target_chamber": "US_HOUSE",
    "unit_cost_cents": 30_000,
}


def test_an_alert_one_second_short_of_the_cooling_window_is_refused():
    """47h59m59s after the last dispatch is still inside the window.

    PRD 3.7: "A new alert's dispatch instant must be at least 48 hours — two full
    days — after the campaign's `last_alert_at`. A gap of exactly 48 hours is
    allowed; anything shorter is refused with `ERR_ALERT_COOLING_PERIOD`."
    PRD 3.7: "And the first `DISPATCHED` alert moves the campaign `PLANNED →
    LIVE`; a `NO_MATCH` alert leaves it in `PLANNED`."

    Design: Difficulty/resource_temporal_overlap/alert_cooling_window_at_exactly_48_hours_is_allowed
    """
    state = setup_live_campaign(alert_overrides=dict(ALERT,
                                                     message_subject="Call your representative today"))
    campaign_id = state["campaign"]["id"]
    assert state["alert"]["status"] == "DISPATCHED"
    assert state["alert"]["matched_member_count"] == 3
    assert state["alert"]["cost_cents"] == 90_000
    assert_instant_equals(state["alert"]["dispatched_at"], DEFAULT_CLOCK_INSTANT, "dispatched_at")
    assert state["campaign"]["status"] == "LIVE"
    assert_instant_equals(state["campaign"]["last_alert_at"], DEFAULT_CLOCK_INSTANT,
                          "last_alert_at")

    set_clock("2026-08-02T23:59:59Z")
    response = api_client.dispatch_alert(
        campaign_id,
        dispatch_alert_payload(message_subject="One second too early", **ALERT),
        DIRECTOR,
    )
    validate_error(response, "ERR_ALERT_COOLING_PERIOD", 409)

    campaign = read_campaign(campaign_id)
    assert campaign["alert_count"] == 1
    assert campaign["cumulative_cost_cents"] == 90_000
    assert campaign["matched_member_total"] == 3


def test_exactly_forty_eight_hours_is_allowed_and_the_third_alert_latches_disclosure():
    """The window is inclusive, and cumulative cost latches the disclosure flag.

    PRD 3.7: "After the accumulators are updated, if the campaign's
    `cumulative_cost_cents` has reached the grassroots disclosure threshold for its
    `target_jurisdiction_code` — 250,000 cents federally, 100,000 in California,
    400,000 in New York — then `disclosure_required` is set to true."
    PRD 3.7: "The boundary is inclusive, and the latch never reverts: once a
    campaign is disclosable it stays disclosable, even if later events would leave
    the total looking smaller."

    Design: Difficulty/resource_temporal_overlap/alert_cooling_window_at_exactly_48_hours_is_allowed
    """
    state = setup_live_campaign(alert_overrides=dict(ALERT,
                                                     message_subject="Call your representative today"))
    campaign_id = state["campaign"]["id"]

    set_clock("2026-08-03T00:00:00Z")
    second = validate_success(
        api_client.dispatch_alert(
            campaign_id,
            dispatch_alert_payload(message_subject="Exactly forty-eight hours later", **ALERT),
            DIRECTOR,
        ),
        201,
    )
    assert second["status"] == "DISPATCHED"
    assert second["matched_member_count"] == 3
    assert second["cost_cents"] == 90_000
    assert "version" not in second
    assert "updated_at" not in second

    campaign = read_campaign(campaign_id)
    assert campaign["alert_count"] == 2
    assert campaign["matched_member_total"] == 6
    assert campaign["cumulative_cost_cents"] == 180_000
    assert campaign["unmatched_alert_count"] == 0
    assert campaign["disclosure_required"] is False

    set_clock("2026-08-05T00:00:00Z")
    third = validate_success(
        api_client.dispatch_alert(
            campaign_id,
            dispatch_alert_payload(message_subject="Third wave crosses the floor", **ALERT),
            DIRECTOR,
        ),
        201,
    )
    assert third["status"] == "DISPATCHED"

    campaign = read_campaign(campaign_id)
    assert campaign["alert_count"] == 3
    assert campaign["matched_member_total"] == 9
    assert campaign["cumulative_cost_cents"] == 270_000
    assert campaign["disclosure_required"] is True
