"""Talent registration defaults, roster listing, access guards, and booking
eligibility boundaries."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NONEXISTENT_UUID,
    assert_talent,
    create_talent, create_arena, create_event,
    create_talent_payload, create_event_payload,
)


class TestTalentDefaults:
    def test_new_talent_starts_unbookable_at_zero_wellness(self, api, talent_relations_headers):
        """PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Corner/entities/talent_creation_applies_system_defaults
        """
        created = validate_success(
            api.create_talent(create_talent_payload(ring_name="Default Dan"),
                              talent_relations_headers),
            expected_status=201)
        data = validate_success(api.get_talent(created["id"], talent_relations_headers))
        assert_talent(data)
        assert data["roster_tier"] == "DEVELOPMENTAL"
        assert data["availability_status"] == "ACTIVE"
        assert float(data["wellness_score"]) == 0.00
        assert data["booking_mode"] == "UNBOOKABLE"
        assert data["likeness_granted"] is False

    def test_new_talent_inputs_cannot_override_system_defaults(self, api, talent_relations_headers):
        """PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Corner/entities/talent_creation_applies_system_defaults
        """
        payload = create_talent_payload(ring_name="Override Ora")
        # Attempt to smuggle system/computed fields in as inputs; the server
        # must ignore them and apply its own initialization.
        payload.update({
            "roster_tier": "MAIN_ROSTER",
            "availability_status": "SUSPENDED",
            "wellness_score": 99.0,
            "booking_mode": "BOOKABLE",
            "likeness_granted": True,
        })
        created = validate_success(api.create_talent(payload, talent_relations_headers),
                                   expected_status=201)
        assert created["roster_tier"] == "DEVELOPMENTAL"
        assert created["availability_status"] == "ACTIVE"
        assert float(created["wellness_score"]) == 0.00
        assert created["booking_mode"] == "UNBOOKABLE"
        assert created["likeness_granted"] is False


class TestTalentRegistrationValidation:
    def test_invalid_contractor_status_rejected(self, api, talent_relations_headers):
        """PRD §3.1: "The only accepted value for `contractor_status` is `INDEPENDENT_CONTRACTOR`; any other value is rejected with `ERR_INVALID_REQUEST`, reflecting that the promotion engages every performer strictly as an independent contractor."

        Design: Corner/entities/talent_creation_invalid_contractor_status_rejected
        """
        resp = api.create_talent(
            create_talent_payload(ring_name="Emp Ed", contractor_status="EMPLOYEE"),
            talent_relations_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_talent_returns_not_found(self, api, talent_relations_headers):
        """PRD §2.7: "then existence of every path identifier, resolved left to right (`ERR_NOT_FOUND`)"

        Design: Corner/entities/talent_get_nonexistent_id_returns_not_found
        """
        resp = api.get_talent(NONEXISTENT_UUID, talent_relations_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestTalentListing:
    def test_list_pagination_envelope(self, api, talent_relations_headers, tour_planner_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/talents_list_pagination_envelope
        """
        create_talent(ring_name="Page One")
        create_talent(ring_name="Page Two")
        resp = api.list_talents(tour_planner_headers, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "array"
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0


class TestAuthentication:
    def test_missing_headers_rejected_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_on_missing_headers
        """
        resp = api._request("GET", "/touring/talents", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_missing_role_header_rejected_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_on_missing_headers
        """
        resp = api._request("GET", "/touring/talents",
                            headers={"X-User-ID": "test-op-1",
                                     "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestForeignKeyExistence:
    def test_booking_with_unknown_talent_returns_reference_not_found(
            self, api, tour_planner_headers):
        """PRD §2.7: "then existence of every foreign-key identifier in the request body (`ERR_REFERENCE_NOT_FOUND`)"

        Design: Corner/errors/error_reference_not_found_on_body_fk
        """
        arena = create_arena(name="Ref Arena")
        event = create_event(arena["id"], name="RE")
        resp = api.create_booking(
            {"event_id": event["id"], "talent_id": NONEXISTENT_UUID,
             "segment_label": "MATCH_1"},
            tour_planner_headers)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestBookingEligibilityBands:
    def test_fresh_unbookable_talent_rejected_on_house_show_and_premium(
            self, api, talent_relations_headers, tour_planner_headers):
        """PRD §3.4: "The talent's `booking_mode` must permit the booking: `BOOKABLE` talent may be booked anywhere, `LIMITED` talent only onto `HOUSE_SHOW` events, and `UNBOOKABLE` talent nowhere, with violations rejected as `ERR_TALENT_UNBOOKABLE`."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Difficulty/boundary_precision_check/booking_mode_threshold_limited_band_floor
        """
        talent = create_talent(ring_name="Boundary Bob")
        arena = create_arena(name="Bnd Arena")
        hs = create_event(arena["id"], name="HS_OK", event_date="2026-09-05")
        pe = create_event(arena["id"], name="PE_NO", event_type="PREMIUM",
                          event_date="2026-09-06", start_time="20:00", end_time="23:00")
        assert talent["booking_mode"] == "UNBOOKABLE"
        resp_hs = api.create_booking(
            {"event_id": hs["id"], "talent_id": talent["id"], "segment_label": "MATCH_1"},
            tour_planner_headers)
        validate_error(resp_hs, ApiErrorId.ERR_TALENT_UNBOOKABLE)
        resp_pe = api.create_booking(
            {"event_id": pe["id"], "talent_id": talent["id"], "segment_label": "MAIN_EVENT"},
            tour_planner_headers)
        validate_error(resp_pe, ApiErrorId.ERR_TALENT_UNBOOKABLE)

    def test_limited_band_floor_at_40_is_inclusive_by_spec(self, api, talent_relations_headers,
                                                           tour_planner_headers):
        """PRD §3.1: "otherwise a score of at least 40.00 makes them `LIMITED`; anything below 40.00 is `UNBOOKABLE`."
        PRD §3.1: "A `LIMITED` talent may only be booked onto `HOUSE_SHOW` events; an `UNBOOKABLE` talent may not be booked at all."

        Design: Difficulty/boundary_precision_check/booking_mode_threshold_limited_band_floor
        """
        # A fresh talent at 0.00 sits below the 40.00 LIMITED floor, so it is
        # UNBOOKABLE and rejected even on a HOUSE_SHOW — the sub-floor side of
        # the inclusive band boundary.
        talent = create_talent(ring_name="Floor Fred")
        assert float(talent["wellness_score"]) < 40.00
        assert talent["booking_mode"] == "UNBOOKABLE"
        arena = create_arena(name="Floor Arena")
        hs = create_event(arena["id"], name="FHS", event_date="2026-09-05")
        resp = api.create_booking(
            {"event_id": hs["id"], "talent_id": talent["id"], "segment_label": "MATCH_1"},
            tour_planner_headers)
        validate_error(resp, ApiErrorId.ERR_TALENT_UNBOOKABLE)


class TestTelevisionAnchorDay:
    def test_television_event_must_land_on_anchor_day(self, api, tour_planner_headers):
        """PRD §3.3: "A `TELEVISION` event must reference an `anchor_id` and must actually land on that anchor's `weekly_day_of_week`; a missing anchor or a day mismatch is rejected with `ERR_ANCHOR_DATE_MISMATCH`."

        Design: Corner/validations/television_event_must_match_anchor_day
        """
        from test_helpers import create_broadcast_anchor
        anchor = create_broadcast_anchor(name="Monday Night Raw-like", weekly_day_of_week=1)
        arena = create_arena(name="TV Arena", capacity=10000, merch_booths=4)
        # 2026-09-05 is a Saturday; 2026-09-07 is a Monday.
        bad = api.create_event(
            create_event_payload(arena["id"], name="TV_BAD", event_type="TELEVISION",
                                 anchor_id=anchor["id"], event_date="2026-09-05",
                                 start_time="20:00", end_time="22:00"),
            tour_planner_headers)
        validate_error(bad, ApiErrorId.ERR_ANCHOR_DATE_MISMATCH)
        good = api.create_event(
            create_event_payload(arena["id"], name="TV_OK", event_type="TELEVISION",
                                 anchor_id=anchor["id"], event_date="2026-09-07",
                                 start_time="20:00", end_time="22:00"),
            tour_planner_headers)
        data = validate_success(good, expected_status=201)
        assert data["status"] == "SCHEDULED"
