"""
Edges taken and edges refused. Every row starts in its declared initial state;
each declared transition applies the whole of its side-effect set; replaying a
trigger from a state that has no such outgoing edge is an error rather than a
no-op; and two terminal states accept nothing further at all.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    EVALUATOR_HEADERS,
    EVALUATOR_USER_ID,
    FISCAL_HEADERS,
    add_service_line,
    assert_authorization_units,
    assert_caseload_summary,
    assert_case_weight,
    assert_cents,
    assert_fpl_percent,
    assert_ledger,
    assert_unit_pool,
    assign_coordinator,
    author_ifsp,
    build_assessments_completed,
    build_authorized,
    build_cost_share_case,
    build_ifsp_pending,
    build_intake,
    build_plan_with_line,
    build_visit_delivered,
    create_coordinator,
    create_cost_share,
    create_provider,
    factories,
    read_assessment,
    read_authorization,
    read_caseload_summary,
    read_child,
    read_coordinator,
    read_cost_share,
    read_ifsp,
    read_provider,
    read_referral,
    read_service_line,
    read_visit,
    record_consent,
    schedule_assessment,
    schedule_visit,
    set_clock,
    validate_error,
    validate_success,
)

DETERMINATION_DATE = "2026-03-20"


class TestDeclaredInitialStates:
    """A fresh row sits where the contract says, not where the data hints."""

    def test_a_case_opens_in_intake_and_an_assessment_opens_scheduled(self, api):
        """
        A case sits in INTAKE even though an eligible coordinator already exists,
        and evaluation work sits SCHEDULED even when the date it was booked for
        has already passed on the logical clock.

        PRD 3.3: "A new record is created with `status` `SCHEDULED`, and the acting
        evaluator's identifier is captured as `evaluator_user_id`."

        Design: Corner/state_machines/referral_and_assessment_start_in_declared_initial_states
        """
        case = build_intake(api)

        opened = read_referral(api, case.referral_id)
        assert opened["status"] == "INTAKE"
        assert opened["version"] == 1

        assigned = assign_coordinator(api, case.referral_id, case.coordinator_id)
        assert assigned["status"] == "EVALUATION_PENDING"

        booked = validate_success(
            api.create_assessment(
                factories.assessment_payload(
                    case.referral_id,
                    assessment_type="INITIAL_EVALUATION",
                    scheduled_date="2026-03-01",
                ),
                EVALUATOR_HEADERS,
            ),
            201,
        )
        assert booked["status"] == "SCHEDULED"
        assert booked["completion_date"] is None
        assert booked["eligibility_recommendation"] is None
        assert booked["family_unavailable_days"] == 0
        assert booked["evaluator_user_id"] == EVALUATOR_USER_ID


class TestAssignmentTransition:
    """One edge, four declared side effects, exactly one version bump."""

    def test_assignment_stores_the_owner_weighs_the_case_and_loads_the_roster(
        self, api
    ):
        """
        Assignment moves the case, records who owns it and when, scores the case at
        the pre-plan base, and reports the coordinator's three aggregates against a
        twelve-point ceiling.

        PRD 3.2: "Either way the case's `coordinator_id` and its `assignment_date` —
        the logical clock date on which assignment happened — are stored, the case's
        `case_weight_points` is computed, the chosen coordinator's three aggregates
        are recomputed, and `Referral.version` is incremented by 1."

        Design: Corner/state_machines/assign_coordinator_transition_applies_every_declared_side_effect
        """
        case = build_intake(api)

        assigned = assign_coordinator(api, case.referral_id, case.coordinator_id)
        assert assigned["status"] == "EVALUATION_PENDING"
        assert assigned["coordinator_id"] == case.coordinator_id
        assert assigned["assignment_date"] == "2026-03-02"
        assert_case_weight(assigned["case_weight_points"], 1.50)
        assert assigned["version"] == 2

        assert_caseload_summary(
            read_caseload_summary(api, case.coordinator_id),
            coordinator_id=case.coordinator_id,
            active_case_count=1,
            weighted_caseload_points=1.50,
            max_weighted_caseload_points=12.00,
            utilization_ratio=0.1250,
            caseload_posture="OPEN",
            headroom_points=10.50,
        )

    def test_a_second_assignment_is_refused_and_never_double_counts(self, api):
        """
        The same trigger replayed from EVALUATION_PENDING is refused, and so is a
        re-assignment to a different coordinator: the case keeps its owner, its
        version is unmoved, and neither roster shifts.

        PRD 3.2: "Assignment is refused with `ERR_REFERRAL_STATE_INVALID` unless the
        case is in `INTAKE`."

        Design: Corner/state_machines/assign_coordinator_second_attempt_returns_referral_state_invalid
        """
        case = build_intake(api)
        rival_id = create_coordinator(api, full_name="Ivo Marek")
        assign_coordinator(api, case.referral_id, case.coordinator_id)

        for target_id in (case.coordinator_id, rival_id):
            validate_error(
                api.assign_coordinator(
                    case.referral_id,
                    factories.assign_coordinator_payload(coordinator_id=target_id),
                    ADMIN_HEADERS,
                ),
                ApiErrorId.REFERRAL_STATE_INVALID.value,
                409,
            )

        referral = read_referral(api, case.referral_id)
        assert referral["coordinator_id"] == case.coordinator_id
        assert referral["version"] == 2

        owner = read_coordinator(api, case.coordinator_id)
        assert_case_weight(owner["weighted_caseload_points"], 1.50)
        assert owner["active_case_count"] == 1

        rival = read_coordinator(api, rival_id)
        assert_case_weight(rival["weighted_caseload_points"], 0)
        assert rival["active_case_count"] == 0


# ─── The NOT_ELIGIBLE fork and the lockdown that follows ──────────────

SUPPLEMENTAL = {
    "assessment_type": "SUPPLEMENTAL_EVALUATION",
    "scheduled_date": "2026-03-27",
    "setting_code": "HOME",
}


def _build_case_ready_for_a_negative_determination(api):
    """Both required assessments completed with a negative recommendation, and a
    third record still on the calendar."""
    return build_assessments_completed(
        api,
        evaluation_completion={"eligibility_recommendation": "NOT_ELIGIBLE"},
        family_completion={"eligibility_recommendation": "NOT_ELIGIBLE"},
    )


def _determine(api, referral_id, is_eligible):
    return api.record_eligibility_determination(
        referral_id,
        factories.eligibility_determination_payload(
            is_eligible=is_eligible, determination_date=DETERMINATION_DATE
        ),
        ADMIN_HEADERS,
    )


class TestNegativeDeterminationBranch:
    """The ineligible fork cascades down to non-terminal children only."""

    def test_ineligibility_cancels_only_the_open_assessment_and_empties_the_roster(
        self, api
    ):
        """
        A negative determination cancels the assessment still on the calendar,
        leaves the two completed records alone, zeroes the case weight, and drops
        both the coordinator's aggregates and the child's open-case count to zero.

        PRD 3.4: "Beyond that: every assessment on the case still in `SCHEDULED`
        transitions to `CANCELLED`, and a cancelled record is frozen — it can never
        be completed and never contributes `family_unavailable_days` to the excluded
        total."

        Design: Corner/state_machines/not_eligible_branch_cancels_scheduled_assessments_and_zeroes_weight
        """
        case = _build_case_ready_for_a_negative_determination(api)
        supplemental_id = schedule_assessment(api, case.referral_id, **SUPPLEMENTAL)
        version_before = read_referral(api, case.referral_id)["version"]

        determined = validate_success(_determine(api, case.referral_id, False), 200)
        assert determined["status"] == "NOT_ELIGIBLE"
        assert determined["eligibility_status"] == "NOT_ELIGIBLE"
        assert determined["eligibility_determination_date"] == DETERMINATION_DATE
        assert_case_weight(determined["case_weight_points"], 0)
        assert determined["version"] == version_before + 1

        assert read_assessment(api, supplemental_id)["status"] == "CANCELLED"
        assert read_assessment(api, case.eval_id)["status"] == "COMPLETED"
        assert read_assessment(api, case.fam_id)["status"] == "COMPLETED"

        coordinator = read_coordinator(api, case.coordinator_id)
        assert_case_weight(coordinator["weighted_caseload_points"], 0)
        assert coordinator["active_case_count"] == 0
        assert coordinator["utilization_ratio"] == 0

        assert read_child(api, case.child_id)["active_referral_count"] == 0


class TestTerminalCaseStatus:
    """Once ineligible, every door is shut regardless of who knocks."""

    def test_no_role_can_write_to_an_ineligible_case(self, api):
        """
        Entry outcomes, exit, a fiscal determination and even a reversing
        eligibility call are all refused with the same conflict from three
        different roles, and the case is left exactly as the determination left it.

        PRD 3.9: "`NOT_ELIGIBLE` and `EXITED` are the two terminal case statuses,
        and neither accepts any further write."

        Design: Corner/state_machines/not_eligible_terminal_state_refuses_every_further_operation
        """
        case = _build_case_ready_for_a_negative_determination(api)
        validate_success(_determine(api, case.referral_id, False), 200)
        version_before = read_referral(api, case.referral_id)["version"]

        refusals = (
            api.record_entry_outcomes(
                case.referral_id,
                factories.entry_outcomes_payload(measurement_date=DETERMINATION_DATE),
                EVALUATOR_HEADERS,
            ),
            api.exit_referral(
                case.referral_id,
                factories.exit_payload(
                    DETERMINATION_DATE, exit_reason="NO_LONGER_ELIGIBLE"
                ),
                case.coordinator_headers,
            ),
            api.create_cost_share(
                factories.cost_share_payload(case.referral_id), FISCAL_HEADERS
            ),
            _determine(api, case.referral_id, True),
        )
        for response in refusals:
            validate_error(
                response, ApiErrorId.REFERRAL_STATE_INVALID.value, 409
            )

        referral = read_referral(api, case.referral_id)
        assert referral["status"] == "NOT_ELIGIBLE"
        assert referral["eligibility_status"] == "NOT_ELIGIBLE"
        assert referral["entry_rating_social"] is None
        assert referral["version"] == version_before


# ─── Plan consent: edges that exist, and edges that do not ────────────

PROVIDER = {
    "agency_name": "Riverbend Therapy",
    "qualified_service_types": ["SPEECH_THERAPY"],
    "credential_expiry_date": "2027-06-30",
}
CONSENT_DATE = "2026-03-20"
SECOND_LINE = {
    "service_type": "PHYSICAL_THERAPY",
    "setting_code": "HOME",
    "frequency_per_month": 2,
    "units_per_session": 2,
    "unit_rate_cents": 7000,
    "planned_units_total": 48,
}


class TestConsentAndAuthorizationSourceStates:
    """Each trigger is fired once from a state without that edge, then from one
    that has it."""

    def test_draft_plan_refuses_consent_and_pending_consent_refuses_funding(self, api):
        """
        Consent against a plan with no service line yet is refused because the plan
        never left DRAFT; adding a line moves it to PENDING_CONSENT, from where
        funding is still refused; consent then succeeds and the line is left
        unfunded.

        PRD 3.5: "The plan must be in `PENDING_CONSENT` or `AMENDMENT_PENDING`, or
        the request is refused with `ERR_IFSP_STATE_INVALID`."

        Design: Corner/state_machines/consent_and_authorization_refused_from_states_without_that_edge
        """
        case = build_ifsp_pending(api)
        case.ifsp_id = author_ifsp(api, case.referral_id, case.coordinator_id)
        provider_id = create_provider(api, **PROVIDER)

        too_early = api.record_consent(
            case.ifsp_id,
            factories.consent_payload(consent_signed_date=CONSENT_DATE),
            case.family_headers,
        )
        validate_error(too_early, ApiErrorId.IFSP_STATE_INVALID.value, 409)
        assert read_ifsp(api, case.ifsp_id)["status"] == "DRAFT"

        case.line_id = add_service_line(api, case.ifsp_id)
        awaiting = read_ifsp(api, case.ifsp_id)
        assert awaiting["status"] == "PENDING_CONSENT"
        assert awaiting["service_line_count"] == 1

        unfunded = api.create_authorization(
            factories.authorization_payload(case.line_id, provider_id),
            ADMIN_HEADERS,
        )
        validate_error(unfunded, ApiErrorId.IFSP_STATE_INVALID.value, 409)

        consented = record_consent(
            api, case.ifsp_id, case.child_id, consent_signed_date=CONSENT_DATE
        )
        assert consented["status"] == "ACTIVE"

        line = read_service_line(api, case.line_id)
        assert line["status"] == "PLANNED"
        assert_unit_pool(
            line, units_committed=0, units_pool_remaining=96, planned_units_total=96
        )


class TestPartialConsent:
    """Naming one line of two declines exactly that line."""

    def test_the_declined_line_is_discontinued_and_the_other_survives(self, api):
        """
        A partial consent activates the plan, discontinues only the line the family
        named, drops the plan's line count to one, and starts services on the case
        at the post-plan weight.

        PRD 3.5: "Each line named in `declined_service_ids` has `declined_by_family`
        set to true and transitions to `DISCONTINUED`, after which the plan's
        `service_line_count` and `non_natural_setting_line_count` are recomputed."

        Design: Corner/state_machines/partial_consent_discontinues_only_the_declined_line
        """
        case = build_plan_with_line(api)
        second_line_id = add_service_line(api, case.ifsp_id, **SECOND_LINE)
        case.line_ids.append(second_line_id)

        consented = record_consent(
            api,
            case.ifsp_id,
            case.child_id,
            consent_scope="PARTIAL",
            consent_signed_date=CONSENT_DATE,
            declined_service_ids=[second_line_id],
        )
        assert consented["status"] == "ACTIVE"
        assert consented["consent_scope"] == "PARTIAL"
        assert consented["consent_signed_date"] == CONSENT_DATE
        assert consented["consent_user_id"] == case.child_id
        assert consented["service_line_count"] == 1
        assert consented["non_natural_setting_line_count"] == 0

        declined = read_service_line(api, second_line_id)
        assert declined["status"] == "DISCONTINUED"
        assert declined["declined_by_family"] is True

        kept = read_service_line(api, case.line_id)
        assert kept["status"] == "PLANNED"
        assert kept["declined_by_family"] is False

        referral = read_referral(api, case.referral_id)
        assert referral["status"] == "ACTIVE_SERVICES"
        assert referral["services_start_date"] == CONSENT_DATE
        assert_case_weight(referral["case_weight_points"], 1.00)

        assert_caseload_summary(
            read_caseload_summary(api, case.coordinator_id),
            coordinator_id=case.coordinator_id,
            active_case_count=1,
            weighted_caseload_points=1.00,
            utilization_ratio=0.0833,
            caseload_posture="OPEN",
            headroom_points=11.00,
        )


# ─── The provider's two branches, and the one reverse edge ────────────

TERMINATION_CLOCK = "2026-03-24T12:00:00Z"
EFFECTIVE_DATE = "2026-03-24"
FUTURE_SESSION = ("2026-03-26T15:00:00Z", "2026-03-26T15:30:00Z")


def _suspend(api, provider_id, reason_code):
    return api.suspend_provider(
        provider_id,
        factories.suspend_provider_payload(
            suspension_reason_code=reason_code, effective_date=EFFECTIVE_DATE
        ),
        ADMIN_HEADERS,
    )


class TestProviderTerminationBranch:
    """CONTRACT_ENDED picks the sibling branch that hands the units back."""

    def test_termination_revokes_the_authorization_and_releases_the_whole_pool(
        self, api
    ):
        """
        Ending the contract terminates the provider rather than suspending it, so
        the authorization is revoked with every unit released and the line's pool
        comes back whole; the cancelled session leaves a two-unit makeup obligation,
        which is under the at-risk threshold, and a second removal attempt is
        refused because TERMINATED accepts no such trigger.

        PRD 3.6: "On the termination branch, those same authorizations transition to
        `REVOKED` instead, each with `units_released` set to its `units_remaining`
        and `revocation_reason_code` recorded as `PROVIDER_TERMINATED`, so the units
        flow back to their lines' pools and the affected lines have
        `units_committed` and `units_pool_remaining` recomputed."

        Design: Corner/state_machines/provider_termination_branch_revokes_and_releases_where_suspension_would_hold
        """
        case = build_authorized(api, provider=PROVIDER)
        case.visit_id = schedule_visit(api, case.authorization_id, *FUTURE_SESSION)
        case.visit_ids.append(case.visit_id)
        set_clock(api, TERMINATION_CLOCK)

        terminated = validate_success(
            _suspend(api, case.provider_id, "CONTRACT_ENDED"), 200
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["suspension_reason_code"] == "CONTRACT_ENDED"
        assert terminated["suspended_date"] == EFFECTIVE_DATE

        authorization = read_authorization(api, case.authorization_id)
        assert authorization["status"] == "REVOKED"
        assert_authorization_units(
            authorization, units_released=24, units_remaining=0
        )
        assert authorization["revocation_reason_code"] == "PROVIDER_TERMINATED"

        visit = read_visit(api, case.visit_id)
        assert visit["visit_status"] == "CANCELLED_PROVIDER"
        assert visit["billing_status"] == "CANCELLED_NO_CHARGE"
        assert visit["actual_units"] == 0

        line = read_service_line(api, case.line_id)
        assert_unit_pool(
            line, units_committed=0, units_pool_remaining=96, planned_units_total=96
        )
        assert line["makeup_owed_units"] == 2
        assert line["status"] == "AUTHORIZED"

        assert read_referral(api, case.referral_id)["service_gap_flag"] is False

        validate_error(
            _suspend(api, case.provider_id, "QUALITY_CONCERN"),
            ApiErrorId.PROVIDER_NOT_ACTIVE.value,
            409,
        )
        assert read_provider(api, case.provider_id)["status"] == "TERMINATED"


def _build_exhausted_authorization_case(api):
    """An authorization funded for exactly the two units a single session spends,
    with no determination on file for the session's month."""
    return build_visit_delivered(
        api, provider=PROVIDER, authorization={"authorized_units": 2}
    )


class TestVoidReturnsAnExhaustedAuthorization:
    """The only reverse edge in the authorization machine."""

    def test_voiding_the_exhausting_session_returns_the_row_to_active(self, api):
        """
        The session that consumed the last unit leaves the authorization exhausted;
        voiding that session hands the units back and returns the row to ACTIVE.

        PRD 3.7: "An authorization sitting in `EXHAUSTED` returns `EXHAUSTED →
        ACTIVE`, provided the voided session had actually delivered more than 0
        units and the authorization's window has not already ended relative to the
        logical clock date."

        Design: Corner/state_machines/exhausted_authorization_returns_to_active_when_the_visit_is_voided
        """
        case = _build_exhausted_authorization_case(api)

        spent = read_authorization(api, case.authorization_id)
        assert spent["status"] == "EXHAUSTED"
        assert_authorization_units(
            spent, units_consumed=2, units_released=0, units_remaining=0
        )

        voided = validate_success(
            api.void_visit(
                case.visit_id, factories.void_visit_payload(), ADMIN_HEADERS
            ),
            200,
        )
        assert voided["visit_status"] == "VOIDED"
        assert voided["void_reason_code"] == "DOCUMENTATION_ERROR"

        restored = read_authorization(api, case.authorization_id)
        assert restored["status"] == "ACTIVE"
        assert_authorization_units(
            restored, units_consumed=0, units_released=0, units_remaining=2
        )

    def test_the_line_keeps_its_state_while_the_fiscal_axis_reverses(self, api):
        """
        The same void walks the line's delivered count back without walking its
        status back, and the fiscal dimension moves off an exempt session with no
        money to unwind.

        PRD 3.7: "Reversing from `EXEMPT` or from `CAPPED` moves only the unit
        counters, because in both of those cases `family_share_cents` was 0 and no
        cost-share money field ever changed."

        Design: Corner/state_machines/exhausted_authorization_returns_to_active_when_the_visit_is_voided
        """
        case = _build_exhausted_authorization_case(api)
        assert read_visit(api, case.visit_id)["billing_status"] == "EXEMPT"

        voided = validate_success(
            api.void_visit(
                case.visit_id, factories.void_visit_payload(), ADMIN_HEADERS
            ),
            200,
        )
        assert voided["billing_status"] == "REVERSED"
        assert_cents(voided["family_share_cents"], 0, "family_share_cents")

        line = read_service_line(api, case.line_id)
        assert line["units_delivered"] == 0
        assert line["status"] == "IN_DELIVERY"
        assert_unit_pool(
            line, units_committed=2, units_pool_remaining=94, planned_units_total=96
        )


# ─── Three edges of the fiscal machine, three different actors ────────

APRIL_CLOCK = "2026-04-05T09:00:00Z"
VERIFICATION_DATE = "2026-04-05"
VERIFIED_INCOME_CENTS = 19_470_000
EXIT_RATINGS = {
    "exit_rating_social": 2,
    "exit_rating_knowledge": 5,
    "exit_rating_needs": 6,
}


class TestCostShareLifecycle:
    """A later month supersedes, verification re-prices, exit closes."""

    def test_a_later_month_supersedes_the_earlier_determination(self, api):
        """
        Creating a determination for April sets the March row aside by system
        action, and the new row opens provisional at the declared-income tier.

        PRD 3.8: "Any determination on the case in `PROVISIONAL` or `VERIFIED` whose
        `effective_month` is strictly earlier than the new row's transitions to
        `SUPERSEDED`; it stops being selected for new sessions, but the balances
        already accrued against it stay exactly where they are and are never
        migrated."

        Design: Corner/state_machines/cost_share_supersede_verify_and_close_lifecycle
        """
        case = build_cost_share_case(api)
        set_clock(api, APRIL_CLOCK)

        april = validate_success(
            api.create_cost_share(
                factories.cost_share_payload(
                    case.referral_id, effective_month="2026-04"
                ),
                FISCAL_HEADERS,
            ),
            201,
        )
        assert april["status"] == "PROVISIONAL"
        assert april["tier_code"] == "TIER_1"
        assert_fpl_percent(april["fpl_percent"], 369.8)
        assert_cents(
            april["assessed_monthly_fee_cents"], 2_600, "assessed_monthly_fee_cents"
        )

        assert read_cost_share(api, case.cost_share_id)["status"] == "SUPERSEDED"

    def test_finalization_verifies_the_row_and_exit_closes_it(self, api):
        """
        Verified income re-runs the scale in its final variant and moves the row to
        VERIFIED; the case exit then closes it while the row already superseded is
        left alone, and with no session accrued the closure moves no money.

        PRD 3.9: "Every cost-share determination on the case in `PROVISIONAL` or
        `VERIFIED` transitions to `CLOSED`."

        Design: Corner/state_machines/cost_share_supersede_verify_and_close_lifecycle
        """
        case = build_cost_share_case(api)
        set_clock(api, APRIL_CLOCK)
        april_id = create_cost_share(api, case.referral_id, effective_month="2026-04")

        verified = validate_success(
            api.finalize_cost_share(
                april_id,
                factories.finalize_cost_share_payload(
                    verified_annual_gross_income_cents=VERIFIED_INCOME_CENTS,
                    verification_date=VERIFICATION_DATE,
                ),
                FISCAL_HEADERS,
            ),
            200,
        )
        assert verified["status"] == "VERIFIED"
        assert_fpl_percent(verified["fpl_percent"], 600.0)
        assert verified["tier_code"] == "TIER_2"
        assert float(verified["effective_coinsurance_rate"]) == pytest.approx(
            0.10, abs=0.001
        )
        assert_cents(verified["monthly_cap_cents"], 30_000, "monthly_cap_cents")
        assert_cents(
            verified["final_monthly_fee_cents"], 5_200, "final_monthly_fee_cents"
        )
        assert_cents(
            verified["insurance_offset_cents"], 0, "insurance_offset_cents"
        )

        exited = validate_success(
            api.exit_referral(
                case.referral_id,
                factories.exit_payload(
                    VERIFICATION_DATE, exit_reason="FAMILY_WITHDREW", **EXIT_RATINGS
                ),
                case.coordinator_headers,
            ),
            200,
        )
        assert exited["status"] == "EXITED"

        closed = read_cost_share(api, april_id)
        assert closed["status"] == "CLOSED"
        assert_ledger(
            closed,
            total_assessed_cents=0,
            family_balance_cents=0,
            family_waived_cents=0,
        )
        assert read_cost_share(api, case.cost_share_id)["status"] == "SUPERSEDED"
