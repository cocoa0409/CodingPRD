"""Derived numbers: fines, occupancy input sets, ratios, deadlines and aggregates.

Each test drives one calculation to a value the PRD states or uniquely derives,
and checks the inputs the formula is *not* allowed to read.
"""

from test_helpers import (
    CODE_NUTRITION,
    CODE_RATIO,
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_cents,
    assert_instant,
    assert_point_ledger,
    assert_points,
    assert_roster_flags,
    assert_score,
    factories as f,
    fixtures as fx,
    supervisor_headers,
    validate_error,
    validate_success,
)

PRESCHOOL_ONLY = ["PRESCHOOL"]
VISIT_INSTANT = "2026-08-05T09:00:00Z"


def _one_critical_citation_finalized(api, catalog):
    """A CENTER carrying exactly 15 open points from one FINALIZED ANNUAL visit."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    provider = fx.create_provider(api, requested_capacity=10)
    inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
    inspection = fx.schedule_visit(
        api,
        provider["id"],
        inspector["id"],
        VISIT_INSTANT,
        inspection_type="ANNUAL",
        target_age_groups=PRESCHOOL_ONLY,
    )
    fx.set_clock(api, VISIT_INSTANT)
    fx.start_visit(api, inspection["id"], inspector["id"])
    violation = fx.cite(
        api,
        inspection["id"],
        inspector["id"],
        catalog[CODE_SUPERVISION],
        primary_age_group="PRESCHOOL",
        narrative="Nap room left unattended.",
    )
    fx.submit_findings(api, inspection["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY)
    finalized = fx.finalize_visit(api, inspection["id"])
    return provider, inspector, {"inspection": finalized, "violations": [violation]}


class TestFineArithmeticAndTheProposalItself:
    """§3.8: "The fine is computed once, at proposal, and frozen"."""

    def test_a_warning_on_fifteen_points_is_the_bare_gross_amount(self, api, catalog):
        """The first pricing tier takes neither surcharge nor credit, so the fine is
        the gross 37500 and the proposal leaves the ladder untouched.

        PRD §3.8: "A warning on 15 basis points grosses 37500, sits in the first
        tier, takes no surcharge and no credit, and its fine is 37500 cents."

        Design: Corner/calculations/calc_correct_result_warning_fine_stays_in_tier_one
        """
        provider, _inspector, visit = _one_critical_citation_finalized(api, catalog)
        before = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(before, 15, 0, 15)

        action = validate_success(
            api.create_enforcement_action(
                f.enforcement_action_payload(
                    provider["id"],
                    requested_action_type="WARNING",
                    source_inspection_id=visit["inspection"]["id"],
                    rationale="First supervision failure.",
                ),
                headers=supervisor_headers(),
            ),
            201,
        )
        assert_points(action["basis_points"], 15, "basis_points")
        assert action["ladder_step"] == 1
        assert_cents(action["fine_amount_cents"], 37500)
        assert action["action_type"] == "WARNING"
        assert action["status"] == "PROPOSED"
        assert_instant(action["proposed_at"], VISIT_INSTANT, "proposed_at")
        assert action["appeal_deadline_at"] is None
        assert action["capacity_held_slots"] == 0

        after = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert after["current_ladder_step"] == 0, "a proposal does not move the ladder"


class TestOccupancyReadsOnlyTheActiveSet:
    """§3.4: "The **active set** for all three is every inspection whose status is
    `SCHEDULED` or `IN_PROGRESS`"."""

    def test_the_same_slot_is_refused_while_scheduled_and_free_once_finalized(
        self, api, catalog
    ):
        """One inspector, one instant, two attempts: the first collides with the
        SCHEDULED incumbent and the second succeeds after that incumbent finalizes.

        PRD §3.4: "a visit that has moved on to `PENDING_REVIEW`, `FINALIZED` or
        `VOIDED` releases its windows and never conflicts again."

        Design: Corner/calculations/calc_input_set_filtering_finalized_inspection_releases_its_window
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider_a = fx.create_provider(api, legal_name="Provider A", site_address="1 A St")
        provider_b = fx.create_provider(api, legal_name="Provider B", site_address="2 B St")
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        incumbent = fx.schedule_visit(
            api,
            provider_a["id"],
            inspector["id"],
            "2026-08-10T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        assert_instant(
            incumbent["visit_window_end"], "2026-08-10T11:00:00Z", "visit_window_end"
        )
        fx.set_clock(api, "2026-08-09T00:00:00Z")

        validate_error(
            api.create_inspection(
                f.inspection_payload(
                    provider_b["id"],
                    inspector["id"],
                    inspection_type="ANNUAL",
                    scheduled_for="2026-08-10T09:00:00Z",
                    target_age_groups=PRESCHOOL_ONLY,
                ),
                headers=supervisor_headers(),
            ),
            "ERR_INSPECTOR_DOUBLE_BOOKED",
            409,
        )

        fx.start_visit(api, incumbent["id"], inspector["id"])
        fx.submit_findings(
            api, incumbent["id"], inspector["id"], "PASS", PRESCHOOL_ONLY
        )
        finalized = fx.finalize_visit(api, incumbent["id"])
        assert finalized["status"] == "FINALIZED"

        replacement = validate_success(
            api.create_inspection(
                f.inspection_payload(
                    provider_b["id"],
                    inspector["id"],
                    inspection_type="ANNUAL",
                    scheduled_for="2026-08-10T09:00:00Z",
                    target_age_groups=PRESCHOOL_ONLY,
                ),
                headers=supervisor_headers(),
            ),
            201,
        )
        assert_instant(
            replacement["scheduled_for"], "2026-08-10T09:00:00Z", "scheduled_for"
        )
        assert_instant(
            replacement["visit_window_end"], "2026-08-10T11:00:00Z", "visit_window_end"
        )
        assert replacement["status"] == "SCHEDULED"
        assert replacement["provider_id"] == provider_b["id"]


class TestRatioConstantsOnAnEmptyRoom:
    """§3.2: "when no children are enrolled the required count is exactly 0"."""

    def test_an_empty_room_with_no_staff_verifies_successfully(self, api):
        """Zero enrolled children need zero adults, so all three flags hold and the
        explicit verification stamps the room instead of refusing it.

        PRD §3.2: "An infant room with 8 approved places and no children enrolled
        verifies successfully with zero staff assigned, because zero children
        require zero adults"

        Design: Corner/calculations/calc_constants_applied_empty_room_needs_zero_staff
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        director = fx.attach_staff(
            api,
            provider["id"],
            full_name="Dana Reed",
            member_type="DIRECTOR",
            date_of_birth="1985-04-02",
            qualified_age_groups=PRESCHOOL_ONLY,
            role_title="Director",
        )
        fx.clear_person(api, director["id"])
        roster = fx.add_roster(
            api,
            provider["id"],
            age_group="PRESCHOOL",
            requested_group_size=10,
            lead_staff_member_id=director["id"],
        )
        assert roster["enrolled_count"] == 0
        assert roster["staff_assigned_count"] == 0

        verified = validate_success(
            api.verify_ratio(roster["id"], headers=supervisor_headers())
        )
        assert_roster_flags(
            verified,
            ratio_compliant=True,
            group_size_compliant=True,
            supervision_compliant=True,
            required_staff_count=0,
        )
        assert_instant(
            verified["last_verified_at"], DEFAULT_LOGICAL_CLOCK, "last_verified_at"
        )
        assert verified["version"] == roster["version"] + 1


class TestCorrectionDeadlinesFollowSeverity:
    """§3.6: the allowance is keyed on the finding's severity, not its points."""

    def test_two_findings_cited_together_get_deadlines_thirty_five_days_apart(
        self, api, catalog
    ):
        """A SERIOUS and a MINOR citation stamped at the same instant differ only by
        their severity allowance, and both survive finalization as CORRECTION_PENDING.

        PRD §3.6: "That date is the citation instant plus a per-severity allowance:
        3 days for `CRITICAL`, 10 days for `SERIOUS`, 30 days for `MODERATE`, 45
        days for `MINOR`, read from the citation's effective severity."

        Design: Corner/calculations/calc_chronological_correction_deadlines_track_severity_not_points
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        serious = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_RATIO],
            primary_age_group="PRESCHOOL",
            narrative="One staff member for twelve preschoolers.",
        )
        minor = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_NUTRITION],
            primary_age_group="PRESCHOOL",
            narrative="Weekly menu not posted.",
        )
        assert_points(serious["assessed_points"], 8, "serious assessed_points")
        assert_points(minor["assessed_points"], 1, "minor assessed_points")
        assert serious["status"] == "CITED"
        assert minor["status"] == "CITED"

        fx.submit_findings(
            api, inspection["id"], inspector["id"], "CONDITIONAL_PASS", PRESCHOOL_ONLY
        )
        finalized = fx.finalize_visit(api, inspection["id"])
        assert_score(finalized["raw_deduction_points"], 9.00, "raw_deduction_points")
        assert_score(finalized["preliminary_compliance_score"], 91.00, "preliminary")
        assert finalized["violation_count"] == 2
        assert finalized["cap_required"] is True

        deadlines = (
            (serious, "SERIOUS", "2026-08-15T09:00:00Z"),
            (minor, "MINOR", "2026-09-19T09:00:00Z"),
        )
        for violation, label, expected_due in deadlines:
            after = validate_success(
                api.get_violation(violation["id"], headers=admin_headers())
            )
            assert after["status"] == "CORRECTION_PENDING", label
            assert_instant(
                after["correction_due_date"],
                expected_due,
                f"{label} correction_due_date",
            )


class TestClearanceIsAnUnstickyAggregate:
    """§3.3: "A provider's `clearance_complete` is an aggregate over *every*
    attached person"."""

    def test_attaching_and_then_clearing_one_assistant_flips_the_flag_twice(self, api):
        """The aggregate is true on the cleared director alone, false the instant an
        uncleared assistant joins, and true again once that assistant clears.

        PRD §3.3: "attaching one uncleared assistant to a provider whose director is
        perfectly cleared flips the flag to false."

        Design: Corner/calculations/calc_aggregation_clearance_flips_with_each_attached_person
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        director = fx.attach_staff(
            api,
            provider["id"],
            full_name="Dana Reed",
            member_type="DIRECTOR",
            date_of_birth="1985-04-02",
            qualified_age_groups=PRESCHOOL_ONLY,
            role_title="Director",
        )
        checks = fx.clear_person(api, director["id"])
        assert_instant(
            checks["CHILD_ABUSE_REGISTRY"]["expires_at"],
            "2031-08-01T00:00:00Z",
            "expires_at sixty months after the decision",
        )

        after_director = validate_success(
            api.get_provider(provider["id"], headers=supervisor_headers())
        )
        assert after_director["clearance_complete"] is True

        assistant = fx.attach_staff(
            api,
            provider["id"],
            full_name="Sam Ortiz",
            member_type="ASSISTANT",
            date_of_birth="1996-11-20",
            qualified_age_groups=PRESCHOOL_ONLY,
        )
        after_assistant = validate_success(
            api.get_provider(provider["id"], headers=supervisor_headers())
        )
        assert after_assistant["clearance_complete"] is False, (
            "the director is untouched, but the aggregate spans every attached person"
        )
        pending = validate_success(
            api.get_staff_member(assistant["id"], headers=admin_headers())
        )
        assert pending["clearance_status"] == "PENDING"

        fx.clear_person(api, assistant["id"])
        after_clear = validate_success(
            api.get_provider(provider["id"], headers=supervisor_headers())
        )
        assert after_clear["clearance_complete"] is True, "the reversal is not sticky"
        cleared = validate_success(
            api.get_staff_member(assistant["id"], headers=admin_headers())
        )
        assert cleared["clearance_status"] == "CLEARED"
        assert cleared["supervision_eligible"] is True, (
            "a CLEARED ASSISTANT is of a supervising member type"
        )
        assert after_clear["application_status"] == "DRAFT", (
            "clearance is independent of the application edge"
        )
