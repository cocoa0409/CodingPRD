"""Derived quantities: attestation levels, risk indices, forfeitures and scores."""

from test_helpers import (
    ComplianceWorld,
    OFFICER_1,
    OFFICER_2,
    assert_attestation_outcome,
    assert_cents,
    assert_decimal_2,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_instant,
    assert_null,
    assert_passport_token,
    assert_provider_counters,
    build_signing_ready_provider,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import ERR_NO_ACTIVE_CERTIFICATE
from test_helpers.constants import (
    NUMBER_1,
    NUMBER_2,
    NUMBER_4,
    NUMBER_CALLED,
    NUMBER_CALLED_ALT,
)
from test_helpers.factories import (
    call_attestation_payload,
    enforcement_action_payload,
    revocation_payload,
    traceback_response_payload,
    traffic_observation_payload,
)


def _signing_ready_without_assignment(
    world: ComplianceWorld, kyc_evidence_level: str = "BUSINESS_REGISTRY_VERIFIED"
):
    """A provider cleared to sign whose customer holds no number assignment."""
    provider = world.register_provider()
    certificate = world.active_certificate(provider["id"])
    world.accepted_plan(provider["id"], officer_id=OFFICER_1)
    customer = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level=kyc_evidence_level
    )
    return provider["id"], certificate["id"], customer["id"]


class TestAttestationLadderArithmetic:
    """Which rung of the seven-step ladder a signing request lands on."""

    def test_strong_kyc_without_owned_number_signs_at_level_b(self, world):
        """Registry-verified evidence over an unowned number stops at rung four.

        PRD: "Otherwise, if `kyc_evidence_level` is `BUSINESS_REGISTRY_VERIFIED` and `ownership_verified` is false, the level is `B` with reason `KYC_ONLY_NO_OWNERSHIP`."

        Design: Corner/calculations/attestation_level_b_when_kyc_is_strong_but_ownership_unverified
        """
        world.set_clock("2026-08-04T00:00:00Z")
        provider_id, certificate_id, customer_id = _signing_ready_without_assignment(
            world
        )

        attestation = expect_created(
            world.client.create_call_attestation(
                call_attestation_payload(
                    provider_id,
                    customer_id,
                    NUMBER_4,
                    NUMBER_CALLED,
                    "2026-08-04T01:00:00Z",
                ),
                world.provider_admin(provider_id),
            )
        )

        assert_attestation_outcome(
            attestation, "B", "KYC_ONLY_NO_OWNERSHIP", False, "LOW"
        )
        assert_passport_token(attestation, certificate_id, "B")
        assert_equals(
            world.read_provider(provider_id), "auth_posture", "FULL_ATTESTATION"
        )


class TestTrafficRiskIndexInputSet:
    """The recency depth is a filter on the input set, not an extra weight."""

    def test_the_fourth_oldest_window_drops_out_of_the_index(self, world):
        """A fourth window pushes the worst window out entirely, giving 0.3680.

        PRD: "Take the customer's three observations with the greatest `window_end`, ordered by `window_end` descending, breaking any tie on `created_at` ascending and never on `id`."

        Design: Corner/calculations/risk_index_ignores_the_fourth_oldest_observation_window
        """
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="CONTRACT_ONLY"
        )
        first = world.record_observation(
            provider["id"],
            customer["id"],
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-02T00:00:00Z",
            total_call_count=1000,
            short_duration_call_count=1000,
            unanswered_call_count=1000,
            complaint_count=100,
        )
        second = world.record_observation(
            provider["id"],
            customer["id"],
            window_start="2026-07-05T00:00:00Z",
            window_end="2026-07-06T00:00:00Z",
            total_call_count=1000,
            short_duration_call_count=200,
            unanswered_call_count=200,
            complaint_count=0,
        )
        third = world.record_observation(
            provider["id"],
            customer["id"],
            window_start="2026-07-10T00:00:00Z",
            window_end="2026-07-11T00:00:00Z",
            total_call_count=1000,
            short_duration_call_count=400,
            unanswered_call_count=400,
            complaint_count=0,
        )

        fourth = expect_created(
            world.client.create_traffic_observation(
                traffic_observation_payload(
                    provider["id"],
                    customer["id"],
                    window_start="2026-07-15T00:00:00Z",
                    window_end="2026-07-16T00:00:00Z",
                    total_call_count=1000,
                    short_duration_call_count=600,
                    unanswered_call_count=600,
                    complaint_count=0,
                ),
                world.provider_admin(provider["id"]),
            )
        )

        assert_decimal_2(first, "window_subscore", 1.00)
        assert_decimal_2(second, "window_subscore", 0.16)
        assert_decimal_2(third, "window_subscore", 0.32)
        assert_decimal_2(fourth, "window_subscore", 0.48)
        assert_decimal_4(first, "resulting_risk_index", 1.0000)
        assert_decimal_4(second, "resulting_risk_index", 0.4750)
        assert_decimal_4(third, "resulting_risk_index", 0.4080)
        assert_decimal_4(fourth, "resulting_risk_index", 0.3680)
        assert_equals(first, "triggered_suspension", False)

        refreshed = world.read_customer(customer["id"])
        assert_fields(refreshed, risk_tier="LOW", observation_count=4)
        assert_decimal_4(refreshed, "traffic_risk_index", 0.3680)


class TestForfeitureArithmetic:
    """Base, cap, tier and credit, in that order."""

    def test_an_uncertified_report_leaves_the_action_at_band_none(self, world):
        """A GENERATED report is no report at all, so no credit reduces the base.

        PRD: "Reports still in `GENERATED`, and reports that have been `SUPERSEDED`, are ignored — which is why a provider that generated a flattering report but never certified it is treated as having no report at all, and its `score_band` on the action reads `NONE` with zero credit."

        Design: Corner/calculations/forfeiture_ignores_a_generated_report_and_uses_band_none
        """
        provider = world.register_provider(provider_type="NON_FACILITIES_RESELLER")
        report = world.generate_report(
            provider["id"],
            variant="CERTIFIED",
            officer_id=OFFICER_1,
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        )
        assert_fields(report, state="GENERATED", score_band="MID")

        action = expect_created(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    provider["id"],
                    basis="UNFILED_PLAN",
                    violation_count=3,
                    violation_days=10,
                    assessment_basis="PER_VIOLATION",
                ),
                world.regulator,
            )
        )

        assert_fields(action, score_band="NONE", assessment_tier="TIER_2")
        assert_cents(action, "base_assessment_cents", 3000000)
        assert_cents(action, "mitigation_credit_cents", 0)
        assert_cents(action, "total_forfeiture_cents", 3000000)
        assert_provider_counters(
            world.read_provider(provider["id"]), outstanding_forfeiture_cents=3000000
        )

    def test_the_tier_ceilings_are_inclusive_across_all_three_tiers(self, world):
        """Eight continuing days sit exactly on the TIER_1 ceiling; nine cross it.

        PRD: "Third, `assessment_tier`, which is keyed on `base_capped_cents` — that is, **after the cap and before any credit**: `TIER_1` when `base_capped_cents` is at most two million cents, `TIER_2` when it is at most twenty million cents, and `TIER_3` above that."

        Design: Corner/calculations/forfeiture_tier_boundaries_across_all_three_tiers
        """
        world.set_clock("2026-08-10T00:00:00Z")
        provider = world.register_provider(provider_type="GATEWAY")

        actions = [
            expect_created(
                world.client.create_enforcement_action(
                    enforcement_action_payload(
                        provider["id"],
                        basis="UNMITIGATED_NOTICE",
                        violation_count=1,
                        violation_days=days,
                        assessment_basis="CONTINUING_DAILY",
                    ),
                    world.regulator,
                )
            )
            for days in (8, 9, 81)
        ]

        expected = ((2000000, "TIER_1"), (2250000, "TIER_2"), (20250000, "TIER_3"))
        for action, (base, tier) in zip(actions, expected):
            assert_fields(action, assessment_tier=tier, score_band="NONE")
            assert_cents(action, "base_assessment_cents", base)
            assert_cents(action, "base_capped_cents", base)
            assert_cents(action, "mitigation_credit_cents", 0)
            assert_cents(action, "total_forfeiture_cents", base)

        assert_provider_counters(
            world.read_provider(provider["id"]), outstanding_forfeiture_cents=24500000
        )

    def test_the_statutory_cap_bites_before_the_tier_three_credit(self, world):
        """150 violations cap at 100,000,000 and the HIGH credit is taken on the cap.

        PRD: "The third case shows the cap biting first: 150 violations under `PER_VIOLATION` produce 150,000,000 cents, capped to 100,000,000, which is `TIER_3`; a `HIGH` band earns 15 percent or 15,000,000 cents, leaving a total of 85,000,000."

        Design: Corner/calculations/forfeiture_caps_the_base_before_applying_the_tier3_credit
        """
        world.set_clock("2026-08-02T00:00:00Z")
        setup = build_signing_ready_provider(world)
        attestation = world.sign_call(
            setup.provider_id,
            setup.customer_id,
            NUMBER_1,
            NUMBER_CALLED,
            "2026-08-02T01:00:00Z",
        )
        assert_equals(attestation, "attestation_level", "A")
        world.set_clock("2026-09-01T00:00:00Z")
        report = world.generate_report(
            setup.provider_id, variant="CERTIFIED", officer_id=OFFICER_2
        )
        signed_off = world.certify_report(report["id"], OFFICER_2)
        assert_fields(signed_off, state="SIGNED_OFF", score_band="HIGH")
        assert_decimal_4(signed_off, "effectiveness_score", 1.0000)

        action = expect_created(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    setup.provider_id,
                    basis="FALSE_ATTESTATION",
                    violation_count=150,
                    violation_days=1,
                    assessment_basis="PER_VIOLATION",
                ),
                world.regulator,
            )
        )

        assert_fields(action, assessment_tier="TIER_3", score_band="HIGH")
        assert_cents(action, "base_assessment_cents", 150000000)
        assert_cents(action, "base_capped_cents", 100000000)
        assert_cents(action, "mitigation_credit_cents", 15000000)
        assert_cents(action, "total_forfeiture_cents", 85000000)
        assert_provider_counters(
            world.read_provider(setup.provider_id),
            outstanding_forfeiture_cents=85000000,
        )


class TestTracebackTimelinessArithmetic:
    """The two inclusive response boundaries and the points they charge."""

    def test_the_deadline_and_the_hard_cutoff_are_both_inclusive(self, world):
        """Answering on the deadline is on time; answering on the cutoff is 172800 late.

        PRD: "As a worked timeline: with `received_at` at `2026-08-05T00:00:00Z`, answering at `2026-08-06T00:00:00Z` is `RESPONDED` with `lateness_seconds` 0; answering one second later is `RESPONDED_LATE` with `lateness_seconds` 1; answering at exactly `2026-08-08T00:00:00Z` is accepted as `RESPONDED_LATE` with `lateness_seconds` 172800; and one second after that the response is refused."

        Design: Corner/calculations/traceback_lateness_at_the_deadline_and_at_the_hard_cutoff
        """
        world.set_clock("2026-08-04T00:00:00Z")
        setup = build_signing_ready_provider(world)
        first_call = world.sign_call(
            setup.provider_id,
            setup.customer_id,
            NUMBER_1,
            NUMBER_CALLED,
            "2026-08-04T01:00:00Z",
        )
        second_call = world.sign_call(
            setup.provider_id,
            setup.customer_id,
            NUMBER_1,
            NUMBER_CALLED_ALT,
            "2026-08-04T02:00:00Z",
        )
        world.set_clock("2026-08-05T00:00:00Z")
        first_traceback = world.open_traceback(
            setup.provider_id,
            calling_number=NUMBER_1,
            called_number=NUMBER_CALLED,
            origination_time="2026-08-04T01:00:00Z",
        )
        second_traceback = world.open_traceback(
            setup.provider_id,
            calling_number=NUMBER_1,
            called_number=NUMBER_CALLED_ALT,
            origination_time="2026-08-04T02:00:00Z",
        )
        assert_instant(
            first_traceback, "response_deadline_at", "2026-08-06T00:00:00Z"
        )
        assert_instant(first_traceback, "hard_cutoff_at", "2026-08-08T00:00:00Z")

        world.set_clock("2026-08-06T00:00:00Z")
        on_time = expect_ok(
            world.client.respond_traceback_request(
                first_traceback["id"],
                traceback_response_payload(setup.customer_id, first_call["id"]),
                world.officer(OFFICER_1),
            )
        )
        world.set_clock("2026-08-08T00:00:00Z")
        late = expect_ok(
            world.client.respond_traceback_request(
                second_traceback["id"],
                traceback_response_payload(setup.customer_id, second_call["id"]),
                world.officer(OFFICER_1),
            )
        )

        assert_fields(
            on_time, state="RESPONDED", lateness_seconds=0, call_detail_complete=True
        )
        assert_fields(late, state="RESPONDED_LATE", lateness_seconds=172800)

        provider = world.read_provider(setup.provider_id)
        assert_provider_counters(
            provider, penalty_points=3, overdue_traceback_count=0
        )
        assert_equals(provider, "auth_posture", "FULL_ATTESTATION")


class TestPostureAndScoreReconciliation:
    """Recomputations that ripple out of one transition."""

    def test_revoking_the_active_certificate_stops_signing_at_the_pointer(self, world):
        """The posture falls to suspended while the filing status stays complete.

        PRD: "When the certificate being revoked was the provider's active one, the operation also nulls `active_certificate_id`, and the posture ladder therefore stops at step one and drives `auth_posture` to `SIGNING_SUSPENDED` — again leaving `rmd_filing_status` untouched, because filing completeness is a plan property, not a certificate property."

        Design: Corner/calculations/certificate_revocation_propagates_to_posture_and_blocks_signing
        """
        world.set_clock("2026-08-04T00:00:00Z")
        setup = build_signing_ready_provider(world)

        revoked = expect_ok(
            world.client.revoke_certificate(
                setup.certificate_id,
                revocation_payload("SPC_WITHDRAWN"),
                world.policy_admin,
            )
        )
        expect_error(
            world.client.create_call_attestation(
                call_attestation_payload(
                    setup.provider_id,
                    setup.customer_id,
                    NUMBER_2,
                    NUMBER_CALLED,
                    "2026-08-04T03:00:00Z",
                ),
                world.provider_admin(setup.provider_id),
            ),
            ERR_NO_ACTIVE_CERTIFICATE,
        )

        assert_equals(revoked, "status", "REVOKED")
        assert_instant(revoked, "revoked_at", "2026-08-04T00:00:00Z")

        provider = world.read_provider(setup.provider_id)
        assert_null(provider, "active_certificate_id")
        assert_fields(
            provider, auth_posture="SIGNING_SUSPENDED", rmd_filing_status="COMPLETE"
        )
        assert_provider_counters(provider, penalty_points=0)
        expect_list_total(
            world.client.list_call_attestations(
                world.regulator, provider_id=setup.provider_id
            ),
            0,
        )

    def test_certification_recomputes_the_score_and_the_later_credit(self, world):
        """The pending traceback leaves the numerator in place, taking 0.6000 to 0.2500.

        PRD: "Sign-off advances `GENERATED → SIGNED_OFF`, records the signing officer's `X-User-ID` as `signed_off_by_user_id`, stamps `signed_off_at`, **overwrites `variant` with `CERTIFIED`**, and recomputes every count, every component, the `effectiveness_score`, the `score_band` and `data_sufficiency` in place under that variant."

        Design: Corner/calculations/certifying_a_report_reconciles_the_score_and_the_later_credit
        """
        provider = world.register_provider(provider_type="NON_FACILITIES_RESELLER")
        plan = world.draft_plan(provider["id"], officer_id=OFFICER_1)
        world.submit_plan(plan["id"], OFFICER_1)
        world.decide_plan(plan["id"], decision="ACCEPT")
        world.set_clock("2026-08-31T12:00:00Z")
        traceback = world.open_traceback(
            provider["id"],
            calling_number=NUMBER_1,
            called_number=NUMBER_CALLED,
            origination_time="2026-08-15T00:00:00Z",
        )
        world.set_clock("2026-09-01T00:00:00Z")
        provisional = world.generate_report(
            provider["id"], variant="PROVISIONAL", officer_id=OFFICER_2
        )
        assert_decimal_4(provisional, "effectiveness_score", 0.6000)
        assert_equals(provisional, "score_band", "MID")

        certified = expect_ok(
            world.client.certify_effectiveness_report(
                provisional["id"], world.officer(OFFICER_2)
            )
        )

        assert_fields(
            certified,
            state="SIGNED_OFF",
            variant="CERTIFIED",
            score_band="LOW",
            data_sufficiency="INSUFFICIENT",
            signed_off_by_user_id=OFFICER_2,
        )
        assert_decimal_4(certified, "attestation_component", 0.0000)
        assert_decimal_4(certified, "traceback_component", 0.0000)
        assert_decimal_4(certified, "notice_component", 1.0000)
        assert_decimal_4(certified, "effectiveness_score", 0.2500)
        assert_equals(world.read_traceback(traceback["id"]), "state", "RECEIVED")

        action = expect_created(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    provider["id"],
                    basis="LATE_TRACEBACK",
                    violation_count=3,
                    violation_days=1,
                    assessment_basis="PER_VIOLATION",
                ),
                world.regulator,
            )
        )
        assert_fields(action, assessment_tier="TIER_2", score_band="LOW")
        assert_cents(action, "mitigation_credit_cents", 150000)
        assert_cents(action, "total_forfeiture_cents", 2850000)
