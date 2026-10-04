"""Dual-variant calculations: provisional vs final relief values, per-account
vs deduped-household counting, and per-donation rounding order."""
from test_helpers import (
    create_account_payload,
    create_org,
    create_active_policy,
    create_priced_portfolio,
    create_settled_portfolio,
    get_success_data,
    make_donor_relations_headers,
    make_finance_officer_headers,
    make_platform_admin_headers,
    set_clock,
    setup_finalized_batch,
    stage_batch,
    validate_success,
)


class TestReliefValuationDualVariant:
    def test_provisional_and_final_values_coexist_on_same_account(self, api):
        """PRD §3.3: "Two valuations of an account coexist throughout the
        pipeline. The provisional relief value is `balance_cents` alone; it
        drives screening totals, the price quote, and pre-purchase reporting.
        The final relief value is `balance_cents` plus
        `accrued_adjustment_cents` — residual interest added or reversed after
        the data cut — and it is the value recorded at abolishment. For an
        account with a non-zero adjustment, the two values deliberately
        differ."

        Design: Difficulty/dual_variant_calc/relief_valuation_provisional_vs_final_on_same_account
        """
        ctx = setup_finalized_batch()
        fin = make_finance_officer_headers()
        a1 = get_success_data(
            api.get_account(ctx["accounts"][0]["id"], fin)
        )
        assert a1["balance_cents"] == 1000000
        assert a1["abolished_amount_cents"] == 1050000  # 1000000 + 50000
        assert a1["lifecycle_status"] == "ABOLISHED"
        portfolio = get_success_data(
            api.get_portfolio(ctx["portfolio"]["id"], fin)
        )
        # Provisional sum over ELIGIBLE accounts excludes the adjustment.
        assert portfolio["eligible_face_value_cents"] == 1500000
        # Final sum includes it.
        assert portfolio["abolished_face_value_cents"] == 1550000
        # The quote was priced on the provisional value: 1500000 * 0.025 * 1.0.
        assert portfolio["quoted_price_cents"] == 37500

    def test_quote_uses_provisional_value_before_abolishment(self, api):
        """PRD §3.3: "The provisional relief value is `balance_cents` alone; it
        drives screening totals, the price quote, and pre-purchase reporting."
        PRD §3.2: "recomputing the portfolio's `eligible_face_value_cents` —
        the sum of `balance_cents` over accounts now `ELIGIBLE`"

        Design: Difficulty/dual_variant_calc/relief_valuation_provisional_vs_final_on_same_account
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        accounts = [
            create_account_payload(
                "A1", debtor_household_key="H1", balance_cents=1000000,
                accrued_adjustment_cents=50000, annual_income_cents=1000000,
            ),
        ]
        priced, _accounts, _run = create_priced_portfolio(
            org["id"], policy["id"], accounts=accounts
        )
        # eligible_face_value_cents sums balance_cents only, not the adjustment.
        assert priced["eligible_face_value_cents"] == 1000000
        assert priced["quoted_price_cents"] == 25000  # 1000000 * 0.025 * 1.0


class TestImpactHouseholdCounting:
    def test_per_account_vs_deduped_household_variants(self, api):
        """PRD §3.10: "The `households_relieved` figure depends on the variant:
        under `PER_ACCOUNT` it is simply the count of in-scope accounts, so
        three abolished accounts belonging to two households report 3; under
        `DEDUPED_HOUSEHOLD` it is the count of distinct `debtor_household_key`
        values over the set, so the same three accounts report 2."
        PRD §3.10: "The report's `dollars_abolished_cents` is the sum of
        `abolished_amount_cents` over that set, identical under both counting
        variants."

        Design: Difficulty/dual_variant_calc/impact_household_counting_per_account_vs_deduped
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        accounts = [
            create_account_payload(
                "B1", debtor_household_key="H1", debtor_zip="75001",
                balance_cents=1000000,
            ),
            create_account_payload(
                "B2", debtor_household_key="H1", debtor_zip="75001",
                balance_cents=500000,
            ),
            create_account_payload(
                "B3", debtor_household_key="H2", debtor_zip="75009",
                balance_cents=700000, mailing_address="9 Elm St",
            ),
        ]
        portfolio, imported, _contract = create_settled_portfolio(
            org["id"], policy["id"], accounts=accounts
        )
        fin = make_finance_officer_headers()
        dro = make_donor_relations_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "General Relief Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 2270000},
                dro,
            )
        )
        get_success_data(api.receive_donation(donation["id"], fin))
        batch = stage_batch(portfolio, [a["id"] for a in imported])
        get_success_data(api.commit_abolishment_batch(batch["id"], fin))
        get_success_data(api.finalize_abolishment_batch(batch["id"], fin))
        admin = make_platform_admin_headers()
        per_account = validate_success(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-09-01",
                    "period_end": "2026-09-30",
                    "counting_variant": "PER_ACCOUNT",
                },
                admin,
            ),
            201,
        )
        deduped = validate_success(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-09-01",
                    "period_end": "2026-09-30",
                    "counting_variant": "DEDUPED_HOUSEHOLD",
                },
                admin,
            ),
            201,
        )
        assert per_account["households_relieved"] == 3
        assert deduped["households_relieved"] == 2
        assert per_account["dollars_abolished_cents"] == 2200000
        assert deduped["dollars_abolished_cents"] == 2200000
        assert per_account["status"] == "DRAFT"
        assert deduped["status"] == "DRAFT"

    def test_deduped_household_counts_distinct_keys(self, api):
        """PRD §3.10: "under `DEDUPED_HOUSEHOLD` it is the count of distinct
        `debtor_household_key` values over the set"

        Design: Difficulty/dual_variant_calc/impact_household_counting_per_account_vs_deduped
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        accounts = [
            create_account_payload(
                "B1", debtor_household_key="HX", debtor_zip="75001",
                balance_cents=400000,
            ),
            create_account_payload(
                "B2", debtor_household_key="HX", debtor_zip="75001",
                balance_cents=400000,
            ),
            create_account_payload(
                "B3", debtor_household_key="HX", debtor_zip="75001",
                balance_cents=400000,
            ),
        ]
        portfolio, imported, _contract = create_settled_portfolio(
            org["id"], policy["id"], accounts=accounts
        )
        fin = make_finance_officer_headers()
        dro = make_donor_relations_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Dedupe Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 2000000},
                dro,
            )
        )
        get_success_data(api.receive_donation(donation["id"], fin))
        batch = stage_batch(portfolio, [a["id"] for a in imported])
        get_success_data(api.commit_abolishment_batch(batch["id"], fin))
        get_success_data(api.finalize_abolishment_batch(batch["id"], fin))
        admin = make_platform_admin_headers()
        report = validate_success(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-09-01",
                    "period_end": "2026-09-30",
                    "counting_variant": "DEDUPED_HOUSEHOLD",
                },
                admin,
            ),
            201,
        )
        # Three accounts, one household key: deduped count is 1.
        assert report["households_relieved"] == 1
        assert report["dollars_abolished_cents"] == 1200000


class TestDonationRoundingOrder:
    def test_fee_rounded_per_item_then_summed(self, api):
        """PRD §3.5: "The rounding order is pinned: the fee is rounded per
        donation, and only then are nets summed into campaign totals. The
        alternative — summing grosses and rounding once — is forbidden because
        it yields different cents: two gifts of 3,333 cents net 3,236 each for
        a campaign total of 6,472, whereas sum-then-round would produce 6,473."

        Design: Difficulty/combinatorial_formula/donation_fee_rounded_per_item_then_summed
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Rounding Fund", "earmark_type": "GENERAL",
                 "goal_cents": 10000000},
                dro,
            )
        )
        d1 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "R1", "donor_email": "r1@x.com",
                 "gross_cents": 3333},
                dro,
            )
        )
        get_success_data(api.receive_donation(d1["id"], fin))
        d2 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "R2", "donor_email": "r2@x.com",
                 "gross_cents": 3333},
                dro,
            )
        )
        get_success_data(api.receive_donation(d2["id"], fin))
        d1_now = get_success_data(api.get_donation(d1["id"], fin))
        d2_now = get_success_data(api.get_donation(d2["id"], fin))
        assert d1_now["fee_cents"] == 97 and d1_now["net_cents"] == 3236
        assert d2_now["fee_cents"] == 97 and d2_now["net_cents"] == 3236
        refreshed = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert refreshed["raised_cents"] == 6472
        assert refreshed["raised_cents"] != 6473

    def test_fee_rounded_half_up_at_fractional_cent(self, api):
        """PRD §3.5: "the processing `fee_cents` is the gift multiplied by a fee
        rate of 2.9 percent (0.029), rounded half-up to whole cents, and
        `net_cents` is the gross minus the fee."

        Design: Difficulty/combinatorial_formula/donation_fee_rounded_per_item_then_summed
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Rounding Fund 2", "earmark_type": "GENERAL",
                 "goal_cents": 10000000},
                dro,
            )
        )
        d1 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "H1", "donor_email": "h1@x.com",
                 "gross_cents": 50000},
                dro,
            )
        )
        # 50000 * 0.029 = 1450.0 exactly
        assert d1["fee_cents"] == 1450
        assert d1["net_cents"] == 48550
        d2 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "H2", "donor_email": "h2@x.com",
                 "gross_cents": 50017},
                dro,
            )
        )
        # 50017 * 0.029 = 1450.493 -> round half-up = 1450
        assert d2["fee_cents"] == 1450
        assert d2["net_cents"] == 48567
        get_success_data(api.receive_donation(d1["id"], fin))
        get_success_data(api.receive_donation(d2["id"], fin))
        refreshed = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert refreshed["raised_cents"] == 48550 + 48567
