"""Boundary precision: exact-threshold and one-over behavior for the
campaign funding threshold and the eligibility income cap."""
from test_helpers import (
    create_account_payload,
    create_active_policy,
    create_org,
    create_portfolio_payload,
    get_success_data,
    make_donor_relations_headers,
    make_eligibility_officer_headers,
    make_finance_officer_headers,
    make_portfolio_analyst_headers,
    set_clock,
    validate_success,
)


class TestCampaignFundingBoundary:
    def test_campaign_funded_at_exact_goal_equality(self, api):
        """PRD §3.5: "If the campaign was `OPEN` and its `raised_cents` now
        meets or exceeds `goal_cents` — equality counts as funded — the
        campaign automatically flips to `FUNDED`; a funded campaign remains
        open to further donations and to funding draws."

        Design: Difficulty/boundary_precision_check/campaign_funded_at_exact_goal_equality
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        c_eq = get_success_data(
            api.create_donor_campaign(
                {"name": "Exact Goal", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        c_lt = get_success_data(
            api.create_donor_campaign(
                {"name": "Just Short", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        d_eq = get_success_data(
            api.create_donation(
                c_eq["id"],
                {"donor_name": "Eq", "donor_email": "eq@x.com",
                 "gross_cents": 1029866},
                dro,
            )
        )
        # fee round_half_up(1029866 * 0.029) = 29866 -> net exactly the goal
        assert d_eq["net_cents"] == 1000000
        get_success_data(api.receive_donation(d_eq["id"], fin))
        d_lt = get_success_data(
            api.create_donation(
                c_lt["id"],
                {"donor_name": "Lt", "donor_email": "lt@x.com",
                 "gross_cents": 1029865},
                dro,
            )
        )
        # fee round_half_up(1029865 * 0.029) = 29866 -> net one cent short
        assert d_lt["net_cents"] == 999999
        get_success_data(api.receive_donation(d_lt["id"], fin))
        eq_now = get_success_data(api.get_donor_campaign(c_eq["id"], fin))
        lt_now = get_success_data(api.get_donor_campaign(c_lt["id"], fin))
        assert eq_now["raised_cents"] == 1000000
        assert eq_now["status"] == "FUNDED"
        assert lt_now["raised_cents"] == 999999
        assert lt_now["status"] == "OPEN"

    def test_campaign_funded_still_accepts_donations(self, api):
        """PRD §3.5: "If the campaign was `OPEN` and its `raised_cents` now
        meets or exceeds `goal_cents` — equality counts as funded — the
        campaign automatically flips to `FUNDED`; a funded campaign remains
        open to further donations and to funding draws."

        Design: Difficulty/boundary_precision_check/campaign_funded_at_exact_goal_equality
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Funded Open", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        d1 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Eq", "donor_email": "eq@x.com",
                 "gross_cents": 1029866},
                dro,
            )
        )
        get_success_data(api.receive_donation(d1["id"], fin))
        now = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert now["status"] == "FUNDED"
        assert now["raised_cents"] == now["goal_cents"]
        # A FUNDED campaign still accepts further donations.
        d2 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "More", "donor_email": "m@x.com",
                 "gross_cents": 100000},
                dro,
            )
        )
        assert d2["status"] == "PLEDGED"


class TestEligibilityIncomeBoundary:
    def test_income_at_exact_cap_qualifies(self, api):
        """PRD §3.2: "Otherwise, if `annual_income_cents` is at most the cap —
        equality qualifies — the account is `ELIGIBLE`, and insolvency is never
        consulted."

        Design: Difficulty/boundary_precision_check/eligibility_income_at_exact_cap_qualifies
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        analyst = make_portfolio_analyst_headers()
        eo = make_eligibility_officer_headers()
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        # Cap at multiplier 4.0, household size 1: 1565000 * 4.0 = 6260000.
        imported = get_success_data(
            api.import_accounts(
                pf["id"],
                [
                    create_account_payload(
                        "AAT", debtor_household_key="HB1", debtor_zip="75020",
                        annual_income_cents=6260000,
                    ),
                    create_account_payload(
                        "AOV", debtor_household_key="HB2", debtor_zip="75021",
                        annual_income_cents=6260001,
                    ),
                ],
                analyst,
            )
        )
        a_at, a_over = imported[0], imported[1]
        get_success_data(api.submit_portfolio(pf["id"], analyst))
        run = get_success_data(api.create_screening_run(pf["id"], policy["id"], eo))
        run_data = validate_success(api.execute_screening_run(run["id"], eo), 200)
        assert run_data["eligible_count"] == 1
        assert run_data["ineligible_count"] == 1
        at = get_success_data(api.get_account(a_at["id"], eo))
        over = get_success_data(api.get_account(a_over["id"], eo))
        assert at["eligibility_status"] == "ELIGIBLE"
        assert over["eligibility_status"] == "INELIGIBLE"

    def test_household_size_scales_the_cap(self, api):
        """PRD §3.2: "For each account, the system computes an income cap: take
        the federal poverty level base of 15,650.00 dollars for a household of
        one, add 5,560.00 dollars for each additional household member, multiply
        by the policy's `fpl_multiplier`, and round the result half-up to whole
        cents."

        Design: Difficulty/boundary_precision_check/eligibility_income_at_exact_cap_qualifies
        """
        set_clock()
        org = create_org()
        policy = create_active_policy()
        analyst = make_portfolio_analyst_headers()
        eo = make_eligibility_officer_headers()
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        # Household size 2 cap: (1565000 + 556000) * 4.0 = 8484000.
        imported = get_success_data(
            api.import_accounts(
                pf["id"],
                [
                    create_account_payload(
                        "SAT", debtor_household_key="HB3", debtor_zip="75022",
                        household_size=2, annual_income_cents=8484000,
                    ),
                    create_account_payload(
                        "SOV", debtor_household_key="HB4", debtor_zip="75023",
                        household_size=2, annual_income_cents=8484001,
                    ),
                ],
                analyst,
            )
        )
        a_at, a_over = imported[0], imported[1]
        get_success_data(api.submit_portfolio(pf["id"], analyst))
        run = get_success_data(api.create_screening_run(pf["id"], policy["id"], eo))
        validate_success(api.execute_screening_run(run["id"], eo), 200)
        at = get_success_data(api.get_account(a_at["id"], eo))
        over = get_success_data(api.get_account(a_over["id"], eo))
        assert at["eligibility_status"] == "ELIGIBLE"
        assert over["eligibility_status"] == "INELIGIBLE"
