"""Corner coverage: resource creation shapes, defaults, computed-field
handling, immutable-leaf reads, and lifecycle transition edges."""

import pytest

from test_helpers import (
    ApiErrorId,
    HOST_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    SCHEDULER_HEADERS,
    SERVER_HEADERS,
    VENUE_MANAGER_HEADERS,
    assert_screen_assignment,
    assert_venue,
    create_and_activate_license,
    create_event,
    create_guest,
    create_open_check,
    create_screen_assignment,
    create_staffing_plan,
    create_trivia_entry_scenario,
    create_venue,
    create_zone,
    event_payload,
    join_waitlist,
    license_payload,
    validate_error,
    validate_success,
    venue_payload,
)


class TestVenueCreationRequiredFields:
    def test_venue_creation_returns_the_full_resource_with_zero_volatility_at_reference_cost(self, api):
        """PRD §3.1: "From that cost the system derives `volatility_score`: the absolute difference between the current wing cost per pound and the reference cost of 180 cents, divided by 180."

        At the 180-cent reference cost the venue is created with a zero
        volatility score and a complete resource body.

        Design: Corner/entities/venue_creation_required_fields
        """
        venue = validate_success(
            api.create_venue(
                venue_payload(
                    name="Downtown",
                    market_zip="14201",
                    capacity_seats=200,
                    wing_cost_cents_per_lb=180,
                ),
                PLATFORM_ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert_venue(venue)
        assert venue["name"] == "Downtown"
        assert venue["volatility_score"] == pytest.approx(0.0)


class TestEventCreationDefaults:
    def test_base_event_without_lift_pct_ingests_with_null_lift(self, api):
        """PRD §3.2: "A freshly ingested event starts in `INGESTED` status and can later be cancelled, moving to `CANCELLED`."
        PRD §3.1: "an overlay event carries a `lift_pct`, a fractional lift that applies only to overlays and is null otherwise"

        A BASE event ingested without `lift_pct` reports the field as null and
        starts in INGESTED.

        Design: Corner/entities/event_creation_defaults
        """
        event = validate_success(
            api.create_event(
                event_payload(kind="BASE", league="FF_NFL", title="Game"),
                SCHEDULER_HEADERS,
            ),
            expected_status=201,
        )

        assert event["lift_pct"] is None
        assert event["status"] == "INGESTED"


class TestCheckComputedFieldsInputIgnored:
    def test_computed_money_fields_supplied_at_open_are_ignored(self, api):
        """PRD §3.5: "The check opens in `OPEN` status with a zero subtotal."

        Whatever money figures the client supplies at creation, a fresh check
        reports zeroed computed money fields.

        Design: Corner/entities/check_computed_fields_input_ignored
        """
        venue = create_venue()
        guest = create_guest(venue["id"])

        check = validate_success(
            api.create_check(
                {
                    "venue_id": venue["id"],
                    "guest_id": guest["id"],
                    "party_size": 2,
                    "kind": "REGULAR",
                    "subtotal_cents": 9999,
                    "tax_cents": 9999,
                    "total_cents": 9999,
                },
                SERVER_HEADERS,
            ),
            expected_status=201,
        )

        assert check["subtotal_cents"] == 0
        assert check["tax_cents"] == 0
        assert check["total_cents"] == 0


class TestScreenAssignmentImmutableNoUpdate:
    def test_assignment_read_back_returns_the_recorded_fields(self, api):
        """PRD §2.5: "Four child record types are immutable-leaf resources and carry only `id` and `created_at` — `updated_at` and `version` are absent on them: screen assignments, shifts, trivia entries, and fantasy entries."

        The assignment created for screen S1 reads back with exactly the
        event and screen it recorded.

        Design: Corner/entities/screen_assignment_immutable_no_update
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Game",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        assignment = create_screen_assignment(zone["id"], event["id"])

        fetched = validate_success(
            api.get_screen_assignment(assignment["id"], VENUE_MANAGER_HEADERS)
        )

        assert_screen_assignment(fetched)
        assert fetched["event_id"] == event["id"]
        assert fetched["screen_id"] == "S1"


class TestLicenseTerminateFromPending:
    def test_terminate_moves_a_pending_license_straight_to_terminated(self, api):
        """PRD §3.2: "A `VenueManager` may terminate a license from `PENDING`, `ACTIVE`, or `SUSPENDED` into the terminal `TERMINATED` state; termination drops every zone assignment showing that league's events and recomputes those zones' posture to `OPEN`."

        A license that never reached ACTIVE can still be terminated.

        Design: Corner/state_machines/license_terminate_from_pending
        """
        venue = create_venue()
        license_data = validate_success(
            api.create_license(
                venue["id"], license_payload(league="NCAA"), VENUE_MANAGER_HEADERS
            ),
            expected_status=201,
        )
        assert license_data["status"] == "PENDING"

        terminated = validate_success(
            api.terminate_license(license_data["id"], VENUE_MANAGER_HEADERS)
        )
        assert terminated["status"] == "TERMINATED"


class TestWaitlistCallSkipGuard:
    def test_calling_a_later_entry_before_the_first_is_rejected(self, api):
        """PRD §3.4: "Calling a party is subject to a strict skip-guard: only the earliest-created `WAITING` entry (by `created_at` ascending) may be called, and the call records `called_at` as the current logical time while moving the entry from `WAITING` to `CALLED`."

        With two WAITING entries, calling the second one first violates the
        skip-guard and is rejected as an invalid state transition.

        Design: Corner/state_machines/waitlist_call_skip_guard
        """
        venue = create_venue()
        guest_a = create_guest(venue["id"], name="Alex")
        guest_b = create_guest(venue["id"], name="Blair")
        entry_a = join_waitlist(venue["id"], guest_a["id"], party_size=4)
        entry_b = join_waitlist(venue["id"], guest_b["id"], party_size=2)

        resp = api.call_waitlist_entry(entry_b["id"], HOST_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestStaffingPlanPublishRequiresShifts:
    def test_publishing_a_plan_with_zero_shifts_is_rejected(self, api):
        """PRD §3.7: "Publishing moves the plan from `DRAFT` to `PUBLISHED` and requires at least one shift and that both `foh_required` and `boh_required` are greater than zero."

        A plan with no shifts cannot satisfy the publish precondition.

        Design: Corner/state_machines/staffing_plan_publish_requires_shifts
        """
        venue = create_venue()
        plan = create_staffing_plan(venue["id"], name="Empty Plan")

        resp = api.publish_staffing_plan(plan["id"], VENUE_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTriviaSettleFromClosed:
    def test_settling_an_open_session_is_rejected(self, api):
        """PRD §3.8: "Settlement, a `VenueManager` action, moves the session from `CLOSED` to the terminal `SETTLED` state and assigns prizes by rank, with tied entries sharing the rank."

        A session still OPEN has not reached CLOSED, so settlement is an
        invalid transition.

        Design: Corner/state_machines/trivia_settle_from_closed
        """
        venue = create_venue()
        session = validate_success(
            api.create_trivia_session(venue["id"], {"title": "Trivia"}, HOST_HEADERS),
            expected_status=201,
        )

        resp = api.settle_trivia_session(session["id"], VENUE_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
