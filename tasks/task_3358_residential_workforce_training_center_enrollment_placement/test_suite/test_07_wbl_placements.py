"""Work-based learning: hour variants, agreement gates, ceilings, wage floor."""
from test_helpers import (
    SPECIALIST,
    ApiErrorId,
    api_client,
    activate_placement,
    create_employer_agreement,
    create_wbl_placement_payload,
    propose_placement,
    record_hours,
    report_incident,
    set_clock,
    setup_enrolled_student,
    transition_incident,
    transition_placement,
    validate_error,
    validate_success,
)


class TestHoursVariants:
    def _setup_active_placement(self):
        set_clock("2026-08-25T00:00:00Z")
        bundle = setup_enrolled_student(center_name="Center WBL")
        agreement = create_employer_agreement(employer_name="WeldShop LLC")
        placement = propose_placement(bundle["enrollment"]["id"],
                                      agreement["id"])
        activate_placement(placement["id"])
        set_clock("2026-08-26T00:00:00Z")
        return placement

    def test_verified_total_counts_only_verified_entries(self):
        """PRD section 3.6: "Entries are processed in ascending work_date order
        and feed two running totals: verified_hours_total, the sum over entries
        flagged verified, and provisional_hours_total, the sum over all entries
        regardless of flag."

        Design: Difficulty/dual_variant_calc/wbl_hours_verified_vs_provisional
        """
        placement = self._setup_active_placement()
        record_hours(placement["id"], "2026-08-25", 10, verified=True)
        updated = record_hours(placement["id"], "2026-08-26", 8, verified=False)
        assert updated["verified_hours_total"] == 10
        assert updated["provisional_hours_total"] == 18

    def test_recording_hours_does_not_change_state(self):
        """PRD section 3.6: "While ACTIVE, the specialist records hours against
        the placement." — hour entries ride the ACTIVE state without leaving
        it.

        Design: Difficulty/dual_variant_calc/wbl_hours_verified_vs_provisional
        """
        placement = self._setup_active_placement()
        record_hours(placement["id"], "2026-08-25", 10, verified=True)
        updated = record_hours(placement["id"], "2026-08-26", 8, verified=False)
        assert updated["status"] == "ACTIVE"


class TestAgreementGate:
    def _setup_expired_agreement(self):
        bundle = setup_enrolled_student(center_name="Agr Center")
        agreement = create_employer_agreement(
            employer_name="Expired LLC", effective_start="2026-01-01",
            effective_end="2026-08-01",
        )
        return bundle, agreement

    def test_expired_agreement_reads_expired_and_rejects_create(self):
        """PRD section 3.6: "The agreement's status is never stored; it reads
        ACTIVE while the logical clock date lies inside that inclusive window
        and EXPIRED once the clock passes effective_end, and it is re-derived
        on every read." and "an expired agreement rejects either step with
        ERR_AGREEMENT_INACTIVE."

        Design: Difficulty/cross_entity_state_dependency/wbl_requires_employer_agreement_active
        """
        bundle, agreement = self._setup_expired_agreement()
        fetched = validate_success(
            api_client.get_employer_agreement(agreement["id"], SPECIALIST)
        )
        assert fetched["status"] == "EXPIRED"
        resp = api_client.create_wbl_placement(
            create_wbl_placement_payload(bundle["enrollment"]["id"],
                                         agreement["id"]),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INACTIVE)

    def test_rejected_proposal_persists_no_placement(self):
        """PRD section 3.6: "The agreement must also read ACTIVE, both at
        proposal and again at activation; an expired agreement rejects either
        step with ERR_AGREEMENT_INACTIVE."

        Design: Difficulty/cross_entity_state_dependency/wbl_requires_employer_agreement_active
        """
        bundle, agreement = self._setup_expired_agreement()
        resp = api_client.create_wbl_placement(
            create_wbl_placement_payload(bundle["enrollment"]["id"],
                                         agreement["id"]),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INACTIVE)
        rows = validate_success(
            api_client.list_enrollment_wbl_placements(
                bundle["enrollment"]["id"], SPECIALIST
            )
        )
        assert rows == [], "the rejected proposal must not persist a row"


class TestSlotCeiling:
    def _setup(self):
        bundle_one = setup_enrolled_student(center_name="Slot Center",
                                            capacity=5)
        bundle_two = setup_enrolled_student(center_name="Slot Center 2",
                                            capacity=5)
        agreement = create_employer_agreement(employer_name="OneSlot LLC",
                                              slot_count=1)
        w1 = propose_placement(bundle_one["enrollment"]["id"],
                               agreement["id"], supervisor_id="sup-1")
        w2 = propose_placement(bundle_two["enrollment"]["id"],
                               agreement["id"], supervisor_id="sup-2")
        return agreement, w1, w2

    def test_second_activation_hits_aggregate_ceiling(self):
        """PRD section 3.6: "the count of concurrent ACTIVE placements under
        the same agreement must remain below its slot_count (else
        ERR_WBL_SLOT_EXCEEDED)".

        Design: Difficulty/resource_temporal_overlap/wbl_agreement_slot_concurrency_ceiling
        """
        _agreement, w1, w2 = self._setup()
        activated = activate_placement(w1["id"])
        assert activated["status"] == "ACTIVE"
        resp = api_client.transition_wbl_placement(
            w2["id"], {"action": "activate"}, SPECIALIST
        )
        validate_error(resp, ApiErrorId.ERR_WBL_SLOT_EXCEEDED)

    def test_termination_reopens_ceiling(self):
        """PRD section 3.6: "Termination moves either PROPOSED or ACTIVE to
        TERMINATED, accepts an optional termination_reason, and frees one
        agreement slot and one supervision slot when the placement had been
        active".

        Design: Difficulty/resource_temporal_overlap/wbl_agreement_slot_concurrency_ceiling
        """
        agreement, w1, w2 = self._setup()
        activate_placement(w1["id"])
        validate_error(
            api_client.transition_wbl_placement(w2["id"], {"action": "activate"},
                                                SPECIALIST),
            ApiErrorId.ERR_WBL_SLOT_EXCEEDED,
        )
        transition_placement(w1["id"], "terminate",
                             termination_reason="END_OF_ASSIGNMENT")
        activated = activate_placement(w2["id"])
        assert activated["status"] == "ACTIVE"
        rows = validate_success(
            api_client.list_agreement_wbl_placements(agreement["id"],
                                                     SPECIALIST)
        )
        assert len(rows) == 2


class TestConductHoldBeatsAgreement:
    def _setup(self):
        bundle = setup_enrolled_student(center_name="Hold Center")
        enrollment = bundle["enrollment"]
        incident = report_incident(enrollment["id"], "THEFT", "2026-08-20")
        transition_incident(incident["id"], "begin_investigation")
        transition_incident(incident["id"], "refer_board")
        agreement = create_employer_agreement(
            employer_name="OldShop", effective_start="2026-01-01",
            effective_end="2026-08-01",
        )
        return bundle, agreement

    def test_conduct_hold_outranks_expired_agreement(self):
        """PRD section 2.7: "Business rules run last: conduct-hold gating,
        zero-tolerance routing, duplicate-application detection, prerequisite
        checks, hours-entry rules, selector emptiness, bed overlap and
        availability, agreement activity, capacity ceilings, wage floors, and
        period closability" — conduct-hold gating is reported before agreement
        activity.
        PRD section 3.6: "a live conduct_hold blocks the proposal with
        ERR_CONDUCT_HOLD".

        Design: Difficulty/priority_pair_validation_conflict/wbl_create_safety_beats_referential
        """
        bundle, agreement = self._setup()
        resp = api_client.create_wbl_placement(
            create_wbl_placement_payload(bundle["enrollment"]["id"],
                                         agreement["id"]),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_CONDUCT_HOLD)

    def test_dual_failure_persists_no_placement(self):
        """PRD section 3.4: "While the hold is on, four kinds of writes are
        gated with ERR_CONDUCT_HOLD: recording a credential, proposing or
        activating a work placement, creating a dormitory assignment, and
        completing training."

        Design: Difficulty/priority_pair_validation_conflict/wbl_create_safety_beats_referential
        """
        bundle, agreement = self._setup()
        resp = api_client.create_wbl_placement(
            create_wbl_placement_payload(bundle["enrollment"]["id"],
                                         agreement["id"]),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_CONDUCT_HOLD)
        rows = validate_success(
            api_client.list_enrollment_wbl_placements(
                bundle["enrollment"]["id"], SPECIALIST
            )
        )
        assert rows == []


class TestWageFloor:
    def test_wage_below_floor_rejected(self):
        """PRD section 3.6: "the offered wage must not fall below the
        agreement's hourly_wage_floor_cents (a lower offer is rejected with
        ERR_WAGE_BELOW_FLOOR)".

        Design: Corner/validations/wage_below_agreement_floor_rejected
        """
        bundle = setup_enrolled_student(center_name="Wage Center")
        agreement = create_employer_agreement(employer_name="FloorCo",
                                              hourly_wage_floor_cents=160000)
        resp = api_client.create_wbl_placement(
            create_wbl_placement_payload(bundle["enrollment"]["id"],
                                         agreement["id"],
                                         hourly_wage_cents=150000),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_WAGE_BELOW_FLOOR)

    def test_wage_exactly_at_floor_accepted(self):
        """PRD section 3.6: "the offered wage must not fall below the
        agreement's hourly_wage_floor_cents" — an offer equal to the floor is
        not below it.

        Design: Corner/validations/wage_below_agreement_floor_rejected
        """
        bundle = setup_enrolled_student(center_name="Wage Center")
        agreement = create_employer_agreement(employer_name="FloorCo",
                                              hourly_wage_floor_cents=160000)
        placement = propose_placement(bundle["enrollment"]["id"],
                                      agreement["id"],
                                      hourly_wage_cents=160000)
        assert placement["status"] == "PROPOSED"
        rows = validate_success(
            api_client.list_enrollment_wbl_placements(
                bundle["enrollment"]["id"], SPECIALIST
            )
        )
        assert len(rows) == 1


class TestHoursShapeRules:
    def _setup_active_placement(self):
        set_clock("2026-08-25T00:00:00Z")
        bundle = setup_enrolled_student(center_name="Cap Center")
        agreement = create_employer_agreement(employer_name="CapCo")
        placement = propose_placement(bundle["enrollment"]["id"],
                                      agreement["id"])
        activate_placement(placement["id"])
        return placement

    def test_hours_above_daily_cap_rejected(self):
        """PRD section 3.6: "Each entry carries a work_date, an hours total
        between 1 and 10 inclusive, and an optional verified flag." and "All
        three violations surface as ERR_INVALID_REQUEST."

        Design: Corner/validations/hours_cap_and_duplicate_workdate_rejected
        """
        placement = self._setup_active_placement()
        resp = api_client.transition_wbl_placement(
            placement["id"],
            {"action": "record_hours", "work_date": "2026-08-25",
             "hours": 11, "verified": True},
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_work_date_rejected(self):
        """PRD section 3.6: "must be unique within the placement — a second
        entry for the same date is rejected. All three violations surface as
        ERR_INVALID_REQUEST."

        Design: Corner/validations/hours_cap_and_duplicate_workdate_rejected
        """
        placement = self._setup_active_placement()
        accepted = record_hours(placement["id"], "2026-08-25", 10,
                                verified=True)
        assert accepted["verified_hours_total"] == 10
        resp = api_client.transition_wbl_placement(
            placement["id"],
            {"action": "record_hours", "work_date": "2026-08-25",
             "hours": 2, "verified": True},
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCompletionHoursBoundary:
    def _placement_at_119(self):
        set_clock("2026-08-20T00:00:00Z")
        bundle = setup_enrolled_student(center_name="Hrs Center")
        agreement = create_employer_agreement(employer_name="HoursCo")
        placement = propose_placement(bundle["enrollment"]["id"],
                                      agreement["id"])
        activate_placement(placement["id"])
        set_clock("2026-09-01T00:00:00Z")
        for day in range(20, 31):  # 2026-08-20 .. 2026-08-30 at 10 h/day
            record_hours(placement["id"], f"2026-08-{day}", 10, verified=True)
        updated = record_hours(placement["id"], "2026-08-31", 9, verified=True)
        assert updated["verified_hours_total"] == 119
        return placement

    def test_complete_at_119_rejected(self):
        """PRD section 3.6: "Completion moves ACTIVE to COMPLETED and demands
        at least 120 hours in verified_hours_total." — below the demand the
        action is undefined from the current state, so PRD section 2.7
        applies: "the request fails with ERR_INVALID_STATE".

        Design: Corner/state_machines/wbl_completion_hours_boundary_119_vs_120
        """
        placement = self._placement_at_119()
        resp = api_client.transition_wbl_placement(
            placement["id"], {"action": "complete"}, SPECIALIST
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_complete_at_exactly_120_succeeds(self):
        """PRD section 3.6: "Completion moves ACTIVE to COMPLETED and demands
        at least 120 hours in verified_hours_total."

        Design: Corner/state_machines/wbl_completion_hours_boundary_119_vs_120
        """
        placement = self._placement_at_119()
        updated = record_hours(placement["id"], "2026-09-01", 1, verified=True)
        assert updated["verified_hours_total"] == 120
        completed = transition_placement(placement["id"], "complete")
        assert completed["status"] == "COMPLETED"
