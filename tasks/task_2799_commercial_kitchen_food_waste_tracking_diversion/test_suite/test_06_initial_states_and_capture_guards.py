"""Initial states of newly created records and the preconditions that guard a weighed capture.

Every test in this module drives the service from an empty database through
PRD-declared endpoints only, and reads back through the public API.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_consignment,
    assert_coaching_alert,
    assert_coaching_posture_ladder,
    assert_gram_conservation,
    assert_shift,
    assert_site,
    assert_tracking_station,
    assert_version_bumped_by,
    assert_waste_entry,
    factories,
    fixtures,
    make_corporate_lead_headers,
    make_kitchen_staff_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Emitted timestamps carry three fractional digits; compare them as instants."""
    if isinstance(value, str):
        return value.replace(".000Z", "Z")
    return value


class TestInitialStates:
    """The state a freshly created record is born in."""

    def test_capture_lands_in_recorded_with_every_curation_field_null(self, api):
        """A weighed loss is born RECORDED at version 1 with no curation annotations.

        PRD Coverage: "Once the guards pass, the capture is written in status `RECORDED` and a
        substantial amount of derivation follows." "The three review fields `flag_reason`,
        `void_reason` and `correction_note` are all null on an originally captured entry, as is
        `corrects_entry_id`." "`version`, an integer that starts at 1 on creation and increases by
        exactly 1 each time the row is mutated"

        Design: Corner/state_machines/waste_entry_is_created_in_the_recorded_initial_state
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"])

        payload = factories.create_waste_entry_payload(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="OVERPRODUCTION",
            captured_at="2026-08-01T10:00:00Z",
        )
        entry = validate_success(api.create_waste_entry(payload, make_kitchen_staff_headers("ks-1")), 201)

        assert_waste_entry(entry)
        assert entry["status"] == "RECORDED"
        assert entry["version"] == 1
        assert entry["flag_reason"] is None
        assert entry["void_reason"] is None
        assert entry["corrects_entry_id"] is None
        assert entry["correction_note"] is None

    def test_consignment_starts_draft_on_logistics_and_unbilled_on_settlement(self, api):
        """One row carries two independent dimensions, each at its own starting value.

        PRD Coverage: "`logistics_status` tracks physical movement through `DRAFT`, `STAGED`,
        `DISPATCHED`, `COMPLETED` and `CANCELLED`, starting at `DRAFT`." "`settlement_status` tracks
        billing through `UNBILLED`, `TICKET_SUBMITTED`, `SETTLED` and `DISPUTED`, starting at
        `UNBILLED`." "A new consignment also has `staged_weight_grams` and `line_count` at 0, and
        `cancel_reason`, `staged_at` and `dispatched_at` all null." "An optional
        `container_tare_grams`, zero or greater and defaulting to 0, records the tare of the
        transport container that will be subtracted from the hauler's gross weight later."

        Design: Corner/state_machines/diversion_consignment_starts_draft_on_logistics_and_unbilled_on_settlement
        """
        site = fixtures.create_site()
        hauler = fixtures.create_hauler(channels=["COMPOST"])

        payload = factories.create_consignment_payload(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )
        consignment = validate_success(
            api.create_consignment(payload, make_site_sustainability_manager_headers(site["id"])), 201
        )

        assert_consignment(consignment)
        assert consignment["logistics_status"] == "DRAFT"
        assert consignment["settlement_status"] == "UNBILLED"
        assert consignment["staged_weight_grams"] == 0
        assert consignment["line_count"] == 0
        assert consignment["container_tare_grams"] == 0
        assert consignment["cancel_reason"] is None
        assert consignment["staged_at"] is None
        assert consignment["dispatched_at"] is None


class TestStationAvailabilityRoundTrip:
    """The reversible pair between an operating station and one out for service."""

    def test_maintenance_round_trip_returns_the_station_to_active(self, api):
        """ACTIVE to MAINTENANCE and back, refreshing calibration on the return leg.

        PRD Coverage: "`ACTIVE → MAINTENANCE` requires the station to currently be `ACTIVE`; from
        that moment captures at the station are refused with `ERR_STATION_NOT_ACTIVE`, the compliance
        figure of the site's open service periods is deliberately *not* recomputed retroactively — it
        is recomputed on the next capture or at closure — and the station's `version` is incremented
        by 1." "`MAINTENANCE → ACTIVE` requires the station to currently be `MAINTENANCE`; it sets
        `calibration_due_at` to the supplied value when one is supplied and leaves it untouched when
        none is, and increments `version` by 1."

        Design: Corner/state_machines/station_maintenance_round_trip_returns_the_station_to_active
        """
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], calibration_due_at="2026-09-01T00:00:00Z")
        headers = make_site_sustainability_manager_headers(site["id"])

        out_of_service = validate_success(
            api.set_station_status(
                station["id"], factories.station_status_payload("MAINTENANCE", note="load cell swap"), headers
            ),
            200,
        )
        assert_tracking_station(out_of_service)
        assert out_of_service["status"] == "MAINTENANCE"
        assert_version_bumped_by(station, out_of_service)

        back_in_service = validate_success(
            api.set_station_status(
                station["id"],
                factories.station_status_payload("ACTIVE", calibration_due_at="2027-03-01T00:00:00Z"),
                headers,
            ),
            200,
        )
        assert_tracking_station(back_in_service)
        assert back_in_service["status"] == "ACTIVE"
        assert _instant(back_in_service["calibration_due_at"]) == "2027-03-01T00:00:00Z"
        assert_version_bumped_by(out_of_service, back_in_service)


class TestCaptureStationGuards:
    """A capture is only accepted at a station that is both available and calibrated."""

    def test_capture_at_a_maintenance_station_is_rejected(self, api):
        """A station pulled out of service refuses captures and no total moves.

        PRD Coverage: "The referenced station must be `ACTIVE`, or the capture is refused with
        `ERR_STATION_NOT_ACTIVE`." "`total_captured_weight_grams` is the sum of `weight_grams` over
        the site's captures whose status is either `RECORDED` or `FLAGGED`"

        Design: Corner/state_machines/capture_at_a_maintenance_station_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        fixtures.set_station_status(site["id"], station["id"], "MAINTENANCE")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"])

        payload = factories.create_waste_entry_payload(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-08-01T10:00:00Z",
        )
        response = api.create_waste_entry(payload, make_kitchen_staff_headers("ks-1"))
        validate_error(response, ApiErrorId.STATION_NOT_ACTIVE.value)

        after_shift = fixtures.read_shift(shift["id"])
        assert_shift(after_shift)
        assert after_shift["shift_waste_grams"] == 0

        after_site = fixtures.read_site(site["id"])
        assert_site(after_site)
        assert after_site["total_captured_weight_grams"] == 0

    def test_capture_at_a_station_with_lapsed_calibration_is_rejected(self, api):
        """An ACTIVE station whose calibration deadline has passed still refuses the weighing.

        PRD Coverage: "The current logical clock must be strictly earlier than the station's
        `calibration_due_at`; once the clock has reached that instant the calibration has lapsed and
        the capture is refused with `ERR_STATION_CALIBRATION_OVERDUE`."

        Design: Corner/state_machines/capture_at_a_station_with_lapsed_calibration_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], calibration_due_at="2026-07-31T00:00:00Z")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"])

        payload = factories.create_waste_entry_payload(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-08-01T10:00:00Z",
        )
        response = api.create_waste_entry(payload, make_kitchen_staff_headers("ks-1"))
        validate_error(response, ApiErrorId.STATION_CALIBRATION_OVERDUE.value)


class TestCaptureAttributionAndPeriodGuards:
    """A capture may only cite a published recipe and may only land in an open period."""

    def test_capture_referencing_a_draft_recipe_is_rejected(self, api):
        """An unpublished recipe has no frozen cost basis, so it cannot value a capture.

        PRD Coverage: "When a `recipe_id` is supplied it must reference a recipe whose status is
        `PUBLISHED`, or the capture is refused with `ERR_RECIPE_NOT_PUBLISHED`." "While it is `DRAFT`,
        `published_cost_per_kg_cents` and `published_at` are both null and no capture may reference
        it."

        Design: Corner/state_machines/capture_referencing_a_draft_recipe_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        food_type = fixtures.create_food_type()
        recipe = fixtures.create_recipe(
            ingredients=[factories.recipe_ingredient("Stock Base", 2.0, 500, 0.00)],
            recipe_code="STK-PLN",
            name="Plain Stock",
        )
        assert recipe["status"] == "DRAFT"
        shift = fixtures.open_shift(site["id"])

        payload = factories.create_waste_entry_payload(
            station["id"],
            shift["id"],
            food_type["id"],
            recipe_id=recipe["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-08-01T10:00:00Z",
        )
        response = api.create_waste_entry(payload, make_kitchen_staff_headers("ks-1"))
        validate_error(response, ApiErrorId.RECIPE_NOT_PUBLISHED.value)

    def test_capture_into_a_closed_shift_is_rejected(self, api):
        """A closed service period accepts nothing more and keeps the score it was given.

        PRD Coverage: "The referenced service period must be `OPEN`, or the capture is refused with
        `ERR_INVALID_SHIFT_STATE`." "The **compliance penalty** is the shortfall in station reporting
        — one minus `capture_compliance_pct` — multiplied by a weight of 25.0 points, so a period
        where every active station reported loses nothing and a period where none did loses the full
        25.0." "The raw score is 100 minus the intensity penalty, minus the compliance penalty, plus
        the bonus."

        Design: Corner/state_machines/capture_into_a_closed_shift_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"])
        closed = fixtures.close_shift(shift["id"])
        assert closed["status"] == "CLOSED"
        assert closed["leaderboard_score"] == pytest.approx(75.0, abs=0.01)

        payload = factories.create_waste_entry_payload(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-08-01T10:00:00Z",
        )
        response = api.create_waste_entry(payload, make_kitchen_staff_headers("ks-1"))
        validate_error(response, ApiErrorId.INVALID_SHIFT_STATE.value)

        after = fixtures.read_shift(shift["id"])
        assert_shift(after)
        assert after["shift_waste_grams"] == 0
        assert after["leaderboard_score"] == pytest.approx(closed["leaderboard_score"], abs=0.01)


class TestCurationGuardsOnACapture:
    """Routed grams block a retraction, and clearing a flag is declared only from FLAGGED."""

    def test_voiding_an_entry_that_already_carries_routed_weight_is_rejected(self, api):
        """Grams already allocated onto a consignment must be released before a void.

        PRD Coverage: "And the capture's `routed_weight_grams` must be exactly 0; any capture with
        grams already routed onto a consignment is refused with `ERR_ENTRY_ROUTED_CANNOT_VOID`, and
        those grams must be released first by removing the allocation lines or cancelling the
        consignment." "First, for every capture, its `weight_grams` always equals
        `routed_weight_grams` plus `unrouted_weight_grams`."

        Design: Corner/state_machines/voiding_an_entry_that_already_carries_routed_weight_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"])
        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="OVERPRODUCTION",
            captured_at="2026-08-01T10:00:00Z",
        )
        hauler = fixtures.create_hauler(channels=["COMPOST"])
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )
        fixtures.add_line(site["id"], consignment["id"], entry["id"], 400)

        response = api.void_waste_entry(
            entry["id"], factories.void_payload(void_reason="double weighed"), make_shift_lead_headers("sl-1")
        )
        validate_error(response, ApiErrorId.ENTRY_ROUTED_CANNOT_VOID.value)

        after = fixtures.read_entry(entry["id"])
        assert_waste_entry(after)
        assert after["status"] == "RECORDED"
        assert after["routed_weight_grams"] == 400
        assert after["unrouted_weight_grams"] == 600
        assert_gram_conservation(after)

    def test_clear_flag_on_a_recorded_entry_is_rejected(self, api):
        """The clear-flag edge leaves FLAGGED only, so a RECORDED capture refuses it untouched.

        PRD Coverage: "Flagging anything that is not `RECORDED`, or clearing a flag on anything that
        is not `FLAGGED`, is refused with `ERR_INVALID_ENTRY_STATE`."

        Design: Corner/state_machines/clear_flag_on_a_recorded_entry_is_an_undeclared_transition_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"])
        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="OVERPRODUCTION",
            captured_at="2026-08-01T10:00:00Z",
        )
        assert entry["status"] == "RECORDED"

        response = api.clear_waste_entry_flag(entry["id"], make_shift_lead_headers("sl-1"))
        validate_error(response, ApiErrorId.INVALID_ENTRY_STATE.value)

        after = fixtures.read_entry(entry["id"])
        assert after["status"] == "RECORDED"
        assert after["version"] == 1


class TestConsignmentMovementGuards:
    """Staging needs a line set, and dispatch is reachable only from a staged load."""

    def test_staging_a_consignment_with_no_lines_is_rejected(self, api):
        """An empty load never freezes a staged weight of zero.

        PRD Coverage: "It requires `line_count` to be at least 1, refusing an empty consignment with
        `ERR_CONSIGNMENT_EMPTY`, and requires `staged_weight_grams` not to exceed the hauler's
        `capacity_kg_per_pickup` converted to grams by multiplying by 1000 — an over-capacity load is
        refused with `ERR_HAULER_CAPACITY_EXCEEDED`." "On success `staged_at` is stamped with the
        current logical clock, `staged_weight_grams` is frozen for the later ticket variance
        comparison, no further line may be added or deleted, and `version` is incremented by 1."

        Design: Corner/state_machines/staging_a_consignment_with_no_lines_is_rejected
        """
        site = fixtures.create_site()
        hauler = fixtures.create_hauler(channels=["COMPOST"])
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )

        response = api.stage_consignment(consignment["id"], make_site_sustainability_manager_headers(site["id"]))
        validate_error(response, ApiErrorId.CONSIGNMENT_EMPTY.value)

        after = fixtures.read_consignment(consignment["id"])
        assert_consignment(after)
        assert after["logistics_status"] == "DRAFT"
        assert after["staged_at"] is None

    def test_dispatching_a_draft_consignment_is_rejected(self, api):
        """Collection is declared out of STAGED alone, even for an approved hauler.

        PRD Coverage: "It advances `logistics_status` `STAGED → DISPATCHED`, refusing any other
        starting state with `ERR_INVALID_CONSIGNMENT_STATE`." "On success `dispatched_at` is stamped
        with the current logical clock, the consignment becomes ticket-eligible on the settlement
        dimension, and `version` is incremented by 1."

        Design: Corner/state_machines/dispatching_a_draft_consignment_is_rejected
        """
        site = fixtures.create_site()
        hauler = fixtures.create_approved_hauler(channels=["COMPOST"])
        assert hauler["status"] == "APPROVED"
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )

        response = api.dispatch_consignment(consignment["id"], make_site_sustainability_manager_headers(site["id"]))
        validate_error(response, ApiErrorId.INVALID_CONSIGNMENT_STATE.value)

        after = fixtures.read_consignment(consignment["id"])
        assert_consignment(after)
        assert after["logistics_status"] == "DRAFT"
        assert after["dispatched_at"] is None


class TestBaselineReviewGuards:
    """Corporate review only acts on a baseline window that has been submitted."""

    def test_certifying_a_baseline_period_straight_from_open_is_rejected(self, api):
        """Certification is declared out of SUBMITTED alone, so an open window freezes nothing.

        PRD Coverage: "Certifying or rejecting a period that is not `SUBMITTED` is refused with
        `ERR_INVALID_BASELINE_STATE`." "Certification advances `SUBMITTED → CERTIFIED`, additionally
        requires `baseline_meals_served` to be greater than 0 — certifying a window with frozen meals
        of zero is refused with `ERR_BASELINE_NO_DATA` — stamps `certified_at` with the current
        logical clock, makes the frozen metrics immutable, and increments `version` by 1."

        Design: Corner/state_machines/certifying_a_baseline_period_straight_from_open_is_rejected
        """
        site = fixtures.create_site()
        baseline = fixtures.open_baseline(site["id"], start_date="2026-08-01", end_date="2026-08-01")
        assert baseline["status"] == "OPEN"

        response = api.certify_baseline_period(baseline["id"], make_corporate_lead_headers("csl-1"))
        validate_error(response, ApiErrorId.INVALID_BASELINE_STATE.value)

        after = fixtures.read_baseline(baseline["id"])
        assert after["status"] == "OPEN"
        assert after["certified_at"] is None
        assert after["submitted_at"] is None


class TestAlertResolutionGuards:
    """Resolution is declared out of ACKNOWLEDGED alone, and the open count holds fast."""

    def test_resolving_an_open_alert_before_acknowledgement_is_rejected(self, api):
        """A breach nobody has acknowledged cannot be resolved, and the posture stays put.

        PRD Coverage: "Acknowledging an alert that is not `OPEN`, or resolving one that is not
        `ACKNOWLEDGED` — including trying to resolve an alert that is still merely `OPEN` — is refused
        with `ERR_INVALID_ALERT_STATE`." "Its `observed_intensity` records the intensity value at the
        instant it was raised, to 3 decimal places, and its `severity` is `HIGH` when that observed
        intensity has reached 18.000 or more and `MEDIUM` otherwise." "`open_alert_count` is the
        number of coaching alerts at the site whose status is `OPEN` or `ACKNOWLEDGED`; and
        `coaching_posture` is derived purely from that count — `MONITORING` when the count is exactly
        0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Corner/state_machines/resolving_an_open_alert_before_acknowledgement_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], meals_served=250)
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=3200,
            loss_reason="TRIM",
            captured_at="2026-08-01T10:00:00Z",
        )

        alerts, meta = validate_paginated(
            api.list_alerts(make_shift_lead_headers("sl-1"), shift_id=shift["id"], status="OPEN")
        )
        assert meta["total_count"] == 1
        alert = alerts[0]
        assert alert["alert_type"] == "INTENSITY_BREACH"

        response = api.resolve_alert(
            alert["id"], factories.resolve_alert_payload(resolution_note="talked to the line"),
            make_shift_lead_headers("sl-1"),
        )
        validate_error(response, ApiErrorId.INVALID_ALERT_STATE.value)

        after = fixtures.read_alert(alert["id"])
        assert_coaching_alert(after)
        assert after["status"] == "OPEN"
        assert after["observed_intensity"] == pytest.approx(12.800, abs=0.01)
        assert after["severity"] == "MEDIUM"

        after_site = fixtures.read_site(site["id"])
        assert_site(after_site)
        assert after_site["open_alert_count"] == 1
        assert after_site["coaching_posture"] == "INTERVENTION"
        assert_coaching_posture_ladder(after_site)
