"""
Catalog error codes reached only by a full chain: the plan-authoring and consent
guards, the unit ceiling at both ends of the visit lifecycle, the three makeup
guards, the family-fee lifecycle, and the notification-deadline sign rule.
"""

from test_helpers import (
    ADMIN_HEADERS,
    EVALUATOR_HEADERS,
    FISCAL_2_HEADERS,
    FISCAL_HEADERS,
    ApiErrorId,
    add_service_line,
    assert_authorization_units,
    assert_cents,
    assert_fpl_percent,
    assert_ledger,
    build_accrued_visit_case,
    build_authorized,
    build_plan_with_line,
    build_transition_planning_case,
    create_authorization,
    create_provider,
    document_visit,
    factories,
    make_provider_headers,
    read_assessment,
    read_authorization,
    read_cost_share,
    read_ifsp,
    read_child,
    read_referral,
    read_service_line,
    read_transition_plan,
    read_visit,
    record_consent,
    referral_version,
    schedule_visit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

EVALUATION_COMPLETION_DATE = "2026-03-18"
FAMILY_COMPLETION_DATE = "2026-03-19"


class TestPlanAuthoringAndConsentErrors:

    def test_completion_partial_consent_and_supersede_guards(self, api):
        """
        Completing a completed record, declining every line of a plan, and both
        halves of the supersede rule each report their own catalog code.

        PRD 3.3: "Only a `SCHEDULED` record may be completed; anything else is
        refused with `ERR_ASSESSMENT_NOT_SCHEDULED`."
        PRD 3.5: "Second, a partial consent must leave something behind: every
        identifier in `declined_service_ids` must belong to this plan, the array
        must be non-empty, and at least one line on the plan must remain
        undeclined. A partial consent that names a line from another plan, or that
        declines every line, is refused with `ERR_ALL_SERVICES_DECLINED`."
        PRD 3.5: "The distinction is enforced through `supersedes_ifsp_id`: it is
        **required** for an `ANNUAL` plan and **forbidden** on an `INITIAL` plan,
        and when supplied it must name a plan whose `status` is `ACTIVE`, on the
        same case, that no other plan outside `WITHDRAWN` already supersedes."
        PRD 3.5: "Any violation of that cluster of conditions — missing when
        required, present when forbidden, pointing at a plan that is not active,
        pointing at another case's plan, or pointing at a plan already claimed by a
        second successor — is rejected with `ERR_SUPERSEDE_TARGET_INVALID`."

        Design: Corner/errors/plan_authoring_and_consent_error_sweep
        """
        case = build_plan_with_line(api)

        already_completed = api.complete_assessment(
            case.eval_id,
            factories.complete_assessment_payload(FAMILY_COMPLETION_DATE),
            EVALUATOR_HEADERS,
        )
        validate_error(
            already_completed, ApiErrorId.ASSESSMENT_NOT_SCHEDULED.value, 409
        )
        assert (
            read_assessment(api, case.eval_id)["completion_date"]
            == EVALUATION_COMPLETION_DATE
        )

        all_declined = api.record_consent(
            case.ifsp_id,
            factories.consent_payload(
                consent_scope="PARTIAL", declined_service_ids=[case.line_id]
            ),
            case.family_headers,
        )
        validate_error(
            all_declined, ApiErrorId.ALL_SERVICES_DECLINED.value, 422
        )
        assert read_ifsp(api, case.ifsp_id)["status"] == "PENDING_CONSENT"
        untouched_line = read_service_line(api, case.line_id)
        assert untouched_line["status"] == "PLANNED"
        assert untouched_line["declined_by_family"] is False
        assert read_referral(api, case.referral_id)["status"] == "IFSP_PENDING"

        activated = validate_success(
            api.record_consent(
                case.ifsp_id, factories.consent_payload(), case.family_headers
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"
        assert read_referral(api, case.referral_id)["status"] == "ACTIVE_SERVICES"

        missing_target = api.create_ifsp(
            factories.ifsp_payload(
                case.referral_id,
                case.coordinator_id,
                referral_version(api, case.referral_id),
                ifsp_type="ANNUAL",
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            missing_target, ApiErrorId.SUPERSEDE_TARGET_INVALID.value, 422
        )

        successor = validate_success(
            api.create_ifsp(
                factories.ifsp_payload(
                    case.referral_id,
                    case.coordinator_id,
                    referral_version(api, case.referral_id),
                    ifsp_type="ANNUAL",
                    supersedes_ifsp_id=case.ifsp_id,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert successor["status"] == "DRAFT"
        assert successor["ifsp_type"] == "ANNUAL"
        assert successor["supersedes_ifsp_id"] == case.ifsp_id
        assert read_ifsp(api, case.ifsp_id)["status"] == "ACTIVE"

        second_claim = api.create_ifsp(
            factories.ifsp_payload(
                case.referral_id,
                case.coordinator_id,
                referral_version(api, case.referral_id),
                ifsp_type="ANNUAL",
                supersedes_ifsp_id=case.ifsp_id,
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            second_claim, ApiErrorId.SUPERSEDE_TARGET_INVALID.value, 422
        )


# ─── The unit ceiling at both ends of the visit lifecycle ─────────────

DECLINED_LINE = {
    "service_type": "OCCUPATIONAL_THERAPY",
    "frequency_per_month": 2,
    "units_per_session": 2,
    "unit_rate_cents": 7000,
    "planned_units_total": 8,
}
FOUR_UNIT_SESSION = ("2026-03-24T09:00:00Z", "2026-03-24T10:00:00Z")
FIRST_SESSION = ("2026-03-24T14:00:00Z", "2026-03-24T14:30:00Z")
SECOND_SESSION = ("2026-03-25T14:00:00Z", "2026-03-25T14:30:00Z")
LATER_SESSION = ("2026-04-01T14:00:00Z", "2026-04-01T14:30:00Z")
DOCUMENT_CLOCK = "2026-03-26T09:00:00Z"


class TestAuthorizationAndVisitUnitCeiling:

    def test_the_ceiling_is_enforced_at_scheduling_and_at_documentation(self, api):
        """
        A discontinued line takes no authorization, a session larger than the
        remaining units is refused at scheduling, two equal sessions are both
        scheduled because scheduling reserves nothing, and the second is refused
        only once documentation has exhausted the authorization.

        PRD 3.6: "The service line must still be deliverable — its `status` must be
        `PLANNED`, `AUTHORIZED`, `IN_DELIVERY` or `AT_RISK`; a `DISCONTINUED` or
        `COMPLETED` line accepts no new authorization and produces
        `ERR_SERVICE_NOT_DELIVERABLE`."
        PRD 3.7: "And the session's `scheduled_units` must not exceed the
        authorization's current `units_remaining`, or it is refused with
        `ERR_UNITS_EXCEED_AUTHORIZATION`."
        PRD 3.7: "No units are consumed and no family money accrues at scheduling
        time; both happen only at documentation."
        PRD 3.7: "Only a session whose `visit_status` is `DELIVERED` may be voided;
        anything else is refused with `ERR_VISIT_NOT_VOIDABLE`."
        PRD 3.7: "If the authorization's `units_consumed` now equals its
        `authorized_units` it advances `ACTIVE → EXHAUSTED`."
        PRD 3.7: "The target authorization must be in `ACTIVE`, or the request is
        refused with `ERR_AUTHORIZATION_NOT_ACTIVE`."

        Design: Corner/errors/authorization_and_visit_unit_ceiling_error_sweep
        """
        case = build_plan_with_line(api)
        declined_line_id = add_service_line(api, case.ifsp_id, **DECLINED_LINE)
        record_consent(
            api,
            case.ifsp_id,
            case.child_id,
            consent_scope="PARTIAL",
            declined_service_ids=[declined_line_id],
        )
        case.provider_id = create_provider(
            api,
            qualified_service_types=["SPEECH_THERAPY", "OCCUPATIONAL_THERAPY"],
        )
        case.authorization_id = create_authorization(
            api, case.line_id, case.provider_id, authorized_units=2
        )
        provider_headers = make_provider_headers(case.provider_id)

        not_deliverable = api.create_authorization(
            factories.authorization_payload(
                declined_line_id, case.provider_id, authorized_units=4
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            not_deliverable, ApiErrorId.SERVICE_NOT_DELIVERABLE.value, 409
        )

        too_many_units = api.create_visit(
            factories.visit_payload(case.authorization_id, *FOUR_UNIT_SESSION),
            ADMIN_HEADERS,
        )
        validate_error(
            too_many_units, ApiErrorId.UNITS_EXCEED_AUTHORIZATION.value, 422
        )

        first_id = schedule_visit(api, case.authorization_id, *FIRST_SESSION)
        second_id = schedule_visit(api, case.authorization_id, *SECOND_SESSION)
        assert read_visit(api, first_id)["scheduled_units"] == 2
        assert read_visit(api, second_id)["scheduled_units"] == 2
        assert_authorization_units(
            read_authorization(api, case.authorization_id), 0, 0, 2
        )

        not_voidable = api.void_visit(
            first_id, factories.void_visit_payload(), ADMIN_HEADERS
        )
        validate_error(not_voidable, ApiErrorId.VISIT_NOT_VOIDABLE.value, 409)

        set_clock(api, DOCUMENT_CLOCK)
        delivered = document_visit(
            api,
            first_id,
            case.provider_id,
            actual_units=2,
            actual_start=FIRST_SESSION[0],
            actual_end=FIRST_SESSION[1],
        )
        assert delivered["visit_status"] == "DELIVERED"
        exhausted = read_authorization(api, case.authorization_id)
        assert_authorization_units(exhausted, 2, 0, 0)
        assert exhausted["status"] == "EXHAUSTED"

        over_ceiling = api.document_visit(
            second_id,
            factories.document_visit_payload(
                actual_units=2,
                actual_start=SECOND_SESSION[0],
                actual_end=SECOND_SESSION[1],
            ),
            provider_headers,
        )
        validate_error(
            over_ceiling, ApiErrorId.UNITS_EXCEED_AUTHORIZATION.value, 422
        )
        assert read_visit(api, second_id)["visit_status"] == "SCHEDULED"

        on_exhausted = api.create_visit(
            factories.visit_payload(case.authorization_id, *LATER_SESSION),
            ADMIN_HEADERS,
        )
        validate_error(
            on_exhausted, ApiErrorId.AUTHORIZATION_NOT_ACTIVE.value, 409
        )


# ─── Repairing a provider cancellation, and the ways it can be refused ─

AUTHORIZATION_END_DATE = "2026-05-31"
DELIVERED_SESSION = ("2026-03-22T14:00:00Z", "2026-03-22T14:30:00Z")
CANCELLED_SESSION = ("2026-03-24T14:00:00Z", "2026-03-24T14:30:00Z")
NON_DELIVERY_CLOCK = "2026-03-25T09:00:00Z"
MAKEUP_OF_DELIVERED = ("2026-04-06T14:00:00Z", "2026-04-06T14:30:00Z")
MAKEUP_TOO_LATE = ("2026-04-25T14:00:00Z", "2026-04-25T14:30:00Z")
MAKEUP_IN_TIME = ("2026-04-20T14:00:00Z", "2026-04-20T14:30:00Z")
MAKEUP_SECOND_ATTEMPT = ("2026-04-21T14:00:00Z", "2026-04-21T14:30:00Z")


class TestMakeupScheduling:

    def test_makeup_target_window_and_uniqueness_are_all_enforced(self, api):
        """
        Only a provider cancellation may be made up, the repair must land within
        thirty days of the session it repairs, and one cancellation admits only
        one live makeup. A two-unit obligation stays below the at-risk threshold,
        so the line keeps running and the case shows no service gap.

        PRD 3.7: "When `makeup_for_visit_id` is supplied it must name a session
        whose `visit_status` is `CANCELLED_PROVIDER` and whose authorization belongs
        to the same service line as the new session; anything else — a family
        cancellation, a no-show, a delivered session, or a provider cancellation on
        a different line — is refused with `ERR_MAKEUP_TARGET_INVALID`."
        PRD 3.7: "And the repair must be prompt: the makeup session must be
        scheduled within 30 days of the cancelled session it repairs, the deadline
        being the calendar date of the target's `scheduled_start` plus 30 days, and
        a later attempt is refused with `ERR_MAKEUP_WINDOW_EXPIRED`."
        PRD 3.7: "A cancellation may be made up only once: if any other session
        whose `visit_status` is neither `VOIDED` nor `CANCELLED_PROGRAM` already
        names the same `makeup_for_visit_id`, the request is refused with
        `ERR_MAKEUP_ALREADY_SCHEDULED`."
        PRD 3.7: "A line is at risk when that owed figure is **strictly greater
        than** 4 units, so a line owing exactly 4 units is not at risk while a line
        owing 5 is."

        Design: Corner/errors/makeup_scheduling_error_sweep
        """
        case = build_authorized(
            api, authorization={"end_date": AUTHORIZATION_END_DATE}
        )
        delivered_id = schedule_visit(api, case.authorization_id, *DELIVERED_SESSION)
        cancelled_id = schedule_visit(api, case.authorization_id, *CANCELLED_SESSION)

        set_clock(api, NON_DELIVERY_CLOCK)
        document_visit(
            api,
            delivered_id,
            case.provider_id,
            actual_units=2,
            actual_start=DELIVERED_SESSION[0],
            actual_end=DELIVERED_SESSION[1],
        )
        cancelled = document_visit(
            api, cancelled_id, case.provider_id, visit_status="CANCELLED_PROVIDER"
        )
        assert cancelled["visit_status"] == "CANCELLED_PROVIDER"
        assert cancelled["actual_units"] == 0
        assert cancelled["billing_status"] == "CANCELLED_NO_CHARGE"

        wrong_target = api.create_visit(
            factories.visit_payload(
                case.authorization_id,
                *MAKEUP_OF_DELIVERED,
                makeup_for_visit_id=delivered_id,
            ),
            ADMIN_HEADERS,
        )
        validate_error(wrong_target, ApiErrorId.MAKEUP_TARGET_INVALID.value, 422)

        too_late = api.create_visit(
            factories.visit_payload(
                case.authorization_id,
                *MAKEUP_TOO_LATE,
                makeup_for_visit_id=cancelled_id,
            ),
            ADMIN_HEADERS,
        )
        validate_error(too_late, ApiErrorId.MAKEUP_WINDOW_EXPIRED.value, 422)

        makeup = validate_success(
            api.create_visit(
                factories.visit_payload(
                    case.authorization_id,
                    *MAKEUP_IN_TIME,
                    makeup_for_visit_id=cancelled_id,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert makeup["makeup_for_visit_id"] == cancelled_id
        assert makeup["visit_status"] == "SCHEDULED"
        assert makeup["scheduled_units"] == 2

        second_makeup = api.create_visit(
            factories.visit_payload(
                case.authorization_id,
                *MAKEUP_SECOND_ATTEMPT,
                makeup_for_visit_id=cancelled_id,
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            second_makeup, ApiErrorId.MAKEUP_ALREADY_SCHEDULED.value, 409
        )

        line = read_service_line(api, case.line_id)
        assert line["makeup_owed_units"] == 2
        assert line["units_delivered"] == 2
        assert line["status"] == "IN_DELIVERY"
        assert read_referral(api, case.referral_id)["service_gap_flag"] is False

        listed, meta = validate_paginated(
            api.list_visits(ADMIN_HEADERS, {"makeup_for_visit_id": cancelled_id})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in listed] == [makeup["id"]]


# ─── The family-fee lifecycle from duplicate to waiver to verdict ─────

TIER_2_INCOME_CENTS = 19_470_000
DUPLICATE_MONTH = "2026-03"
HOUSEHOLD_SIZE = 4
ACCRUED_SHARE_CENTS = 1_300
ASSESSED_MONTHLY_FEE_CENTS = 5_200
TIER_2_CAP_CENTS = 30_000
FEE_VERIFICATION_DATE = "2026-03-25"


class TestFamilyFeeLifecycle:

    def test_duplicate_over_waiver_and_re_finalization_are_all_refused(self, api):
        """
        One month admits one live determination, a waiver may not exceed the
        current balance, and once the row is verified neither finalization nor a
        bare consent update may touch it again. Finalization re-prices the future
        without re-pricing the history already accrued.

        PRD 3.8: "A case may hold only one live determination per month: if another
        determination on the same case already governs the same `effective_month`
        in `PROVISIONAL` or `VERIFIED`, the request is refused with
        `ERR_COST_SHARE_DUPLICATE`."
        PRD 3.8: "The amount must be at least 1 cent and at most the
        determination's current `family_balance_cents`, or the request is refused
        with `ERR_WAIVE_EXCEEDS_BALANCE`."
        PRD 3.8: "On success `family_waived_cents` rises by the waived amount,
        `family_balance_cents` falls by the same amount, the `waiver_reason_code` is
        stored, and `total_assessed_cents` is deliberately left untouched — which is
        exactly how the identity `total_assessed_cents` equals
        `family_balance_cents` plus `family_waived_cents` survives the waiver."
        PRD 3.8: "Sessions already accrued keep the share they accrued:
        `total_assessed_cents`, `family_balance_cents` and `month_accrued_cents` all
        retain their pre-finalization values, which is precisely why the ledger
        identity of §2.10 continues to hold across the transition."
        PRD 3.8: "That capability takes `insurance_use_consent` and an optional
        `insurance_policy_id`, and updates both on the determination while it is
        still in `PROVISIONAL` — a row in any other status is refused with
        `ERR_COST_SHARE_NOT_PROVISIONAL`."

        Design: Corner/errors/family_fee_lifecycle_error_sweep
        """
        case = build_accrued_visit_case(
            api,
            cost_share={
                "effective_month": DUPLICATE_MONTH,
                "household_size": HOUSEHOLD_SIZE,
                "declared_annual_gross_income_cents": TIER_2_INCOME_CENTS,
            },
        )
        provisional = read_cost_share(api, case.cost_share_id)
        assert provisional["status"] == "PROVISIONAL"
        assert provisional["tier_code"] == "TIER_2"
        assert_cents(
            provisional["assessed_monthly_fee_cents"],
            ASSESSED_MONTHLY_FEE_CENTS,
            "assessed_monthly_fee_cents",
        )
        assert_ledger(provisional, ACCRUED_SHARE_CENTS, ACCRUED_SHARE_CENTS, 0)
        assert_cents(
            provisional["month_accrued_cents"],
            ACCRUED_SHARE_CENTS,
            "month_accrued_cents",
        )

        duplicate = api.create_cost_share(
            factories.cost_share_payload(
                case.referral_id,
                effective_month=DUPLICATE_MONTH,
                household_size=HOUSEHOLD_SIZE,
                declared_annual_gross_income_cents=TIER_2_INCOME_CENTS,
            ),
            FISCAL_HEADERS,
        )
        validate_error(duplicate, ApiErrorId.COST_SHARE_DUPLICATE.value, 409)

        over_balance = api.waive_cost_share(
            case.cost_share_id,
            factories.waive_payload(ACCRUED_SHARE_CENTS + 1),
            FISCAL_2_HEADERS,
        )
        validate_error(
            over_balance, ApiErrorId.WAIVE_EXCEEDS_BALANCE.value, 422
        )

        waived = validate_success(
            api.waive_cost_share(
                case.cost_share_id,
                factories.waive_payload(ACCRUED_SHARE_CENTS),
                FISCAL_2_HEADERS,
            ),
            200,
        )
        assert_ledger(waived, ACCRUED_SHARE_CENTS, 0, ACCRUED_SHARE_CENTS)
        assert_cents(
            waived["month_accrued_cents"], ACCRUED_SHARE_CENTS, "month_accrued_cents"
        )
        assert waived["waiver_reason_code"] == "HARDSHIP"

        verified = validate_success(
            api.finalize_cost_share(
                case.cost_share_id,
                factories.finalize_cost_share_payload(
                    TIER_2_INCOME_CENTS, FEE_VERIFICATION_DATE
                ),
                FISCAL_HEADERS,
            ),
            200,
        )
        assert verified["status"] == "VERIFIED"
        assert verified["tier_code"] == "TIER_2"
        assert_fpl_percent(verified["fpl_percent"], 600.0)
        assert round(float(verified["effective_coinsurance_rate"]), 2) == 0.10
        assert_cents(
            verified["monthly_cap_cents"], TIER_2_CAP_CENTS, "monthly_cap_cents"
        )
        assert_cents(verified["insurance_offset_cents"], 0, "insurance_offset_cents")
        assert_cents(
            verified["final_monthly_fee_cents"],
            ASSESSED_MONTHLY_FEE_CENTS,
            "final_monthly_fee_cents",
        )
        assert_ledger(verified, ACCRUED_SHARE_CENTS, 0, ACCRUED_SHARE_CENTS)

        re_finalized = api.finalize_cost_share(
            case.cost_share_id,
            factories.finalize_cost_share_payload(
                TIER_2_INCOME_CENTS, FEE_VERIFICATION_DATE
            ),
            FISCAL_HEADERS,
        )
        validate_error(
            re_finalized, ApiErrorId.COST_SHARE_NOT_PROVISIONAL.value, 409
        )

        late_consent = api.record_insurance_consent(
            case.cost_share_id,
            factories.insurance_consent_payload(
                insurance_use_consent=False
            ),
            FISCAL_HEADERS,
        )
        validate_error(
            late_consent, ApiErrorId.COST_SHARE_NOT_PROVISIONAL.value, 409
        )


# ─── The sign of the notification lead ────────────────────────────────

PAST_THIRD_BIRTHDAY_CLOCK = "2027-01-15T09:00:00Z"
THIRD_BIRTHDAY = "2027-01-10"
LATE_NOTIFICATION_DATE = THIRD_BIRTHDAY
NOTIFIED_LEA_CODE = "LEA_014"


class TestNotificationDeadlineSign:

    def test_a_negative_lead_is_refused_and_a_zero_lead_grades_late(self, api):
        """
        A notification dated after the child's third birthday is refused outright,
        while a notification landing exactly on the birthday is accepted with a
        lead of zero days and graded at the bottom of the scale.

        PRD 3.9: "`notification_lead_days` is the whole number of days from
        `notification_date` to the child's `third_birthday_date`. A negative lead — a
        notification dated after the third birthday — is refused with
        `ERR_NOTIFICATION_AFTER_THIRD_BIRTHDAY`."
        PRD 3.9: "Given a non-negative lead, the verdict follows in this order: an
        opted-out plan is `WAIVED_OPT_OUT`; otherwise a lead of more than 270 days is
        `EARLY`; otherwise a lead of at least 90 days is `TIMELY`; otherwise the
        notification is `LATE`."
        PRD 3.9: "On success `lea_code`, `notification_date`,
        `notification_lead_days` and `notification_compliance` are all stored."

        Design: Corner/errors/notification_after_third_birthday_and_late_verdict_sweep
        """
        case = build_transition_planning_case(api)
        # PRD 3.1 derives third_birthday_date on the Child, not the Referral.
        assert read_child(api, case.child_id)["third_birthday_date"] == THIRD_BIRTHDAY

        set_clock(api, PAST_THIRD_BIRTHDAY_CLOCK)
        negative_lead = api.notify_lea(
            case.transition_plan_id,
            factories.notify_lea_payload(
                PAST_THIRD_BIRTHDAY_CLOCK[:10], lea_code=NOTIFIED_LEA_CODE
            ),
            case.coordinator_headers,
        )
        validate_error(
            negative_lead,
            ApiErrorId.NOTIFICATION_AFTER_THIRD_BIRTHDAY.value,
            422,
        )
        still_draft = read_transition_plan(api, case.transition_plan_id)
        assert still_draft["status"] == "DRAFT"
        assert still_draft["notification_date"] is None
        assert still_draft["notification_lead_days"] is None
        assert still_draft["notification_compliance"] is None

        on_the_birthday = validate_success(
            api.notify_lea(
                case.transition_plan_id,
                factories.notify_lea_payload(
                    LATE_NOTIFICATION_DATE, lea_code=NOTIFIED_LEA_CODE
                ),
                case.coordinator_headers,
            ),
            200,
        )
        assert on_the_birthday["status"] == "NOTIFIED"
        assert on_the_birthday["notification_date"] == LATE_NOTIFICATION_DATE
        assert on_the_birthday["notification_lead_days"] == 0
        assert on_the_birthday["notification_compliance"] == "LATE"
        assert on_the_birthday["lea_code"] == NOTIFIED_LEA_CODE
        assert on_the_birthday["family_opt_out"] is False
