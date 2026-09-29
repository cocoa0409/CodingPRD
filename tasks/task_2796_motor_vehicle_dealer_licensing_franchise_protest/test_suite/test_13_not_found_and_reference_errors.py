"""The error contract on reads and reference data: entity-specific 404 codes, the
forward-only clock, room-code uniqueness, the filing's conditional field shape,
protestant standing and the closed protest window.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.test_users import BOARD_ADMIN, make_dealer_headers, make_manufacturer_headers


class TestEntitySpecificNotFoundCodes:
    def test_each_detail_reader_answers_with_its_own_not_found_code(self, api):
        """PRD 2.10 puts "**Path existence** — every identifier in the path
        resolves, left to right (the 404 catalogue)." ahead of the body checks, and
        PRD 2.2 fixes what the failure envelope carries: "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error." One syntactically valid but unknown identifier therefore
        draws eight different codes across the eight collections.

        Design: Corner/errors/unknown_ids_on_reads_return_entity_specific_not_found_codes
        """
        cases = [
            (api.get_manufacturer, ApiErrorId.ERR_MANUFACTURER_NOT_FOUND),
            (api.get_hearing_room, ApiErrorId.ERR_HEARING_ROOM_NOT_FOUND),
            (api.get_license_application, ApiErrorId.ERR_APPLICATION_NOT_FOUND),
            (api.get_salesperson, ApiErrorId.ERR_SALESPERSON_NOT_FOUND),
            (api.get_franchise_filing, ApiErrorId.ERR_FILING_NOT_FOUND),
            (api.get_protest, ApiErrorId.ERR_PROTEST_NOT_FOUND),
            (api.get_warranty_rate_dispute, ApiErrorId.ERR_DISPUTE_NOT_FOUND),
            (api.get_consumer_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        ]
        seen = []
        for reader, expected in cases:
            response = reader(NON_EXISTENT_UUID, BOARD_ADMIN)
            validate_error(response, expected.value, expected_status=404)
            body = response.json()
            assert body["response_type"] == "error"
            assert body["data"]["message"].strip()
            seen.append(body["data"]["error_id"])

        assert len(set(seen)) == 8


class TestClockIsForwardOnly:
    def test_neither_a_rewind_nor_a_restamp_is_admitted(self, api):
        """PRD 2.3: "An administrator advances it by supplying a `to_iso8601`
        instant; the clock only ever moves forward, so an instant that is not
        strictly later than the current value is refused with
        `ERR_CLOCK_NOT_MONOTONIC`." A single second forward is admitted instead,
        and PRD 2.3 fixes what that answer carries: "The response to a clock
        advance reports the resulting `current_utc` together with four counters
        describing what the sweep touched: `swept_dealer_count`,
        `swept_salesperson_count`, `swept_protest_count` and
        `swept_complaint_count`."

        Design: Corner/errors/clock_rewind_and_restamp_rejected_as_non_monotonic
        """
        fx.set_clock("2026-09-10T00:00:00Z")

        rewind = api.advance_clock("2026-09-09T23:59:59Z", BOARD_ADMIN)
        validate_error(rewind, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
                       expected_status=422)

        restamp = api.advance_clock("2026-09-10T00:00:00Z", BOARD_ADMIN)
        validate_error(restamp, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
                       expected_status=422)

        forward = get_success_data(
            api.advance_clock("2026-09-10T00:00:01Z", BOARD_ADMIN), 200)

        assert_same_instant(forward["current_utc"], "2026-09-10T00:00:01Z")
        assert forward["swept_dealer_count"] == 0
        assert forward["swept_salesperson_count"] == 0
        assert forward["swept_protest_count"] == 0
        assert forward["swept_complaint_count"] == 0


class TestRoomCodeUniqueness:
    def test_a_second_room_reusing_the_code_is_refused(self, api):
        """PRD 2.5: "A **hearing room** is created with a `room_code` unique across
        rooms and between 2 and 12 characters — a duplicate is refused with
        `ERR_DUPLICATE_ROOM_CODE` — and a `seating_capacity` of between 10 and 400
        physical seats." A different capacity, a different day cap and a different
        changeover buffer make no difference, because PRD 2.5 keys the room only on
        its code.

        Design: Corner/errors/second_hearing_room_reusing_a_room_code_rejected
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        first = fx.create_hearing_room(room_code="HR-A", seating_capacity=40)
        assert first["seating_capacity"] == 40
        assert first["version"] == 1

        response = api.create_hearing_room(
            f.hearing_room_payload(room_code="HR-A", seating_capacity=80,
                                   max_hearings_per_day=3, buffer_minutes=45),
            BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_DUPLICATE_ROOM_CODE.value,
                       expected_status=409)

        after = fx.read_room(first["id"])
        assert after["seating_capacity"] == 40
        assert after["version"] == first["version"]
        _, meta = validate_paginated(api.list_hearing_rooms(BOARD_ADMIN))
        assert meta["total_count"] == 1


class TestFilingFieldShapeAndLineMake:
    def test_the_conditional_field_shape_and_the_line_make_are_both_enforced(self, api):
        """PRD 3.4: "The remaining inputs are conditional on the type, and getting
        them wrong is `ERR_FILING_FIELDS_INCONSISTENT`: a `TERMINATION` and a
        `RELOCATION` must both name the `affected_dealer_id` whose franchise is at
        issue, a `RELOCATION` and an `ADDITIONAL_POINT` must both carry the proposed
        destination as `site_x_km` and `site_y_km`, an `ADDITIONAL_POINT` must omit
        `affected_dealer_id` entirely, and `termination_cause_code` — the statutory
        cause cited — is present for a `TERMINATION` and for nothing else." PRD 3.4:
        "Where an affected dealership is named, its `line_make` must match the
        franchisor's; a mismatch is refused with `ERR_LINE_MAKE_MISMATCH`." PRD 2.10
        puts line-make agreement ahead of filing-type field consistency, so the
        BOREAS dealership named on a well-shaped `TERMINATION` reports the mismatch.

        Design: Corner/errors/filing_conditional_fields_and_line_make_guards_rejected
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        manufacturer = fx.create_manufacturer(line_make="AURORA")
        dealer = fx.create_dealer(legal_name="Boreal Motors", line_make="BOREAS")
        # An AURORA incumbent so the ADDITIONAL_POINT probe below clears the
        # line-make check and isolates the conditional-field-shape rule.
        incumbent = fx.create_dealer(legal_name="Northgate Aurora", line_make="AURORA")
        headers = make_manufacturer_headers(manufacturer["id"])

        no_dealer = api.create_franchise_filing({
            "manufacturer_id": manufacturer["id"],
            "filing_type": "TERMINATION",
            "proposed_effective_on": "2026-12-01",
            "termination_cause_code": "FAILURE_TO_MEET_SALES_PERFORMANCE",
        }, headers)
        validate_error(no_dealer, ApiErrorId.ERR_FILING_FIELDS_INCONSISTENT.value,
                       expected_status=422)

        wrong_line_make = api.create_franchise_filing(
            f.termination_filing_payload(manufacturer["id"], dealer["id"],
                                         "2026-12-01"),
            headers)
        validate_error(wrong_line_make, ApiErrorId.ERR_LINE_MAKE_MISMATCH.value,
                       expected_status=422)

        point_with_dealer = api.create_franchise_filing(
            f.additional_point_filing_payload(
                manufacturer["id"], "2026-12-01", site_x_km=9, site_y_km=12,
                affected_dealer_id=incumbent["id"]),
            headers)
        validate_error(point_with_dealer,
                       ApiErrorId.ERR_FILING_FIELDS_INCONSISTENT.value,
                       expected_status=422)

        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 0
        _, meta = validate_paginated(api.list_franchise_filings(
            BOARD_ADMIN, params={"manufacturer_id": manufacturer["id"]}))
        assert meta["total_count"] == 0


class TestTerminationStandingBelongsToTheAffectedDealer:
    def test_a_neighbouring_franchised_dealer_has_no_standing(self, api):
        """PRD 3.5: "Against a `TERMINATION`, the only party with standing is the
        dealership being terminated, so the protestant must be the filing's own
        `affected_dealer_id`." PRD 3.5: "A party that fits neither description is
        refused with `ERR_NOT_INCUMBENT_DEALER`." Northgate is itself licensed,
        `FRANCHISED` and an `AURORA` dealership, so it clears the licence check and
        the line-make check and fails only for want of standing.

        Design: Corner/errors/termination_protest_by_a_dealer_other_than_the_affected_one_rejected
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        manufacturer = fx.create_manufacturer()
        affected = fx.create_dealer(legal_name="Lakeside Aurora",
                                    site_x_km=0, site_y_km=0)
        fx.license_dealer(affected["id"])
        neighbour = fx.create_dealer(legal_name="Northgate Aurora",
                                     site_x_km=5, site_y_km=0)
        fx.license_dealer(neighbour["id"])

        filing = fx.open_termination_filing(
            manufacturer["id"], affected["id"], "2026-12-01")
        filing = fx.serve_notice(filing["id"], manufacturer["id"])
        assert fx.read_dealer(neighbour["id"])["license_status"] == "LICENSED"
        assert fx.read_dealer(neighbour["id"])["franchise_status"] == "FRANCHISED"

        refused = api.create_protest(
            f.protest_payload(filing["id"], neighbour["id"], filing["version"]),
            make_dealer_headers(neighbour["id"]))
        validate_error(refused, ApiErrorId.ERR_NOT_INCUMBENT_DEALER.value,
                       expected_status=422)

        untouched = fx.read_filing(filing["id"])
        assert untouched["status"] == "NOTICE_SERVED"
        assert untouched["active_protest_count"] == 0
        assert untouched["version"] == filing["version"]

        admitted = get_success_data(api.create_protest(
            f.protest_payload(filing["id"], affected["id"], filing["version"]),
            make_dealer_headers(affected["id"])), 201)

        assert admitted["status"] == "FILED"
        assert admitted["protestant_dealer_id"] == affected["id"]
        after = fx.read_filing(filing["id"])
        assert after["status"] == "PROTEST_PENDING"
        assert after["active_protest_count"] == 1


class TestProtestWindowLastDayIsInclusive:
    def test_the_day_after_the_window_closes_is_refused(self, api):
        """PRD 3.4 makes the last day inclusive: service "sets
        `protest_window_ends_on` to 30 days after `notice_served_on` — the last day,
        inclusive, on which an incumbent may protest." PRD 3.5: "The 30-day window
        must still be running: the clock date must be on or before the filing's
        `protest_window_ends_on`, and a later filing draws
        `ERR_PROTEST_WINDOW_CLOSED`." The affected dealership is still `LICENSED`
        and `TERMINATION_PENDING`, so every earlier check in the scan passes.

        Design: Corner/errors/protest_filed_one_day_after_the_window_closes_rejected
        """
        ctx = fx.setup_served_termination_notice()
        filing, dealer = ctx["filing"], ctx["dealer"]
        assert filing["notice_served_on"] == "2026-09-01"
        assert filing["protest_window_ends_on"] == "2026-10-01"

        fx.set_clock("2026-10-02T00:00:00Z")
        response = api.create_protest(
            f.protest_payload(filing["id"], dealer["id"], filing["version"]),
            make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED.value,
                       expected_status=422)

        after_filing = fx.read_filing(filing["id"])
        assert after_filing["status"] == "NOTICE_SERVED"
        assert after_filing["active_protest_count"] == 0
        assert after_filing["version"] == filing["version"]
        after_dealer = fx.read_dealer(dealer["id"])
        assert after_dealer["franchise_status"] == "TERMINATION_PENDING"
        assert after_dealer["license_status"] == "LICENSED"
