"""Shift assignments: half-open overlap, certification-vs-overlap priority,
and the confirm/cancel/no-show minutes ledger."""

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    set_clock, create_restaurant, create_manager, create_cook,
    create_station, create_shift_assignment_payload,
    make_kitchen_manager_headers,
)


def _shift_env(api):
    set_clock("2026-09-01T00:00:00Z")
    rest = create_restaurant()
    mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
    mh = make_kitchen_manager_headers(mgr["id"])
    return rest, mgr, mh


class TestHalfOpenIntervalAdjacency:
    def test_touching_intervals_allowed_true_overlap_rejected(self, api):
        """PRD section 3.3: "Second, overlap: a cook may not hold two
        non-terminal assignments — those in `SCHEDULED` or `CONFIRMED` —
        whose half-open intervals intersect; two intervals that merely touch,
        where one ends exactly when the other begins, do not intersect and
        are allowed. A genuine intersection is rejected with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cook_shift_half_open_interval_adjacency
        """
        rest, mgr, mh = _shift_env(api)
        cook = create_cook(rest["id"], mgr["id"], name="Chris Cook",
                           certified_station_types=["GRILL"])
        station = create_station(rest["id"], mgr["id"], name="Grill 1",
                                 station_type="GRILL", rack_slot_capacity=100)
        a1 = validate_success(api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], station["id"],
                shift_start="2026-09-02T08:00:00Z",
                shift_end="2026-09-02T12:00:00Z"), mh), 201)
        a2 = validate_success(api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], station["id"],
                shift_start="2026-09-02T12:00:00Z",
                shift_end="2026-09-02T16:00:00Z"), mh), 201)
        resp = api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], station["id"],
                shift_start="2026-09-02T11:00:00Z",
                shift_end="2026-09-02T13:00:00Z"), mh)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP, 409)
        data, meta = validate_paginated(api.list_shift_assignments(
            mh, params={"cook_id": cook["id"]}))
        assert len(data) == 2

    def test_containment_overlap_rejected(self, api):
        """PRD section 3.3: "A genuine intersection is rejected with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cook_shift_half_open_interval_adjacency
        """
        rest, mgr, mh = _shift_env(api)
        cook = create_cook(rest["id"], mgr["id"], name="Chris Cook",
                           certified_station_types=["GRILL"])
        station = create_station(rest["id"], mgr["id"], name="Grill 1",
                                 station_type="GRILL", rack_slot_capacity=100)
        validate_success(api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], station["id"],
                shift_start="2026-09-02T08:00:00Z",
                shift_end="2026-09-02T12:00:00Z"), mh), 201)
        resp = api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], station["id"],
                shift_start="2026-09-02T09:00:00Z",
                shift_end="2026-09-02T10:00:00Z"), mh)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP, 409)


class TestCertificationBeatsOverlap:
    def test_uncertified_and_overlapping_reports_certification(self, api):
        """PRD section 3.3: "First, certification: the station's
        `station_type` must appear in the cook's `certified_station_types`,
        failing which the assignment is rejected with
        `ERR_COOK_NOT_CERTIFIED`."
        PRD section 2.6: "A request that fails an earlier rung never surfaces
        a later rung's error."

        Design: Difficulty/priority_pair_validation_conflict/shift_certification_beats_overlap
        """
        rest, mgr, mh = _shift_env(api)
        cook = create_cook(rest["id"], mgr["id"], name="Chris Cook",
                           certified_station_types=["SAUTE"])
        st_saute = create_station(rest["id"], mgr["id"], name="Saute 1",
                                  station_type="SAUTE", rack_slot_capacity=100)
        st_grill = create_station(rest["id"], mgr["id"], name="Grill 1",
                                  station_type="GRILL", rack_slot_capacity=100)
        validate_success(api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], st_saute["id"],
                shift_start="2026-09-02T08:00:00Z",
                shift_end="2026-09-02T12:00:00Z"), mh), 201)
        # GRILL station (uncertified) AND the interval overlaps 08:00-12:00.
        resp = api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], st_grill["id"],
                shift_start="2026-09-02T11:00:00Z",
                shift_end="2026-09-02T13:00:00Z"), mh)
        validate_error(resp, ApiErrorId.ERR_COOK_NOT_CERTIFIED, 422)
        data, meta = validate_paginated(api.list_shift_assignments(
            mh, params={"cook_id": cook["id"]}))
        assert len(data) == 1

    def test_uncertified_non_overlapping_also_reports_certification(self, api):
        """PRD section 3.3: "First, certification: the station's
        `station_type` must appear in the cook's `certified_station_types`,
        failing which the assignment is rejected with
        `ERR_COOK_NOT_CERTIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/shift_certification_beats_overlap
        """
        rest, mgr, mh = _shift_env(api)
        cook = create_cook(rest["id"], mgr["id"], name="Chris Cook",
                           certified_station_types=["SAUTE"])
        st_saute = create_station(rest["id"], mgr["id"], name="Saute 1",
                                  station_type="SAUTE", rack_slot_capacity=100)
        st_grill = create_station(rest["id"], mgr["id"], name="Grill 1",
                                  station_type="GRILL", rack_slot_capacity=100)
        validate_success(api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], st_saute["id"],
                shift_start="2026-09-02T08:00:00Z",
                shift_end="2026-09-02T12:00:00Z"), mh), 201)
        resp = api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], st_grill["id"],
                shift_start="2026-09-03T08:00:00Z",
                shift_end="2026-09-03T12:00:00Z"), mh)
        validate_error(resp, ApiErrorId.ERR_COOK_NOT_CERTIFIED, 422)


class TestConfirmCancelMinutesConservation:
    def _confirmed_assignment(self, api):
        rest, mgr, mh = _shift_env(api)
        cook = create_cook(rest["id"], mgr["id"], name="Chris Cook",
                           certified_station_types=["GRILL"])
        station = create_station(rest["id"], mgr["id"], name="Grill 1",
                                 station_type="GRILL", rack_slot_capacity=100)
        assignment = validate_success(api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], station["id"]), mh), 201)
        return mh, cook, assignment

    def test_confirm_debits_then_cancel_credits_minutes(self, api):
        """PRD section 3.3: "On confirmation, the shift's length in minutes,
        measured from `shift_start` to `shift_end`, is added to the cook's
        `weekly_scheduled_minutes`." and "When a `CONFIRMED` assignment is
        cancelled, the same shift length is subtracted back out of the cook's
        `weekly_scheduled_minutes` as a compensating action; cancelling a
        merely `SCHEDULED` assignment touches no minutes."

        Design: Difficulty/compensating_invariant/shift_minutes_confirm_then_cancel_conserves_minutes
        """
        mh, cook, assignment = self._confirmed_assignment(api)
        validate_success(api.confirm_assignment(assignment["id"], mh))
        cook_mid = validate_success(api.get_cook(cook["id"], mh))
        assert cook_mid["weekly_scheduled_minutes"] == 240
        cancelled = validate_success(api.cancel_assignment(assignment["id"], mh))
        assert cancelled["status"] == "CANCELLED"
        cook_after = validate_success(api.get_cook(cook["id"], mh))
        assert cook_after["weekly_scheduled_minutes"] == 0

    def test_cancel_of_scheduled_touches_no_minutes(self, api):
        """PRD section 3.3: "cancelling a merely `SCHEDULED` assignment
        touches no minutes."

        Design: Difficulty/compensating_invariant/shift_minutes_confirm_then_cancel_conserves_minutes
        """
        mh, cook, assignment = self._confirmed_assignment(api)
        cancelled = validate_success(api.cancel_assignment(assignment["id"], mh))
        assert cancelled["status"] == "CANCELLED"
        cook_after = validate_success(api.get_cook(cook["id"], mh))
        assert cook_after["weekly_scheduled_minutes"] == 0


class TestMarkNoShowCompensates:
    def test_no_show_lands_terminal_and_credits_minutes(self, api):
        """PRD section 3.3: "Marking a no-show likewise requires `CONFIRMED`
        (otherwise `ERR_ASSIGNMENT_NOT_CONFIRMED`), moves the assignment to
        `NO_SHOW`, and applies the identical compensating subtraction of the
        shift's minutes from the cook's weekly total."

        Design: Corner/state_machines/mark_no_show_terminal_compensates_minutes
        """
        rest, mgr, mh = _shift_env(api)
        cook = create_cook(rest["id"], mgr["id"], name="Chris Cook",
                           certified_station_types=["GRILL"])
        station = create_station(rest["id"], mgr["id"], name="Grill 1",
                                 station_type="GRILL", rack_slot_capacity=100)
        assignment = validate_success(api.create_shift_assignment(
            create_shift_assignment_payload(
                cook["id"], station["id"]), mh), 201)
        validate_success(api.confirm_assignment(assignment["id"], mh))
        cook_mid = validate_success(api.get_cook(cook["id"], mh))
        assert cook_mid["weekly_scheduled_minutes"] == 240
        no_show = validate_success(api.mark_no_show(assignment["id"], mh))
        assert no_show["status"] == "NO_SHOW"
        cook_after = validate_success(api.get_cook(cook["id"], mh))
        assert cook_after["weekly_scheduled_minutes"] == 0
