"""Software licenses: suspend/resume cycle, pinned billing evaluation order,
sample tier boundaries, cloud credit flat costs, and provisional-vs-final
billing divergence (PRD sections 2.5, 3.7).
"""
from test_helpers import (
    TEST_USERS,
    activate_license,
    assert_billing_close_result,
    create_license,
    create_submitted_forecast,
    forecast_line,
    grant_credits,
    license_status_payload,
    record_run,
    setup_run_ready,
    validate_success,
)
from test_helpers import api_client


def _close_billing(license_id: str) -> dict:
    return validate_success(
        api_client.close_billing_period(
            license_id, TEST_USERS["finance_admin_headers"]
        )
    )


def _setup_billing_order_scenario() -> dict:
    """ACTIVE license with 70 fresh credits (granted 2026-08-01) and 30 stale
    credits (granted 2025-08-01, more than 365 days old at the close instant);
    one LOCAL SUCCESS run of 1000 samples inside period 1."""
    bag = setup_run_ready()
    license_id = bag["license"]["id"]
    grant_credits(license_id, 70, grant_type="PURCHASE", granted_on="2026-08-01")
    grant_credits(license_id, 30, grant_type="GRANT", granted_on="2025-08-01")
    record_run(
        bag["instrument"]["id"], bag["lot"]["id"], license_id,
        bag["account"]["id"], samples_count=1000,
    )
    return bag


class TestBillingEvaluationOrderPinned:
    def test_expiry_runs_before_offset(self, api):
        """With 100 total credits of which 30 are stale, the pinned order
        expires the 30 FIRST, so only 70 credits offset the invoice — not
        the 100 an offset-then-expire order would consume.

        PRD §3.7: "Fourth, credit expiry runs before any offset: an `EXPIRY` entry is appended for every granted credit (from `GRANT` or `PURCHASE` entries) whose `granted_on` is more than 365 days old at the close instant and which has not yet been consumed, and `credits_balance` is recomputed."
        PRD §3.7: "Fifth, the offset: `offset_credits` is the smaller of the post-expiry balance and the whole-credit floor of half the gross divided by 100 cents per credit; `offset_cents` is `offset_credits` times 100; and an `OFFSET` entry of negative `offset_credits` is appended."
        PRD §3.7: "Applying the offset before expiry would let expiring credits pay down the invoice, and that order is forbidden."

        Design: Difficulty/combinatorial_formula/billing_evaluation_order_pinned
        """
        bag = _setup_billing_order_scenario()
        result = _close_billing(bag["license"]["id"])
        assert_billing_close_result(result)
        assert result["expired_credits"] == 30, (
            "the 2025-08-01 grant is more than 365 days old at close, got "
            f"{result['expired_credits']}"
        )
        # offset = min(post-expiry balance 70, floor(200000 * 0.5 / 100) = 1000)
        assert result["offset_credits"] == 70
        assert result["net_cents"] == 193_000
        assert result["credits_balance"] == 0

    def test_tier_gross_and_offset_cents_of_pinned_order(self, api):
        """Same scenario: 1000 billable samples land in T2 and gross
        200,000c; the offset posts 70 credits x 100 cents.

        PRD §3.7: "Second, the tier is chosen: T1 below 1,000 billable samples, T2 from 1,000 up to 4,999, and T3 at 5,000 or more."
        PRD §3.7: "Third, `gross_cents` is `billable_samples` times the pinned per-sample rate for that tier — a single average rate applied to all samples, not a marginal bracket."

        Design: Difficulty/combinatorial_formula/billing_evaluation_order_pinned
        """
        bag = _setup_billing_order_scenario()
        result = _close_billing(bag["license"]["id"])
        assert result["billable_samples"] == 1000
        assert result["tier"] == "T2"
        assert result["gross_cents"] == 200_000
        assert result["offset_cents"] == 7_000


class TestSampleTierExactBoundary:
    def test_exactly_1000_samples_uses_t2_rate(self, api):
        """Exactly 1000 billable samples belongs to T2 (the breakpoint is
        inclusive of the lower-rate tier's minimum): gross 1000 x 200c.

        PRD §3.7: "Second, the tier is chosen: T1 below 1,000 billable samples, T2 from 1,000 up to 4,999, and T3 at 5,000 or more."
        PRD §3.7: "Third, `gross_cents` is `billable_samples` times the pinned per-sample rate for that tier — a single average rate applied to all samples, not a marginal bracket."

        Design: Difficulty/boundary_precision_check/sample_tier_exact_boundary_uses_lower_rate
        """
        bag = setup_run_ready()
        record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"], samples_count=1000,
        )
        result = _close_billing(bag["license"]["id"])
        assert result["billable_samples"] == 1000
        assert result["tier"] == "T2"
        assert result["gross_cents"] == 200_000
        assert result["net_cents"] == 200_000

    def test_999_samples_uses_t1_rate(self, api):
        """One sample below the boundary prices all samples at T1:
        gross 999 x 250c = 249,750c.

        PRD §3.7: "Second, the tier is chosen: T1 below 1,000 billable samples, T2 from 1,000 up to 4,999, and T3 at 5,000 or more."
        PRD §3.7: "Third, `gross_cents` is `billable_samples` times the pinned per-sample rate for that tier — a single average rate applied to all samples, not a marginal bracket."

        Design: Difficulty/boundary_precision_check/sample_tier_exact_boundary_uses_lower_rate
        """
        bag = setup_run_ready()
        record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"], samples_count=999,
        )
        result = _close_billing(bag["license"]["id"])
        assert result["billable_samples"] == 999
        assert result["tier"] == "T1"
        assert result["gross_cents"] == 249_750
        assert result["net_cents"] == 249_750


class TestLicenseSuspendResumeCycle:
    def test_two_full_suspend_resume_loops(self, api):
        """The license cycles ACTIVE -> SUSPENDED -> ACTIVE twice with no
        terminal state.

        PRD §3.7: "The license then cycles `DRAFT` to `ACTIVE` to `SUSPENDED` and back to `ACTIVE` under `FinanceAdmin` control, with no terminal state; its `version` increments on each move."

        Design: Difficulty/non_linear_state_machine/license_suspend_resume_cycle
        """
        license_data = create_license()
        activate_license(license_data["id"])
        observed = []
        for action in ("SUSPEND", "REINSTATE", "SUSPEND", "REINSTATE"):
            data = validate_success(
                api_client.set_license_status(
                    license_data["id"],
                    license_status_payload(action),
                    TEST_USERS["finance_admin_headers"],
                )
            )
            observed.append(data["license_state"])
        assert observed == ["SUSPENDED", "ACTIVE", "SUSPENDED", "ACTIVE"], (
            f"two full loops must cycle, got {observed}"
        )

    def test_cycle_increments_version_on_each_move(self, api):
        """Create (1) + ACTIVATE (2) + four cycle transitions land the
        license on version 6.

        PRD §3.7: "The license then cycles `DRAFT` to `ACTIVE` to `SUSPENDED` and back to `ACTIVE` under `FinanceAdmin` control, with no terminal state; its `version` increments on each move."
        PRD §2.5: "`version` (integer): begins at 1 at creation and increases by exactly one on every mutation, whether user-triggered or system-driven."

        Design: Difficulty/non_linear_state_machine/license_suspend_resume_cycle
        """
        license_data = create_license()
        activate_license(license_data["id"])
        data = None
        for action in ("SUSPEND", "REINSTATE", "SUSPEND", "REINSTATE"):
            data = validate_success(
                api_client.set_license_status(
                    license_data["id"],
                    license_status_payload(action),
                    TEST_USERS["finance_admin_headers"],
                )
            )
        assert data["version"] == 6, (
            f"1 create + 1 activate + 4 cycle moves must give 6, got {data['version']}"
        )


class TestProvisionalBillingDivergence:
    def test_provisional_and_final_disagree_on_same_period(self, api):
        """The forecast-implied provisional figure (75 kits x 16 samples =
        1,200 -> T2 -> 240,000c) and the actual-runs figure (950 -> T1 ->
        237,500c) diverge in both tier and total.

        PRD §3.7: "`provisional_samples` is the sum, over the account's `SUBMITTED` or `FROZEN` forecast lines whose week intersects the period window, of the line quantity times the referenced kit's `samples_per_kit`; `provisional_gross_cents` multiplies that provisional count by the pinned rate of whichever tier the provisional count lands in."
        PRD §3.7: "The final gross uses actual run records and may legitimately land in a different tier than the provisional figure."

        Design: Corner/calculations/provisional_billing_diverges_from_final
        """
        bag = setup_run_ready()
        create_submitted_forecast(
            account_id=bag["account"]["id"],
            lines=[forecast_line(
                bag["kit"]["kit_code"], "2026-09-07T00:00:00Z", 75
            )],
        )
        record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"], samples_count=950, output_gb=48.0,
        )
        result = _close_billing(bag["license"]["id"])
        assert result["provisional_samples"] == 1200
        assert result["provisional_gross_cents"] == 240_000
        assert result["billable_samples"] == 950
        assert result["tier"] == "T1"
        assert result["gross_cents"] == 237_500


class TestCloudCreditFlatCosts:
    def test_flat_costs_and_exact_balance_boundary(self, api):
        """CLOUD_STANDARD debits a flat 10 and CLOUD_DEEP a flat 25; with 35
        credits the second run's balance is exactly 25 — the at-least-cost
        rule admits it and drains the balance to 0.

        PRD §3.7: "For `SUCCESS` and `PARTIAL` runs, the license's `samples_this_period` grows by `samples_count`, and cloud analysis debits a flat per-run cost — 0 credits for `LOCAL`, 10 for `CLOUD_STANDARD`, and 25 for `CLOUD_DEEP` — recorded as a `CONSUMPTION` ledger entry and echoed on the record as `credits_consumed`."
        PRD §3.7: "The `credits_balance` is always the sum of all ledger entries' `credits` and may never go negative — a run whose cloud cost would exceed the balance is refused outright."

        Design: Corner/calculations/cloud_credit_flat_cost_and_exact_balance_boundary
        """
        bag = setup_run_ready(grant_credits_amount=35, granted_on="2026-08-15")
        run1 = record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"], analysis_mode="CLOUD_STANDARD",
        )
        assert run1["credits_consumed"] == 10
        run2 = record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"], analysis_mode="CLOUD_DEEP",
        )
        assert run2["credits_consumed"] == 25, (
            "balance exactly 25 >= cost 25 must be allowed"
        )
        license_after = validate_success(
            api_client.get_software_license(
                bag["license"]["id"], TEST_USERS["finance_admin_headers"]
            )
        )
        assert license_after["credits_balance"] == 0, (
            "35 - 10 - 25 must conserve to 0, got "
            f"{license_after['credits_balance']}"
        )
