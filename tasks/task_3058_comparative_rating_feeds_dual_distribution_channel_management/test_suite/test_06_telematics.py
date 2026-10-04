"""Snapshot telematics: dual discount realization by channel, score-tier
boundaries, and the policy-in-force precondition for scoring."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_consumer,
    get_policy_enrollment,
    make_agent_headers,
    make_consumer_headers,
    set_clock,
    setup_bound_agent_policy,
    setup_bound_direct_policy,
    setup_participating_enrollment,
    validate_error,
    validate_success,
)

SYS = TEST_USERS["system_headers"]

DUAL_PRODUCT = {
    "coverage_rates": {
        "LIABILITY": {"BASIC": 50000, "STANDARD": 70000},
        "COLLISION": {"STANDARD": 90000, "PLUS": 120000},
    },
    "direct_discount_pct": 0.10,
    "agent_load_pct": 0.15,
    "bundle_credit_pct": 0.05,
    "min_premium_cents": 40000,
    "bundle_eligible": True,
}

DUAL_COVERAGES = [
    {"coverage_code": "LIABILITY", "tier": "BASIC"},
    {"coverage_code": "COLLISION", "tier": "STANDARD"},
]

SIMPLE_PRODUCT = {
    "coverage_rates": {"LIABILITY": {"BASIC": 50000}},
    "direct_discount_pct": 0.10,
    "min_premium_cents": 0,
}


class TestDualChannelDiscountRealization:
    def test_telematics_discount_realization_differs_by_channel_at_bind(self, api):
        """PRD §3.5: "In the direct variant, the 15% participation discount is taken
        **at bind**: the policy's `written_premium_cents` is the quoted premium
        minus the quoted premium times 0.15 rounded half-up, and the enrollment's
        `upfront_discount_cents` records exactly that discount."
        PRD §3.5: "In the agent variant, nothing moves at bind:
        `written_premium_cents` equals the quoted premium and
        `upfront_discount_cents` is 0."

        Design: Difficulty/dual_variant_calc/telematics_discount_realization_differs_by_channel_on_policy_domain
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        direct = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True,
            coverages=DUAL_COVERAGES, product_overrides=DUAL_PRODUCT,
        )
        agent_side = setup_bound_agent_policy(
            consumer=consumer, telematics_opt_in=True,
            coverages=DUAL_COVERAGES, product_overrides=DUAL_PRODUCT,
        )

        # DIRECT: quoted 126000, written 126000 - round(126000*0.15) = 107100
        assert direct["policy"]["written_premium_cents"] == 107100
        enr_direct = get_policy_enrollment(direct["policy"]["id"])
        assert enr_direct["upfront_discount_cents"] == 18900
        assert enr_direct["channel"] == "DIRECT"

        # AGENT: quoted 161000, written 161000 (no up-front discount)
        assert agent_side["policy"]["written_premium_cents"] == 161000
        enr_agent = get_policy_enrollment(agent_side["policy"]["id"])
        assert enr_agent["upfront_discount_cents"] == 0
        assert enr_agent["channel"] == "AGENT"

    def test_telematics_discount_realization_differs_by_channel_at_scoring(self, api):
        """PRD §3.5: "When the enrollment is later scored, `discount_pct_applied`
        records the table fraction and `adjustment_cents` records the final
        premium minus the written premium — negative when the earned discount
        exceeds the participation discount, a credit to the consumer."
        PRD §3.5: "At scoring, `adjustment_cents` is again the final premium
        minus the written premium, so the entire discount realizes as a
        retroactive credit."

        Design: Difficulty/dual_variant_calc/telematics_discount_realization_differs_by_channel_on_policy_domain
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        direct = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True,
            coverages=DUAL_COVERAGES, product_overrides=DUAL_PRODUCT,
        )
        agent_side = setup_bound_agent_policy(
            consumer=consumer, telematics_opt_in=True,
            coverages=DUAL_COVERAGES, product_overrides=DUAL_PRODUCT,
        )
        enr_direct = setup_participating_enrollment(
            direct["policy"]["id"], make_consumer_headers(consumer["id"])
        )
        enr_agent = setup_participating_enrollment(
            agent_side["policy"]["id"], make_agent_headers(agent_side["agent"]["id"])
        )

        scored_direct = validate_success(
            api.score_telematics_enrollment(enr_direct["id"], {"driving_score": 92}, SYS)
        )
        assert scored_direct["status"] == "SCORED"
        assert scored_direct["discount_pct_applied"] == 0.20
        # final = round(126000 * 0.80) = 100800; adjustment = 100800 - 107100
        assert scored_direct["adjustment_cents"] == -6300

        scored_agent = validate_success(
            api.score_telematics_enrollment(enr_agent["id"], {"driving_score": 92}, SYS)
        )
        assert scored_agent["status"] == "SCORED"
        assert scored_agent["discount_pct_applied"] == 0.20
        # final = round(161000 * 0.80) = 128800; adjustment = 128800 - 161000
        assert scored_agent["adjustment_cents"] == -32200


class TestScoreTierBoundary:
    def test_telematics_score_tier_boundary_89_vs_90(self, api):
        """PRD §3.5: "A `driving_score` of 90 or above earns a 0.20 discount
        fraction; a score of 70 through 89 earns 0.10; below 70 earns 0.00. The
        boundary is inclusive at the top of each tier: a score of exactly 90 earns
        0.20, a score of exactly 89 earns 0.10."

        Design: Corner/calculations/telematics_score_tier_boundary_89_vs_90
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        ctx1 = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True, product_overrides=SIMPLE_PRODUCT
        )
        ctx2 = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True, product_overrides=SIMPLE_PRODUCT
        )
        enr1 = setup_participating_enrollment(ctx1["policy"]["id"], consumer_headers)
        enr2 = setup_participating_enrollment(ctx2["policy"]["id"], consumer_headers)

        scored_90 = validate_success(
            api.score_telematics_enrollment(enr1["id"], {"driving_score": 90}, SYS)
        )
        assert scored_90["discount_pct_applied"] == 0.20
        # quoted 45000 -> final 36000; written 38250 -> adjustment -2250
        assert scored_90["adjustment_cents"] == -2250

        scored_89 = validate_success(
            api.score_telematics_enrollment(enr2["id"], {"driving_score": 89}, SYS)
        )
        assert scored_89["discount_pct_applied"] == 0.10
        # quoted 45000 -> final 40500; written 38250 -> adjustment +2250 (debit)
        assert scored_89["adjustment_cents"] == 2250


class TestScoringRequiresPolicyInForce:
    def test_telematics_scoring_requires_policy_in_force(self, api):
        """PRD §3.5: "Scoring is performed exclusively by the `System` automation
        identity: it moves `PARTICIPATING → SCORED`, requires the policy to remain
        `IN_FORCE` (`ERR_POLICY_NOT_IN_FORCE`), and requires `driving_score`
        within the inclusive range 0 to 100 (`ERR_INVALID_REQUEST` outside it)."
        PRD §3.4: "If the policy carries a telematics enrollment still in
        `ENROLLED` or `PARTICIPATING`, cancellation forces it to `OPTED_OUT`;
        crucially, any direct-channel up-front discount already baked into the
        written premium is **not** retroactively clawed back on the policy, and
        the enrollment's `adjustment_cents` stays null."

        Design: Difficulty/cross_entity_state_dependency/telematics_scoring_requires_policy_in_force
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        ctx1 = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True, product_overrides=SIMPLE_PRODUCT
        )
        ctx2 = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True, product_overrides=SIMPLE_PRODUCT
        )
        enr1 = setup_participating_enrollment(ctx1["policy"]["id"], consumer_headers)
        enr2 = setup_participating_enrollment(ctx2["policy"]["id"], consumer_headers)

        validate_success(api.cancel_policy(ctx2["policy"]["id"], consumer_headers))

        scored = validate_success(
            api.score_telematics_enrollment(enr1["id"], {"driving_score": 95}, SYS)
        )
        assert scored["status"] == "SCORED"
        assert scored["discount_pct_applied"] == 0.20

        resp = api.score_telematics_enrollment(enr2["id"], {"driving_score": 95}, SYS)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_IN_FORCE, 409)

        enr2_after = get_policy_enrollment(ctx2["policy"]["id"])
        assert enr2_after["status"] == "OPTED_OUT"

    def test_device_activation_requires_policy_in_force(self, api):
        """PRD §3.5: "Device activation — by the consumer or the agent — moves
        the enrollment `ENROLLED → PARTICIPATING` and requires the policy to be
        `IN_FORCE` (`ERR_POLICY_NOT_IN_FORCE`)."
        PRD §3.4: "If the policy carries a telematics enrollment still in
        `ENROLLED` or `PARTICIPATING`, cancellation forces it to `OPTED_OUT`;
        crucially, any direct-channel up-front discount already baked into the
        written premium is **not** retroactively clawed back on the policy, and
        the enrollment's `adjustment_cents` stays null."

        Design: Difficulty/cross_entity_state_dependency/telematics_scoring_requires_policy_in_force
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        ctx = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True, product_overrides=SIMPLE_PRODUCT
        )
        enrollment = get_policy_enrollment(ctx["policy"]["id"])
        assert enrollment["status"] == "ENROLLED"

        validate_success(api.cancel_policy(ctx["policy"]["id"], consumer_headers))

        resp = api.activate_telematics_device(enrollment["id"], consumer_headers)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_IN_FORCE, 409)

        enr_after = get_policy_enrollment(ctx["policy"]["id"])
        assert enr_after["status"] == "OPTED_OUT"
