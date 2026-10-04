"""Bundled home placements (eligibility, AOR transfer waterfall) and the
referral appointment-match precondition, plus channel-bound quote creation."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_aor_commission_conservation,
    create_active_product,
    create_appointed_agent,
    create_consumer,
    create_direct_quote,
    get_success_data,
    make_agent_headers,
    make_consumer_headers,
    set_clock,
    setup_bound_agent_policy,
    setup_placed_bundle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["carrier_admin_headers"]
UR = TEST_USERS["underwriting_reviewer_headers"]


class TestBundleEligibility:
    def test_bundle_placement_on_non_eligible_product_rejected(self, api):
        """PRD §3.9: "The policy's product must be `bundle_eligible`
        (`ERR_BUNDLE_NOT_ELIGIBLE`), the policy must be `IN_FORCE`
        (`ERR_POLICY_NOT_IN_FORCE`), and the policy must carry an agent — the
        placement's `agent_id` becomes the policy's `agent_id` as the current
        agency of record, and a direct policy with no agent cannot take a
        placement (`ERR_AGENT_MISMATCH`)."
        PRD §3.1: "`bundle_eligible` (default false) marks whether policies of
        this product may carry a bundled home placement."

        Design: Corner/validations/bundle_placement_on_non_eligible_product_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_bound_agent_policy()  # bundle_eligible defaults to False
        agent = ctx["agent"]
        resp = api.create_bundle_placement(
            ctx["policy"]["id"],
            {
                "unaffiliated_carrier_name": "Unaffiliated Home Mutual",
                "home_premium_cents": 240000,
                "total_commission_cents": 36500,
            },
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUNDLE_NOT_ELIGIBLE, 409)


class TestAorTransfer:
    def test_transfer_aor_on_quoted_placement_rejected(self, api):
        """PRD §3.9: "Agency-of-record transfer, performed by a `CarrierAdmin`
        supplying a `new_agent_id`, moves a `PLACED` placement to
        `AOR_TRANSFERRED`. The receiving agent must be `APPOINTED`, must differ
        from the current `agent_id` (`ERR_AOR_NOT_ALLOWED` otherwise — the same
        error covers a transfer attempted on a non-`PLACED` placement), and must
        hold an `ACTIVE` appointment for the policy product's state and line of
        business (`ERR_AGENT_NOT_APPOINTED_IN_STATE`)."

        Design: Corner/errors/transfer_aor_on_quoted_placement_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_bound_agent_policy(
            product_overrides={"bundle_eligible": True}
        )
        agent_a = ctx["agent"]
        agent_b = create_appointed_agent()
        placement = get_success_data(api.create_bundle_placement(
            ctx["policy"]["id"],
            {
                "unaffiliated_carrier_name": "Unaffiliated Home Mutual",
                "home_premium_cents": 240000,
                "total_commission_cents": 36500,
            },
            make_agent_headers(agent_a["id"]),
        ))
        assert placement["status"] == "QUOTED"

        resp = api.transfer_bundle_placement_aor(
            placement["id"], {"new_agent_id": agent_b["id"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_AOR_NOT_ALLOWED, 409)
        after = get_success_data(api.get_bundle_placement(placement["id"], ADMIN))
        assert after["status"] == "QUOTED"

    def test_aor_transfer_conserves_total_bundle_commission_across_agents(self, api):
        """PRD §3.9: "the `earned_commission_cents` retained by the original agent
        is the total commission multiplied by those days and divided by the
        policy's `term_days`, rounded half-up; and the
        `transferred_commission_cents` moved to the receiving agent is the exact
        complement — total minus earned — so the two legs sum to the total
        exactly and nothing is created or lost. The placement's `agent_id` and
        `transferred_to_agent_id` both become the `new_agent_id`,
        and the placement's `version` increments."

        Design: Difficulty/compensating_invariant/aor_transfer_conserves_total_bundle_commission_across_agents
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_placed_bundle(total_commission_cents=36500)
        agent_a = ctx["agent"]
        agent_b = create_appointed_agent()

        set_clock("2026-04-11T00:00:00Z")
        transferred = validate_success(api.transfer_bundle_placement_aor(
            ctx["placement"]["id"], {"new_agent_id": agent_b["id"]}, ADMIN
        ))
        assert transferred["status"] == "AOR_TRANSFERRED"
        assert transferred["agent_id"] == agent_b["id"]
        assert transferred["transferred_to_agent_id"] == agent_b["id"]
        # 36500 * 100 / 365 = 10000 retained; complement 26500 transferred
        assert transferred["earned_commission_cents"] == 10000
        assert transferred["transferred_commission_cents"] == 26500
        assert_aor_commission_conservation(transferred)

    def test_aor_transfer_updates_agent_of_record_atomically(self, api):
        """PRD §3.9: "The placement's `agent_id` and `transferred_to_agent_id`
        both become the `new_agent_id`, and the placement's `version`
        increments."

        Design: Difficulty/compensating_invariant/aor_transfer_conserves_total_bundle_commission_across_agents
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_placed_bundle(total_commission_cents=36500)
        agent_a = ctx["agent"]
        agent_b = create_appointed_agent()
        placed_version = ctx["placement"]["version"]

        set_clock("2026-04-11T00:00:00Z")
        transferred = validate_success(api.transfer_bundle_placement_aor(
            ctx["placement"]["id"], {"new_agent_id": agent_b["id"]}, ADMIN
        ))
        assert transferred["agent_id"] == agent_b["id"]
        assert transferred["transferred_to_agent_id"] == agent_b["id"]
        assert transferred["agent_id"] != agent_a["id"]
        assert transferred["version"] == placed_version + 1
        assert (
            transferred["earned_commission_cents"]
            + transferred["transferred_commission_cents"]
            == transferred["total_commission_cents"]
        )


class TestReferralPreconditions:
    def test_agent_quote_without_state_appointment_rejected(self, api):
        """PRD §3.3: "the target agent must be `APPOINTED` (`ERR_AGENT_TERMINATED`)
        and hold an `ACTIVE` appointment for the product's state and line
        (`ERR_AGENT_NOT_APPOINTED_IN_STATE`)"
        PRD §3.6: "Appointment records themselves are created by an
        `UnderwritingReviewer` with a `state_code`, a `line_of_business`, and a
        half-open window from `effective_start` to an optional `effective_end`
        (null means open-ended)"

        Design: Corner/validations/agent_quote_without_state_appointment_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        # Agent appointed in OK, AUTO only; the product is filed in TX
        agent = create_appointed_agent(state_code="OK")
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])

        quote = create_direct_quote(consumer, product["id"])
        validate_success(api.submit_quote(quote["id"], consumer_headers))

        resp = api.refer_quote_to_agent(
            quote["id"], {"agent_id": agent["id"]}, consumer_headers
        )
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_APPOINTED_IN_STATE, 409)

        after = get_success_data(api.get_quote(quote["id"], consumer_headers))
        assert after["status"] == "QUOTED"
        assert after["agent_id"] is None


class TestQuoteCreationChannelBinding:
    def test_agent_channel_quote_without_agent_id_rejected(self, api):
        """PRD §3.3: "Channel and identity are bound at creation: an agent-channel
        quote must carry an `agent_id` (omitting it fails with
        `ERR_AGENT_MISMATCH`), an `Agent` caller may only create quotes naming
        themselves as `agent_id`, and a `Consumer` caller may only create `DIRECT`
        quotes for their own `consumer_id`."

        Design: Corner/errors/agent_channel_quote_without_agent_id_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer()
        resp = api.create_quote(
            {
                "consumer_id": consumer["id"],
                "product_id": product["id"],
                "channel": "AGENT",
                "coverages": [{"coverage_code": "LIABILITY", "tier": "BASIC"}],
            },
            make_consumer_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGENT_MISMATCH, 409)
