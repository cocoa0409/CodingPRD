"""Input, temporal and cross-entity rules, and the order they are surfaced in."""

from test_helpers import (
    OFFICER_1,
    OFFICER_7,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_instant,
    assert_null,
    assert_provider_counters,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import (
    ERR_CUSTOMER_NOT_KYC_VERIFIED,
    ERR_CUSTOMER_PROVIDER_MISMATCH,
    ERR_ORIGINATION_NOT_ENABLED,
    ERR_PRACTICES_INSUFFICIENT,
    ERR_REPORT_PERIOD_NOT_ELAPSED,
    ERR_WINDOW_IN_FUTURE,
)
from test_helpers.constants import (
    CLOCK_DEFAULT,
    MINIMUM_COMPLIANT_PRACTICES,
    NUMBER_1,
)
from test_helpers.factories import (
    effectiveness_report_payload,
    notice_investigation_payload,
    number_assignment_payload,
    origination_action_payload,
    traffic_observation_payload,
)


class TestPlanPracticeAudit:
    """The practice list is audited at submission, never at drafting."""

    def test_a_practice_set_without_traceback_cooperation_is_refused(self, world):
        """Three practices are not enough when a mandatory one is missing.

        PRD: "A list that is shorter than three elements, or that omits either mandatory practice, is refused with `ERR_PRACTICES_INSUFFICIENT` (422) — so a three-element list of `TRAFFIC_PATTERN_MONITORING`, `CONTRACT_TERMS_PROHIBITION` and `CALL_BLOCKING_ANALYTICS` fails despite being long enough."

        Design: Corner/validations/plan_submit_rejects_a_practice_set_missing_traceback_cooperation
        """
        provider = world.register_provider()
        plan = world.draft_plan(
            provider["id"],
            practices=[
                "KYC_ONBOARDING",
                "TRAFFIC_PATTERN_MONITORING",
                "CALL_BLOCKING_ANALYTICS",
            ],
        )

        expect_error(
            world.client.submit_mitigation_plan(plan["id"], world.officer(OFFICER_1)),
            ERR_PRACTICES_INSUFFICIENT,
        )

        unchanged = world.read_plan(plan["id"])
        assert_fields(unchanged, filing_state="DRAFT", revision_count=0)
        assert_null(unchanged, "submitted_at")
        assert_null(unchanged, "filed_by_user_id")
        assert_equals(
            world.read_provider(provider["id"]), "rmd_filing_status", "UNFILED"
        )

    def test_the_minimum_compliant_practice_set_files_the_plan(self, world):
        """Exactly three practices including both mandatory ones stamp the filing.

        PRD: "A successful submission stamps `submitted_at` with the current logical clock and records the submitting officer's `X-User-ID` as `filed_by_user_id`, which is the value the report sign-off gate in §2.12 will later compare against."

        Design: Corner/validations/plan_submit_passes_with_the_minimum_compliant_practice_set
        """
        provider = world.register_provider()
        plan = world.draft_plan(
            provider["id"],
            practices=list(MINIMUM_COMPLIANT_PRACTICES),
            officer_id=OFFICER_7,
        )

        submitted = expect_ok(
            world.client.submit_mitigation_plan(plan["id"], world.officer(OFFICER_7))
        )

        assert_equals(submitted, "filing_state", "SUBMITTED")
        assert_instant(submitted, "submitted_at", CLOCK_DEFAULT)
        assert_equals(submitted, "filed_by_user_id", OFFICER_7)

        refreshed = world.read_provider(provider["id"])
        assert_fields(
            refreshed,
            rmd_filing_status="PARTIAL",
            auth_posture="SIGNING_SUSPENDED",
        )


class TestCrossEntityAttribution:
    """A rule whose truth lives on a second entity's provider_id."""

    def test_a_notice_cannot_be_attributed_to_another_providers_customer(self, world):
        """The foreign attribution is refused, then the provider's own one succeeds.

        PRD: "The named customer must belong to the notice's own provider, or the attribution is refused with `ERR_CUSTOMER_PROVIDER_MISMATCH` (422)."

        Design: Corner/validations/notice_investigation_rejects_a_customer_of_another_provider
        """
        world.set_clock("2026-08-10T00:00:00Z")
        first = world.register_provider(provider_type="GATEWAY")
        second = world.register_provider(provider_type="GATEWAY")
        own_customer = world.onboard_customer(
            first["id"], kyc_evidence_level="CONTRACT_ONLY"
        )
        foreign_customer = world.onboard_customer(
            second["id"], kyc_evidence_level="CONTRACT_ONLY"
        )
        notice = world.serve_notice(first["id"], calling_number=NUMBER_1)

        expect_error(
            world.client.investigate_notice(
                notice["id"],
                notice_investigation_payload(foreign_customer["id"]),
                world.officer(OFFICER_1),
            ),
            ERR_CUSTOMER_PROVIDER_MISMATCH,
        )
        blocked = world.read_notice(notice["id"])
        assert_equals(blocked, "state", "NOTIFIED")
        assert_null(blocked, "customer_id")

        investigated = expect_ok(
            world.client.investigate_notice(
                notice["id"],
                notice_investigation_payload(own_customer["id"]),
                world.officer(OFFICER_1),
            )
        )

        assert_fields(
            investigated,
            state="UNDER_INVESTIGATION",
            customer_id=own_customer["id"],
        )
        assert_instant(
            investigated, "mitigation_deadline_at", "2026-08-12T00:00:00Z"
        )
        assert_provider_counters(
            world.read_provider(first["id"]), open_notice_count=1
        )
        assert_provider_counters(
            world.read_provider(second["id"]), open_notice_count=0
        )


class TestTemporalBounds:
    """Windows and reporting periods may touch the clock but not pass it."""

    def test_a_monitoring_window_may_not_end_after_the_clock(self, world):
        """One second past the clock is refused and no window is stored.

        PRD: "Two further temporal rules apply: `window_start` must be strictly earlier than `window_end` or the refusal is `ERR_INVALID_INTERVAL` (422), and `window_end` must be at or before the current logical clock — there are no observations about the future — or the refusal is `ERR_WINDOW_IN_FUTURE` (422)."

        Design: Corner/validations/observation_with_a_future_window_end_is_rejected
        """
        world.set_clock("2026-08-10T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="CONTRACT_ONLY"
        )

        expect_error(
            world.client.create_traffic_observation(
                traffic_observation_payload(
                    provider["id"],
                    customer["id"],
                    window_start="2026-08-09T00:00:00Z",
                    window_end="2026-08-10T00:00:01Z",
                    total_call_count=100,
                    short_duration_call_count=90,
                    unanswered_call_count=90,
                    complaint_count=5,
                ),
                world.provider_admin(provider["id"]),
            ),
            ERR_WINDOW_IN_FUTURE,
        )

        refreshed = world.read_customer(customer["id"])
        assert_fields(refreshed, observation_count=0, risk_tier="LOW")
        assert_decimal_4(refreshed, "traffic_risk_index", 0.0)
        expect_list_total(
            world.client.list_traffic_observations(
                world.regulator, customer_id=customer["id"]
            ),
            0,
        )

    def test_a_reporting_period_ending_on_the_clock_is_elapsed(self, world):
        """One second early is refused; at the boundary instant the report generates.

        PRD: "`period_start` must be strictly earlier than `period_end`, or the refusal is `ERR_INVALID_INTERVAL`, and `period_end` must be at or before the current logical clock so that the reported period has fully elapsed — a period extending into the future is refused with `ERR_REPORT_PERIOD_NOT_ELAPSED` (422), a code raised by report generation alone."

        Design: Corner/validations/report_generation_for_a_period_that_has_not_elapsed_is_rejected
        """
        world.set_clock("2026-08-31T23:59:59Z")
        provider = world.register_provider(provider_type="NON_FACILITIES_RESELLER")
        version = world.provider_version(provider["id"])
        payload = effectiveness_report_payload(
            provider["id"],
            version,
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            variant="PROVISIONAL",
        )

        expect_error(
            world.client.create_effectiveness_report(payload, world.officer(OFFICER_1)),
            ERR_REPORT_PERIOD_NOT_ELAPSED,
        )
        expect_list_total(
            world.client.list_effectiveness_reports(
                world.regulator, provider_id=provider["id"]
            ),
            0,
        )

        world.set_clock("2026-09-01T00:00:00Z")
        report = expect_created(
            world.client.create_effectiveness_report(payload, world.officer(OFFICER_1))
        )

        assert_fields(
            report,
            state="GENERATED",
            score_band="MID",
            data_sufficiency="INSUFFICIENT",
        )
        assert_decimal_4(report, "effectiveness_score", 0.6000)


class TestCheckScoping:
    """Which branch a gate guards, and which of two violated gates speaks first."""

    def test_the_kyc_gate_guards_enable_but_not_terminate(self, world):
        """The same unverified customer is refused ENABLE and granted TERMINATE.

        PRD: "`ENABLE` is available only from `DISABLED` and only for a customer whose `kyc_state` is `VERIFIED`; an attempt on an unverified customer is refused with `ERR_CUSTOMER_NOT_KYC_VERIFIED` (422)."

        Design: Corner/validations/kyc_gate_applies_to_enable_but_not_to_terminate
        """
        world.set_clock("2026-08-10T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="SELF_ATTESTED"
        )

        expect_error(
            world.client.origination_action(
                customer["id"],
                origination_action_payload("ENABLE"),
                world.provider_admin(provider["id"]),
            ),
            ERR_CUSTOMER_NOT_KYC_VERIFIED,
        )
        still_disabled = world.read_customer(customer["id"])
        assert_fields(
            still_disabled, origination_state="DISABLED", kyc_state="PENDING"
        )

        terminated = expect_ok(
            world.client.origination_action(
                customer["id"],
                origination_action_payload("TERMINATE"),
                world.provider_admin(provider["id"]),
            )
        )

        assert_fields(
            terminated, origination_state="TERMINATED", kyc_state="PENDING"
        )
        assert_provider_counters(
            world.read_provider(provider["id"]), active_assigned_number_count=0
        )

    def test_the_kyc_refusal_precedes_the_origination_refusal(self, world):
        """Both gates are violated, and the lower-numbered rule answers first.

        PRD: "12. **Business rules**, in this exact relative order: `ERR_PRACTICES_INSUFFICIENT`, then `ERR_SIGNING_SUSPENDED`, then `ERR_CUSTOMER_NOT_KYC_VERIFIED`, then `ERR_ORIGINATION_NOT_ENABLED`, then `ERR_SUSPENSION_CAUSE_NOT_SELF_CLEARABLE`, then `ERR_SCORE_BELOW_BLOCKING_THRESHOLD`, then `ERR_RESPONSE_WINDOW_CLOSED`, then `ERR_WINDOW_IN_FUTURE`, then `ERR_REPORT_PERIOD_NOT_ELAPSED`, then `ERR_NUMBER_INTERVAL_OVERLAP`, then `ERR_OBSERVATION_WINDOW_OVERLAP`, then `ERR_DUPLICATE_DISPUTE`, then `ERR_CUSTOMER_PROVIDER_MISMATCH`, then `ERR_CALL_DETAIL_MISMATCH`, then `ERR_CALL_DETAIL_INCOMPLETE`, and finally `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/validations/assignment_surfaces_the_kyc_check_before_the_origination_check
        """
        world.set_clock("2026-08-10T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="CONTRACT_ONLY"
        )
        payload = number_assignment_payload(
            provider["id"],
            customer["id"],
            telephone_number=NUMBER_1,
            ownership_evidence="DIRECT_ALLOCATION",
            effective_from=CLOCK_DEFAULT,
        )

        expect_error(
            world.client.create_number_assignment(
                payload, world.provider_admin(provider["id"])
            ),
            ERR_CUSTOMER_NOT_KYC_VERIFIED,
        )
        world.kyc_submit(customer["id"])
        world.kyc_decide(customer["id"], decision="VERIFY")

        expect_error(
            world.client.create_number_assignment(
                payload, world.provider_admin(provider["id"])
            ),
            ERR_ORIGINATION_NOT_ENABLED,
        )

        refreshed = world.read_customer(customer["id"])
        assert_fields(refreshed, kyc_state="VERIFIED", origination_state="DISABLED")
        expect_list_total(
            world.client.list_number_assignments(
                world.regulator, customer_id=customer["id"]
            ),
            0,
        )
        assert_provider_counters(
            world.read_provider(provider["id"]), active_assigned_number_count=0
        )
