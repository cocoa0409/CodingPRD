"""Covering the duty rotation: staffing, the rest rule, swaps and close-out."""
from test_helpers import (
    ApiErrorId,
    assert_duty_shift,
    assert_floor_coverage,
    assert_timestamp_equals,
    assign_duty_shift,
    create_duty_shift,
    create_ra,
    read_duty_shift,
    read_floor,
    read_ra,
    set_clock,
    setup_duty_load_scenario,
    setup_floor_with_shifts,
    setup_hall_with_floor,
    setup_two_certified_ras_on_one_floor,
    validate_error,
    validate_paginated,
    validate_success,
)

SA = {"shift_type": "WEEKEND", "start_at": "2026-09-05T18:00:00Z", "end_at": "2026-09-06T02:00:00Z"}
SB = {"shift_type": "WEEKDAY", "start_at": "2026-09-06T02:00:00Z", "end_at": "2026-09-06T06:00:00Z"}
SC = {"shift_type": "WEEKDAY", "start_at": "2026-09-06T10:00:00Z", "end_at": "2026-09-06T14:00:00Z"}


class TestDutyLoadVariants:
    def test_term_to_date_score_doubles_the_missed_block(self, api, director_headers):
        """PRD §3.4: "it sums, over the RA's shifts whose status is `COMPLETED` or
        `MISSED` and whose `start_at` falls at or after the term start instant of
        `2026-08-01T00:00:00Z` and strictly before the logical clock, that shift's
        `points_value` — except that a `MISSED` shift contributes double its points
        value as a reliability penalty."
        PRD §3.4: "The shift's `points_value` is derived from its type and never
        supplied: one point for a `WEEKDAY` block, three for a `WEEKEND` block and five
        for a `BREAK` block."

        Design: Difficulty/dual_variant_calc/ra_duty_load_term_to_date_vs_forward_28_window
        """
        base = setup_duty_load_scenario()

        load = validate_success(api.get_duty_load(base["ra"]["id"], director_headers))

        assert load["term_to_date_score"] == 5, (
            "a COMPLETED WEEKEND block scores 3 and a MISSED WEEKDAY block scores 2; "
            f"got {load['term_to_date_score']}"
        )
        assert load["missed_shift_count"] == 1
        assert read_ra(base["ra"]["id"])["duty_points_balance"] == 3, (
            "only completion moves duty points"
        )

    def test_forward_28_window_excludes_the_block_beyond_the_horizon(
        self, api, director_headers
    ):
        """PRD §3.4: "The **forward-28** figure looks ahead: it sums the plain
        `points_value`, with no penalty multiplier, over the RA's shifts whose status is
        `ASSIGNED`, `SWAP_PENDING` or `CHECKED_IN` and whose `start_at` falls at or
        after the logical clock and strictly before the instant 28 days later."
        PRD §3.4: "That window is half-open — a block starting exactly at the current
        instant is counted, a block starting exactly 28 days out is not."
        PRD §3.4: "A read of one RA's duty load returns `term_to_date_score`,
        `forward_28_score`, the RA's `missed_shift_count` and `upcoming_shift_count`,
        the number of shifts feeding the forward window."

        Design: Difficulty/dual_variant_calc/ra_duty_load_term_to_date_vs_forward_28_window
        """
        base = setup_duty_load_scenario()

        load = validate_success(api.get_duty_load(base["ra"]["id"], director_headers))

        assert load["forward_28_score"] == 4, (
            "only the 2026-09-20 WEEKEND and 2026-09-25 WEEKDAY blocks sit inside "
            f"[2026-09-15, 2026-10-13); got {load['forward_28_score']}"
        )
        assert load["upcoming_shift_count"] == 2
        beyond_horizon = read_duty_shift(base["shift_map"]["s5"]["id"])
        assert beyond_horizon["status"] == "ASSIGNED", (
            "the 2026-10-20 block is still held; it is simply outside the window"
        )
        assert load["forward_28_score"] != load["term_to_date_score"], (
            "the two readings legitimately differ over the same shift table"
        )


class TestAssignmentSafetyGates:
    def test_uncertified_ra_with_a_conflicting_block_reports_the_certification_error(
        self, api, director_headers
    ):
        """PRD §2.7: "A duty assignment naming an RA who is neither certified nor free
        of a conflicting shift reports `ERR_RA_NOT_CERTIFIED`, because the
        certification check sits above the coverage-conflict check."

        Design: Difficulty/priority_pair_validation_conflict/duty_assignment_safety_check_outranks_temporal_conflict_check
        """
        base = setup_floor_with_shifts([SA, SB])
        shift_a, shift_b = base["shifts"]
        assign_duty_shift(shift_a["id"], base["ra"]["id"])
        validate_success(
            api.ra_certification(base["ra"]["id"], {"action": "LAPSE"}, director_headers)
        )

        response = api.assign_duty_shift(
            shift_b["id"], {"ra_id": base["ra"]["id"]}, director_headers
        )

        validate_error(response, ApiErrorId.ERR_RA_NOT_CERTIFIED.value, 409)
        refused = read_duty_shift(shift_b["id"])
        assert refused["status"] == "OPEN"
        assert refused["assigned_ra_id"] is None

    def test_recertifying_the_ra_exposes_the_coverage_conflict_underneath(
        self, api, director_headers
    ):
        """PRD §3.4: "A candidate block conflicts with any block already held by the
        same RA whose status is `ASSIGNED`, `SWAP_PENDING`, `CHECKED_IN` or `COMPLETED`
        when the two intervals intersect, **or** when the clear gap between them is
        strictly less than eight hours."
        PRD §3.4: "Any such collision reports `ERR_DUTY_COVERAGE_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/duty_assignment_safety_check_outranks_temporal_conflict_check
        """
        base = setup_floor_with_shifts([SA, SB])
        shift_a, shift_b = base["shifts"]
        ra_id = base["ra"]["id"]
        assign_duty_shift(shift_a["id"], ra_id)
        validate_success(api.ra_certification(ra_id, {"action": "LAPSE"}, director_headers))
        validate_error(
            api.assign_duty_shift(shift_b["id"], {"ra_id": ra_id}, director_headers),
            ApiErrorId.ERR_RA_NOT_CERTIFIED.value,
            409,
        )

        validate_success(
            api.ra_certification(ra_id, {"action": "START_TRAINING"}, director_headers)
        )
        recertified = validate_success(
            api.ra_certification(ra_id, {"action": "CERTIFY"}, director_headers)
        )
        assert recertified["certification_status"] == "CERTIFIED"

        response = api.assign_duty_shift(shift_b["id"], {"ra_id": ra_id}, director_headers)

        validate_error(response, ApiErrorId.ERR_DUTY_COVERAGE_CONFLICT.value, 409)
        assert read_duty_shift(shift_b["id"])["status"] == "OPEN"
        assert read_duty_shift(shift_a["id"])["status"] == "ASSIGNED"


class TestAssignmentReadsBothRaDimensions:
    def test_suspended_ra_cannot_take_an_open_block(self, api, director_headers):
        """PRD §3.4: "Either way the same six conditions hold: the shift must be
        `OPEN`; the named RA must have `employment_status` `ACTIVE`; the named RA must
        have `certification_status` `CERTIFIED`; the named RA's `assigned_floor_id` must
        equal the shift's `floor_id`, and a mismatch is `ERR_FLOOR_MISMATCH`; the RA
        must have no conflicting shift under the rest rule below; and the shift's
        `start_at` must be strictly later than the logical clock, since a block already
        under way cannot be newly staffed — a late assignment is refused with
        `ERR_SHIFT_WINDOW_NOT_REACHED`."
        PRD §2.7: "An assignment naming an uncertified, inactive RA reports
        `ERR_RA_NOT_CERTIFIED` rather than `ERR_RA_NOT_ACTIVE`, because certification is
        checked immediately before employment standing."

        Design: Difficulty/cross_entity_state_dependency/duty_shift_assignment_reads_both_ra_state_dimensions
        """
        base = setup_floor_with_shifts([{"shift_type": "WEEKEND",
                                         "start_at": "2026-09-10T18:00:00Z",
                                         "end_at": "2026-09-11T02:00:00Z"}])
        shift = base["shifts"][0]
        ra_id = base["ra"]["id"]
        validate_success(
            api.ra_employment(
                ra_id, {"action": "SUSPEND", "reason": "pending review"}, director_headers
            )
        )

        response = api.assign_duty_shift(shift["id"], {"ra_id": ra_id}, director_headers)

        validate_error(response, ApiErrorId.ERR_RA_NOT_ACTIVE.value, 409)
        assert read_ra(ra_id)["certification_status"] == "CERTIFIED", (
            "the block is refused on the employment dimension alone"
        )
        assert read_duty_shift(shift["id"])["status"] == "OPEN"

    def test_lapsed_ra_cannot_take_the_block_until_recertified(self, api, director_headers):
        """PRD §2.7: "An assignment naming an uncertified, inactive RA reports
        `ERR_RA_NOT_CERTIFIED` rather than `ERR_RA_NOT_ACTIVE`, because certification is
        checked immediately before employment standing."
        PRD §3.4: "On success `assigned_ra_id` is written and the floor's
        `uncovered_shift_count` and `coverage_status` are recomputed."
        PRD §3.4: "The server-chosen path additionally sets `filled_by_selector` to
        true; the directly-named path leaves it false."

        Design: Difficulty/cross_entity_state_dependency/duty_shift_assignment_reads_both_ra_state_dimensions
        """
        base = setup_floor_with_shifts([{"shift_type": "WEEKEND",
                                         "start_at": "2026-09-10T18:00:00Z",
                                         "end_at": "2026-09-11T02:00:00Z"}])
        shift = base["shifts"][0]
        ra_id = base["ra"]["id"]
        validate_success(
            api.ra_employment(
                ra_id, {"action": "SUSPEND", "reason": "pending review"}, director_headers
            )
        )
        validate_success(api.ra_employment(ra_id, {"action": "REINSTATE"}, director_headers))
        validate_success(api.ra_certification(ra_id, {"action": "LAPSE"}, director_headers))

        lapsed_attempt = api.assign_duty_shift(
            shift["id"], {"ra_id": ra_id}, director_headers
        )
        validate_error(lapsed_attempt, ApiErrorId.ERR_RA_NOT_CERTIFIED.value, 409)

        validate_success(
            api.ra_certification(ra_id, {"action": "START_TRAINING"}, director_headers)
        )
        validate_success(api.ra_certification(ra_id, {"action": "CERTIFY"}, director_headers))
        assigned = validate_success(
            api.assign_duty_shift(shift["id"], {"ra_id": ra_id}, director_headers)
        )

        assert_duty_shift(assigned)
        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_ra_id"] == ra_id
        assert assigned["filled_by_selector"] is False
        floor = read_floor(base["floor"]["id"])
        assert floor["uncovered_shift_count"] == 0
        assert_floor_coverage(floor)


class TestRestRule:
    def test_back_to_back_block_breaches_the_eight_hour_rest_gap(self, api, director_headers):
        """PRD §3.4: "A gap of exactly eight hours is permitted; a gap of seven hours
        fifty-nine minutes is not, and back-to-back blocks with no gap at all are
        refused."
        PRD §3.4: "Any such collision reports `ERR_DUTY_COVERAGE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/duty_shift_half_open_interval_plus_eight_hour_rest_buffer
        """
        base = setup_floor_with_shifts([SA, SB, SC])
        shift_a, shift_b, _ = base["shifts"]
        assign_duty_shift(shift_a["id"], base["ra"]["id"])

        response = api.assign_duty_shift(
            shift_b["id"], {"ra_id": base["ra"]["id"]}, director_headers
        )

        validate_error(response, ApiErrorId.ERR_DUTY_COVERAGE_CONFLICT.value, 409)
        refused = read_duty_shift(shift_b["id"])
        assert refused["status"] == "OPEN"
        assert refused["assigned_ra_id"] is None

    def test_block_exactly_eight_hours_after_the_held_one_is_accepted(
        self, api, director_headers
    ):
        """PRD §3.4: "A gap of exactly eight hours is permitted; a gap of seven hours
        fifty-nine minutes is not, and back-to-back blocks with no gap at all are
        refused."
        PRD §3.4: "`MISSED`, `VOID` and `OPEN` blocks never participate in the conflict
        test."

        Design: Difficulty/resource_temporal_overlap/duty_shift_half_open_interval_plus_eight_hour_rest_buffer
        """
        base = setup_floor_with_shifts([SA, SB, SC])
        shift_a, shift_b, shift_c = base["shifts"]
        ra_id = base["ra"]["id"]
        assign_duty_shift(shift_a["id"], ra_id)
        validate_error(
            api.assign_duty_shift(shift_b["id"], {"ra_id": ra_id}, director_headers),
            ApiErrorId.ERR_DUTY_COVERAGE_CONFLICT.value,
            409,
        )

        accepted = validate_success(
            api.assign_duty_shift(shift_c["id"], {"ra_id": ra_id}, director_headers)
        )

        assert accepted["status"] == "ASSIGNED"
        assert accepted["assigned_ra_id"] == ra_id
        floor = read_floor(base["floor"]["id"])
        assert floor["uncovered_shift_count"] == 1, (
            "only the refused back-to-back block is still OPEN"
        )
        assert floor["coverage_status"] == "NORMAL"


def test_swap_cycle_installs_the_replacement_and_returns_the_block_to_assigned(
    api, director_headers
):
    """PRD §3.4: "The RA holding an `ASSIGNED` block may propose a replacement, moving
    it to `SWAP_PENDING`."
    PRD §3.4: "A director then closes the cycle with an `action` of `APPROVE` or
    `WITHDRAW`, both of which return the block to `ASSIGNED` and clear
    `swap_requested_ra_id`."
    PRD §3.4: "`APPROVE` installs the replacement as `assigned_ra_id`, and before it
    does so the replacement is put through exactly the same active, certified,
    floor-coherence and rest-gap checks the original assignment passed."

    Design: Corner/state_machines/duty_swap_cycle_installs_replacement_and_returns_shift_to_assigned
    """
    base = setup_two_certified_ras_on_one_floor()
    holder, replacement = base["first"], base["second"]
    shift = create_duty_shift(
        base["floor"]["id"], SA["start_at"], SA["end_at"], shift_type="WEEKEND"
    )
    assign_duty_shift(shift["id"], holder["ra"]["id"])

    pending = validate_success(
        api.swap_duty_shift(
            shift["id"],
            {"action": "REQUEST", "replacement_ra_id": replacement["ra"]["id"]},
            holder["ra_headers"],
        )
    )
    assert pending["status"] == "SWAP_PENDING"
    assert pending["swap_requested_ra_id"] == replacement["ra"]["id"]
    assert pending["assigned_ra_id"] == holder["ra"]["id"], (
        "the original holder keeps the block until the swap is approved"
    )

    approved = validate_success(
        api.swap_duty_shift(shift["id"], {"action": "APPROVE"}, director_headers)
    )
    assert approved["status"] == "ASSIGNED"
    assert approved["assigned_ra_id"] == replacement["ra"]["id"]
    assert approved["swap_requested_ra_id"] is None
    assert read_floor(base["floor"]["id"])["uncovered_shift_count"] == 0
    assert read_ra(holder["ra"]["id"])["duty_points_balance"] == 0
    assert read_ra(replacement["ra"]["id"])["duty_points_balance"] == 0


def test_separating_an_ra_reopens_future_blocks_and_flips_the_floor_to_critical(
    api, director_headers
):
    """PRD §3.3: "First, every duty shift held by the separating RA that is still in
    the future — that is, whose `start_at` is strictly later than the logical clock —
    and whose status is `ASSIGNED` or `SWAP_PENDING` returns to `OPEN`, with both
    `assigned_ra_id` and `swap_requested_ra_id` cleared."
    PRD §3.3: "Third, any floor whose recomputed count reaches two or more flips
    `coverage_status` to `CRITICAL`; below two it reads `NORMAL`."
    PRD §3.3: "Separation is available from either `ACTIVE` or `SUSPENDED`, records the
    supplied `reason` as `separation_reason`, and is terminal — `SEPARATED` admits no
    further employment action, and an attempt draws `ERR_RA_STATE_INVALID`."

    Design: Corner/state_machines/ra_separation_reopens_future_shifts_and_flips_floor_to_critical
    """
    base = setup_floor_with_shifts(
        [SA, {"shift_type": "WEEKDAY", "start_at": "2026-09-07T18:00:00Z",
              "end_at": "2026-09-08T02:00:00Z"}]
    )
    shift_a, shift_b = base["shifts"]
    ra_id = base["ra"]["id"]
    assign_duty_shift(shift_a["id"], ra_id)
    assign_duty_shift(shift_b["id"], ra_id)

    separated = validate_success(
        api.ra_employment(
            ra_id, {"action": "SEPARATE", "reason": "resigned mid-term"}, director_headers
        )
    )

    assert separated["employment_status"] == "SEPARATED"
    assert separated["separation_reason"] == "resigned mid-term"
    assert separated["certification_status"] == "CERTIFIED", (
        "separation never writes the certification dimension"
    )
    for shift_id in (shift_a["id"], shift_b["id"]):
        reopened = read_duty_shift(shift_id)
        assert reopened["status"] == "OPEN"
        assert reopened["assigned_ra_id"] is None
    floor = read_floor(base["floor"]["id"])
    assert floor["uncovered_shift_count"] == 2
    assert floor["coverage_status"] == "CRITICAL"


def test_voiding_a_completed_block_reverses_its_duty_points_exactly(api, director_headers):
    """PRD §3.4: "`COMPLETE` moves it `CHECKED_IN → COMPLETED`, again by the assigned
    RA, and requires the clock to have reached `end_at`; it stamps `completed_at` and
    adds the block's `points_value` to the RA's `duty_points_balance`."
    PRD §3.4: "`VOID` is a director action available from two states with two very
    different meanings: voiding an `OPEN` block simply retires it and refreshes the
    floor's `uncovered_shift_count` and `coverage_status`, while voiding a `COMPLETED`
    block is a compensating reversal that subtracts exactly the same `points_value`
    that completion added, leaving the RA's `duty_points_balance` at its pre-completion
    figure with no drift."

    Design: Corner/state_machines/voiding_a_completed_shift_reverses_duty_points_with_no_drift
    """
    base = setup_floor_with_shifts([SA])
    shift = base["shifts"][0]
    ra_id = base["ra"]["id"]
    assign_duty_shift(shift["id"], ra_id)
    set_clock(SA["start_at"])
    validate_success(
        api.duty_shift_outcome(shift["id"], {"action": "CHECK_IN"}, base["ra_headers"])
    )
    set_clock(SA["end_at"])
    completed = validate_success(
        api.duty_shift_outcome(shift["id"], {"action": "COMPLETE"}, base["ra_headers"])
    )
    assert completed["status"] == "COMPLETED"
    assert completed["points_value"] == 3
    assert read_ra(ra_id)["duty_points_balance"] == 3

    voided = validate_success(
        api.duty_shift_outcome(shift["id"], {"action": "VOID"}, director_headers)
    )

    assert voided["status"] == "VOID"
    after = read_ra(ra_id)
    assert after["duty_points_balance"] == 0, (
        f"VOID must subtract exactly the 3 points COMPLETE added, got "
        f"{after['duty_points_balance']}"
    )
    assert after["missed_shift_count"] == 0
    assert_timestamp_equals(voided["completed_at"], SA["end_at"], "completed_at")


def test_auto_fill_with_no_certified_candidate_reports_no_eligible_ra(api, director_headers):
    """PRD §3.4: "When a director asks the server to fill an unstaffed block, the
    candidate pool is every RA whose `employment_status` is `ACTIVE`, whose
    `certification_status` is `CERTIFIED`, whose `assigned_floor_id` equals the shift's
    floor, who is not named in the optional `exclude_ra_ids` list supplied with the
    request, and who has no conflicting block under the rest rule above."
    PRD §3.4: "When the pool comes out empty, the request is refused with
    `ERR_NO_ELIGIBLE_RA` (HTTP 422), the block stays `OPEN`, and the floor's
    `uncovered_shift_count` is left exactly as it was."

    Design: Corner/calculations/auto_fill_with_no_certified_candidate_returns_no_eligible_ra
    """
    base = setup_hall_with_floor()
    staff = create_ra(floor_id=base["floor"]["id"], modules=[], certify=False)
    shift = create_duty_shift(
        base["floor"]["id"], SA["start_at"], SA["end_at"], shift_type="WEEKEND"
    )
    assert staff["ra"]["certification_status"] == "IN_TRAINING"

    response = api.auto_fill_duty_shift(shift["id"], {}, director_headers)

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_RA.value, 422)
    unfilled = read_duty_shift(shift["id"])
    assert unfilled["status"] == "OPEN"
    assert unfilled["assigned_ra_id"] is None
    assert unfilled["filled_by_selector"] is False
    floor = read_floor(base["floor"]["id"])
    assert floor["uncovered_shift_count"] == 1
    assert floor["coverage_status"] == "NORMAL"


def test_check_in_before_the_block_starts_reports_the_window_error(api, director_headers):
    """PRD §3.4: "`CHECK_IN` moves it `ASSIGNED → CHECKED_IN`, requires the caller to
    be the assigned RA, and requires the logical clock to sit at or after `start_at`
    and strictly before `end_at`; it stamps `checked_in_at`."
    PRD §3.4: "Any outcome action issued outside its clock window is
    `ERR_SHIFT_WINDOW_NOT_REACHED`, and any action issued from a status where it is not
    declared is `ERR_SHIFT_STATE_INVALID`."

    Design: Corner/validations/shift_check_in_before_start_at_returns_shift_window_not_reached
    """
    base = setup_floor_with_shifts([SA])
    shift = base["shifts"][0]
    assign_duty_shift(shift["id"], base["ra"]["id"])

    early = api.duty_shift_outcome(
        shift["id"], {"action": "CHECK_IN"}, base["ra_headers"]
    )

    validate_error(early, ApiErrorId.ERR_SHIFT_WINDOW_NOT_REACHED.value, 409)
    refused = read_duty_shift(shift["id"])
    assert refused["status"] == "ASSIGNED"
    assert refused["checked_in_at"] is None

    set_clock(SA["start_at"])
    checked_in = validate_success(
        api.duty_shift_outcome(shift["id"], {"action": "CHECK_IN"}, base["ra_headers"])
    )
    assert checked_in["status"] == "CHECKED_IN"
    assert_timestamp_equals(checked_in["checked_in_at"], SA["start_at"], "checked_in_at")
    assert read_ra(base["ra"]["id"])["duty_points_balance"] == 0, (
        "points land only at COMPLETE"
    )


def test_duty_shift_listing_combines_the_status_filter_with_pagination(api, director_headers):
    """PRD §2.3: "Duty shifts accept `floor_id`, `assigned_ra_id`,
    `swap_requested_ra_id` and `status`."
    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they
    were applied, `total_count` as the number of rows matching the filters before the
    page window was taken, and `has_more` as a boolean that is true when rows remain
    beyond the current window."

    Design: Corner/cross_cutting_complexity_layers/duty_shift_list_combines_status_filter_with_pagination
    """
    base = setup_hall_with_floor()
    floor_id = base["floor"]["id"]
    specs = [
        ("WEEKDAY", "2026-09-01T18:00:00Z", "2026-09-02T02:00:00Z"),
        ("WEEKDAY", "2026-09-03T18:00:00Z", "2026-09-04T02:00:00Z"),
        ("WEEKEND", "2026-09-05T18:00:00Z", "2026-09-06T02:00:00Z"),
        ("WEEKEND", "2026-09-07T18:00:00Z", "2026-09-08T02:00:00Z"),
    ]
    shifts = [
        create_duty_shift(floor_id, start, end, shift_type=kind)
        for kind, start, end in specs
    ]
    validate_success(
        api.duty_shift_outcome(shifts[3]["id"], {"action": "VOID"}, director_headers)
    )

    params = {"floor_id": floor_id, "status": "OPEN", "limit": 2, "offset": 0}
    first_page, first_meta = validate_paginated(api.list_duty_shifts(director_headers, params))
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    params["offset"] = 2
    second_page, second_meta = validate_paginated(api.list_duty_shifts(director_headers, params))
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    listed_ids = {row["id"] for row in first_page + second_page}
    assert shifts[3]["id"] not in listed_ids, "the VOID block matches no page"
    floor = read_floor(floor_id)
    assert floor["uncovered_shift_count"] == 3
    assert floor["coverage_status"] == "CRITICAL"
