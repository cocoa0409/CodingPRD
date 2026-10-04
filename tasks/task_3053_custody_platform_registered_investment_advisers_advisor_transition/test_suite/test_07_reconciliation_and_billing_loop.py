"""Fee-basis reconciliation, credit consumption and the billing loop."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    setup_firm_with_relinkable_households,
    setup_billing_ready_household,
    setup_household_with_credits,
    setup_firm_with_agreement,
    setup_household,
    open_account,
    credit_lot_position,
    refetch_household,
    refetch_account,
    settle_billing_run,
    setup_configured_system,
    refetch_run,
)
"""Fee-basis reconciliation, credit consumption and the billing loop."""
"""Fee-basis reconciliation, credit consumption and the billing loop."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestHouseholdBasisConservation:

    def test_relinking_an_account_preserves_the_firm_level_total(self):
        """PRD §3.7: "`household_fee_basis_total_cents` on the firm is the sum of
        `household_fee_basis_cents` across every household of the firm".
        PRD §3.3: "relinking reassigns an account's `household_id` to a
        `target_household_id` and re-derives the fee basis and annual fee of both the
        old and the new household".

        Design: Difficulty/compensating_invariant/household_fee_basis_conservation_under_relink
        """
        scenario = setup_firm_with_relinkable_households()
        firm = scenario["firm"]
        moving = scenario["accounts"][1]

        destination = refetch_household(scenario["destination"]["id"])
        validate_success(api_client.relink_account(
            moving["id"],
            {"target_household_id": destination["id"], "expected_household_version": destination["version"]},
            ADVISOR, row=moving), 200)

        source = refetch_household(scenario["household"]["id"])
        target = refetch_household(destination["id"])
        assert source["household_fee_basis_cents"] == 200_000_000
        assert target["household_fee_basis_cents"] == 120_000_000
        assert source["household_fee_basis_cents"] + target["household_fee_basis_cents"] == 320_000_000

        refreshed = validate_success(api_client.get_firm(firm["id"], ADVISOR), 200)
        assert refreshed["household_fee_basis_total_cents"] == 320_000_000

    def test_the_reconciliation_invariant_holds_with_zero_drift(self):
        """PRD §3.9: "The invariant is `BROKEN` exactly when either drift is non-zero
        and the platform configuration has `database_invariant_enforcement` set to
        `ENFORCED`; the tolerance is zero cents".
        PRD §3.9: "the drift between the household-level and account-level figures is
        the second minus the third".

        Design: Difficulty/compensating_invariant/household_fee_basis_conservation_under_relink
        """
        scenario = setup_firm_with_relinkable_households()
        destination = refetch_household(scenario["destination"]["id"])
        validate_success(api_client.relink_account(
            scenario["accounts"][1]["id"],
            {"target_household_id": destination["id"], "expected_household_version": destination["version"]},
            ADVISOR, row=scenario["accounts"][1]), 200)

        invariants = validate_success(api_client.evaluate_invariants(
            {"firm_id": scenario["firm"]["id"]}, CUSTODY,
        ), 200)
        reconciliation = next(
            i for i in invariants if i["invariant_code"] == "HOUSEHOLD_FEE_BASIS_RECONCILIATION"
        )
        assert reconciliation["invariant_status"] == "HOLDING"
        assert reconciliation["expected_total_cents"] == 320_000_000
        assert reconciliation["observed_total_cents"] == 320_000_000
        assert reconciliation["breach_detail_code"] is None


class TestImmediateConsistency:

    def test_the_household_basis_is_already_current_on_the_next_read(self):
        """PRD §2.12: "The clock's startup default is exactly `2026-09-01T00:00:00Z`".
        PRD §1: "the design therefore treats a small number of conserved quantities —
        the firm's agreement authority, its evidence rollup, the household fee basis
        — as invariants that the platform recomputes".
        PRD §3.4: "one hop further, has each owning household recompute
        `household_fee_basis_cents`."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_the_same_response
        """
        firm, agreement = setup_firm_with_agreement(
            entitlement_codes=("TRADING_AUTHORIZATION", "BILLING")
        )
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-110001")

        transfer, _lots = credit_lot_position(account["id"], firm["id"])
        assert transfer["carryover_cents"] == 90_000_000

        first = refetch_household(household["id"])
        assert first["household_fee_basis_cents"] == 100_000_000
        second = refetch_household(household["id"])
        assert second["household_fee_basis_cents"] == first["household_fee_basis_cents"]
        assert refetch_account(account["id"])["account_fee_basis_cents"] == 100_000_000


class TestBillingRunLoop:

    def test_a_mismatched_remittance_holds_the_household_without_compensating(self):
        """PRD §3.7: "This operation never rejects on a mismatch: it records the
        stated amount and, when the two differ, transitions the run from `SETTLED` to
        `INVOICE_MISMATCH` and holds the household's billing by moving
        `household_status` from `ACTIVE` to `BILLING_HELD`."

        Design: Corner/consistency_model/housekeeping_confirmation_that_no_compensation_path_is_required
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=320_000_000,
        )
        run = settle_billing_run(firm["id"], household["id"], stated_invoice_cents=999_999)
        assert run["gross_fee_cents"] == 890_553

        mismatched = validate_success(
            api_client.remit_invoice(run["id"], {"stated_invoice_cents": 999_999}, ADVISOR, row=refetch_run(run["id"])), 200
        )
        assert mismatched["billing_run_status"] == "INVOICE_MISMATCH"
        assert refetch_household(household["id"])["household_status"] == "BILLING_HELD"
        assert mismatched["gross_fee_cents"] == 890_553

    def test_reopening_releases_the_hold_and_the_consumed_credits(self):
        """PRD §3.7: "From `INVOICE_MISMATCH` the run moves to `REOPENED`; the
        consumed credits are released, with every `FeeCredit` the run consumed
        returning to `credit_status` `AVAILABLE` and the run's `credit_applied_cents`
        and `net_fee_cents` released with them; and the household returns from
        `BILLING_HELD` to `ACTIVE`."

        Design: Corner/consistency_model/housekeeping_confirmation_that_no_compensation_path_is_required
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=320_000_000,
        )
        run = settle_billing_run(firm["id"], household["id"], stated_invoice_cents=890_553)
        validate_success(
            api_client.remit_invoice(run["id"], {"stated_invoice_cents": 999_999}, ADVISOR, row=refetch_run(run["id"])), 200
        )

        reopened = validate_success(
            api_client.reopen_billing_run(run["id"], {}, COMPLIANCE, row=refetch_run(run["id"])), 200
        )
        assert reopened["billing_run_status"] == "REOPENED"
        assert refetch_household(household["id"])["household_status"] == "ACTIVE"
        assert reopened["credit_applied_cents"] == 0

    def test_a_held_household_cannot_seed_a_new_run(self):
        """PRD §3.7: "Then comes the household's own lifecycle: a household whose
        `household_status` is `BILLING_HELD` cannot seed a new run at all, and the
        attempt is refused with `ERR_HOUSEHOLD_BILLING_HELD` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/billing_run_state_before_fiscal_pair
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=320_000_000,
        )
        run = settle_billing_run(firm["id"], household["id"], stated_invoice_cents=890_553)
        validate_success(
            api_client.remit_invoice(run["id"], {"stated_invoice_cents": 999_999}, ADVISOR, row=refetch_run(run["id"])), 200
        )

        res = api_client.create_billing_run(
            {"firm_id": firm["id"], "household_id": household["id"],
             "period_start_date": "2026-12-01T00:00:00Z",
             "period_end_date": "2027-03-01T00:00:00Z",
             "fee_variant_used": "HOUSEHOLD_AGGREGATED", "stated_invoice_cents": 0},
            ADVISOR,
        )
        validate_error(res, "ERR_HOUSEHOLD_BILLING_HELD", expected_status=409)

    def test_the_state_error_outranks_both_fiscal_failures(self):
        """PRD §3.7: "a household whose basis is zero fails both the zero test and the
        minimum test, and the zero test is the earlier of the two."
        PRD §2.1: "for example a seeding attempt against a zero-basis household that is
        also below the minimum threshold reports the zero-basis error rather than the
        minimum error".

        Design: Difficulty/priority_pair_validation_conflict/billing_run_state_before_fiscal_pair
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=320_000_000, account_number="RIA-101001",
        )
        run = settle_billing_run(firm["id"], household["id"], stated_invoice_cents=890_553)
        validate_success(
            api_client.remit_invoice(run["id"], {"stated_invoice_cents": 999_999}, ADVISOR, row=refetch_run(run["id"])), 200
        )
        validate_success(api_client.close_account(
            accounts[0]["id"], {}, CUSTODY, row=refetch_account(accounts[0]["id"]),
        ), 200)
        assert refetch_household(household["id"])["household_fee_basis_cents"] == 0

        error = validate_error(
            api_client.create_billing_run(
                {"firm_id": firm["id"], "household_id": household["id"],
                 "period_start_date": "2026-12-01T00:00:00Z",
                 "period_end_date": "2027-03-01T00:00:00Z",
                 "fee_variant_used": "HOUSEHOLD_AGGREGATED", "stated_invoice_cents": 0},
                ADVISOR,
            ),
            "ERR_HOUSEHOLD_BILLING_HELD", expected_status=409,
        )
        assert error["error_id"] != "ERR_FEE_BASIS_ZERO"
        assert error["error_id"] != "ERR_FEE_BASIS_BELOW_MINIMUM"


class TestCreditConsumption:

    def test_credits_are_consumed_in_earned_order_down_to_the_headroom(self):
        """PRD §3.6: "The platform walks the household's `FeeCredit` rows whose
        `credit_status` is `AVAILABLE` or `PARTIALLY_APPLIED` in ascending
        `earned_on_date` order".
        PRD §3.6: "A credit fully consumed becomes `APPLIED`; one only partly consumed
        becomes `PARTIALLY_APPLIED` and keeps its remainder".

        Design: Corner/endpoints/billing_run_partial_fill_style_partial_success_on_credit_application
        """
        scenario = setup_household_with_credits(
            basis_cents=320_000_000, credit_amounts=(300_000, 700_000),
        )
        run = settle_billing_run(
            scenario["firm"]["id"], scenario["household"]["id"], stated_invoice_cents=890_553,
        )
        assert run["gross_fee_cents"] == 890_553
        assert run["credit_applied_cents"] == 890_553
        assert run["net_fee_cents"] == 0
        assert run["billing_run_status"] == "SETTLED"

    def test_the_run_never_over_consumes_the_partial_credit(self):
        """PRD §3.6: "Each credit is consumed only down to the remaining headroom,
        which is `gross_fee_cents` minus `credit_applied_cents` accumulated so far."
        PRD §3.6: "A consequence worth stating plainly is that `credit_applied_cents`
        never exceeds `gross_fee_cents`."

        Design: Corner/endpoints/billing_run_partial_fill_style_partial_success_on_credit_application
        """
        scenario = setup_household_with_credits(
            basis_cents=320_000_000, credit_amounts=(300_000, 700_000),
        )
        run = settle_billing_run(
            scenario["firm"]["id"], scenario["household"]["id"], stated_invoice_cents=890_553,
        )

        consumed = validate_success(
            api_client.list_run_fee_credits(run["id"], COMPLIANCE), 200
        )
        assert any(c["credit_status"] == "APPLIED" for c in consumed)

        household_credits = validate_success(api_client.list_household_fee_credits(
            scenario["household"]["id"], ADVISOR,
        ), 200)
        partials = [c for c in household_credits if c["credit_status"] == "PARTIALLY_APPLIED"]
        assert partials, "the newer credit must survive partially consumed"
        assert run["credit_applied_cents"] <= run["gross_fee_cents"]


class TestInvariantEnforcementSwitch:

    def test_the_enforcement_switch_does_not_retroactively_change_a_settled_run(self):
        """PRD §2.12: "Whether a broken invariant merely reports or actually blocks
        writes is a platform-wide switch, held on the singleton `SystemConfig` row
        whose `config_key` is always `CUSTODY_PLATFORM_DEFAULTS`."
        PRD §2.12: "Its `database_invariant_enforcement` field takes the values `WARN`
        and `ENFORCED` and defaults to `WARN`".

        Design: Corner/cross_cutting_layers/idempotent_duplicate_feature_flag_free_config_read
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=320_000_000,
        )
        config = setup_configured_system("ENFORCED")
        assert config["database_invariant_enforcement"] == "ENFORCED"
        assert config["platform_fee_enabled"] is True

        run = settle_billing_run(firm["id"], household["id"], stated_invoice_cents=890_553)
        assert run["net_fee_cents"] == 890_553

        validate_success(api_client.patch_system_config(
            config["id"], {"database_invariant_enforcement": "WARN"}, TEST_USERS["admin_headers"], row=config), 200)
        unchanged = validate_success(api_client.get_billing_run(run["id"], ADVISOR), 200)
        assert unchanged["net_fee_cents"] == 890_553

    def test_the_reconciliation_figures_agree_under_enforcement(self):
        """PRD §3.9: "An invariant sweep recomputes every invariant of a firm and
        stores the results".
        PRD §3.9: "`observed_total_cents` records the account-level sum,
        `expected_total_cents` records the firm-level total".

        Design: Corner/cross_cutting_layers/idempotent_duplicate_feature_flag_free_config_read
        """
        firm, agreement, household, accounts = setup_billing_ready_household(
            basis_cents=320_000_000,
        )
        setup_configured_system("ENFORCED")
        settle_billing_run(firm["id"], household["id"], stated_invoice_cents=588_384)

        invariants = validate_success(api_client.evaluate_invariants(
            {"firm_id": firm["id"]}, CUSTODY,
        ), 200)
        reconciliation = next(
            i for i in invariants if i["invariant_code"] == "HOUSEHOLD_FEE_BASIS_RECONCILIATION"
        )
        assert reconciliation["invariant_status"] == "HOLDING"
        assert reconciliation["expected_total_cents"] == 320_000_000
        assert reconciliation["observed_total_cents"] == 320_000_000
        assert validate_success(
            api_client.get_firm(firm["id"], ADVISOR), 200
        )["household_fee_basis_total_cents"] == 320_000_000