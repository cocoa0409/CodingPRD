"""Two temporal resources: the bull's closed rest spacing and the facility's bench."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    make_facility_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSireRestBufferClosedOnBothSides:
    """Exactly 48 hours is admissible; one second tighter is not."""

    FIRST_START = "2026-09-01T08:00:00Z"
    FIRST_END = "2026-09-01T10:00:00Z"
    ONE_SECOND_INSIDE = "2026-09-03T09:59:59Z"
    ONE_SECOND_INSIDE_END = "2026-09-03T11:59:59Z"
    AT_THE_BOUNDARY = "2026-09-03T10:00:00Z"
    AT_THE_BOUNDARY_END = "2026-09-03T12:00:00Z"
    FAR_START = "2026-09-20T08:00:00Z"
    FAR_END = "2026-09-20T10:00:00Z"
    FORTY_SEVEN_HOURS_BEFORE = "2026-09-18T09:00:00Z"
    FORTY_SEVEN_HOURS_BEFORE_END = "2026-09-18T11:00:00Z"
    FORTY_EIGHT_HOURS_BEFORE = "2026-09-18T08:00:00Z"
    FORTY_EIGHT_HOURS_BEFORE_END = "2026-09-18T10:00:00Z"

    @classmethod
    def _bull_with_one_completed_window(cls, api):
        context = fx.collected_ejaculate(
            api,
            start_at=cls.FIRST_START,
            end_at=cls.FIRST_END,
            collection_clock=cls.FIRST_START,
            facility_overrides={
                "code": "F-IA-15",
                "housing_capacity": 4,
                "bench_capacity": 4,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
        )
        assert context["booking"]["status"] == "COMPLETED"
        assert context["booking"]["end_at"] == "2026-09-01T10:00:00.000Z"
        fx.advance_clock(api, cls.FIRST_END)
        return context

    def test_the_backward_buffer_is_closed_at_forty_eight_hours(self, api):
        """A new window's `start_at` must be at least 48 hours after the `end_at`
        of the bull's most recent `SCHEDULED` or `COMPLETED` booking... Both
        boundaries are closed, so a gap of exactly 48 hours is permitted; anything
        tighter is `ERR_SIRE_REST_BUFFER`.

        Design: Difficulty/resource_temporal_overlap/sire_rest_buffer_closed_forty_eight_hour_spacing_both_sides
        """
        context = self._bull_with_one_completed_window(api)
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]
        headers = make_facility_headers(facility_id)

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    sire_id, facility_id, self.ONE_SECOND_INSIDE, self.ONE_SECOND_INSIDE_END
                ),
                headers,
            ),
            ApiErrorId.ERR_SIRE_REST_BUFFER.value,
            422,
        )

        accepted = validate_success(
            api.create_booking(
                factories.booking_payload(
                    sire_id, facility_id, self.AT_THE_BOUNDARY, self.AT_THE_BOUNDARY_END
                ),
                headers,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"
        assert accepted["start_at"] == "2026-09-03T10:00:00.000Z"

    def test_the_forward_buffer_is_closed_against_the_next_booking(self, api):
        """A new window's `start_at` must be... at least 48 hours before the
        `start_at` of his next one.

        Design: Difficulty/resource_temporal_overlap/sire_rest_buffer_closed_forty_eight_hour_spacing_both_sides
        """
        context = self._bull_with_one_completed_window(api)
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]
        headers = make_facility_headers(facility_id)

        fx.book_collection(
            api, sire_id, facility_id, self.AT_THE_BOUNDARY, self.AT_THE_BOUNDARY_END
        )
        fx.book_collection(api, sire_id, facility_id, self.FAR_START, self.FAR_END)

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    sire_id,
                    facility_id,
                    self.FORTY_SEVEN_HOURS_BEFORE,
                    self.FORTY_SEVEN_HOURS_BEFORE_END,
                ),
                headers,
            ),
            ApiErrorId.ERR_SIRE_REST_BUFFER.value,
            422,
        )

        accepted = validate_success(
            api.create_booking(
                factories.booking_payload(
                    sire_id,
                    facility_id,
                    self.FORTY_EIGHT_HOURS_BEFORE,
                    self.FORTY_EIGHT_HOURS_BEFORE_END,
                ),
                headers,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"

        rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": sire_id})
        )
        assert meta["total_count"] == 4
        assert [row["status"] for row in rows].count("SCHEDULED") == 3
        assert [row["status"] for row in rows].count("COMPLETED") == 1


class TestFacilityBenchHalfOpenOverlap:
    """The bench is shared, and the windows are half-open."""

    E_START = "2026-09-10T09:00:00Z"
    E_END = "2026-09-10T11:00:00Z"
    OVERLAPPING_START = "2026-09-10T10:00:00Z"
    OVERLAPPING_END = "2026-09-10T12:00:00Z"
    CONTAINED_START = "2026-09-10T09:30:00Z"
    CONTAINED_END = "2026-09-10T10:30:00Z"
    ADJACENT_START = "2026-09-10T11:00:00Z"
    ADJACENT_END = "2026-09-10T13:00:00Z"
    BOOKING_CLOCK = "2026-09-01T00:00:00Z"

    @classmethod
    def _one_bench_two_resident_bulls(cls, api):
        facility = fx.register_facility(
            api,
            code="F-IA-16",
            name="Single Bench Centre",
            housing_capacity=4,
            bench_capacity=1,
            approved_export_countries=["CA"],
        )
        bulls = {}
        for code, birth_date in (("REG-E", "2022-01-10"), ("REG-F", "2022-02-11")):
            sire = fx.register_sire(api, registration_code=code, birth_date=birth_date)
            fx.contract_sire(api, sire["id"])
            fx.house_sire(api, sire["id"], facility["id"], fx.DEFAULT_ISOLATION_DAYS)
            fx.grant_base_health_currency(api, sire["id"], facility["id"])
            bulls[code] = sire
        fx.advance_clock(api, fx.CLOCK_ISOLATION_SERVED)
        for code, sire in bulls.items():
            cleared = validate_success(
                api.clear_sire_for_collection(
                    sire["id"], factories.clearance_payload(), fx.VET
                ),
                200,
            )
            assert cleared["collection_status"] == "ELIGIBLE"
            bulls[code] = cleared
        fx.advance_clock(api, cls.BOOKING_CLOCK)

        rows, meta = validate_paginated(
            api.list_sires(fx.DIRECTOR, {"housing_facility_id": facility["id"]})
        )
        assert meta["total_count"] == 2

        booking = fx.book_collection(
            api, bulls["REG-E"]["id"], facility["id"], cls.E_START, cls.E_END
        )
        return {"facility": facility, "bulls": bulls, "booking": booking}

    def test_any_half_open_overlap_on_the_single_bench_is_refused(self, api):
        """Count the `SCHEDULED` bookings at that facility whose half-open windows
        overlap the requested one; that count plus one must not exceed the
        facility's `bench_capacity`, or the request is refused with
        `ERR_BENCH_CAPACITY_EXCEEDED`.

        Design: Difficulty/resource_temporal_overlap/facility_bench_half_open_overlap_across_two_sires
        """
        context = self._one_bench_two_resident_bulls(api)
        facility_id = context["facility"]["id"]
        headers = make_facility_headers(facility_id)
        second_bull = context["bulls"]["REG-F"]["id"]

        for start_at, end_at in (
            (self.OVERLAPPING_START, self.OVERLAPPING_END),
            (self.CONTAINED_START, self.CONTAINED_END),
            (self.E_START, self.E_END),
        ):
            validate_error(
                api.create_booking(
                    factories.booking_payload(second_bull, facility_id, start_at, end_at),
                    headers,
                ),
                ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED.value,
                422,
            )

        rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"facility_id": facility_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == context["booking"]["id"]

    def test_adjacency_is_not_overlap_and_cancelling_frees_the_bench(self, api):
        """Adjacency is explicitly not overlap: a previous booking whose `end_at`
        equals the new `start_at` does not count. `CANCELLED` and `VOIDED` bookings
        are likewise excluded from the overlap count, which is precisely why
        cancelling a booking frees the slot.

        Design: Difficulty/resource_temporal_overlap/facility_bench_half_open_overlap_across_two_sires
        """
        context = self._one_bench_two_resident_bulls(api)
        facility_id = context["facility"]["id"]
        headers = make_facility_headers(facility_id)
        second_bull = context["bulls"]["REG-F"]["id"]

        adjacent = validate_success(
            api.create_booking(
                factories.booking_payload(
                    second_bull, facility_id, self.ADJACENT_START, self.ADJACENT_END
                ),
                headers,
            ),
            201,
        )
        assert adjacent["status"] == "SCHEDULED"

        rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"facility_id": facility_id})
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["SCHEDULED", "SCHEDULED"]

        for booking_id in (context["booking"]["id"], adjacent["id"]):
            cancelled = validate_success(
                api.cancel_booking(
                    booking_id, factories.booking_cancel_payload(), headers
                ),
                200,
            )
            assert cancelled["status"] == "CANCELLED"

        freed = validate_success(
            api.create_booking(
                factories.booking_payload(
                    second_bull, facility_id, self.OVERLAPPING_START, self.OVERLAPPING_END
                ),
                headers,
            ),
            201,
        )
        assert freed["status"] == "SCHEDULED"
