"""
Two multi-hop cascades, in opposite directions.

The first runs down the permitting chain: a re-inspection that fails revokes the
utility's blessing and unwinds everything that depended on it. The second runs down the
money and compliance chain: a second reversed payment suspends the installer and freezes
its unbuilt designs. In both, each hop exists only because the hop before it fired.
"""

from test_helpers import (
    AHJ_HEADERS,
    REBATE_ADMIN_HEADERS,
    UTILITY_REVIEWER_HEADERS,
    ApplicationStatus,
    BuildStatus,
    CertificationStatus,
    ClaimStatus,
    EnrollmentStatus,
    EventStatus,
    ExportMode,
    GridStatus,
    PerformanceStatus,
    PermitStatus,
    assert_program_ledger,
    assert_quantity,
    assert_status_pair,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)

UTILITY_PROGRAM = dict(
    total_budget_cents=2000000,
    tier1_limit_kwh=10,
    tier1_rate_cents_per_kwh=8000,
    tier2_rate_cents_per_kwh=4000,
    per_project_cap_cents=400000,
    stack_priority=2,
    max_stack_pct_of_cost_bp=4000,
    requires_export_commitment=True,
    min_capacity_commitment_kw=5.0,
)


class TestFailedReinspectionCascade:
    """A post-energization failure unwinds five coupled hops."""

    def _energized_and_dispatched(self, api):
        """A commissioned, permission-granted bank called into a scheduled event."""
        return fixtures.event_with_participation(api)

    def _fail_the_reinspection(self, api, project):
        return validate_success(
            api.record_inspection_result(
                project.permit_id,
                factories.inspection_fail_payload(
                    inspection_findings="Rapid-shutdown label missing after retrofit."
                ),
                headers=AHJ_HEADERS,
            )
        )

    def test_a_failed_reinspection_withdraws_the_utilitys_blessing(self, api):
        """The permit failure drags the application back and the grid dimension with it.

        The first three hops travel from the permit to the application to the bank: the
        application returns to supplemental review with its round counter advanced, its
        approved allowance and its permission-to-operate record cleared, and the bank's grid
        dimension falls back to the submitted stage while the build dimension does not move.

        PRD 3.4: "the second hop finds the interconnection application of the same bank whose `status` is either `APPROVED_TO_INSTALL` or `PTO_GRANTED` and returns it to `SUPPLEMENTAL_REVIEW`, incrementing its `supplemental_round_count` by one and clearing `approved_export_kw` back to null; when the application had reached `PTO_GRANTED`, both `pto_granted_by_user_id` and `pto_granted_at` are cleared to null as well, because permission to operate no longer exists"
        PRD 3.4: "Caused by the second hop, the third hop sets the bank's `grid_status` to `APPLICATION_SUBMITTED`, whichever of `APPROVED_TO_INSTALL` or `PTO_GRANTED` it held before."

        Design: Difficulty/transitive_cascade/cascade_a_failed_reinspection_revokes_pto_suspends_enrollment_cancels_performance
        """
        project = self._energized_and_dispatched(api)

        permit = self._fail_the_reinspection(api, project)

        assert permit["status"] == PermitStatus.INSPECTION_FAILED
        application = get_success_data(
            api.get_application(project.application_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert application["status"] == ApplicationStatus.SUPPLEMENTAL_REVIEW
        assert application["supplemental_round_count"] == 1
        assert_unset(
            application, "approved_export_kw", "pto_granted_by_user_id", "pto_granted_at"
        )
        system = fixtures.read_system(api, project)
        assert_status_pair(
            system, BuildStatus.COMMISSIONED, GridStatus.APPLICATION_SUBMITTED
        )

    def test_the_revoked_permission_suspends_the_enrollment_and_returns_its_capacity(
        self, api
    ):
        """The last two hops fire because the bank actually held permission to operate.

        With permission withdrawn the household's enrollment is suspended, its pending
        participation in the scheduled event is cancelled, and the event's committed-capacity
        ledger falls back to zero kilowatts — exactly what it held before the battery was
        called in. The event itself is untouched and remains schedulable.

        PRD 3.4: "In that case every BYOD enrollment of that bank whose `status` is `ENROLLED` becomes `SUSPENDED`, and for each such enrollment every dispatch participation still in `PENDING` whose event is still `SCHEDULED` becomes `CANCELLED`, with that event's `enrolled_pledged_kw` reduced by the cancelled participation's `pledged_kw_snapshot`."
        PRD 2.10: "Whenever a participation is cancelled — by a homeowner withdrawing, or by cascade A or cascade C — that participation's `pledged_kw_snapshot` is subtracted from its event's `enrolled_pledged_kw`, restoring the ledger to exactly its pre-participation value."

        Design: Difficulty/transitive_cascade/cascade_a_failed_reinspection_revokes_pto_suspends_enrollment_cancels_performance
        """
        project = self._energized_and_dispatched(api)

        self._fail_the_reinspection(api, project)

        enrollment = get_success_data(
            api.get_enrollment(project.enrollment_id, headers=project.installer_headers)
        )
        assert enrollment["status"] == EnrollmentStatus.SUSPENDED
        performance = get_success_data(
            api.get_performance(project.performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert performance["status"] == PerformanceStatus.CANCELLED
        event = get_success_data(
            api.get_dispatch_event(project.event_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(event, "enrolled_pledged_kw", 0.0)
        assert event["status"] == EventStatus.SCHEDULED


class TestSecondClawbackCascade:
    """A second reversed payment suspends the installer and freezes its designs."""

    def _one_clawback_on_record(self, api):
        """Two paid claims on one bank, the first of them already reversed."""
        project = fixtures.tests_recorded_project(api)
        state_id = fixtures.create_state_program(api, project)
        utility_id = fixtures.create_utility_program(api, project, **UTILITY_PROGRAM)

        claim_a = fixtures.reserve_claim(api, project, state_id)
        claim_b = fixtures.reserve_claim(
            api,
            project,
            utility_id,
            capacity_commitment_kw=6.0,
            export_commitment=ExportMode.FULL_EXPORT,
        )

        fixtures.pass_inspection(api, project)
        fixtures.advance_clock(api, project, fixtures.COMMISSIONING_INSTANT)
        validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )
        fixtures.grant_pto(api, project)
        fixtures.register_warranty(api, project)

        second_bank = validate_success(
            api.create_battery_system(
                factories.battery_system_payload(
                    project.site_id,
                    project.installer_id,
                    project.load_calculation_id,
                    installed_cost_cents=3100000,
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        for claim_id in (claim_a["id"], claim_b["id"]):
            fixtures.submit_claim(api, project, claim_id)
            fixtures.approve_claim(api, claim_id)
            fixtures.pay_claim(api, claim_id)

        validate_success(
            api.clawback_claim(
                claim_a["id"],
                factories.clawback_payload(
                    clawback_reason="Capacity commitment not honoured in season 1."
                ),
                headers=REBATE_ADMIN_HEADERS,
            )
        )
        return project, state_id, utility_id, claim_b["id"], second_bank["id"]

    def test_the_first_clawback_restores_the_pool_and_counts_without_suspending(self, api):
        """One reversal returns the money and raises the count, and stops there.

        The 410850 cents disbursed against the state program come back out of the disbursed
        bucket and into the unencumbered one, and the installer's reversal count rises to
        one. Because the suspension threshold is two, the certification is still active and
        the installer's second, unbuilt design is untouched.

        PRD 3.7: "The first hop moves the claim `PAID → CLAWED_BACK`, records the supplied `clawback_reason`, and moves exactly `final_amount_cents` out of `paid_budget_cents` and back into `remaining_budget_cents`."
        PRD 3.7: "A first clawback therefore has hops one and two only; the second clawback against the same installer trips the suspension and the design hold."

        Design: Difficulty/transitive_cascade/cascade_d_second_clawback_suspends_certification_and_holds_pending_designs
        """
        project, state_id, _, _, second_bank_id = self._one_clawback_on_record(api)

        state = fixtures.read_program(api, state_id)
        assert_program_ledger(state, remaining=5000000, reserved=0, paid=0)
        installer = get_success_data(
            api.get_installer(project.installer_id, headers=project.installer_headers)
        )
        assert installer["clawback_count"] == 1
        assert installer["certification_status"] == CertificationStatus.ACTIVE
        second_bank = get_success_data(
            api.get_battery_system(second_bank_id, headers=project.installer_headers)
        )
        assert second_bank["build_status"] == BuildStatus.DESIGN_DRAFT

    def test_the_second_clawback_suspends_the_certification_and_holds_pending_designs(
        self, api
    ):
        """The threshold reversal propagates from the pool to the installer to its designs.

        The utility program's 142600 cents return to the unencumbered bucket, the reversal
        count reaches the threshold of two, the certification is suspended, and the still-
        unbuilt second design is frozen. The commissioned bank is deliberately left alone.

        PRD 3.7: "Caused by the count reaching the threshold, the third hop fires when that installer's `clawback_count` is 2 or more, setting its `certification_status` to `SUSPENDED`. Caused by the suspension, the fourth hop walks every bank belonging to that installer whose `build_status` is `DESIGN_DRAFT` or `DESIGN_LOCKED`, in ascending `created_at`, and moves each to `DESIGN_HOLD`."
        PRD 3.3: "Banks already at `INSTALLED` or `COMMISSIONED` are left alone."

        Design: Difficulty/transitive_cascade/cascade_d_second_clawback_suspends_certification_and_holds_pending_designs
        """
        project, _, utility_id, claim_b_id, second_bank_id = self._one_clawback_on_record(
            api
        )

        reversed_claim = validate_success(
            api.clawback_claim(
                claim_b_id,
                factories.clawback_payload(
                    clawback_reason="Export commitment breached."
                ),
                headers=REBATE_ADMIN_HEADERS,
            )
        )

        assert reversed_claim["status"] == ClaimStatus.CLAWED_BACK
        utility = fixtures.read_program(api, utility_id)
        assert_program_ledger(utility, remaining=2000000, reserved=0, paid=0)
        installer = get_success_data(
            api.get_installer(project.installer_id, headers=project.installer_headers)
        )
        assert installer["clawback_count"] == 2
        assert installer["certification_status"] == CertificationStatus.SUSPENDED
        second_bank = get_success_data(
            api.get_battery_system(second_bank_id, headers=project.installer_headers)
        )
        assert second_bank["build_status"] == BuildStatus.DESIGN_HOLD
        commissioned = fixtures.read_system(api, project)
        assert commissioned["build_status"] == BuildStatus.COMMISSIONED
