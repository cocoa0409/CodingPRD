"""
Writes whose legality is decided by the state of a different row: a case
transition gated on two sibling assessment records, and an authorization gated
on the grandparent plan two hops above the line it names.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_case_weight,
    assert_unit_pool,
    add_service_line,
    build_active_services,
    build_assessments_completed,
    complete_assessment,
    create_provider,
    factories,
    read_assessment,
    read_ifsp,
    read_referral,
    read_service_line,
    record_consent,
    validate_error,
    validate_success,
)

DETERMINATION_DATE = "2026-03-20"


def _build_case_with_one_completed_assessment(api):
    """A case whose evaluation is completed while its family assessment is still
    on the calendar."""
    return build_assessments_completed(api, complete_family_assessment=False)


def _attempt_determination(api, referral_id):
    return api.record_eligibility_determination(
        referral_id,
        factories.eligibility_determination_payload(
            is_eligible=True, determination_date=DETERMINATION_DATE
        ),
        ADMIN_HEADERS,
    )


class TestDeterminationGatedOnBothAssessmentTypes:
    """One completed evaluation is not two completed assessment types."""

    def test_missing_family_assessment_blocks_the_determination(self, api):
        """
        With the evaluation completed but the family assessment still scheduled,
        the determination is refused and the case is left untouched, version
        included.

        PRD 3.4: "The case must have at least one `COMPLETED` assessment of type
        `INITIAL_EVALUATION` **and** at least one `COMPLETED` assessment of type
        `FAMILY_ASSESSMENT` — a case with only one of the two, or with both still
        merely scheduled, is refused with `ERR_REQUIRED_ASSESSMENTS_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/eligibility_determination_requires_both_completed_assessment_types
        """
        case = _build_case_with_one_completed_assessment(api)
        before = read_referral(api, case.referral_id)
        assert read_assessment(api, case.eval_id)["status"] == "COMPLETED"
        assert read_assessment(api, case.fam_id)["status"] == "SCHEDULED"

        response = _attempt_determination(api, case.referral_id)
        validate_error(response, ApiErrorId.REQUIRED_ASSESSMENTS_INCOMPLETE.value, 422)

        after = read_referral(api, case.referral_id)
        assert after["status"] == "EVALUATION_PENDING"
        assert after["eligibility_status"] == "PENDING"
        assert after["eligibility_determination_date"] is None
        # A refused write is a true no-op, so the concurrency token is unmoved.
        assert after["version"] == before["version"]

    def test_completing_the_second_type_admits_the_same_request(self, api):
        """
        Completing the family assessment satisfies the sibling precondition and
        the identical determination then succeeds.

        PRD 3.4: "When `is_eligible` is true the case moves `EVALUATION_PENDING →
        ELIGIBILITY_DETERMINED`. Its `eligibility_status` becomes `ELIGIBLE`, its
        `eligibility_determination_date` records the supplied date, and the
        statutory counters — `excluded_delay_days`, `gross_elapsed_days`,
        `net_elapsed_days` and `initial_timeline_status` — are recomputed."

        Design: Difficulty/cross_entity_state_dependency/eligibility_determination_requires_both_completed_assessment_types
        """
        case = _build_case_with_one_completed_assessment(api)
        _attempt_determination(api, case.referral_id)

        completed = complete_assessment(
            api,
            case.fam_id,
            completion_date="2026-03-19",
            family_unavailable_days=0,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completion_date"] == "2026-03-19"

        determined = validate_success(
            _attempt_determination(api, case.referral_id), 200
        )
        assert determined["status"] == "ELIGIBILITY_DETERMINED"
        assert determined["eligibility_status"] == "ELIGIBLE"
        assert determined["eligibility_determination_date"] == DETERMINATION_DATE

        # Neither assessment carried an excused day, so the statutory counts move
        # together and the clock is still running.
        stored = read_referral(api, case.referral_id)
        assert stored["excluded_delay_days"] == 0
        assert stored["gross_elapsed_days"] == 18
        assert stored["net_elapsed_days"] == 18
        assert stored["initial_timeline_status"] == "IN_PROGRESS"
        assert read_assessment(api, case.eval_id)["status"] == "COMPLETED"


# ─── The plan two hops above the line ─────────────────────────────────

SECOND_LINE = {
    "service_type": "PHYSICAL_THERAPY",
    "setting_code": "HOME",
    "frequency_per_month": 2,
    "units_per_session": 2,
    "unit_rate_cents": 7000,
    "planned_units_total": 48,
}
AUTHORIZATION_REQUEST = {
    "start_date": "2026-03-21",
    "end_date": "2026-04-30",
    "authorized_units": 24,
}


def _build_amending_plan_case(api):
    """A live case whose plan has just gained a second line and so sits in the
    amendment cycle, with a provider ready for either line."""
    case = build_active_services(api)
    case.provider_id = create_provider(
        api,
        agency_name="Riverbend Pediatric Therapies",
        qualified_service_types=["SPEECH_THERAPY", "PHYSICAL_THERAPY"],
        credential_expiry_date="2027-06-30",
    )
    case.provider_ids.append(case.provider_id)
    second_line_id = add_service_line(api, case.ifsp_id, **SECOND_LINE)
    case.line_ids.append(second_line_id)
    return case, second_line_id


def _attempt_authorization(api, line_id, provider_id):
    return api.create_authorization(
        factories.authorization_payload(line_id, provider_id, **AUTHORIZATION_REQUEST),
        ADMIN_HEADERS,
    )


class TestAuthorizationGatedOnTheAmendingPlan:
    """A perfectly valid line cannot be authorized while its plan is amending."""

    def test_amendment_pending_plan_blocks_authorization_of_a_valid_line(self, api):
        """
        Adding a second line puts the plan into the amendment cycle, and while it
        is there no line of that plan may be authorized, however healthy the line
        itself is.

        PRD 3.5: "A line added to a plan already in `ACTIVE` moves it `ACTIVE →
        AMENDMENT_PENDING`, and while a plan sits in `AMENDMENT_PENDING` **no new
        provider authorization may be created for any of its lines** until the
        family has re-consented and the plan has returned to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/authorization_create_blocked_by_ifsp_amendment_pending
        """
        case, _second_line_id = _build_amending_plan_case(api)

        plan = read_ifsp(api, case.ifsp_id)
        assert plan["status"] == "AMENDMENT_PENDING"
        assert plan["service_line_count"] == 2

        response = _attempt_authorization(api, case.line_id, case.provider_id)
        validate_error(response, ApiErrorId.IFSP_STATE_INVALID.value, 409)

        line = read_service_line(api, case.line_id)
        assert line["status"] == "PLANNED"
        assert_unit_pool(
            line, units_committed=0, units_pool_remaining=96, planned_units_total=96
        )

    def test_re_consent_closes_the_cycle_and_the_units_commit(self, api):
        """
        Re-consent returns the plan to ACTIVE and the identical authorization is
        then accepted, moving the named line's units out of its pool while the
        sibling line stays untouched.

        PRD 3.5: "Consent advances the plan `PENDING_CONSENT → ACTIVE` or,
        closing the amendment cycle, `AMENDMENT_PENDING → ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/authorization_create_blocked_by_ifsp_amendment_pending
        """
        case, second_line_id = _build_amending_plan_case(api)
        _attempt_authorization(api, case.line_id, case.provider_id)

        reactivated = record_consent(
            api, case.ifsp_id, case.child_id, consent_signed_date="2026-03-20"
        )
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["activated_date"] == "2026-03-20"
        assert reactivated["service_line_count"] == 2

        authorization = validate_success(
            _attempt_authorization(api, case.line_id, case.provider_id), 201
        )
        assert authorization["status"] == "ACTIVE"
        assert authorization["authorized_units"] == 24
        # The rate is copied from the line, not from the request.
        assert authorization["unit_rate_cents"] == 6_500

        authorized_line = read_service_line(api, case.line_id)
        assert authorized_line["status"] == "AUTHORIZED"
        assert_unit_pool(
            authorized_line,
            units_committed=24,
            units_pool_remaining=72,
            planned_units_total=96,
        )

        sibling = read_service_line(api, second_line_id)
        assert sibling["status"] == "PLANNED"
        assert_unit_pool(
            sibling, units_committed=0, units_pool_remaining=48, planned_units_total=48
        )

        assert_case_weight(
            read_referral(api, case.referral_id)["case_weight_points"], 1.00
        )
