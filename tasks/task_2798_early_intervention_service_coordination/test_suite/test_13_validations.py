"""
Layered validation rules: age and duplicate guards at the front door, the
five-domain rule for initial evaluations, date discipline, the natural-environment
justification, exit prerequisites, the authorization guard ladder, visit timing,
insurance offsets, and the transition window.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ALL_DOMAINS,
    EVALUATOR_HEADERS,
    FISCAL_HEADERS,
    FISCAL_OFFICER_USER_ID,
    INTAKE_CLOCK,
    INTAKE_HEADERS,
    POST_EVALUATION_CLOCK,
    ApiErrorId,
    assert_authorization_units,
    assert_cents,
    assert_fpl_percent,
    assert_ledger,
    assert_unit_pool,
    build_active_services,
    build_assigned,
    build_authorized,
    build_cost_share_case,
    build_intake,
    build_plan_with_line,
    create_child,
    create_provider,
    factories,
    read_assessment,
    read_authorization,
    read_child,
    read_cost_share,
    read_ifsp,
    read_referral,
    read_service_line,
    read_transition_plan,
    read_visit,
    schedule_assessment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

RECEIVED_DATE = "2026-03-02"
STATUTORY_DEADLINE = "2026-04-16"

AT_THIRD_BIRTHDAY_CHILD = {
    "first_name": "Ines",
    "last_name": "Marek",
    "date_of_birth": "2023-03-02",
}
A_DAY_YOUNGER_CHILD = {
    "first_name": "Bram",
    "last_name": "Marek",
    "date_of_birth": "2023-03-03",
}


# ─── The front-door guards ────────────────────────────────────────────

class TestChildAgeEligibility:

    def test_third_birthday_on_the_received_date_is_ineligible(self, api):
        """
        A child who reaches three on the received date cannot be referred, while
        a child one day younger opens a case with a 45-day statutory deadline.

        PRD 3.1: "First, the program serves children under three: the child's
        `third_birthday_date` must fall strictly after `referral_received_date`,
        and a referral for a child who has already reached the third birthday on
        the received date is rejected with `ERR_CHILD_AGE_INELIGIBLE`."
        PRD 3.1: "On creation the server computes `statutory_deadline_date` as
        that date plus 45 calendar days, sets `status` to `INTAKE`, sets
        `eligibility_status` to `PENDING`, sets `initial_timeline_status` to
        `IN_PROGRESS`, and recomputes the child's `active_referral_count`."

        Design: Corner/validations/child_age_eligibility_is_strict_at_the_third_birthday
        """
        set_clock(api, INTAKE_CLOCK)

        too_old = create_child(api, **AT_THIRD_BIRTHDAY_CHILD)
        refused = api.create_referral(
            factories.referral_payload(
                too_old, referral_received_date=RECEIVED_DATE
            ),
            INTAKE_HEADERS,
        )
        validate_error(refused, ApiErrorId.CHILD_AGE_INELIGIBLE.value, 422)
        assert read_child(api, too_old)["active_referral_count"] == 0

        young_enough = create_child(api, **A_DAY_YOUNGER_CHILD)
        accepted = validate_success(
            api.create_referral(
                factories.referral_payload(
                    young_enough, referral_received_date=RECEIVED_DATE
                ),
                INTAKE_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == "INTAKE"
        assert accepted["statutory_deadline_date"] == STATUTORY_DEADLINE
        assert read_child(api, young_enough)["active_referral_count"] == 1


class TestDuplicateOpenReferral:

    def test_the_duplicate_guard_is_scoped_to_the_child(self, api):
        """
        A second open referral for the same child is refused, while an otherwise
        identical referral for a sibling in the same county is accepted.

        PRD 3.1: "Second, a child may hold only one open case at a time: if any
        other referral for the same child sits in a status other than
        `NOT_ELIGIBLE` or `EXITED`, the request is rejected with
        `ERR_DUPLICATE_REFERRAL`."
        PRD 3.1: "The child's `active_referral_count` starts at 0 and thereafter
        always reports how many referral records for that child are in a
        non-terminal status, that is, any status other than `NOT_ELIGIBLE` or
        `EXITED`."

        Design: Corner/validations/duplicate_open_referral_is_rejected_per_child_not_per_county
        """
        case = build_intake(api)

        duplicate = api.create_referral(
            factories.referral_payload(
                case.child_id, referral_received_date=RECEIVED_DATE
            ),
            INTAKE_HEADERS,
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_REFERRAL.value, 409)

        sibling = create_child(
            api, first_name="Rui", last_name="Nolan", date_of_birth="2024-11-08"
        )
        sibling_referral = validate_success(
            api.create_referral(
                factories.referral_payload(
                    sibling, referral_received_date=RECEIVED_DATE
                ),
                INTAKE_HEADERS,
            ),
            201,
        )
        assert sibling_referral["status"] == "INTAKE"

        assert read_child(api, case.child_id)["active_referral_count"] == 1
        assert read_child(api, sibling)["active_referral_count"] == 1

        _, meta = validate_paginated(
            api.list_referrals(INTAKE_HEADERS, {"child_id": case.child_id})
        )
        assert meta["total_count"] == 1


# ─── Assessment scope and date discipline ─────────────────────────────

FOUR_DOMAINS = list(ALL_DOMAINS[:4])


class TestFiveDomainRule:

    def test_only_initial_evaluations_need_all_five_domains(self, api):
        """
        An initial evaluation missing a domain is refused; a family assessment
        may omit `domains_assessed` entirely.

        PRD 3.3: "An initial evaluation is held to a stricter standard than the
        others: its `domains_assessed` must list all five developmental domains,
        and one that omits any domain is rejected with
        `ERR_EVALUATION_DOMAINS_INCOMPLETE`."
        PRD 3.3: "Family and supplemental assessments may cover any subset."
        PRD 3.3: "A new record is created with `status` `SCHEDULED`, and the
        acting evaluator's identifier is captured as `evaluator_user_id`."

        Design: Corner/validations/five_domain_rule_applies_only_to_initial_evaluations
        """
        case = build_assigned(api)

        incomplete = api.create_assessment(
            factories.assessment_payload(
                case.referral_id, domains_assessed=FOUR_DOMAINS
            ),
            EVALUATOR_HEADERS,
        )
        validate_error(
            incomplete, ApiErrorId.EVALUATION_DOMAINS_INCOMPLETE.value, 422
        )

        family = validate_success(
            api.create_assessment(
                factories.assessment_payload(
                    case.referral_id,
                    assessment_type="FAMILY_ASSESSMENT",
                    scheduled_date="2026-03-12",
                ),
                EVALUATOR_HEADERS,
            ),
            201,
        )
        assert family["status"] == "SCHEDULED"
        assert family["domains_assessed"] is None

        complete = validate_success(
            api.create_assessment(
                factories.assessment_payload(
                    case.referral_id, domains_assessed=list(ALL_DOMAINS)
                ),
                EVALUATOR_HEADERS,
            ),
            201,
        )
        assert complete["status"] == "SCHEDULED"
        assert complete["domains_assessed"] == list(ALL_DOMAINS)

        _, meta = validate_paginated(
            api.list_assessments(
                EVALUATOR_HEADERS, {"referral_id": case.referral_id}
            )
        )
        assert meta["total_count"] == 2


class TestEventDateDiscipline:

    def test_future_dates_and_reversed_pairs_are_both_refused(self, api):
        """
        A received date ahead of the clock, a completion date before the received
        date, and a completion date ahead of the clock are each refused with their
        own identifier, and the assessment survives all three untouched.

        PRD 2.5: "Dates that record something that has already happened may
        not be in the future relative to the logical clock date. This applies to
        `referral_received_date`, an assessment's `completion_date`, an
        eligibility `determination_date`, an entry-outcome `measurement_date`,
        an IFSP `meeting_date`, a `consent_signed_date`, an
        `opt_out_signed_date`, a `notification_date`, a `verification_date`, a
        `contact_date`, an `exit_date`, and the `effective_date` recorded when a
        provider leaves active standing. A violation is rejected with
        `ERR_DATE_IN_FUTURE` (HTTP 422)."
        PRD 2.5: "An assessment's `completion_date` must be on or after the
        referral's `referral_received_date`."
        PRD 3.3: "The `completion_date` must be on or after the case's
        `referral_received_date` and must not be after the logical clock date."

        Design: Corner/validations/event_dates_must_not_lead_the_clock_and_pairs_must_stay_ordered
        """
        case = build_assigned(api)
        evaluation_id = schedule_assessment(api, case.referral_id)
        set_clock(api, POST_EVALUATION_CLOCK)
        version_before = read_assessment(api, evaluation_id)["version"]

        another_child = create_child(
            api, first_name="Tovah", last_name="Bly", date_of_birth="2024-09-14"
        )
        ahead_of_clock = api.create_referral(
            factories.referral_payload(
                another_child, referral_received_date="2026-03-21"
            ),
            INTAKE_HEADERS,
        )
        validate_error(ahead_of_clock, ApiErrorId.DATE_IN_FUTURE.value, 422)

        before_referral = api.complete_assessment(
            evaluation_id,
            factories.complete_assessment_payload("2026-03-01"),
            EVALUATOR_HEADERS,
        )
        validate_error(
            before_referral, ApiErrorId.INVALID_DATE_RANGE.value, 422
        )

        after_clock = api.complete_assessment(
            evaluation_id,
            factories.complete_assessment_payload("2026-04-01"),
            EVALUATOR_HEADERS,
        )
        validate_error(after_clock, ApiErrorId.DATE_IN_FUTURE.value, 422)

        untouched = read_assessment(api, evaluation_id)
        assert untouched["status"] == "SCHEDULED"
        assert untouched["completion_date"] is None
        assert untouched["version"] == version_before

        accepted = validate_success(
            api.complete_assessment(
                evaluation_id,
                factories.complete_assessment_payload("2026-03-18"),
                EVALUATOR_HEADERS,
            ),
            200,
        )
        assert accepted["status"] == "COMPLETED"
        assert accepted["completion_date"] == "2026-03-18"


# ─── The natural-environment obligation at consent ────────────────────

LINE_JUSTIFICATION = (
    "Specialised feeding equipment is available only in the clinic suite"
)
PLAN_JUSTIFICATION = (
    "The plan offers clinic sessions because the feeding equipment cannot travel"
)
CLINIC_LINE = {
    "setting_code": "CLINIC",
    "natural_environment_justification": LINE_JUSTIFICATION,
}
CONSENT_DATE = "2026-03-20"


class TestNaturalEnvironmentJustificationAtConsent:

    def test_a_clinic_line_without_the_plan_level_justification_blocks_consent(
        self, api
    ):
        """
        A line-level justification does not satisfy the plan-level obligation, and
        the refused consent leaves the plan, the case and the line untouched.

        PRD 3.5: "First, the natural-environment obligation lands here rather than
        at authoring: when the plan's `non_natural_setting_line_count` is greater
        than zero, the plan's own `natural_environment_justification` must be
        present and at least 20 characters long, and a consent attempt on a plan
        that offers clinic or office services without that plan-level
        justification is refused with
        `ERR_NATURAL_ENVIRONMENT_JUSTIFICATION_REQUIRED`."

        Design: Corner/validations/consent_refused_when_a_clinic_line_lacks_the_plan_level_justification
        """
        case = build_plan_with_line(api, line=CLINIC_LINE)

        refused = api.record_consent(
            case.ifsp_id,
            factories.consent_payload(consent_signed_date=CONSENT_DATE),
            case.family_headers,
        )
        validate_error(
            refused,
            ApiErrorId.NATURAL_ENVIRONMENT_JUSTIFICATION_REQUIRED.value,
            422,
        )

        plan = read_ifsp(api, case.ifsp_id)
        assert plan["status"] == "PENDING_CONSENT"
        assert plan["service_line_count"] == 1
        assert plan["non_natural_setting_line_count"] == 1
        assert plan["consent_scope"] is None
        assert plan["activated_date"] is None

        referral = read_referral(api, case.referral_id)
        assert referral["status"] == "IFSP_PENDING"
        assert referral["services_start_date"] is None

        assert read_service_line(api, case.line_id)["status"] == "PLANNED"

    def test_the_plan_level_justification_unlocks_consent(self, api):
        """
        With the justification carried on the plan itself the same clinic line
        consents cleanly and services start on the signing date.

        PRD 3.5: "Consent advances the plan `PENDING_CONSENT → ACTIVE` or, closing
        the amendment cycle, `AMENDMENT_PENDING → ACTIVE`."
        PRD 3.5: "It stores `consent_scope`, `consent_signed_date`, the acting
        family identifier as `consent_user_id`, and `activated_date` — the date
        the plan most recently reached `ACTIVE`."

        Design: Corner/validations/consent_succeeds_when_the_plan_carries_the_clinic_justification
        """
        case = build_plan_with_line(
            api,
            ifsp={"natural_environment_justification": PLAN_JUSTIFICATION},
            line=CLINIC_LINE,
        )

        plan = validate_success(
            api.record_consent(
                case.ifsp_id,
                factories.consent_payload(consent_signed_date=CONSENT_DATE),
                case.family_headers,
            ),
            200,
        )
        assert plan["status"] == "ACTIVE"
        assert plan["consent_scope"] == "FULL"
        assert plan["activated_date"] == CONSENT_DATE
        assert plan["service_line_count"] == 1
        assert plan["non_natural_setting_line_count"] == 1

        referral = read_referral(api, case.referral_id)
        assert referral["status"] == "ACTIVE_SERVICES"
        assert referral["services_start_date"] == CONSENT_DATE

        line = read_service_line(api, case.line_id)
        assert line["status"] == "PLANNED"
        assert line["declined_by_family"] is False


# ─── Exit prerequisites ───────────────────────────────────────────────

EXIT_DATE = "2026-03-20"
EXIT_RATINGS = {
    "exit_rating_social": 2,
    "exit_rating_knowledge": 5,
    "exit_rating_needs": 6,
}
PROGRESS_CATEGORY_FIELDS = (
    "progress_category_social",
    "progress_category_knowledge",
    "progress_category_needs",
)


class TestExitPrerequisites:

    def test_ratings_and_a_notified_plan_are_both_required(self, api):
        """
        Exit from active services needs all three ratings, and an age-three exit
        additionally needs a notified or opted-out transition plan; a withdrawal
        exit with ratings runs the closure cascade.

        PRD 3.9: "All three exit ratings are required and each must be an integer
        from 1 through 7, and when the `exit_reason` is `REACHED_AGE_THREE` the
        case must additionally carry a transition plan on its `ACTIVE` plan whose
        status is `NOTIFIED` or `OPT_OUT` — a child cannot age out of the program
        without the district having been notified or the family having formally
        declined. A violation of either requirement is refused with
        `ERR_EXIT_OUTCOMES_REQUIRED`."
        PRD 3.9: "`service_duration_days` is the whole number of days from
        `services_start_date` to `exit_date`, and it is 0 for as long as
        `services_start_date` is null. If a case received services for fewer than
        180 days, no meaningful comparison is possible and all three of
        `progress_category_social`, `progress_category_knowledge` and
        `progress_category_needs` are recorded as `NOT_COMPARABLE`, whatever the
        ratings say."
        PRD 3.9: "Every service line on that closed plan whose status is
        `PLANNED`, `AUTHORIZED`, `IN_DELIVERY` or `AT_RISK` transitions to
        `DISCONTINUED`."

        Design: Corner/validations/exit_requires_ratings_and_a_notified_transition_plan_for_age_three
        """
        case = build_active_services(api)

        no_ratings = api.exit_referral(
            case.referral_id,
            factories.exit_payload(EXIT_DATE, exit_reason="FAMILY_WITHDREW"),
            case.coordinator_headers,
        )
        validate_error(
            no_ratings, ApiErrorId.EXIT_OUTCOMES_REQUIRED.value, 422
        )

        no_transition_plan = api.exit_referral(
            case.referral_id,
            factories.exit_payload(
                EXIT_DATE, exit_reason="REACHED_AGE_THREE", **EXIT_RATINGS
            ),
            case.coordinator_headers,
        )
        validate_error(
            no_transition_plan, ApiErrorId.EXIT_OUTCOMES_REQUIRED.value, 422
        )
        assert read_referral(api, case.referral_id)["status"] == "ACTIVE_SERVICES"

        exited = validate_success(
            api.exit_referral(
                case.referral_id,
                factories.exit_payload(
                    EXIT_DATE, exit_reason="FAMILY_WITHDREW", **EXIT_RATINGS
                ),
                case.coordinator_headers,
            ),
            200,
        )
        assert exited["status"] == "EXITED"
        assert exited["service_duration_days"] == 0
        for field in PROGRESS_CATEGORY_FIELDS:
            assert exited[field] == "NOT_COMPARABLE"

        assert read_ifsp(api, case.ifsp_id)["status"] == "CLOSED"
        assert read_service_line(api, case.line_id)["status"] == "DISCONTINUED"


# ─── The authorization guard ladder ───────────────────────────────────

FIRST_WINDOW = {"start_date": "2026-03-21", "end_date": "2026-04-30"}
SECOND_WINDOW = {"start_date": "2026-05-01", "end_date": "2026-05-31"}
REVERSED_WINDOW = {"start_date": "2026-05-10", "end_date": "2026-05-01"}


class TestAuthorizationGuardOrder:

    def test_service_type_then_date_range_then_pool(self, api):
        """
        A provider not qualified for the line is refused before anything else, a
        reversed window is refused before the pool is consulted, and only an
        over-commitment on an ordered window reaches the pool check.

        PRD 3.6: "The line's `service_type` must appear in the provider's
        `qualified_service_types`, or the request is refused with
        `ERR_PROVIDER_SERVICE_TYPE_MISMATCH`."
        PRD 3.6: "The window itself must be ordered, with `end_date` on or after
        `start_date`, or the request fails with `ERR_INVALID_DATE_RANGE`."
        PRD 3.6: "And finally `authorized_units` must be less than or equal to the
        line's current `units_pool_remaining`, or the request is refused with
        `ERR_UNITS_EXCEED_SERVICE_POOL`."
        PRD 3.6: "On creation the authorization's `status` is `ACTIVE`, its
        `unit_rate_cents` is copied from the service line's `unit_rate_cents` and
        **pinned for the life of the authorization** so that a later rate change
        on the plan cannot retroactively re-price sessions already funded, its
        `units_consumed` and `units_released` are 0, and its `units_remaining`
        equals `authorized_units`."

        Design: Corner/validations/authorization_checks_fire_in_priority_order_across_provider_pool_and_dates
        """
        case = build_active_services(api)
        wrong_discipline = create_provider(
            api,
            agency_name="Northgate Occupational",
            qualified_service_types=["OCCUPATIONAL_THERAPY"],
        )
        mismatch = api.create_authorization(
            factories.authorization_payload(
                case.line_id, wrong_discipline, authorized_units=10, **FIRST_WINDOW
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            mismatch, ApiErrorId.PROVIDER_SERVICE_TYPE_MISMATCH.value, 422
        )

        provider_id = create_provider(api)
        first = validate_success(
            api.create_authorization(
                factories.authorization_payload(
                    case.line_id, provider_id, authorized_units=90, **FIRST_WINDOW
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert first["status"] == "ACTIVE"
        assert first["unit_rate_cents"] == 6500
        assert_authorization_units(first, 0, 0, 90)

        over_pool = api.create_authorization(
            factories.authorization_payload(
                case.line_id, provider_id, authorized_units=12, **SECOND_WINDOW
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            over_pool, ApiErrorId.UNITS_EXCEED_SERVICE_POOL.value, 422
        )

        reversed_window = api.create_authorization(
            factories.authorization_payload(
                case.line_id, provider_id, authorized_units=500, **REVERSED_WINDOW
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            reversed_window, ApiErrorId.INVALID_DATE_RANGE.value, 422
        )

        remainder = validate_success(
            api.create_authorization(
                factories.authorization_payload(
                    case.line_id, provider_id, authorized_units=6, **SECOND_WINDOW
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_authorization_units(remainder, 0, 0, 6)

        line = read_service_line(api, case.line_id)
        assert_unit_pool(line, 96, 0, 96)
        assert line["status"] == "AUTHORIZED"


# ─── Visit duration, window and timing ────────────────────────────────

OFF_GRID_SESSION = ("2026-03-24T14:00:00Z", "2026-03-24T14:20:00Z")
OVERLONG_SESSION = ("2026-03-24T14:00:00Z", "2026-03-24T18:15:00Z")
OUT_OF_WINDOW_SESSION = ("2026-05-05T14:00:00Z", "2026-05-05T14:30:00Z")
LEGAL_SESSION = ("2026-03-24T14:00:00Z", "2026-03-24T14:30:00Z")
DELIVERY_CLOCK = "2026-03-24T15:00:00Z"


class TestVisitTimingLayers:

    def test_duration_window_and_documentation_timing(self, api):
        """
        Duration is checked against the 15-minute grid and the four-hour ceiling
        before the authorization window is consulted, and a legal session still
        cannot be documented before it has begun.

        PRD 3.7: "Its length must be strictly positive, a whole multiple of 15
        minutes, and at most 240 minutes — four hours, or 16 units — with both
        endpoints falling on a 15-minute boundary; anything else is refused with
        `ERR_INVALID_VISIT_DURATION`."
        PRD 3.7: "The session's scheduled date must fall inside the
        authorization's window, inclusive of both `start_date` and `end_date`, or
        it is refused with `ERR_VISIT_OUTSIDE_AUTHORIZATION_WINDOW`."
        PRD 3.7: "A new session is created with `visit_status` `SCHEDULED` and
        `billing_status` `PENDING`, and the server computes `scheduled_units` as
        the length of the interval in minutes divided by 15."
        PRD 3.7: "And a session may not be documented before it has begun: its
        `scheduled_start` must be at or before the logical clock instant, or the
        request is refused with `ERR_VISIT_NOT_YET_OCCURRED`."
        PRD 3.8: "If that candidate set is empty, the session's
        `family_share_cents` is 0 and its `billing_status` is set to `EXEMPT`."

        Design: Corner/validations/visit_duration_window_and_timing_rules_are_layered
        """
        case = build_authorized(api)

        off_grid = api.create_visit(
            factories.visit_payload(case.authorization_id, *OFF_GRID_SESSION),
            ADMIN_HEADERS,
        )
        validate_error(off_grid, ApiErrorId.INVALID_VISIT_DURATION.value, 422)

        overlong = api.create_visit(
            factories.visit_payload(case.authorization_id, *OVERLONG_SESSION),
            ADMIN_HEADERS,
        )
        validate_error(overlong, ApiErrorId.INVALID_VISIT_DURATION.value, 422)

        out_of_window = api.create_visit(
            factories.visit_payload(case.authorization_id, *OUT_OF_WINDOW_SESSION),
            ADMIN_HEADERS,
        )
        validate_error(
            out_of_window,
            ApiErrorId.VISIT_OUTSIDE_AUTHORIZATION_WINDOW.value,
            422,
        )

        visit = validate_success(
            api.create_visit(
                factories.visit_payload(case.authorization_id, *LEGAL_SESSION),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert visit["visit_status"] == "SCHEDULED"
        assert visit["billing_status"] == "PENDING"
        assert visit["scheduled_units"] == 2
        assert visit["actual_units"] is None

        too_early = api.document_visit(
            visit["id"],
            factories.document_visit_payload(
                actual_units=2,
                actual_start=LEGAL_SESSION[0],
                actual_end=LEGAL_SESSION[1],
            ),
            case.provider_headers,
        )
        validate_error(
            too_early, ApiErrorId.VISIT_NOT_YET_OCCURRED.value, 422
        )
        assert read_visit(api, visit["id"])["visit_status"] == "SCHEDULED"

        set_clock(api, DELIVERY_CLOCK)
        delivered = validate_success(
            api.document_visit(
                visit["id"],
                factories.document_visit_payload(
                    actual_units=2,
                    actual_start=LEGAL_SESSION[0],
                    actual_end=LEGAL_SESSION[1],
                ),
                case.provider_headers,
            ),
            200,
        )
        assert delivered["visit_status"] == "DELIVERED"
        assert delivered["billing_status"] == "EXEMPT"
        assert_cents(delivered["family_share_cents"], 0, "family_share_cents")

        assert_authorization_units(
            read_authorization(api, case.authorization_id), 2, 0, 22
        )


# ─── Insurance consent and the offset ─────────────────────────────────

POLICY_ID = "POL-88213"
HOUSEHOLD_THRESHOLD_CENTS = 3_245_000
VERIFIED_INCOME_CENTS = 12_000_000
VERIFICATION_DATE = "2026-03-20"


class TestInsuranceOffsetPrerequisites:

    def test_consent_needs_a_policy_and_only_finalization_offsets(self, api):
        """
        Consent to bill insurance is refused without a policy identifier, carrying
        a policy recomputes nothing, and the 60 percent offset appears only when
        the determination is finalized.

        PRD 3.8: "Setting consent to true without supplying a policy identifier is
        refused with `ERR_INSURANCE_POLICY_REQUIRED`."
        PRD 3.8: "No fee is recomputed by this capability: the offset belongs to
        the final variant alone."
        PRD 3.8: "The provisional variant **never** applies the insurance offset,
        even when `insurance_use_consent` is true and a policy is on file:
        `insurance_offset_cents` stays at 0 and `final_monthly_fee_cents` stays
        null."
        PRD 3.8: "The insurance offset is applied here and only here: when
        `insurance_use_consent` is true **and** an `insurance_policy_id` is on
        file, `insurance_offset_cents` is 60 percent of the capped monthly figure,
        rounded half up to whole cents; otherwise it is 0."
        PRD 3.8: "The tier is never re-derived from the post-offset amount — the
        offset reduces what the family owes, not the band the family sits in."

        Design: Corner/validations/insurance_offset_requires_consent_and_a_policy_on_file
        """
        case = build_cost_share_case(api)

        provisional = read_cost_share(api, case.cost_share_id)
        assert provisional["status"] == "PROVISIONAL"
        assert provisional["fpl_threshold_cents"] == HOUSEHOLD_THRESHOLD_CENTS
        assert_fpl_percent(provisional["fpl_percent"], 369.8)
        assert provisional["tier_code"] == "TIER_1"
        assert provisional["coinsurance_rate"] == 0.05
        assert provisional["effective_coinsurance_rate"] == 0.05
        assert_cents(provisional["monthly_cap_cents"], 12_000, "monthly_cap_cents")
        assert_cents(
            provisional["assessed_monthly_fee_cents"],
            2_600,
            "assessed_monthly_fee_cents",
        )
        assert_cents(
            provisional["insurance_offset_cents"], 0, "insurance_offset_cents"
        )
        assert provisional["final_monthly_fee_cents"] is None
        assert provisional["determined_by_user_id"] == FISCAL_OFFICER_USER_ID

        no_policy = api.record_insurance_consent(
            case.cost_share_id,
            factories.insurance_consent_payload(insurance_use_consent=True),
            FISCAL_HEADERS,
        )
        validate_error(
            no_policy, ApiErrorId.INSURANCE_POLICY_REQUIRED.value, 422
        )

        consented = validate_success(
            api.record_insurance_consent(
                case.cost_share_id,
                factories.insurance_consent_payload(
                    insurance_use_consent=True, insurance_policy_id=POLICY_ID
                ),
                FISCAL_HEADERS,
            ),
            200,
        )
        assert consented["insurance_use_consent"] is True
        assert consented["insurance_policy_id"] == POLICY_ID
        assert consented["status"] == "PROVISIONAL"
        assert_cents(
            consented["insurance_offset_cents"], 0, "insurance_offset_cents"
        )
        assert consented["final_monthly_fee_cents"] is None
        assert_cents(
            consented["assessed_monthly_fee_cents"],
            2_600,
            "assessed_monthly_fee_cents",
        )

        finalized = validate_success(
            api.finalize_cost_share(
                case.cost_share_id,
                factories.finalize_cost_share_payload(
                    VERIFIED_INCOME_CENTS, VERIFICATION_DATE
                ),
                FISCAL_HEADERS,
            ),
            200,
        )
        assert finalized["status"] == "VERIFIED"
        assert finalized["tier_code"] == "TIER_1"
        assert finalized["effective_coinsurance_rate"] == 0.05
        assert_fpl_percent(finalized["fpl_percent"], 369.8)
        assert_cents(
            finalized["insurance_offset_cents"], 1_560, "insurance_offset_cents"
        )
        assert_cents(
            finalized["final_monthly_fee_cents"], 1_040, "final_monthly_fee_cents"
        )
        assert_ledger(finalized, 0, 0, 0)


# ─── The transition window ────────────────────────────────────────────

TRANSITION_CHILD = {
    "first_name": "Miles",
    "last_name": "Okafor",
    "date_of_birth": "2024-01-10",
}
WINDOW_CLOSED_CLOCK = POST_EVALUATION_CLOCK
WINDOW_OPEN_CLOCK = "2026-04-20T09:00:00Z"
TARGET_CONFERENCE_DATE = "2026-12-01"
NOTIFICATION_DATE = "2026-04-20"


class TestTransitionWindowAndUniqueness:

    def test_the_window_opens_at_270_days_and_one_plan_per_ifsp(self, api):
        """
        A plan opened 296 days before the third birthday is refused, the same
        request lands once the window has narrowed to 265 days, notification
        without a held conference is incomplete, and a second plan collides.

        PRD 3.9: "The window must be open: the whole number of days from the
        logical clock date to the child's `third_birthday_date` must be at most
        270 — the final nine months before the child ages out — and an earlier
        attempt is refused with `ERR_TRANSITION_WINDOW_NOT_OPEN`."
        PRD 3.9: "And a plan may carry at most one transition plan: if the plan
        already has one in `DRAFT`, `NOTIFIED`, `OPT_OUT` or `COMPLETE`, the
        request is refused with `ERR_TRANSITION_PLAN_DUPLICATE`."
        PRD 3.9: "The new plan is created in `DRAFT` with every notification field
        left null: no `lea_code`, no `notification_date`, `family_opt_out` false,
        no `opt_out_signed_date`, no `notification_lead_days`, no
        `notification_compliance`."
        PRD 3.9: "That branch requires the transition work to have actually
        happened: `conference_held_date` must be present and
        `transition_steps_count` must be at least 1, and a plan missing either is
        refused with `ERR_TRANSITION_PLAN_INCOMPLETE`."

        Design: Corner/validations/transition_window_opens_at_270_days_and_the_plan_is_unique_per_ifsp
        """
        case = build_active_services(api, child=TRANSITION_CHILD)
        assert read_child(api, case.child_id)["third_birthday_date"] == "2027-01-10"

        set_clock(api, WINDOW_CLOSED_CLOCK)

        too_early = api.create_transition_plan(
            factories.transition_plan_payload(
                case.ifsp_id, TARGET_CONFERENCE_DATE, transition_steps_count=4
            ),
            case.coordinator_headers,
        )
        validate_error(
            too_early, ApiErrorId.TRANSITION_WINDOW_NOT_OPEN.value, 422
        )

        set_clock(api, WINDOW_OPEN_CLOCK)
        plan = validate_success(
            api.create_transition_plan(
                factories.transition_plan_payload(
                    case.ifsp_id, TARGET_CONFERENCE_DATE, transition_steps_count=4
                ),
                case.coordinator_headers,
            ),
            201,
        )
        assert plan["status"] == "DRAFT"
        assert plan["transition_steps_count"] == 4
        assert plan["conference_held_date"] is None
        assert plan["lea_code"] is None
        assert plan["notification_date"] is None
        assert plan["family_opt_out"] is False
        assert plan["opt_out_signed_date"] is None
        assert plan["notification_lead_days"] is None
        assert plan["notification_compliance"] is None

        incomplete = api.notify_lea(
            plan["id"],
            factories.notify_lea_payload(NOTIFICATION_DATE, lea_code="LEA_44"),
            case.coordinator_headers,
        )
        validate_error(
            incomplete, ApiErrorId.TRANSITION_PLAN_INCOMPLETE.value, 422
        )

        duplicate = api.create_transition_plan(
            factories.transition_plan_payload(
                case.ifsp_id,
                "2026-12-15",
                conference_held_date="2026-04-15",
                transition_steps_count=4,
            ),
            case.coordinator_headers,
        )
        validate_error(
            duplicate, ApiErrorId.TRANSITION_PLAN_DUPLICATE.value, 409
        )

        still_draft = read_transition_plan(api, plan["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["lea_code"] is None

        _, meta = validate_paginated(
            api.list_transition_plans(ADMIN_HEADERS, {"ifsp_id": case.ifsp_id})
        )
        assert meta["total_count"] == 1
