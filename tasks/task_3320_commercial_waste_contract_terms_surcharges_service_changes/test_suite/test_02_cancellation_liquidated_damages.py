"""Cancellation, liquidated damages, and waiver tests (PRD section 3.8)."""
from test_helpers import (
    set_clock,
    make_customer,
    make_contract,
    add_service_line,
    activate_contract,
    make_cancellation,
    get_customer_balance,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_customer_headers

OPS = TEST_USERS["ops_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_ld_contract(legal_name, billing_email):
    """ACTIVE contract: start 2026-09-01, term 12mo (end 2027-09-01),
    notice 60d, one line @ 300000."""
    set_clock("2026-09-01T00:00:00Z")
    customer = make_customer(legal_name=legal_name, billing_email=billing_email)
    contract = make_contract(
        customer["id"], term_months=12, cancellation_notice_days=60
    )
    add_service_line(
        contract["id"], container_size="CY_6",
        frequency_per_week=3, base_rate_cents=300000,
    )
    activate_contract(contract["id"])
    return customer, contract


class TestTimelyVsUntimelySameContract:
    def test_timely_branch_terminates_immediately_with_zero_ld(self, api):
        """PRD section 3.8: "On the timely branch — where `timely` is true and
        therefore `ld_total_cents` is 0 — the contract moves directly from
        `ACTIVE` to `TERMINATED` and no damages are assessed."
        PRD section 3.8: "The `timely` flag is true exactly when the
        `requested_end_date` is on or before the contract's `end_date` minus
        `cancellation_notice_days` days; a requested date later than that
        threshold is untimely."

        Design: Difficulty/dual_variant_calc/ld_amount_timely_vs_untimely_same_contract
        """
        customer, contract = _setup_ld_contract("Timely Corp", "t@x.example")
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2027-07-03T00:00:00Z"
        )
        assert cancellation["timely"] is True

        approved = validate_success(
            api.approve_cancellation(cancellation["id"], OPS)
        )
        assert approved["ld_total_cents"] == 0
        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["status"] == "TERMINATED"
        assert get_customer_balance(customer["id"]) == 0

    def test_untimely_branch_assesses_two_month_ld_and_parks(self, api):
        """PRD section 3.8: "otherwise it is the number of calendar months from
        the `requested_end_date` to the contract's `end_date` with any partial
        month rounded up to a full month — both dates are day-aligned, so for
        example a span from 2027-07-04 to 2027-09-01 is one whole month plus 28
        days and counts as 2."
        PRD section 3.8: "The `ld_total_cents` is the `ld_base_cents`
        multiplied by `months_remaining` multiplied by one half (0.5), rounded
        half-up to a whole cent; when the filing is timely the total is 0."
        PRD section 3.8: "Assessing damages sets the request's `ld_status`
        from its initial `NONE` to `ASSESSED` and immediately debits the
        customer's `credit_balance_cents` by `ld_total_cents` per section 2.7."

        Design: Difficulty/dual_variant_calc/ld_amount_timely_vs_untimely_same_contract
        """
        customer, contract = _setup_ld_contract("Untimely Corp", "u@x.example")
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2027-07-04T00:00:00Z"
        )
        assert cancellation["timely"] is False
        assert cancellation["months_remaining"] == 2

        approved = validate_success(
            api.approve_cancellation(cancellation["id"], OPS)
        )
        assert approved["ld_status"] == "ASSESSED"
        assert approved["ld_base_cents"] == 300000
        assert approved["ld_total_cents"] == 300000, (
            "300000 base * 2 months * 0.5 must give 300000, "
            f"got {approved['ld_total_cents']}"
        )
        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["status"] == "TERMINATION_PENDING"
        assert get_customer_balance(customer["id"]) == -300000


class TestLdAssessThenWaive:
    def test_waive_credits_balance_back_and_keeps_termination_pending(self, api):
        """PRD section 3.8: "an `OpsManager` waiving the damages moves
        `ld_status` from `ASSESSED` to `WAIVED` and immediately credits the
        customer's `credit_balance_cents` back by the waived `ld_total_cents`."

        Design: Difficulty/compensating_invariant/ld_assess_then_waive_conserves_balance
        """
        customer, contract = _setup_ld_contract("Waive Co", "wv@x.example")
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2027-07-04T00:00:00Z"
        )
        approved = validate_success(
            api.approve_cancellation(cancellation["id"], OPS)
        )
        assert approved["ld_status"] == "ASSESSED"
        assert get_customer_balance(customer["id"]) == -300000

        waived = validate_success(
            api.waive_cancellation_ld(cancellation["id"], OPS)
        )
        assert waived["ld_status"] == "WAIVED"
        assert waived["ld_total_cents"] == 300000
        assert get_customer_balance(customer["id"]) == 0, (
            "the waived amount must credit the balance back to exactly 0"
        )
        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["status"] == "TERMINATION_PENDING"

    def test_assess_then_waive_returns_balance_to_starting_value(self, api):
        """PRD section 2.7: "waiving assessed damages raises it back by the
        waived amount".
        PRD section 2.7: "Each customer carries a server-maintained ledger
        balance, `credit_balance_cents`, which starts at 0 when the customer is
        created and is never accepted from client input".

        Design: Difficulty/compensating_invariant/ld_assess_then_waive_conserves_balance
        """
        customer, contract = _setup_ld_contract("Waive2 Co", "wv2@x.example")
        assert get_customer_balance(customer["id"]) == 0
        cancellation = make_cancellation(
            customer["id"], contract["id"], "2027-07-04T00:00:00Z"
        )
        validate_success(api.approve_cancellation(cancellation["id"], OPS))
        validate_success(api.waive_cancellation_ld(cancellation["id"], OPS))
        assert get_customer_balance(customer["id"]) == 0


class TestDerivedBalanceAfterWaiveAndNewCredit:
    def test_balance_reconciles_after_waive_then_new_credit(self, api):
        """PRD section 2.7: "it equals the sum of `credit_cents` over every
        service credit in `ACTIVE` status whose service line belongs to a
        contract of this customer, minus the sum of `ld_total_cents` over every
        cancellation request with `ld_status` equal to `ASSESSED` on contracts
        of this customer."
        PRD section 3.6: "The credit amount is server-computed and any
        client-supplied value is ignored: `credit_cents` equals the floor of
        the line's `base_rate_cents` multiplied by the credit percentage of
        base, `credit_pct_of_base`, in effect under the surcharge configuration
        active at filing."

        Design: Corner/cross_cutting_layers/derived_balance_after_waive_and_new_credit
        """
        from test_helpers import (
            make_fixed_config,
            make_pickup_event,
            make_service_credit,
        )

        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z",
            fuel_fixed_pct=0.10, environmental_pct=0.10, admin_pct=0.05,
            contamination_fee_cents=15000, overweight_fee_cents=20000,
            credit_pct_of_base=0.05,
        )
        customer = make_customer(legal_name="Dfr Co", billing_email="df@x.example")
        contract = make_contract(
            customer["id"], term_months=12, cancellation_notice_days=60
        )
        line = add_service_line(
            contract["id"], container_size="CY_4",
            frequency_per_week=5, base_rate_cents=600000,
        )
        activate_contract(contract["id"])

        cancellation = make_cancellation(
            customer["id"], contract["id"], "2027-07-04T00:00:00Z"
        )
        validate_success(api.approve_cancellation(cancellation["id"], OPS))
        assert get_customer_balance(customer["id"]) == -600000
        validate_success(api.waive_cancellation_ld(cancellation["id"], OPS))
        assert get_customer_balance(customer["id"]) == 0

        missed = make_pickup_event(line["id"], "2026-09-01", "MISSED")
        credit = make_service_credit(customer["id"], line["id"], missed["id"])
        assert credit["credit_cents"] == 30000
        assert credit["status"] == "ACTIVE"
        assert get_customer_balance(customer["id"]) == 30000
