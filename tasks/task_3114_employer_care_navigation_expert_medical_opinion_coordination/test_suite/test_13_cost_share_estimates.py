"""Prospective cost-share estimates: pinned evaluation order, accumulator
non-mutation, and the out-of-network flat-rate variant."""
from test_helpers import (
    validate_success,
    claim_line,
    set_clock, setup_employer_with_member, setup_provider,
    setup_adjudicated_claim,
)
from test_helpers.test_users import make_member_headers


class TestCostShareEstimate:
    def test_estimate_uses_persisted_accumulators_and_pinned_order(
            self, api, platform_admin_headers):
        """PRD §3.7: "Members and their advocates can ask for a prospective
        cost-share estimate before receiving care, supplying the target
        `provider_id` and an `allowed_amount_cents`. The estimate reads the
        persisted accumulators only and never mutates them. For an `IN_NETWORK`
        provider the estimate mirrors adjudication: the deductible portion is
        the smaller of the remaining deductible and the allowed amount; the
        coinsurance portion is one-fifth of the remainder, rounded half-up; the
        uncapped total is their sum; and the final `member_responsibility_cents`
        is the smaller of that uncapped total and the room left under the
        member's `oop_max_cents`".

        Design: Difficulty/combinatorial_formula/cost_share_estimate_pinned_evaluation_order_with_oop_cap
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000,
                              "oop_max_cents": 500000})
        provider = setup_provider(name="Valley Imaging", specialty="RADIOLOGY")
        setup_adjudicated_claim(
            member, provider, service_date="2026-07-01",
            billed_amount_cents=60000, allowed_amount_cents=60000,
            lines=[claim_line("X", 60000, 1.0, "NONE")])

        estimate = validate_success(api.get_cost_share_estimate(
            member["id"], make_member_headers(member["id"]),
            params={"provider_id": provider["id"],
                    "allowed_amount_cents": 80000}))
        # remaining deductible 40000 -> portion 40000; coinsurance 0.2*40000=8000
        assert estimate["member_responsibility_cents"] == 48000
        assert estimate["deductible_portion_cents"] == 40000
        assert estimate["coinsurance_portion_cents"] == 8000
        assert estimate["oop_capped"] is False

    def test_estimate_never_mutates_accumulators(self, api,
                                                 platform_admin_headers):
        """PRD §3.7: "The estimate reads the persisted accumulators only and
        never mutates them."

        Design: Difficulty/combinatorial_formula/cost_share_estimate_pinned_evaluation_order_with_oop_cap
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000,
                              "oop_max_cents": 500000})
        provider = setup_provider(name="Valley Imaging", specialty="RADIOLOGY")
        setup_adjudicated_claim(
            member, provider, service_date="2026-07-01",
            billed_amount_cents=60000, allowed_amount_cents=60000,
            lines=[claim_line("X", 60000, 1.0, "NONE")])

        before = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert before["deductible_used_cents"] == 60000
        assert before["oop_used_cents"] == 60000

        validate_success(api.get_cost_share_estimate(
            member["id"], make_member_headers(member["id"]),
            params={"provider_id": provider["id"],
                    "allowed_amount_cents": 80000}))

        after = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert after["deductible_used_cents"] == 60000
        assert after["oop_used_cents"] == 60000

    def test_cost_share_estimate_out_of_network_flat_rate(self, api):
        """PRD §3.7: "For an `OUT_OF_NETWORK` provider the member's
        responsibility is simply two-fifths of the allowed amount, rounded
        half-up to whole cents — no deductible offset, no out-of-pocket cap."

        Design: Corner/endpoints/cost_share_estimate_out_of_network_flat_rate
        """
        set_clock()
        _, member = setup_employer_with_member()
        provider_in = setup_provider(name="InNet")
        setup_adjudicated_claim(
            member, provider_in, service_date="2026-07-01",
            billed_amount_cents=60000, allowed_amount_cents=60000,
            lines=[claim_line("A", 60000, 1.0, "NONE")])
        provider_out = setup_provider(name="OutNet",
                                      network_status="OUT_OF_NETWORK")

        estimate = validate_success(api.get_cost_share_estimate(
            member["id"], make_member_headers(member["id"]),
            params={"provider_id": provider_out["id"],
                    "allowed_amount_cents": 80000}))
        assert estimate["member_responsibility_cents"] == 32000
        assert estimate["oop_capped"] is False
