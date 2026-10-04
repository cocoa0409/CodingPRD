"""Dormitory beds: half-open overlap, auto-select, invariant, checkout cascade."""
from test_helpers import (
    ADVISOR,
    MANAGER,
    ApiErrorId,
    api_client,
    assert_center_bed_invariant,
    assign_applicant,
    assign_bed,
    create_center,
    create_dormitory_assignment_payload,
    create_trade_program,
    enroll_applicant,
    get_center,
    get_enrollment,
    make_eligible_applicant,
    validate_error,
    validate_success,
)


def _resident_enrollment(program, full_name, barrier="FOSTER_CARE"):
    applicant, _case = make_eligible_applicant(
        full_name=full_name, barrier_flags=[barrier],
    )
    assign_applicant(applicant, residential_track=True)
    return enroll_applicant(applicant["id"], program["id"],
                            residential_track=True)


class TestHalfOpenIntervals:
    def _setup(self):
        center = create_center(name="Adj Center", total_beds=1)
        program = create_trade_program(center["id"], capacity=5)
        e1 = _resident_enrollment(program, "Adj One")
        e2 = _resident_enrollment(program, "Adj Two", barrier="HOMELESS")
        return center, e1, e2

    def test_open_ended_assignment_blocks_same_bed(self):
        """PRD section 3.4: "an existing ACTIVE assignment on the same center
        and bed conflicts exactly when its move_out_date is null (open-ended)
        or the new move_in_date falls before that existing move-out" and "A
        colliding request is rejected with ERR_BED_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/dorm_bed_half_open_interval_adjacency
        """
        _center, e1, e2 = self._setup()
        assign_bed(e1["id"], move_in_date="2026-09-01", bed_label="B-01")
        resp = api_client.create_dormitory_assignment(
            create_dormitory_assignment_payload(
                e2["id"], move_in_date="2026-10-01", bed_label="B-01"
            ),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_BED_OVERLAP)

    def test_adjacent_move_in_equals_move_out_allowed(self):
        """PRD section 3.4: "a new move-in exactly equal to the existing
        move-out is adjacency and is allowed."

        Design: Difficulty/resource_temporal_overlap/dorm_bed_half_open_interval_adjacency
        """
        _center, e1, e2 = self._setup()
        first = assign_bed(e1["id"], move_in_date="2026-09-01",
                           bed_label="B-01")
        checkout = api_client.checkout_dormitory_assignment(
            first["id"], {"move_out_date": "2026-10-01"}, ADVISOR
        )
        validate_success(checkout, 200)
        adjacent = assign_bed(e2["id"], move_in_date="2026-10-01",
                              bed_label="B-01")
        assert adjacent["status"] == "ACTIVE"
        assert adjacent["move_in_date"] == "2026-10-01"


class TestLastBed:
    def _setup(self):
        center = create_center(name="Tiny Center", total_beds=1)
        program = create_trade_program(center["id"], capacity=5)
        e1 = _resident_enrollment(program, "Bed One")
        e2 = _resident_enrollment(program, "Bed Two", barrier="HOMELESS")
        return center, e1, e2

    def test_last_free_bed_assignment_succeeds(self):
        """PRD section 3.4: "When bed_label is omitted, the server auto-selects
        the lowest-numbered free bed label in ascending label order".

        Design: Difficulty/boundary_precision_check/last_bed_assignment_succeeds_then_pool_empty
        """
        _center, e1, _e2 = self._setup()
        assignment = assign_bed(e1["id"], move_in_date="2026-09-01")
        assert assignment["bed_label"] == "B-01"
        assert assignment["status"] == "ACTIVE"

    def test_pool_exactly_empty_rejects_next_auto_select(self):
        """PRD section 3.4: "if every bed of the center is occupied the create
        fails with ERR_NO_BED_AVAILABLE."

        Design: Difficulty/boundary_precision_check/last_bed_assignment_succeeds_then_pool_empty
        """
        center, e1, e2 = self._setup()
        assign_bed(e1["id"], move_in_date="2026-09-01")
        resp = api_client.create_dormitory_assignment(
            create_dormitory_assignment_payload(e2["id"],
                                                move_in_date="2026-09-01"),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_NO_BED_AVAILABLE)
        center_after = get_center(center["id"])
        assert center_after["beds_in_use"] == 1
        assert center_after["beds_available"] == 0


class TestBedInvariant:
    def test_assignments_conserve_total_beds(self):
        """PRD section 2.9: "A center's beds_in_use counts its ACTIVE dormitory
        assignments and its beds_available is the remainder of total_beds, with
        the invariant that the two sum to total_beds after every mutation."

        Design: Difficulty/compensating_invariant/bed_assign_checkout_conserves_total_beds
        """
        center = create_center(name="Inv Center", total_beds=2)
        assert center["beds_in_use"] == 0
        assert center["beds_available"] == 2
        program = create_trade_program(center["id"], capacity=5)
        e1 = _resident_enrollment(program, "Inv One")
        e2 = _resident_enrollment(program, "Inv Two", barrier="HOMELESS")
        first = assign_bed(e1["id"], move_in_date="2026-09-01")
        second = assign_bed(e2["id"], move_in_date="2026-09-01")
        assert (first["bed_label"], second["bed_label"]) == ("B-01", "B-02"), (
            "auto-select takes the lowest-numbered free bed label in "
            "ascending label order"
        )
        full = get_center(center["id"])
        assert full["beds_in_use"] == 2
        assert full["beds_available"] == 0
        assert_center_bed_invariant(full)

    def test_compensating_checkout_restores_invariant(self):
        """PRD section 3.4: "the assignment settles to CHECKED_OUT, the freed
        bed returns to the pool as beds_available rises by one".

        Design: Difficulty/compensating_invariant/bed_assign_checkout_conserves_total_beds
        """
        center = create_center(name="Inv Center", total_beds=2)
        program = create_trade_program(center["id"], capacity=5)
        e1 = _resident_enrollment(program, "Inv One")
        e2 = _resident_enrollment(program, "Inv Two", barrier="HOMELESS")
        first = assign_bed(e1["id"], move_in_date="2026-09-01")
        assign_bed(e2["id"], move_in_date="2026-09-01")
        validate_success(
            api_client.checkout_dormitory_assignment(
                first["id"], {"move_out_date": "2026-10-01"}, ADVISOR
            ),
            200,
        )
        after = get_center(center["id"])
        assert after["beds_in_use"] == 1
        assert after["beds_available"] == 1
        assert_center_bed_invariant(after)


class TestCheckoutCascade:
    def _setup(self):
        center = create_center(name="Checkout Center", total_beds=2)
        program = create_trade_program(center["id"], capacity=5)
        e1 = _resident_enrollment(program, "Out Stu")
        assignment = assign_bed(e1["id"], move_in_date="2026-09-01")
        return center, e1, assignment

    def test_checkout_settles_assignment_and_releases_resident_axis(self):
        """PRD section 3.4: "Checkout is the compensating action for an
        assignment: the advisor supplies a move_out_date that must not fall
        before the move_in_date, the assignment settles to CHECKED_OUT, the
        freed bed returns to the pool as beds_available rises by one, and the
        enrollment's residential axis moves from RESIDENT to RELEASED."

        Design: Difficulty/transitive_cascade/checkout_cascades_residential_release_and_bed_reconcile
        """
        _center, e1, assignment = self._setup()
        checked = validate_success(
            api_client.checkout_dormitory_assignment(
                assignment["id"], {"move_out_date": "2026-10-15"}, ADVISOR
            ),
            200,
        )
        assert checked["status"] == "CHECKED_OUT"
        assert checked["move_out_date"] == "2026-10-15"
        enrollment = get_enrollment(e1["id"])
        assert enrollment["residential_status"] == "RELEASED"
        assert enrollment["training_status"] == "TRAINING", (
            "the training axis is untouched by a dormitory checkout"
        )

    def test_checkout_recomputes_center_bed_ledger(self):
        """PRD section 2.9: "A center's beds_in_use counts its ACTIVE dormitory
        assignments and its beds_available is the remainder of total_beds".

        Design: Difficulty/transitive_cascade/checkout_cascades_residential_release_and_bed_reconcile
        """
        center, _e1, assignment = self._setup()
        before = get_center(center["id"])
        assert (before["beds_in_use"], before["beds_available"]) == (1, 1)
        validate_success(
            api_client.checkout_dormitory_assignment(
                assignment["id"], {"move_out_date": "2026-10-15"}, ADVISOR
            ),
            200,
        )
        after = get_center(center["id"])
        assert (after["beds_in_use"], after["beds_available"]) == (0, 2)


class TestStateBeatsCapacity:
    def _setup(self):
        center = create_center(name="Prio Center", total_beds=1)
        program = create_trade_program(center["id"], capacity=5)
        e1 = _resident_enrollment(program, "Res One")
        # Both enrollments must exist before the only bed is taken: PRD 3.2
        # excludes centers with beds_available < 1 from a residential-track
        # assignment pool, so creating e2 after the bed is gone would fail
        # with ERR_NO_ELIGIBLE_CENTER instead of reaching the target state.
        e2 = _resident_enrollment(program, "Res Two", barrier="HOMELESS")
        assign_bed(e1["id"], move_in_date="2026-09-01")  # pool now exhausted
        validate_success(
            api_client.transition_enrollment(
                e2["id"], {"action": "unenroll", "reason": "WITHDRAWN"},
                MANAGER,
            ),
            200,
        )
        return center, e2

    def test_terminal_enrollment_assignment_reports_invalid_state(self):
        """PRD section 2.7: "the same ERR_INVALID_STATE also covers create
        endpoints whose referenced entities violate a state precondition" and
        "Business rules run last: conduct-hold gating, zero-tolerance routing,
        duplicate-application detection, prerequisite checks, hours-entry
        rules, selector emptiness, bed overlap and availability, agreement
        activity, capacity ceilings, wage floors, and period closability".

        Design: Difficulty/priority_pair_validation_conflict/dorm_assign_state_beats_capacity
        """
        _center, e2 = self._setup()
        resp = api_client.create_dormitory_assignment(
            create_dormitory_assignment_payload(e2["id"],
                                                move_in_date="2026-09-01"),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_assignment_persists_no_row(self):
        """PRD section 3.4: "Residential life begins when a ResidentialAdvisor
        assigns a bed to an enrollment that is waiting for one." — an
        enrollment that has left AWAITING_BED admits no assignment row.

        Design: Difficulty/priority_pair_validation_conflict/dorm_assign_state_beats_capacity
        """
        _center, e2 = self._setup()
        resp = api_client.create_dormitory_assignment(
            create_dormitory_assignment_payload(e2["id"],
                                                move_in_date="2026-09-01"),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows = validate_success(
            api_client.list_dormitory_assignments(e2["id"], ADVISOR)
        )
        assert rows == [], "the rejected create must not persist a row"
