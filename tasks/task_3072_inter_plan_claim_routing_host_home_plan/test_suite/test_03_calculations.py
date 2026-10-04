"""Calculations: access fee tiering, admin charge brackets, pricing variants, settlement sweep."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    ApiClient,
    create_routed_claim,
    get_success_data,
    set_clock,
    setup_two_plan_world,
    validate_success,
)
from test_helpers import factories as f


class TestAccessFeeTiering:
    def test_access_fee_tier1_flat_below_cap(self, api: ApiClient):
        """PRD §3.5: "When the current allowed amount is at or below the schedule's `tier1_cap_cents` — the boundary is inclusive — the base fee is the flat `tier1_fee_cents`."
        PRD §3.5: "the slice of the allowed amount up to and including 10000 cents is charged at 5 percent"

        Design: Corner/calculations/access_fee_tier1_flat_below_cap
        """
        world = setup_two_plan_world(
            api,
            rate_overrides={"negotiated_rate_cents": 8000},
        )
        claim = create_routed_claim(api, world, billed_amount_cents=50000)
        assert claim["access_fee_cents"] == 150
        assert claim["admin_charge_cents"] == 400

    def test_access_fee_tier1_flat_at_lower_billed(self, api: ApiClient):
        """PRD §3.5: "When the current allowed amount is at or below the schedule's `tier1_cap_cents` — the boundary is inclusive — the base fee is the flat `tier1_fee_cents`."

        Billed 5000 with rate 8000 -> allowed 5000 (< cap) -> flat fee 150.

        Design: Corner/calculations/access_fee_tier1_flat_below_cap
        """
        world = setup_two_plan_world(
            api,
            rate_overrides={"negotiated_rate_cents": 8000},
        )
        claim = create_routed_claim(api, world, billed_amount_cents=5000)
        assert claim["access_fee_cents"] == 150


class TestSettlementSweepScope:
    def test_sweep_excludes_unpaid_and_out_of_window_claims(self, api: ApiClient):
        """PRD §3.8: "The sweep deterministically includes every claim whose home plan is the debtor, whose host plan is the creditor, whose status is `PAID`, and whose `service_date` falls within the closed batch window"

        Design: Corner/calculations/settlement_sweep_input_set_excludes_unpaid_and_out_of_window
        """
        world = setup_two_plan_world(api)
        member = world["member"]
        member2 = get_success_data(
            api.create_member(f.member_payload(world["home"]["id"], member_number="M2", full_name="Pat Two"), world["home_headers"])
        )
        member3 = get_success_data(
            api.create_member(f.member_payload(world["home"]["id"], member_number="M3", full_name="Pat Three"), world["home_headers"])
        )

        # C1: in-window PAID claim.
        c1 = create_routed_claim(api, world)
        get_success_data(api.determine_benefit(c1["id"], world["home_headers"]))
        get_success_data(api.pay_claim(c1["id"], world["host_headers"]))

        # C2: ROUTED only (never paid).
        create_routed_claim(api, world, service_date="2026-08-11")

        # C3: out-of-window PAID claim (service 2026-07-31).
        c3 = get_success_data(
            api.create_claim(
                f.claim_payload(member3["id"], world["host"]["id"], service_date="2026-07-31"),
                world["host_headers"],
            )
        )
        get_success_data(api.price_claim(c3["id"], world["host_headers"]))
        get_success_data(api.route_claim(c3["id"], world["host_headers"]))
        get_success_data(api.determine_benefit(c3["id"], world["home_headers"]))
        get_success_data(api.pay_claim(c3["id"], world["host_headers"]))

        batch = get_success_data(
            api.create_settlement_batch(
                f.settlement_batch_payload(world["home"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        finalized = validate_success(api.finalize_batch(batch["id"], world["host_headers"]), 200)
        assert finalized["gross_claims_total_cents"] == 20000
        assert finalized["fees_total_cents"] == 1200
        assert finalized["net_settlement_cents"] == 18800

    def test_sweep_includes_only_paid_claims_in_scope(self, api: ApiClient):
        """PRD §3.8: "The sweep deterministically includes every claim whose home plan is the debtor, whose host plan is the creditor, whose status is `PAID`, and whose `service_date` falls within the closed batch window"

        A single in-window PAID claim finalizes with gross equal to its payment.

        Design: Corner/calculations/settlement_sweep_input_set_excludes_unpaid_and_out_of_window
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)
        get_success_data(api.determine_benefit(claim["id"], world["home_headers"]))
        get_success_data(api.pay_claim(claim["id"], world["host_headers"]))

        batch = get_success_data(
            api.create_settlement_batch(
                f.settlement_batch_payload(world["home"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        finalized = validate_success(api.finalize_batch(batch["id"], world["host_headers"]), 200)
        assert finalized["gross_claims_total_cents"] == 20000
        assert finalized["net_settlement_cents"] == 20000 - finalized["fees_total_cents"]


class TestNationalAccountDiscount:
    def test_discount_lost_when_account_suspended(self, api: ApiClient):
        """PRD §3.3: "while suspended the members of that account lose the national-account access-fee discount described in §3.5"

        Design: Corner/calculations/national_account_discount_lost_when_account_suspended
        """
        world = setup_two_plan_world(
            api,
            with_national_account=True,
            fee_overrides={"national_account_discount_pct": 0.25},
        )
        priced = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        get_success_data(api.price_claim(priced["id"], world["host_headers"]))

        get_success_data(api.suspend_national_account(world["account"]["id"], ASSOCIATION_ADMIN_HEADERS))

        routed = validate_success(api.route_claim(priced["id"], world["host_headers"]), 200)
        assert routed["access_fee_cents"] == 400

    def test_discount_applies_while_account_active(self, api: ApiClient):
        """PRD §3.5: "The base fee is then discounted when the claim's `national_account_id` references a national account that is controlled by the claim's home plan, is in `ACTIVE` status, and whose closed effective window covers the `service_date`"

        Design: Corner/calculations/national_account_discount_lost_when_account_suspended
        """
        world = setup_two_plan_world(
            api,
            with_national_account=True,
            fee_overrides={"national_account_discount_pct": 0.25},
        )
        claim = create_routed_claim(api, world)
        assert claim["access_fee_cents"] == 300
