"""Calculation rules: eligibility screening, tiered pricing, donation
netting, funding waterfall, and FAP scoring."""
from test_helpers import (
    ApiErrorId,
    create_account_payload,
    create_active_policy,
    create_org,
    create_portfolio_payload,
    create_priced_portfolio,
    create_settled_portfolio,
    create_source_organization_payload,
    get_success_data,
    make_donor_relations_headers,
    make_eligibility_officer_headers,
    make_finance_officer_headers,
    make_platform_admin_headers,
    make_portfolio_analyst_headers,
    set_clock,
    stage_batch,
    validate_error,
    validate_success,
)


class TestEligibilityScreening:
    def test_insolvency_override_above_cap(self, api):
        """PRD §3.2: "Otherwise, above the cap, the account is `ELIGIBLE` only
        when `is_insolvent` is true and the policy's `insolvency_qualifies` is
        true — the insolvency override; failing either, it is `INELIGIBLE`."

        Design: Corner/calculations/eligibility_insolvency_override_above_cap
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        analyst = make_portfolio_analyst_headers()
        eo = make_eligibility_officer_headers()
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        accounts = [
            create_account_payload(
                "INS", debtor_household_key="HI", debtor_zip="75060",
                annual_income_cents=9000000, is_insolvent=True,
            ),
            create_account_payload(
                "SOL", debtor_household_key="HS", debtor_zip="75061",
                annual_income_cents=9000000, is_insolvent=False,
            ),
        ]
        imported = get_success_data(api.import_accounts(pf["id"], accounts, analyst))
        a_ins, a_sol = imported[0], imported[1]
        get_success_data(api.submit_portfolio(pf["id"], analyst))
        run = get_success_data(api.create_screening_run(pf["id"], policy["id"], eo))
        resp = api.execute_screening_run(run["id"], eo)
        run_data = validate_success(resp, 200)
        assert run_data["eligible_count"] == 1
        assert run_data["ineligible_count"] == 1
        ins = get_success_data(api.get_account(a_ins["id"], eo))
        sol = get_success_data(api.get_account(a_sol["id"], eo))
        assert ins["eligibility_status"] == "ELIGIBLE"
        assert sol["eligibility_status"] == "INELIGIBLE"

    def test_missing_income_routes_to_needs_review_then_review(self, api):
        """PRD §3.2: "Otherwise, if `annual_income_cents` is absent, the account
        is `ELIGIBLE` only when `is_insolvent` is true and the policy's
        `insolvency_qualifies` is true; failing either, it lands in
        `NEEDS_REVIEW`."
        PRD §3.3: "at least one `COMPLETED` screening run must exist for the
        portfolio and zero accounts may remain in `UNSCREENED` or
        `NEEDS_REVIEW`; otherwise the request fails with
        `ERR_SCREENING_INCOMPLETE`."
        PRD §3.2: "a decision of `ELIGIBLE` moves the account there and triggers
        the same recomputation of the portfolio's eligible totals"

        Design: Corner/calculations/eligibility_missing_income_routes_to_needs_review_then_review
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        analyst = make_portfolio_analyst_headers()
        eo = make_eligibility_officer_headers()
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        imported = get_success_data(
            api.import_accounts(
                pf["id"],
                [
                    create_account_payload(
                        "NR", debtor_household_key="HNR", debtor_zip="75062",
                        household_size=2, annual_income_cents=None,
                    )
                ],
                analyst,
            )
        )
        a_nr = imported[0]
        get_success_data(api.submit_portfolio(pf["id"], analyst))
        run = get_success_data(api.create_screening_run(pf["id"], policy["id"], eo))
        run_data = validate_success(api.execute_screening_run(run["id"], eo), 200)
        assert run_data["needs_review_count"] == 1
        account = get_success_data(api.get_account(a_nr["id"], eo))
        assert account["eligibility_status"] == "NEEDS_REVIEW"
        # NEEDS_REVIEW blocks the price quote.
        resp = api.price_quote_portfolio(pf["id"], analyst)
        validate_error(resp, ApiErrorId.ERR_SCREENING_INCOMPLETE, 409)
        # Manual review resolves it to ELIGIBLE.
        resp = api.review_account(a_nr["id"], "ELIGIBLE", eo)
        data = validate_success(resp, 200)
        assert data["eligibility_status"] == "ELIGIBLE"
        # Now quoting succeeds: 100000 * 0.025 * 1.0 = 2500.
        priced = validate_success(api.price_quote_portfolio(pf["id"], analyst), 200)
        assert priced["status"] == "PRICED"
        assert priced["quoted_price_cents"] == 2500


class TestTieredPricing:
    def test_tiered_pricing_straddles_tiers_for_hospital(self, api):
        """PRD §3.3: "The first tier covers the eligible face value up to one
        million dollars (100,000,000 cents) at a rate of 2.5 cents per dollar of
        face (0.025). The second tier covers the next four million dollars
        (400,000,000 cents) of face at 1.5 cents per dollar (0.015)."
        PRD §3.3: "The three tier amounts are summed, and the sum is then
        multiplied by a factor reflecting the seller's `org_type`: 1.0 for a
        `HOSPITAL`, 0.9 for a `PHYSICIAN_GROUP`, and 0.75 for a `DEBT_BUYER`."

        Design: Difficulty/combinatorial_formula/tiered_portfolio_pricing_straddles_tiers_with_org_factor
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        accounts = [
            create_account_payload(
                "T1", debtor_household_key="HT1", debtor_zip="75010",
                balance_cents=150000000, mailing_address="10 A St",
            ),
            create_account_payload(
                "T2", debtor_household_key="HT2", debtor_zip="75011",
                balance_cents=100000000, mailing_address="11 B St",
            ),
        ]
        priced, _accounts, _run = create_priced_portfolio(
            org["id"],
            policy["id"],
            accounts=accounts,
            label="Big bundle",
            face_value_cents=250000000,
            asking_price_cents=5000000,
        )
        assert priced["eligible_face_value_cents"] == 250000000
        # 100000000 * 0.025 + 150000000 * 0.015 = 2500000 + 2250000, factor 1.0.
        assert priced["quoted_price_cents"] == 4750000
        assert priced["quoted_price_cents"] != 6250000
        assert priced["status"] == "PRICED"

    def test_physician_group_factor_reduces_quote(self, api):
        """PRD §3.3: "The three tier amounts are summed, and the sum is then
        multiplied by a factor reflecting the seller's `org_type`: 1.0 for a
        `HOSPITAL`, 0.9 for a `PHYSICIAN_GROUP`, and 0.75 for a `DEBT_BUYER`."

        Design: Difficulty/combinatorial_formula/tiered_portfolio_pricing_straddles_tiers_with_org_factor
        """
        set_clock()
        admin = make_platform_admin_headers()
        pg_org = get_success_data(
            api.create_source_organization(
                create_source_organization_payload(
                    name="Pecos Valley Physicians",
                    org_type="PHYSICIAN_GROUP",
                    state_code="NM",
                ),
                admin,
            )
        )
        policy = create_active_policy()
        accounts = [
            create_account_payload(
                "P1", debtor_household_key="HP1", debtor_zip="88001",
                debtor_state="NM", balance_cents=150000000,
            ),
            create_account_payload(
                "P2", debtor_household_key="HP2", debtor_zip="88002",
                debtor_state="NM", balance_cents=100000000,
            ),
        ]
        priced, _accounts, _run = create_priced_portfolio(
            pg_org["id"],
            policy["id"],
            accounts=accounts,
            label="Pecos bundle",
            face_value_cents=250000000,
            asking_price_cents=5000000,
        )
        # Tiered sum 4750000, then factor 0.9: round_half_up(4750000*0.9).
        assert priced["quoted_price_cents"] == 4275000
        assert priced["status"] == "PRICED"

    def test_debt_buyer_factor_reduces_quote(self, api):
        """PRD §3.3: "The three tier amounts are summed, and the sum is then
        multiplied by a factor reflecting the seller's `org_type`: 1.0 for a
        `HOSPITAL`, 0.9 for a `PHYSICIAN_GROUP`, and 0.75 for a `DEBT_BUYER`."
        PRD §3.3: "The final quoted price is this product rounded half-up to
        whole cents — exactly one rounding, at the very end, never per tier."

        Design: Corner/calculations/pricing_debt_buyer_factor_reduces_quote
        """
        set_clock()
        admin = make_platform_admin_headers()
        db_org = get_success_data(
            api.create_source_organization(
                create_source_organization_payload(
                    name="Apex Receivables LLC",
                    org_type="DEBT_BUYER",
                    state_code="FL",
                ),
                admin,
            )
        )
        policy = create_active_policy()
        accounts = [
            create_account_payload(
                "D1", debtor_household_key="HD1", debtor_zip="33001",
                debtor_state="FL", balance_cents=150000000,
            ),
            create_account_payload(
                "D2", debtor_household_key="HD2", debtor_zip="33002",
                debtor_state="FL", balance_cents=100000000,
            ),
        ]
        priced, _accounts, _run = create_priced_portfolio(
            db_org["id"],
            policy["id"],
            accounts=accounts,
            label="Apex bundle",
            face_value_cents=250000000,
            asking_price_cents=5000000,
        )
        # round_half_up(4750000 * 0.75) = 3562500
        assert priced["quoted_price_cents"] == 3562500
        assert priced["status"] == "PRICED"


class TestFapScore:
    def test_waived_milestone_excluded_from_denominator(self, api):
        """PRD §3.9: "Every transition to `MET` or `WAIVED` recomputes the
        partnership's `fap_current_score` as a weighted attainment ratio: sum
        the `weight` of milestones in `MET`, divide by the sum of `weight` over
        all milestones not in `WAIVED`, multiply by one hundred, and round
        half-up to an integer. Waived milestones are excluded from both the
        numerator and the denominator."

        Design: Corner/calculations/fap_score_waived_milestone_excluded_from_denominator
        """
        set_clock()
        admin = make_platform_admin_headers()
        dro = make_donor_relations_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        hp = get_success_data(
            api.create_hospital_partnership(
                {
                    "source_org_id": org["id"],
                    "fap_baseline_score": 10,
                    "fap_target_score": 90,
                },
                dro,
            )
        )
        get_success_data(api.activate_hospital_partnership(hp["id"], dro))
        m30 = get_success_data(
            api.create_partnership_milestone(
                hp["id"],
                {"code": "M30", "description": "m30", "weight": 30,
                 "due_date": "2026-12-31"},
                dro,
            )
        )
        get_success_data(
            api.create_partnership_milestone(
                hp["id"],
                {"code": "M50", "description": "m50", "weight": 50,
                 "due_date": "2026-12-31"},
                dro,
            )
        )
        m20 = get_success_data(
            api.create_partnership_milestone(
                hp["id"],
                {"code": "M20", "description": "m20", "weight": 20,
                 "due_date": "2026-12-31"},
                dro,
            )
        )
        get_success_data(api.mark_milestone_met(m30["id"], dro))
        get_success_data(api.waive_milestone(m20["id"], dro))
        partnership = get_success_data(api.get_hospital_partnership(hp["id"], dro))
        # round_half_up(100 * 30 / (30 + 50)) = 38; waived 20 leaves both sides.
        assert partnership["fap_current_score"] == 38
        assert partnership["fap_current_score"] != 30


class TestFundingWaterfall:
    def test_waterfall_draws_earmarked_classes_in_order(self, api):
        """PRD §3.5: "Candidates are campaigns in `OPEN` or `FUNDED` — `CLOSED`
        campaigns never participate — sorted into three classes: first,
        hospital-earmarked campaigns whose `earmark_source_org_id` equals the
        portfolio's seller; second, geography-earmarked campaigns whose
        `earmark_state_code` equals the seller organization's `state_code`;
        third, general campaigns."
        PRD §3.5: "From each candidate the waterfall draws the smaller of the
        batch's remaining need and the campaign's uncommitted balance — its
        `raised_cents` minus its `committed_cents`."

        Design: Corner/calculations/funding_waterfall_draws_earmarked_classes_in_order
        """
        set_clock()
        admin = make_platform_admin_headers()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        policy = create_active_policy()
        accounts = [
            create_account_payload(
                "W1", debtor_household_key="HW1", debtor_zip="75070",
                balance_cents=500000,
            ),
            create_account_payload(
                "W2", debtor_household_key="HW2", debtor_zip="75071",
                balance_cents=300000,
            ),
        ]
        portfolio, imported, _contract = create_settled_portfolio(
            org["id"],
            policy["id"],
            accounts=accounts,
            label="WF bundle",
            face_value_cents=800000,
            asking_price_cents=30000,
        )
        w1, w2 = imported[0]["id"], imported[1]["id"]
        camp_h = get_success_data(
            api.create_donor_campaign(
                {"name": "Hospital Earmark", "earmark_type": "HOSPITAL",
                 "goal_cents": 1000000000, "earmark_source_org_id": org["id"]},
                dro,
            )
        )
        camp_g = get_success_data(
            api.create_donor_campaign(
                {"name": "TX Geography", "earmark_type": "GEOGRAPHY",
                 "goal_cents": 1000000000, "earmark_state_code": "TX"},
                dro,
            )
        )
        camp_gen = get_success_data(
            api.create_donor_campaign(
                {"name": "General Pool", "earmark_type": "GENERAL",
                 "goal_cents": 1000000000},
                dro,
            )
        )
        # net: 514933 - round_half_up(514933*0.029) = 514933 - 14933 = 500000
        # (fee computed per donation: round_half_up(14933.057) = 14933).
        d_h1 = get_success_data(
            api.create_donation(
                camp_h["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 514933},
                dro,
            )
        )
        get_success_data(api.receive_donation(d_h1["id"], fin))
        h_now = get_success_data(api.get_donor_campaign(camp_h["id"], fin))
        assert h_now["raised_cents"] == 500000  # all drawable
        d_g = get_success_data(
            api.create_donation(
                camp_g["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 411946},
                dro,
            )
        )
        get_success_data(api.receive_donation(d_g["id"], fin))
        g_now = get_success_data(api.get_donor_campaign(camp_g["id"], fin))
        # fee round_half_up(411946 * 0.029) = 11946 -> net 400000
        assert g_now["raised_cents"] == 400000
        d_gen = get_success_data(
            api.create_donation(
                camp_gen["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 10000000},
                dro,
            )
        )
        get_success_data(api.receive_donation(d_gen["id"], fin))
        batch = stage_batch(portfolio, [w1, w2])
        assert batch["total_abolished_cents"] == 800000
        resp = api.commit_abolishment_batch(batch["id"], fin)
        committed = validate_success(resp, 200)
        assert committed["status"] == "COMMITTED"
        assert committed["funding_allocations"] == [
            {"campaign_id": camp_h["id"], "amount_cents": 500000},
            {"campaign_id": camp_g["id"], "amount_cents": 300000},
        ]
        h_after = get_success_data(api.get_donor_campaign(camp_h["id"], fin))
        g_after = get_success_data(api.get_donor_campaign(camp_g["id"], fin))
        gen_after = get_success_data(api.get_donor_campaign(camp_gen["id"], fin))
        assert h_after["committed_cents"] == 500000
        assert g_after["committed_cents"] == 300000
        assert gen_after["committed_cents"] == 0
