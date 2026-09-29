"""
The automatic assignment selector and the travel-calendar conflict test.

Both families depend on the roster ordering rules: caseload weight ascending for
assignment, and a symmetric thirty-minute buffer for travel.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    assert_caseload_weight,
    assign_representative_payload,
    conditions,
    create_active_representative,
    create_claim_in_evidence_development,
    create_represented_veteran,
    create_screened_veteran,
    instant,
    make_county_officer_headers,
    outreach_event_payload,
    plan_outreach_event,
    read_representative,
    read_veteran,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def mixed_accreditation_roster(api):
    """
    Three active representatives: a loaded county officer, an attorney created
    next, and a lightly loaded organisation representative created last.
    """
    set_clock(api, CLOCK_START_INSTANT)
    rep_a = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    loaded = create_represented_veteran(api, designee=rep_a)
    create_claim_in_evidence_development(
        api, loaded, claimed_conditions=conditions("tinnitus")
    )
    rep_c = create_active_representative(
        api, accreditation_type="ATTORNEY", accreditation_expires_on="2029-12-31"
    )
    rep_b = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    candidate = create_screened_veteran(
        api, make_county_officer_headers(rep_a["id"])
    )
    return {
        "rep_a": rep_a,
        "rep_b": rep_b,
        "rep_c": rep_c,
        "veteran_id": candidate["veteran"]["id"],
    }


@pytest.fixture
def travel_calendar(api):
    """A representative whose calendar already holds one two-hour morning event."""
    set_clock(api, CLOCK_START_INSTANT)
    rep = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    first = plan_outreach_event(
        api,
        rep["id"],
        instant("2026-09-10", "09:00:00"),
        instant("2026-09-10", "11:00:00"),
        event_type="RURAL_CLINIC",
    )
    return {"rep": rep, "first": first}


class TestAutomaticAssignmentSelector:
    """Type filters run before the ordering, so a lighter attorney never wins."""

    def test_the_selector_skips_the_ineligible_type_despite_a_lighter_load(
        self, api, mixed_accreditation_roster
    ):
        """
        The candidate set requires that "their `accreditation_type` must be `COUNTY_CVSO` or `VSO_ORG`, so an `ATTORNEY` or a `CLAIMS_AGENT` is never auto-assigned however light their load".

        Design: Difficulty/cross_entity_state_dependency/automatic_representative_assignment_skips_ineligible_type_despite_earlier_created_at
        """
        response = api.assign_representative(
            mixed_accreditation_roster["veteran_id"],
            assign_representative_payload(),
            INTAKE_CLERK_HEADERS,
        )
        validate_success(response, 200)
        veteran = read_veteran(api, mixed_accreditation_roster["veteran_id"])
        assert veteran["assigned_representative_id"] == (
            mixed_accreditation_roster["rep_b"]["id"]
        )
        assert veteran["assigned_representative_id"] != (
            mixed_accreditation_roster["rep_c"]["id"]
        )

    def test_the_ordering_prefers_the_lighter_of_the_two_eligible_rows(
        self, api, mixed_accreditation_roster
    ):
        """
        "Candidates are then ordered by `caseload_weight` ascending, and ties are broken by `created_at` ascending — the longest-registered representative wins a tie, and the ordering is fully deterministic because `created_at` is unique per row."

        Design: Difficulty/cross_entity_state_dependency/automatic_representative_assignment_skips_ineligible_type_despite_earlier_created_at
        """
        rep_a = read_representative(api, mixed_accreditation_roster["rep_a"]["id"])
        rep_b = read_representative(api, mixed_accreditation_roster["rep_b"]["id"])
        rep_c = read_representative(api, mixed_accreditation_roster["rep_c"]["id"])
        assert_caseload_weight(rep_a["caseload_weight"], 4)
        assert_caseload_weight(rep_b["caseload_weight"], 0)
        assert_caseload_weight(rep_c["caseload_weight"], 0)
        validate_success(
            api.assign_representative(
                mixed_accreditation_roster["veteran_id"],
                assign_representative_payload(),
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        veteran = read_veteran(api, mixed_accreditation_roster["veteran_id"])
        assert veteran["assigned_representative_id"] == rep_b["id"]

    def test_the_assignment_activates_the_case(self, api, mixed_accreditation_roster):
        """
        "Assignment is `IntakeClerk` work and drives the veteran from `SCREENED` to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/automatic_representative_assignment_skips_ineligible_type_despite_earlier_created_at
        """
        validate_success(
            api.assign_representative(
                mixed_accreditation_roster["veteran_id"],
                assign_representative_payload(),
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        veteran = read_veteran(api, mixed_accreditation_roster["veteran_id"])
        assert veteran["intake_status"] == "ACTIVE"


class TestTravelBufferGapBoundary:
    """Sixty minutes of daylight is enough; fifty-nine is not."""

    def test_a_sixty_minute_gap_is_accepted(self, api, travel_calendar):
        """
        "Because the comparison is strict while each side reserves 30 minutes, two events separated by a gap of exactly 60 minutes have blocks that meet without crossing and are both accepted, whereas a 59-minute gap is refused."

        Design: Difficulty/resource_temporal_overlap/outreach_accepts_exactly_sixty_minute_gap_and_rejects_fifty_nine_minute_gap
        """
        planned = validate_success(
            api.create_outreach_event(
                outreach_event_payload(
                    travel_calendar["rep"]["id"],
                    instant("2026-09-10", "12:00:00"),
                    instant("2026-09-10", "13:00:00"),
                    event_type="TRIBAL_OUTREACH",
                ),
                SYSTEM_ADMIN_HEADERS,
            ),
            201,
        )
        assert planned["status"] == "PLANNED"
        assert planned["veterans_contacted"] == 0
        assert planned["veterans_enrolled"] == 0

    def test_a_fifty_nine_minute_gap_is_refused(self, api, travel_calendar):
        """
        The proposed block "runs from 30 minutes before its `starts_at` to 30 minutes after its `ends_at`",
        so an event ending at 08:01 crosses the reserved edge of a 09:00 start.

        Design: Difficulty/resource_temporal_overlap/outreach_accepts_exactly_sixty_minute_gap_and_rejects_fifty_nine_minute_gap
        """
        response = api.create_outreach_event(
            outreach_event_payload(
                travel_calendar["rep"]["id"],
                instant("2026-09-10", "07:00:00"),
                instant("2026-09-10", "08:01:00"),
                event_type="JAIL_INREACH",
            ),
            SYSTEM_ADMIN_HEADERS,
        )
        validate_error(response, "ERR_REPRESENTATIVE_TRAVEL_CONFLICT", 409)

    def test_only_the_two_accepted_events_are_on_the_calendar(self, api, travel_calendar):
        """
        A refused plan leaves nothing behind, while each accepted one
        "recomputes the assigned representative's `caseload_weight` — a planned event costs 2 points".

        Design: Difficulty/resource_temporal_overlap/outreach_accepts_exactly_sixty_minute_gap_and_rejects_fifty_nine_minute_gap
        """
        validate_success(
            api.create_outreach_event(
                outreach_event_payload(
                    travel_calendar["rep"]["id"],
                    instant("2026-09-10", "12:00:00"),
                    instant("2026-09-10", "13:00:00"),
                    event_type="TRIBAL_OUTREACH",
                ),
                SYSTEM_ADMIN_HEADERS,
            ),
            201,
        )
        validate_error(
            api.create_outreach_event(
                outreach_event_payload(
                    travel_calendar["rep"]["id"],
                    instant("2026-09-10", "07:00:00"),
                    instant("2026-09-10", "08:01:00"),
                    event_type="JAIL_INREACH",
                ),
                SYSTEM_ADMIN_HEADERS,
            ),
            "ERR_REPRESENTATIVE_TRAVEL_CONFLICT",
            409,
        )
        rows, meta = validate_paginated(
            api.list_representative_outreach_events(
                travel_calendar["rep"]["id"], SYSTEM_ADMIN_HEADERS
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2
        representative = read_representative(api, travel_calendar["rep"]["id"])
        assert_caseload_weight(representative["caseload_weight"], 4)
