"""Queue A — dual-variant and invariant calculations on the donor ledger."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fund_payload, create_donation_payload,
    setup_fund_and_open_protocol, create_fund,
    assert_fund_pool_conservation, set_clock,
    TEST_USERS, ApiErrorId,
)


class TestFundCommitmentSplit:

    def test_fund_pools_at_commitment(self, logical_clock):
        """PRD §2.4: "The research pool `research_balance_cents` holds the share
        of the money raised that belongs to research: it is the fundraising
        total multiplied by the research allocation percentage, rounded up to
        the next whole cent."
        PRD §2.4: "The patient-support pool `patient_support_balance_cents`
        holds what remains: net fundraising — the money raised minus the federal
        grant funds — less that same rounded-up research share."

        Design: Difficulty/dual_variant_calc/dual_variant_fund_pools_at_commitment_vs_after_donation
        """
        res = api_client.create_fund(
            create_fund_payload(
                fund_code="SJ-FY26",
                fiscal_year=2026,
                fundraising_raised_cents=400_000_000,
                research_allocation_pct=0.4,
                federal_grant_cents=80_000_000,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        fund = validate_success(res, 201)
        assert fund["research_balance_cents"] == 160_000_000
        assert fund["patient_support_balance_cents"] == 160_000_000
        assert_fund_pool_conservation(fund)

    def test_fund_pools_rederive_after_donation(self, logical_clock):
        """PRD §2.4: "Because both pools are re-derived on every read rather
        than frozen, recording a later donation through the fund's donation
        capability changes the totals a subsequent read reports, while any
        protocol budget already committed against the fund is unchanged."
        PRD §2.4: "a successful donation increases `fundraising_raised_cents`,
        or increases `federal_grant_cents` instead when `is_federal_grant` is
        true, re-derives both pools, and advances the fund's `version` by one."

        Design: Difficulty/dual_variant_calc/dual_variant_fund_pools_at_commitment_vs_after_donation
        """
        fund = create_fund(
            fundraising_raised_cents=400_000_000,
            research_allocation_pct=0.4,
            federal_grant_cents=80_000_000,
        )
        assert fund["research_balance_cents"] == 160_000_000

        res = api_client.record_donation(
            fund["id"],
            create_donation_payload(amount_cents=20_000_000, is_federal_grant=False),
            TEST_USERS["platform_admin_headers"],
        )
        after = validate_success(res, 201)
        assert after["fundraising_raised_cents"] == 420_000_000
        assert after["research_balance_cents"] == 168_000_000
        assert after["patient_support_balance_cents"] == 172_000_000

        read_back = get_success_data(api_client.get_fund(fund["id"], TEST_USERS["any_headers"]))
        assert read_back["research_balance_cents"] == 168_000_000
        assert read_back["patient_support_balance_cents"] == 172_000_000


class TestFundDonationPairInvariant:

    def test_donation_reversal_restores_the_pools(self, logical_clock):
        """PRD §2.4: "A donation carries an `amount_cents` and an optional
        `is_federal_grant` flag; a successful donation increases
        `fundraising_raised_cents`, or increases `federal_grant_cents` instead
        when `is_federal_grant` is true, re-derives both pools, and advances the
        fund's `version` by one."

        Design: Difficulty/compensating_invariant/invariant_donation_pair_conserves_every_donor_cent
        """
        fund = create_fund(
            fundraising_raised_cents=400_000_000,
            research_allocation_pct=0.4,
            federal_grant_cents=80_000_000,
        )

        added = get_success_data(api_client.record_donation(
            fund["id"],
            create_donation_payload(amount_cents=25_000_000, is_federal_grant=False),
            TEST_USERS["platform_admin_headers"],
        ))
        assert added["research_balance_cents"] == 170_000_000

        reversed_resp = get_success_data(api_client.record_donation(
            fund["id"],
            create_donation_payload(amount_cents=-25_000_000, is_federal_grant=False),
            TEST_USERS["platform_admin_headers"],
        ))
        assert reversed_resp["research_balance_cents"] == 160_000_000
        assert reversed_resp["patient_support_balance_cents"] == 160_000_000
        assert_fund_pool_conservation(reversed_resp)

    def test_donation_pair_conserves_every_donor_cent(self, logical_clock):
        """PRD §2.4: "When the fund is created, and again on every later read of
        the fund, the server derives two pools from those figures using the
        `research_allocation_pct` chosen at commitment time."

        Design: Difficulty/compensating_invariant/invariant_donation_pair_conserves_every_donor_cent
        """
        fund = create_fund(
            fundraising_raised_cents=400_000_000,
            research_allocation_pct=0.4,
            federal_grant_cents=80_000_000,
        )
        read_before = get_success_data(api_client.get_fund(fund["id"], TEST_USERS["any_headers"]))
        assert read_before["research_balance_cents"] + read_before["patient_support_balance_cents"] == 320_000_000

        get_success_data(api_client.record_donation(
            fund["id"], create_donation_payload(amount_cents=25_000_000),
            TEST_USERS["platform_admin_headers"],
        ))
        get_success_data(api_client.record_donation(
            fund["id"], create_donation_payload(amount_cents=-25_000_000),
            TEST_USERS["platform_admin_headers"],
        ))

        read_after = get_success_data(api_client.get_fund(fund["id"], TEST_USERS["any_headers"]))
        assert read_after["fundraising_raised_cents"] == 400_000_000
        assert read_after["research_balance_cents"] + read_after["patient_support_balance_cents"] == (
            read_after["fundraising_raised_cents"] - read_after["federal_grant_cents"]
        )
        assert_fund_pool_conservation(read_after)


class TestProtocolBudgetIsFrozen:

    def test_protocol_budget_survives_a_later_donation(self, logical_clock):
        """PRD §2.4: "The three-quarters share and the division are evaluated as
        described here; the budget itself, once accepted, stays fixed even if
        later donations enlarge the fund."

        Design: Difficulty/derived_field_reconciliation/derived_protocol_budget_frozen_while_fund_pools_rederive
        """
        fund = create_fund(
            fundraising_raised_cents=400_000_000,
            research_allocation_pct=0.4,
            federal_grant_cents=80_000_000,
        )
        assert fund["research_balance_cents"] == 160_000_000

        protocol = get_success_data(api_client.create_protocol(
            {
                "fund_id": fund["id"], "protocol_code": "ALL-INT-001",
                "disease_group": "ALL", "age_min_years": 5, "age_max_years": 17,
                "required_stage": "NEWLY_DIAGNOSED",
                "protocol_budget_cents": 10_000_000, "capacity": 8,
            },
            TEST_USERS["protocol_coordinator_headers"],
        ))
        assert protocol["protocol_budget_cents"] == 10_000_000
        assert protocol["available_cents"] == 10_000_000

        after_donation = get_success_data(api_client.record_donation(
            fund["id"], create_donation_payload(amount_cents=20_000_000, is_federal_grant=False),
            TEST_USERS["platform_admin_headers"],
        ))
        assert after_donation["research_balance_cents"] == 168_000_000

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["protocol_budget_cents"] == 10_000_000
        assert protocol_after["available_cents"] == 10_000_000
        assert protocol_after["is_budget_saturated"] is False

    def test_fund_pool_reconciles_on_a_different_schedule_than_the_budget(self, logical_clock):
        """PRD §2.4: "Protocol budgets are capped against the fund at creation."
        PRD §2.4: "Because both pools are re-derived on every read rather than
        frozen, recording a later donation through the fund's donation
        capability changes the totals a subsequent read reports, while any
        protocol budget already committed against the fund is unchanged."

        Design: Difficulty/derived_field_reconciliation/derived_protocol_budget_frozen_while_fund_pools_rederive
        """
        fund, protocol = setup_fund_and_open_protocol()
        before = get_success_data(api_client.get_protocol(protocol["id"], TEST_USERS["any_headers"]))

        get_success_data(api_client.record_donation(
            fund["id"], create_donation_payload(amount_cents=20_000_000, is_federal_grant=False),
            TEST_USERS["platform_admin_headers"],
        ))
        fund_after = get_success_data(api_client.get_fund(fund["id"], TEST_USERS["any_headers"]))
        protocol_after = get_success_data(api_client.get_protocol(protocol["id"], TEST_USERS["any_headers"]))

        assert fund_after["research_balance_cents"] != fund["research_balance_cents"]
        assert protocol_after["protocol_budget_cents"] == before["protocol_budget_cents"]
        assert protocol_after["available_cents"] == before["available_cents"]
        assert protocol_after["status"] == before["status"]