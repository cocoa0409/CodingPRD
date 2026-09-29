"""Values landing exactly on a threshold, and one hundredth below it."""

from test_helpers import (
    ComplianceWorld,
    OFFICER_1,
    OFFICER_2,
    assert_cents,
    assert_decimal_2,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_provider_counters,
    expect_created,
    expect_ok,
)
from test_helpers.constants import NUMBER_1, NUMBER_2
from test_helpers.factories import (
    effectiveness_report_payload,
    enforcement_action_payload,
    traffic_observation_payload,
)


def _build_two_monitored_customers(world: ComplianceWorld):
    """One provider, two enabled customers, one number each."""
    provider = world.register_provider()
    customer_a = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
    )
    assignment_a = world.assign_number(provider["id"], customer_a["id"], NUMBER_1)
    customer_b = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
    )
    assignment_b = world.assign_number(provider["id"], customer_b["id"], NUMBER_2)
    return provider["id"], (customer_a, assignment_a), (customer_b, assignment_b)


def _observe(world: ComplianceWorld, provider_id: str, customer_id: str, **counts):
    return expect_created(
        world.client.create_traffic_observation(
            traffic_observation_payload(
                provider_id,
                customer_id,
                window_start="2026-07-01T00:00:00Z",
                window_end="2026-07-02T00:00:00Z",
                **counts,
            ),
            world.provider_admin(provider_id),
        )
    )


class TestRiskIndexAutoSuspendThreshold:
    """The auto-suspend threshold is inclusive at 0.9000."""

    def test_an_index_of_exactly_the_threshold_suspends_origination(self, world):
        """0.9000 exactly triggers the suspension and empties the active inventory.

        PRD: "Two fields on the observation itself capture the outcome: `resulting_risk_index` is a snapshot of the customer's `traffic_risk_index` immediately after this window was folded in, and `triggered_suspension` is true exactly when this observation drove the index to 0.9000 or above while the customer's `origination_state` was `ENABLED` — in which case the customer is suspended with `suspension_cause` `TRAFFIC_RISK_THRESHOLD` and `suspension_source_id` set to this observation's `id`, with the assignment cascade of §3.4 following."

        Design: Difficulty/boundary_precision_check/risk_index_exactly_at_auto_suspend_threshold_suspends
        """
        provider_id, (customer_a, assignment_a), _b = _build_two_monitored_customers(
            world
        )

        observation = _observe(
            world,
            provider_id,
            customer_a["id"],
            total_call_count=100,
            short_duration_call_count=100,
            unanswered_call_count=100,
            complaint_count=1,
        )

        assert_decimal_2(observation, "window_subscore", 0.90)
        assert_decimal_4(observation, "resulting_risk_index", 0.9000)
        assert_equals(observation, "triggered_suspension", True)

        suspended = world.read_customer(customer_a["id"])
        assert_decimal_4(suspended, "traffic_risk_index", 0.9000)
        assert_fields(
            suspended,
            risk_tier="HIGH",
            origination_state="SUSPENDED",
            suspension_cause="TRAFFIC_RISK_THRESHOLD",
        )
        assert_equals(
            world.read_assignment(assignment_a["id"]),
            "status",
            "SUSPENDED_BY_CUSTOMER",
        )

    def test_an_index_one_hundredth_below_the_threshold_leaves_origination_alone(
        self, world
    ):
        """0.8900 is HIGH risk yet still originating, so one number stays active.

        PRD: "Two fields on the observation itself capture the outcome: `resulting_risk_index` is a snapshot of the customer's `traffic_risk_index` immediately after this window was folded in, and `triggered_suspension` is true exactly when this observation drove the index to 0.9000 or above while the customer's `origination_state` was `ENABLED` — in which case the customer is suspended with `suspension_cause` `TRAFFIC_RISK_THRESHOLD` and `suspension_source_id` set to this observation's `id`, with the assignment cascade of §3.4 following."

        Design: Difficulty/boundary_precision_check/risk_index_exactly_at_auto_suspend_threshold_suspends
        """
        provider_id, (customer_a, _asg_a), (
            customer_b,
            assignment_b,
        ) = _build_two_monitored_customers(world)
        _observe(
            world,
            provider_id,
            customer_a["id"],
            total_call_count=100,
            short_duration_call_count=100,
            unanswered_call_count=100,
            complaint_count=1,
        )

        observation = _observe(
            world,
            provider_id,
            customer_b["id"],
            total_call_count=1000,
            short_duration_call_count=1000,
            unanswered_call_count=1000,
            complaint_count=9,
        )

        assert_decimal_2(observation, "window_subscore", 0.89)
        assert_decimal_4(observation, "resulting_risk_index", 0.8900)
        assert_equals(observation, "triggered_suspension", False)
        assert_fields(
            world.read_customer(customer_b["id"]),
            risk_tier="HIGH",
            origination_state="ENABLED",
        )
        assert_equals(world.read_assignment(assignment_b["id"]), "status", "ACTIVE")
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=1
        )


def _build_empty_period_provider(world: ComplianceWorld):
    """A provider that filed a plan and then did nothing at all in August."""
    provider = world.register_provider(provider_type="NON_FACILITIES_RESELLER")
    world.accepted_plan(
        provider["id"],
        officer_id=OFFICER_1,
        practices=["KYC_ONBOARDING", "TRACEBACK_COOPERATION", "CALL_BLOCKING_ANALYTICS"],
    )
    world.set_clock("2026-09-01T00:00:00Z")
    return provider["id"]


def _generate_and_certify(world: ComplianceWorld, provider_id: str):
    report = expect_created(
        world.client.create_effectiveness_report(
            effectiveness_report_payload(
                provider_id, world.provider_version(provider_id), variant="CERTIFIED"
            ),
            world.officer(OFFICER_2),
        )
    )
    return expect_ok(
        world.client.certify_effectiveness_report(
            report["id"], world.officer(OFFICER_2)
        )
    )


class TestEmptyPeriodBandEdge:
    """An empty reporting period lands exactly on the MID band edge."""

    def test_an_empty_period_scores_the_band_edge_on_insufficient_data(self, world):
        """0.4000 x 0 plus the two forgiven components make 0.6000, banding MID.

        PRD: "Its `score_band` reads `HIGH` at 0.8000 or above, `MID` at 0.6000 or above but below 0.8000, and `LOW` otherwise."

        Design: Difficulty/boundary_precision_check/empty_period_effectiveness_lands_exactly_on_mid_band_edge
        """
        provider_id = _build_empty_period_provider(world)

        report = _generate_and_certify(world, provider_id)

        assert_decimal_4(report, "attestation_component", 0.0000)
        assert_decimal_4(report, "traceback_component", 1.0000)
        assert_decimal_4(report, "notice_component", 1.0000)
        assert_decimal_4(report, "effectiveness_score", 0.6000)
        assert_fields(
            report,
            score_band="MID",
            data_sufficiency="INSUFFICIENT",
            state="SIGNED_OFF",
        )

    def test_the_band_edge_is_visible_in_the_mitigation_credit(self, world):
        """A MID band on TIER_2 credits 300,000 cents, leaving 2,700,000 due.

        PRD: "In `TIER_2` a `HIGH` band earns 25 percent, `MID` earns 10 percent, `LOW` earns 5 percent and `NONE` nothing."

        Design: Difficulty/boundary_precision_check/empty_period_effectiveness_lands_exactly_on_mid_band_edge
        """
        provider_id = _build_empty_period_provider(world)
        _generate_and_certify(world, provider_id)

        action = expect_created(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    provider_id,
                    basis="LATE_TRACEBACK",
                    violation_count=3,
                    violation_days=10,
                    assessment_basis="PER_VIOLATION",
                ),
                world.regulator,
            )
        )

        assert_fields(action, assessment_tier="TIER_2", score_band="MID")
        assert_cents(action, "base_assessment_cents", 3000000)
        assert_cents(action, "mitigation_credit_cents", 300000)
        assert_cents(action, "total_forfeiture_cents", 2700000)
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=2700000
        )
