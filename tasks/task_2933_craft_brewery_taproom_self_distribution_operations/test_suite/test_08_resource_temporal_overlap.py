"""Two interval conventions: the half-open tank window and the closed event window."""

from test_helpers import (
    ADMIN,
    BATCH_SCHEDULED,
    CELLAR,
    COMPLIANCE,
    ERR_OFFSITE_EVENT_CAPACITY_EXCEEDED,
    ERR_TANK_SCHEDULE_CONFLICT,
    LICENSE_SELF_DISTRIBUTION,
    PERMIT_APPROVED,
    PERMIT_DECISION_APPROVED,
    PERMIT_FARMERS_MARKET,
    PERMIT_FESTIVAL,
    PERMIT_OFF_SITE_TASTING,
    PERMIT_SUBMITTED,
    REGULATOR,
    TANK_IDLE,
    batch_payload,
    permit_decision_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_approved_permit,
    create_exempt_beer,
    create_license,
    create_scheduled_batch,
    create_tank,
    draft_permit,
    submit_permit,
)


class TestTankOccupationBuffer:
    def _tank_with_one_scheduled_batch(self, api):
        bootstrap_brewery(api)
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        first = create_scheduled_batch(
            api,
            beer["id"],
            tank["id"],
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-09T06:00:00Z",
        )
        return beer, tank, first

    def test_a_successor_one_second_inside_the_twelve_hour_pad_collides(self, api):
        """A brew starting at 17:59:59Z is still inside the buffered window.

        PRD §3.2: "Concretely: for the batch being scheduled, take the window that
        begins twelve hours before its `brew_start_utc` and ends twelve hours
        after its `brew_end_utc`, treating that window as inclusive at its start
        and exclusive at its end. No other batch on the same vessel whose `state`
        is `SCHEDULED`, `BREWING` or `CONDITIONING` may have its own half-open
        interval, from its `brew_start_utc` inclusive to its `brew_end_utc`
        exclusive, overlap that window."

        Design: Difficulty/resource_temporal_overlap/tank_occupation_half_open_interval_with_twelve_hour_cip_buffer
        """
        beer, tank, first = self._tank_with_one_scheduled_batch(api)

        validate_error(
            api.create_batch(
                batch_payload(
                    beer["id"],
                    tank["id"],
                    batch_code="B-1002",
                    planned_volume_bbl=16.00,
                    brew_start_utc="2026-08-09T17:59:59Z",
                    brew_end_utc="2026-08-17T06:00:00Z",
                ),
                CELLAR,
            ),
            ERR_TANK_SCHEDULE_CONFLICT,
            409,
        )

        assert validate_success(api.get_batch(first["id"], CELLAR))["state"] == BATCH_SCHEDULED
        batches, meta = validate_paginated(
            api.list_batches(CELLAR, {"tank_id": tank["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in batches] == [first["id"]]

    def test_a_successor_at_exactly_twelve_hours_is_accepted(self, api):
        """18:00:00Z is the exclusive right edge, so the turnaround is satisfied.

        PRD §3.2: "Because both intervals are half-open, two occupations separated
        by a gap of exactly twelve hours do **not** overlap and are legal; a gap of
        eleven hours and fifty-nine minutes is not."

        Design: Difficulty/resource_temporal_overlap/tank_occupation_half_open_interval_with_twelve_hour_cip_buffer
        """
        beer, tank, first = self._tank_with_one_scheduled_batch(api)

        accepted = validate_success(
            api.create_batch(
                batch_payload(
                    beer["id"],
                    tank["id"],
                    batch_code="B-1003",
                    planned_volume_bbl=16.00,
                    brew_start_utc="2026-08-09T18:00:00Z",
                    brew_end_utc="2026-08-17T06:00:00Z",
                ),
                CELLAR,
            ),
            201,
        )

        assert accepted["state"] == BATCH_SCHEDULED
        assert accepted["tank_id"] == tank["id"]
        assert validate_success(api.get_batch(first["id"], CELLAR))["state"] == BATCH_SCHEDULED
        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored_tank["status"] == TANK_IDLE
        assert stored_tank["occupying_batch_id"] is None


class TestOffsiteEventConcurrency:
    def _two_approved_permits_and_a_touching_third(self, api):
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        create_license(
            api,
            "OR",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        first = create_approved_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=2.00,
            event_start_utc="2026-09-10T12:00:00Z",
            event_end_utc="2026-09-10T18:00:00Z",
            permit_type=PERMIT_FESTIVAL,
            event_name="Riverfront Fest",
        )
        second = create_approved_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=2.00,
            event_start_utc="2026-09-10T22:00:00Z",
            event_end_utc="2026-09-11T04:00:00Z",
            permit_type=PERMIT_OFF_SITE_TASTING,
            event_name="Night Market",
        )
        third = draft_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=2.00,
            event_start_utc="2026-09-10T18:00:00Z",
            event_end_utc="2026-09-10T22:00:00Z",
            permit_type=PERMIT_FARMERS_MARKET,
            event_name="Twilight Tasting",
        )
        submit_permit(api, third["id"])
        return first, second, third

    def test_two_touching_endpoints_make_a_third_concurrent_approval_impossible(self, api):
        """A window that merely abuts two approved ones intersects both.

        PRD §3.9: "Because these intervals are closed, two events that merely
        touch at an endpoint — one ending at the exact instant the other begins —
        **do** intersect and do count against each other."

        Design: Difficulty/resource_temporal_overlap/offsite_permit_closed_interval_capacity_two_per_state
        """
        _, _, third = self._two_approved_permits_and_a_touching_third(api)

        validate_error(
            api.decide_event_permit(
                third["id"], permit_decision_payload(PERMIT_DECISION_APPROVED), REGULATOR
            ),
            ERR_OFFSITE_EVENT_CAPACITY_EXCEEDED,
            409,
        )

    def test_the_refused_permit_stays_submitted_and_undecided(self, api):
        """The two neighbours keep their approvals; the third holds at SUBMITTED.

        PRD §3.9: "If that count has already reached two, the approval is refused
        with `ERR_OFFSITE_EVENT_CAPACITY_EXCEEDED`; approval proceeds only while
        the count is strictly below two."

        Design: Difficulty/resource_temporal_overlap/offsite_permit_closed_interval_capacity_two_per_state
        """
        first, second, third = self._two_approved_permits_and_a_touching_third(api)

        validate_error(
            api.decide_event_permit(
                third["id"], permit_decision_payload(PERMIT_DECISION_APPROVED), REGULATOR
            ),
            ERR_OFFSITE_EVENT_CAPACITY_EXCEEDED,
        )

        blocked = validate_success(api.get_event_permit(third["id"], COMPLIANCE))
        assert blocked["state"] == PERMIT_SUBMITTED
        assert blocked["decided_at_utc"] is None
        assert blocked["submission_count"] == 1
        for permit in (first, second):
            assert (
                validate_success(api.get_event_permit(permit["id"], ADMIN))["state"]
                == PERMIT_APPROVED
            )
