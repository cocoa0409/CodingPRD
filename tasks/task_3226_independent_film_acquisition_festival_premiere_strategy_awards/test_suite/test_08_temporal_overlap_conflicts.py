"""Resource temporal-overlap conflicts: venue overlap and travel buffer.

Design: Difficulty/resource_temporal_overlap
"""
from test_helpers import (
    TEST_USERS, acquire_film, create_offer_payload, create_talent_obligation_payload,
    get_success_data, setup_festival, setup_film, setup_premiere_slot,
    setup_territory, validate_error, validate_success,
)
from test_helpers.api_errors import ApiErrorId

ACQ = TEST_USERS["acq_exec_headers"]
ACQ2 = TEST_USERS["acq_exec_2_headers"]
PROG = TEST_USERS["festival_prog_headers"]
COORD = TEST_USERS["talent_coord_headers"]


def _acquire(api, **film_overrides):
    """Acquire a film (offer created by ACQ2, accepted by ACQ)."""
    return acquire_film(film_overrides=film_overrides)


class TestPremiereSlotVenueOverlapHalfOpen:
    def test_premiere_slot_festival_venue_overlap_half_open(self, api):
        """PRD §3.4: "a different `BOOKED` slot at the same festival whose
        interval overlaps rejects the booking with `ERR_VENUE_OVERLAP`
        (HTTP 409)" — with half-open interval semantics, two slots at the same
        festival whose screening intervals merely touch (one ends exactly when
        the next begins) do NOT conflict; slots that share any interior time
        DO conflict.

        Design: Difficulty/resource_temporal_overlap/premiere_slot_festival_venue_overlap_half_open
        """
        festival = setup_festival()
        f1, _o1, _d1 = acquire_film(
            film_overrides={"title": "F1", "director_name": "D1",
                            "production_budget_cents": 100},
            territory_code="US",
        )
        f2, _o2, _d2 = acquire_film(
            film_overrides={"title": "F2", "director_name": "D2",
                            "genre": "COMEDY", "runtime_minutes": 95,
                            "production_budget_cents": 100},
            territory_code="UK",
        )

        s1 = setup_premiere_slot(
            festival["id"], section="COMPETITION",
            screening_starts_at="2027-01-22T18:00:00Z",
            screening_ends_at="2027-01-22T20:00:00Z",
        )
        s2 = setup_premiere_slot(
            festival["id"], section="PREMIERES",
            screening_starts_at="2027-01-22T20:00:00Z",  # touches s1's end
            screening_ends_at="2027-01-22T22:00:00Z",
        )
        s3 = setup_premiere_slot(
            festival["id"], section="MIDNIGHT",
            screening_starts_at="2027-01-22T19:30:00Z",  # overlaps s1's tail
            screening_ends_at="2027-01-22T21:30:00Z",
        )

        validate_success(api.hold_premiere_slot(
            festival["id"], s1["id"], {"film_id": f1["id"]}, PROG,
        ))
        validate_success(api.hold_premiere_slot(
            festival["id"], s2["id"], {"film_id": f2["id"]}, PROG,
        ))
        validate_success(api.hold_premiere_slot(
            festival["id"], s3["id"], {"film_id": f2["id"]}, PROG,
        ))

        # Book s1 (18:00-20:00)
        f1_now = get_success_data(api.get_film(f1["id"], PROG))
        booked1 = validate_success(api.book_premiere_slot(
            festival["id"], s1["id"],
            {"expected_film_version": f1_now["version"]}, PROG,
        ))
        assert booked1["status"] == "BOOKED"

        # Book s2 (20:00-22:00): touching intervals do NOT overlap
        f2_now = get_success_data(api.get_film(f2["id"], PROG))
        booked2 = validate_success(api.book_premiere_slot(
            festival["id"], s2["id"],
            {"expected_film_version": f2_now["version"]}, PROG,
        ))
        assert booked2["status"] == "BOOKED"

        # Book s3 (19:30-21:30): shares interior time with both booked slots
        f2_now2 = get_success_data(api.get_film(f2["id"], PROG))
        resp = api.book_premiere_slot(
            festival["id"], s3["id"],
            {"expected_film_version": f2_now2["version"]}, PROG,
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_OVERLAP)

        s3_after = get_success_data(
            api.get_premiere_slot_nested(festival["id"], s3["id"], PROG)
        )
        assert s3_after["status"] == "HELD"

    def test_premiere_slot_same_film_double_booking_rejected(self, api):
        """PRD §3.4: "a different `BOOKED` slot on the same film whose
        screening interval overlaps this slot's interval rejects the booking
        with `ERR_FILM_DOUBLE_BOOKED` (HTTP 409)" — same half-open interval
        semantics applied within one film, across different festivals.

        Design: Difficulty/resource_temporal_overlap/premiere_slot_festival_venue_overlap_half_open
        """
        fest_a = setup_festival()
        fest_b = setup_festival(
            code="TIFF", name="Toronto",
            start_date="2027-01-21T00:00:00Z", end_date="2027-01-31T00:00:00Z",
        )
        film, _o, _d = _acquire(api)

        s1 = setup_premiere_slot(
            fest_a["id"],
            screening_starts_at="2027-01-22T20:00:00Z",
            screening_ends_at="2027-01-22T22:00:00Z",
        )
        s2 = setup_premiere_slot(
            fest_b["id"],
            screening_starts_at="2027-01-22T21:00:00Z",  # overlaps s1
            screening_ends_at="2027-01-22T23:00:00Z",
        )
        validate_success(api.hold_premiere_slot(
            fest_a["id"], s1["id"], {"film_id": film["id"]}, PROG,
        ))
        validate_success(api.hold_premiere_slot(
            fest_b["id"], s2["id"], {"film_id": film["id"]}, PROG,
        ))

        film_now = get_success_data(api.get_film(film["id"], PROG))
        validate_success(api.book_premiere_slot(
            fest_a["id"], s1["id"],
            {"expected_film_version": film_now["version"]}, PROG,
        ))

        film_now2 = get_success_data(api.get_film(film["id"], PROG))
        resp = api.book_premiere_slot(
            fest_b["id"], s2["id"],
            {"expected_film_version": film_now2["version"]}, PROG,
        )
        validate_error(resp, ApiErrorId.ERR_FILM_DOUBLE_BOOKED)


class TestTalentTravelBufferAggregate:
    def test_talent_travel_buffer_aggregate_capacity_semantics(self, api):
        """PRD §3.8: "for any other `CONFIRMED` obligation on the same
        `talent_name` in the same `city_code`, the gap in whole hours between
        the two obligations is computed by taking the later window's start
        minus the earlier window's end, flooring at zero, then dividing by
        3600 with floor division. If that gap is strictly greater than zero
        and strictly less than 6 hours, confirmation is rejected with
        `ERR_TRAVEL_BUFFER_VIOLATION` (HTTP 422). Adjacent obligations in the
        same city — a gap of exactly zero — are permitted. Adjacent
        obligations in different cities are not covered by the travel-buffer
        rule at all and fall under the direct-overlap rule only."
        PRD §3.8: "When confirmation is rejected by either rule, the
        obligation stays `REQUESTED` and its `conflicts_with_obligation_id` is
        set to the conflicting obligation's `id`."

        Design: Difficulty/resource_temporal_overlap/talent_travel_buffer_aggregate_capacity_semantics
        """
        film = setup_film()  # principal_cast ["Jae Park"]
        film_id = film["id"]

        ob1 = get_success_data(api.create_talent_obligation(
            film_id, create_talent_obligation_payload(
                window_starts_at="2026-12-01T10:00:00Z",
                window_ends_at="2026-12-01T12:00:00Z", city_code="NY",
            ), COORD,
        ))
        validate_success(api.confirm_talent_obligation(film_id, ob1["id"], COORD))

        # OB2: adjacent (gap == 0), same city — permitted
        ob2 = get_success_data(api.create_talent_obligation(
            film_id, create_talent_obligation_payload(
                obligation_kind="PHOTO_SHOOT",
                window_starts_at="2026-12-01T12:00:00Z",
                window_ends_at="2026-12-01T13:00:00Z", city_code="NY",
            ), COORD,
        ))
        confirmed2 = validate_success(
            api.confirm_talent_obligation(film_id, ob2["id"], COORD)
        )
        assert confirmed2["status"] == "CONFIRMED"

        # OB3: gap = 3h, same city — travel-buffer violation
        ob3 = get_success_data(api.create_talent_obligation(
            film_id, create_talent_obligation_payload(
                obligation_kind="AWARDS_SHOW",
                window_starts_at="2026-12-01T16:00:00Z",
                window_ends_at="2026-12-01T18:00:00Z", city_code="NY",
            ), COORD,
        ))
        resp3 = api.confirm_talent_obligation(film_id, ob3["id"], COORD)
        validate_error(resp3, ApiErrorId.ERR_TRAVEL_BUFFER_VIOLATION)

        ob3_after = get_success_data(api.get_talent_obligation(ob3["id"], COORD))
        assert ob3_after["status"] == "REQUESTED"
        assert ob3_after["conflicts_with_obligation_id"] is not None

        # OB4: gap = 3h, DIFFERENT city — buffer rule does not apply
        ob4 = get_success_data(api.create_talent_obligation(
            film_id, create_talent_obligation_payload(
                obligation_kind="TRAVEL",
                window_starts_at="2026-12-01T16:00:00Z",
                window_ends_at="2026-12-01T18:00:00Z", city_code="LA",
            ), COORD,
        ))
        confirmed4 = validate_success(
            api.confirm_talent_obligation(film_id, ob4["id"], COORD)
        )
        assert confirmed4["status"] == "CONFIRMED"

    def test_talent_direct_overlap_rejected_half_open(self, api):
        """PRD §3.8: "The direct-overlap rule rejects confirmation if any
        other obligation on the same `talent_name` is `CONFIRMED` and its
        window overlaps the new one, where overlap uses half-open interval
        semantics — window A overlaps window B if and only if A starts
        strictly before B ends and B starts strictly before A ends. A direct
        overlap rejection surfaces as `ERR_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/talent_travel_buffer_aggregate_capacity_semantics
        """
        film = setup_film()
        film_id = film["id"]

        ob1 = get_success_data(api.create_talent_obligation(
            film_id, create_talent_obligation_payload(
                window_starts_at="2026-12-01T10:00:00Z",
                window_ends_at="2026-12-01T12:00:00Z", city_code="NY",
            ), COORD,
        ))
        validate_success(api.confirm_talent_obligation(film_id, ob1["id"], COORD))

        # Overlapping window in a different city: direct overlap still applies
        # (direct overlap ignores city), so the confirm is rejected.
        ob2 = get_success_data(api.create_talent_obligation(
            film_id, create_talent_obligation_payload(
                obligation_kind="PHOTO_SHOOT",
                window_starts_at="2026-12-01T11:00:00Z",
                window_ends_at="2026-12-01T13:00:00Z", city_code="LA",
            ), COORD,
        ))
        resp = api.confirm_talent_obligation(film_id, ob2["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)

        ob2_after = get_success_data(api.get_talent_obligation(ob2["id"], COORD))
        assert ob2_after["status"] == "REQUESTED"
        assert ob2_after["conflicts_with_obligation_id"] == ob1["id"]
