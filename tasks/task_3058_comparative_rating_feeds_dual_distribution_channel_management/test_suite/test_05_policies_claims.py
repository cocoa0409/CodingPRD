"""Policies: bind side effects, immediate consistency, cancellation proration
and the conditional enrollment cascade, and policy listing reverse-reach."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    bind_agent_policy_via_referral,
    create_agent_quote,
    create_appointed_agent,
    create_consumer,
    create_direct_quote,
    get_success_data,
    make_agent_headers,
    make_consumer_headers,
    set_clock,
    setup_bound_agent_policy,
    setup_bound_direct_policy,
    setup_product_with_feed,
    submit_agent_quote,
    submit_direct_quote,
    validate_paginated,
    validate_success,
)


class TestBindSideEffects:
    def test_bind_creates_policy_and_telematics_enrollment_side_effects(self, api, system_headers):
        """PRD §3.3: "Either way the quote moves to `BOUND` and a `Policy` is born
        `IN_FORCE` with `inception_at` set to the logical clock, a `term_days` of
        365, and `quote_id`, `consumer_id`, `agent_id` (null on direct policies),
        `product_id`, and `channel` copied from the quote."
        PRD §3.5: "In the direct variant, the 15% participation discount is taken
        **at bind**: the policy's `written_premium_cents` is the quoted premium
        minus the quoted premium times 0.15 rounded half-up, and the enrollment's
        `upfront_discount_cents` records exactly that discount."

        Design: Corner/state_machines/bind_creates_policy_and_telematics_enrollment_side_effects
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        ctx = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True,
            product_overrides={
                "coverage_rates": {"LIABILITY": {"BASIC": 50000}},
                "direct_discount_pct": 0.10,
                "min_premium_cents": 0,
            },
        )
        policy = ctx["policy"]
        assert policy["status"] == "IN_FORCE"
        assert policy["term_days"] == 365
        assert policy["inception_at"] == "2026-01-01T00:00:00.000Z"
        # quoted 45000; up-front 15% discount of 6750 taken at bind
        assert policy["written_premium_cents"] == 38250

        enrollments, meta = validate_paginated(
            api.list_policy_telematics_enrollments(policy["id"], system_headers)
        )
        assert len(enrollments) == 1
        enrollment = enrollments[0]
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["channel"] == "DIRECT"
        assert enrollment["upfront_discount_cents"] == 6750

        bound_quote = get_success_data(
            api.get_quote(ctx["quote"]["id"], make_consumer_headers(consumer["id"]))
        )
        assert bound_quote["status"] == "BOUND"

    def test_bind_side_effects_immediately_visible(self, api, carrier_admin_headers):
        """PRD §3.3: "Either way the quote moves to `BOUND` and a `Policy` is born
        `IN_FORCE` with `inception_at` set to the logical clock, a `term_days` of
        365, and `quote_id`, `consumer_id`, `agent_id` (null on direct policies),
        `product_id`, and `channel` copied from the quote."

        Design: Corner/consistency_model/bind_side_effects_immediately_visible
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        ctx = setup_bound_direct_policy(
            consumer=consumer,
            product_overrides={
                "coverage_rates": {"LIABILITY": {"BASIC": 50000}},
                "direct_discount_pct": 0.10,
                "min_premium_cents": 0,
            },
        )
        policy = ctx["policy"]
        assert policy["status"] == "IN_FORCE"

        quote_after = get_success_data(
            api.get_quote(ctx["quote"]["id"], carrier_admin_headers)
        )
        policy_after = get_success_data(api.get_policy(policy["id"], carrier_admin_headers))
        assert quote_after["status"] == "BOUND"
        assert policy_after["status"] == "IN_FORCE"


class TestPolicyCancelProration:
    def test_policy_earned_premium_reconciles_on_cancel_while_in_force(self, api, carrier_admin_headers):
        """PRD §3.4: "While `IN_FORCE`, its `earned_premium_cents` equals its full
        `written_premium_cents` and `unearned_premium_cents` is zero."

        Design: Corner/cross_cutting_layers/policy_earned_premium_reconciles_on_cancel
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_bound_agent_policy(
            coverages=[{"coverage_code": "FLAT", "tier": "TIER_D"}],
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_D": 730000}},
                "min_premium_cents": 0,
            },
        )
        policy = get_success_data(api.get_policy(ctx["policy"]["id"], carrier_admin_headers))
        assert policy["earned_premium_cents"] == 730000
        assert policy["unearned_premium_cents"] == 0

    def test_policy_earned_premium_reconciles_on_cancel_at_day_100(self, api, carrier_admin_headers):
        """PRD §3.4: "the days in force are the whole calendar days in the
        half-open interval from `inception_at` to `cancelled_at`, the earned premium
        is the written premium multiplied by the days in force and divided by
        `term_days` (365), rounded half-up to integer cents, and the unearned
        premium is the written premium minus the earned."

        Design: Corner/cross_cutting_layers/policy_earned_premium_reconciles_on_cancel
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_bound_agent_policy(
            coverages=[{"coverage_code": "FLAT", "tier": "TIER_D"}],
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_D": 730000}},
                "min_premium_cents": 0,
            },
        )
        set_clock("2026-04-11T00:00:00Z")
        cancelled = validate_success(
            api.cancel_policy(ctx["policy"]["id"], carrier_admin_headers)
        )
        assert cancelled["status"] == "CANCELLED"
        # 730000 * 100 / 365 = 200000
        assert cancelled["earned_premium_cents"] == 200000
        assert cancelled["unearned_premium_cents"] == 530000
        assert cancelled["cancelled_at"] == "2026-04-11T00:00:00.000Z"

        after = get_success_data(api.get_policy(ctx["policy"]["id"], carrier_admin_headers))
        assert after["earned_premium_cents"] == 200000
        assert after["unearned_premium_cents"] == 530000


class TestCancelForcesEnrollmentOptOut:
    def _setup_two_policies(self, api):
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        product_overrides = {
            "coverage_rates": {"LIABILITY": {"BASIC": 50000}},
            "direct_discount_pct": 0.10,
            "min_premium_cents": 0,
        }
        ctx1 = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True,
            product_overrides=product_overrides,
        )
        ctx2 = setup_bound_direct_policy(
            consumer=consumer, telematics_opt_in=True,
            product_overrides=product_overrides,
        )
        return consumer, ctx1, ctx2

    def test_policy_cancel_forces_enrollment_opted_out_conditional_cascade(
        self, api, system_headers
    ):
        """PRD §3.4: "If the policy carries a telematics enrollment still in
        `ENROLLED` or `PARTICIPATING`, cancellation forces it to `OPTED_OUT`;
        crucially, any direct-channel up-front discount already baked into the
        written premium is **not** retroactively clawed back on the policy, and
        the enrollment's `adjustment_cents` stays null."

        Design: Corner/state_machines/policy_cancel_forces_enrollment_opted_out_conditional_cascade
        """
        from test_helpers import get_policy_enrollment
        consumer, ctx1, ctx2 = self._setup_two_policies(api)
        consumer_headers = make_consumer_headers(consumer["id"])

        # Drive ctx2's enrollment to SCORED first
        enr2 = get_policy_enrollment(ctx2["policy"]["id"])
        validate_success(api.activate_telematics_device(enr2["id"], consumer_headers))
        validate_success(
            api.score_telematics_enrollment(enr2["id"], {"driving_score": 95}, system_headers)
        )

        validate_success(api.cancel_policy(ctx1["policy"]["id"], consumer_headers))
        validate_success(api.cancel_policy(ctx2["policy"]["id"], consumer_headers))

        enr1_after = get_policy_enrollment(ctx1["policy"]["id"])
        assert enr1_after["status"] == "OPTED_OUT"
        assert enr1_after["adjustment_cents"] is None

        enr2_after = get_policy_enrollment(ctx2["policy"]["id"])
        assert enr2_after["status"] == "SCORED"
        # final 45000 * 0.80 = 36000 vs written 38250 -> credit -2250
        assert enr2_after["adjustment_cents"] == -2250

        pol1_after = get_success_data(api.get_policy(ctx1["policy"]["id"], consumer_headers))
        pol2_after = get_success_data(api.get_policy(ctx2["policy"]["id"], consumer_headers))
        assert pol1_after["status"] == "CANCELLED"
        assert pol2_after["status"] == "CANCELLED"


class TestPolicyListing:
    def test_policies_filtered_list_reverse_reaches_agent(self, api, carrier_admin_headers):
        """PRD §4: "List policies (filters: quote_id, consumer_id, agent_id,
        product_id, status)"

        Design: Corner/endpoints/policies_filtered_list_reverse_reaches_agent
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_C": 99995}},
                "min_premium_cents": 0,
            }
        )
        agent_a = create_appointed_agent()
        agent_b = create_appointed_agent()
        consumer = create_consumer()

        pol_a = bind_agent_policy_via_referral(
            consumer, agent_a, ctx["product"]["id"],
            coverages=[{"coverage_code": "FLAT", "tier": "TIER_C"}],
        )["policy"]
        pol_b = bind_agent_policy_via_referral(
            consumer, agent_b, ctx["product"]["id"],
            coverages=[{"coverage_code": "FLAT", "tier": "TIER_C"}],
        )["policy"]

        rows, meta = validate_paginated(
            api.list_policies(carrier_admin_headers, params={"agent_id": agent_a["id"]})
        )
        assert meta["total_count"] == 1
        assert [r["id"] for r in rows] == [pol_a["id"]]
        assert pol_b["id"] not in [r["id"] for r in rows]
