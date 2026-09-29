"""Formulas whose inputs interact rather than combine linearly."""

from test_helpers import (
    ComplianceWorld,
    assert_attestation_outcome,
    assert_decimal_2,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_passport_token,
    build_provider_with_customer,
    build_signing_ready_provider,
    expect_created,
)
from test_helpers.constants import NUMBER_1, NUMBER_CALLED
from test_helpers.factories import (
    call_attestation_payload,
    traffic_observation_payload,
)


def _build_high_risk_customer(world: ComplianceWorld):
    """A signing-ready provider whose only customer has just turned HIGH risk."""
    setup = build_signing_ready_provider(
        world, effective_from="2026-07-01T00:00:00Z"
    )
    observation = expect_created(
        world.client.create_traffic_observation(
            traffic_observation_payload(
                setup.provider_id,
                setup.customer_id,
                window_start="2026-07-01T00:00:00Z",
                window_end="2026-07-02T00:00:00Z",
                total_call_count=1000,
                short_duration_call_count=1000,
                unanswered_call_count=600,
                complaint_count=9,
            ),
            world.provider_admin(setup.provider_id),
        )
    )
    return setup, observation


class TestAttestationLadderOverFourInputs:
    """Posture, risk tier, evidence strength and ownership, resolved in order."""

    def test_risk_tier_high_stops_the_ladder_before_the_evidence_branches(self, world):
        """Registry-verified evidence with owned numbers still signs at C.

        PRD: "Otherwise, if `risk_tier` is `HIGH`, the level is `C` with reason `RISK_DOWNGRADE`. Recent traffic risk beats know-your-customer strength."

        Design: Difficulty/combinatorial_formula/attestation_ladder_nonlinear_precedence_over_four_inputs
        """
        setup, _ = _build_high_risk_customer(world)

        attestation = expect_created(
            world.client.create_call_attestation(
                call_attestation_payload(
                    setup.provider_id,
                    setup.customer_id,
                    NUMBER_1,
                    NUMBER_CALLED,
                    "2026-08-01T00:00:00Z",
                ),
                world.provider_admin(setup.provider_id),
            )
        )

        assert_attestation_outcome(
            attestation,
            level="C",
            reason_code="RISK_DOWNGRADE",
            ownership_verified=True,
            risk_tier_at_signing="HIGH",
        )
        assert_passport_token(attestation, setup.certificate_id, "C")

    def test_the_downgrading_index_sits_below_the_origination_cut_off(self, world):
        """An index of exactly 0.7500 caps the level without stopping origination.

        PRD: "Note the two distinct thresholds: 0.7500 makes a customer `HIGH` risk and therefore caps its calls at attestation level `C`, while the higher 0.9000 stops it originating at all."

        Design: Difficulty/combinatorial_formula/attestation_ladder_nonlinear_precedence_over_four_inputs
        """
        setup, observation = _build_high_risk_customer(world)

        assert_decimal_2(observation, "window_subscore", 0.75)
        assert_decimal_4(observation, "resulting_risk_index", 0.7500)
        assert_equals(observation, "triggered_suspension", False)

        customer = world.read_customer(setup.customer_id)
        assert_decimal_4(customer, "traffic_risk_index", 0.7500)
        assert_fields(customer, risk_tier="HIGH", origination_state="ENABLED")

        provider = world.read_provider(setup.provider_id)
        assert_equals(provider, "auth_posture", "FULL_ATTESTATION")


def _record(world: ComplianceWorld, provider_id: str, customer_id: str, **window):
    return expect_created(
        world.client.create_traffic_observation(
            traffic_observation_payload(provider_id, customer_id, **window),
            world.provider_admin(provider_id),
        )
    )


def _build_two_monitored_windows(world: ComplianceWorld):
    """Two recorded windows subscoring 0.62 and 0.38 on one customer."""
    setup = build_provider_with_customer(
        world,
        provider_type="NON_FACILITIES_RESELLER",
        kyc_evidence_level="CONTRACT_ONLY",
    )
    first = _record(
        world,
        setup.provider_id,
        setup.customer_id,
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-07-02T00:00:00Z",
        total_call_count=1000,
        short_duration_call_count=800,
        unanswered_call_count=600,
        complaint_count=5,
    )
    second = _record(
        world,
        setup.provider_id,
        setup.customer_id,
        window_start="2026-07-03T00:00:00Z",
        window_end="2026-07-04T00:00:00Z",
        total_call_count=3,
        short_duration_call_count=1,
        unanswered_call_count=2,
        complaint_count=0,
    )
    return setup, first, second


class TestRiskIndexRoundsPerWindow:
    """Per-window rounding first, recency weighting second."""

    def test_third_window_weights_the_stored_two_decimal_subscores(self, world):
        """0.62, 0.38 and 1.00 weight to 0.7380 rather than to 0.7390.

        PRD: "The two-stage rounding is observable and mandatory: three windows scoring 0.62, 0.38 and 1.00 under the per-window rounding yield an index of 0.7380, whereas carrying the raw unrounded values all the way through would yield 0.7390."

        Design: Difficulty/combinatorial_formula/risk_index_rounds_per_window_before_recency_weighting
        """
        setup, first, second = _build_two_monitored_windows(world)

        third = _record(
            world,
            setup.provider_id,
            setup.customer_id,
            window_start="2026-07-05T00:00:00Z",
            window_end="2026-07-06T00:00:00Z",
            total_call_count=7,
            short_duration_call_count=7,
            unanswered_call_count=7,
            complaint_count=1,
        )

        assert_decimal_2(first, "window_subscore", 0.62)
        assert_decimal_2(second, "window_subscore", 0.38)
        assert_decimal_2(third, "window_subscore", 1.00)
        assert_decimal_4(third, "resulting_risk_index", 0.7380)
        assert_equals(third, "triggered_suspension", False)

        customer = world.read_customer(setup.customer_id)
        assert_decimal_4(customer, "traffic_risk_index", 0.7380)
        assert customer["traffic_risk_index"] != 0.7390, (
            "traffic_risk_index 0.7390 means the raw unrounded subscores were "
            "carried through the recency weighting"
        )
        assert_fields(customer, risk_tier="ELEVATED", observation_count=3)

    def test_two_windows_renormalise_over_the_weights_actually_used(self, world):
        """0.38 and 0.62 under weights 0.50 and 0.30 renormalise to 0.4700.

        PRD: "If the customer has fewer than three observations, use only the leading weights — one observation uses only the first, two use the first and second — and renormalise by dividing by the sum of the weights actually used."

        Design: Difficulty/combinatorial_formula/risk_index_rounds_per_window_before_recency_weighting
        """
        setup, first, second = _build_two_monitored_windows(world)

        assert_decimal_4(first, "resulting_risk_index", 0.6200)
        assert_decimal_4(second, "resulting_risk_index", 0.4700)

        customer = world.read_customer(setup.customer_id)
        assert_decimal_4(customer, "traffic_risk_index", 0.4700)
        assert_fields(customer, risk_tier="ELEVATED", observation_count=2)
