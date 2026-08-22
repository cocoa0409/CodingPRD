"""Multi-input formulas: the tiered fee split, and the capped effective-weight loop."""
from test_helpers import (
    TEST_USERS,
    create_fee_invoice_payload,
    list_trade_orders,
    open_account,
    setup_drifted_account_with_orders,
    setup_platform,
    validate_success,
)

BILLING = TEST_USERS["billing_officer_headers"]

PERIOD_START = "2026-01-01T00:00:00Z"
PERIOD_END = "2026-04-01T00:00:00Z"
AVERAGE_DAILY_VALUE_CENTS = 150_000_000


def _billable_account():
    """Sponsor NRTH on 3333 bps of revenue share, strategy CORE on a 90 bps base
    fee, and one account opened against that pair with billing_status CURRENT."""
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10_000)],
        sleeves=[("ALFA", 10000)],
        sponsor_overrides={"revenue_share_bps": 3333},
        model_overrides={"base_fee_bps": 90},
    )
    env["account"] = open_account(env, "ACC-001")
    return env


def _invoice_straddling_all_three_tiers(api, env):
    """Compute one invoice over a 90-day period on an average daily value that
    reaches into every one of the three fee tiers."""
    payload = create_fee_invoice_payload(
        env["account"]["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        average_daily_value_cents=AVERAGE_DAILY_VALUE_CENTS,
    )
    return validate_success(api.create_fee_invoice(payload, BILLING), 201)


def _capped_drifted_account():
    """The canonical 25,000,000c account driven to DRIFTED while two ACTIVE
    MAX_POSITION restrictions cap ALFA at 3000 bps and BETA at 4000 bps."""
    return setup_drifted_account_with_orders(
        drift_threshold_bps=1000,
        restrictions=[("ALFA", "MAX_POSITION", 3000), ("BETA", "MAX_POSITION", 4000)],
    )


def _proposed_order(account_id, security_id):
    orders = list_trade_orders(
        account_id=account_id, security_id=security_id, status="PROPOSED"
    )
    assert len(orders) == 1, (
        f"expected exactly one PROPOSED order for security {security_id}, got {len(orders)}"
    )
    return orders[0]


def test_each_tier_slice_is_prorated_and_rounded_on_its_own(api):
    """PRD §3.9: "First, `billing_days` is the number of whole UTC days from `period_start` inclusive to `period_end` exclusive."
    PRD §3.9: "Next the average daily value is cut into three tier slices: the first slice is the average daily value capped at two hundred fifty thousand dollars, that is 25000000 cents; the second slice is the amount by which the average daily value exceeds that first ceiling, itself capped at one million dollars, that is 100000000 cents, and floored at zero; and the third slice is whatever exceeds the second ceiling, again floored at zero."
    PRD §3.9: "Each slice carries its own annual rate in basis points, taken from the strategy the account tracks: the first tier bills at the strategy's `base_fee_bps`, the second at `base_fee_bps` reduced by 10 basis points, and the third at `base_fee_bps` reduced by 20 basis points."
    PRD §3.9: "Each tier's fee is then prorated over the period and rounded **independently**: `tier1_fee_cents`, `tier2_fee_cents` and `tier3_fee_cents` are each that tier's slice multiplied by its rate in basis points, multiplied by `billing_days`, divided by 10000 and again by 365, then rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/fee_tier_prorate_rounding_order_and_residual_split
    """
    env = _billable_account()

    invoice = _invoice_straddling_all_three_tiers(api, env)

    assert invoice["billing_days"] == 90
    assert invoice["tier1_fee_cents"] == 55479
    assert invoice["tier2_fee_cents"] == 147945
    assert invoice["tier3_fee_cents"] == 86301
    assert invoice["status"] == "DRAFT"


def test_the_gross_fee_sums_three_already_rounded_tier_fees(api):
    """PRD §3.9: "`gross_fee_cents` is the sum of those three already-rounded numbers."
    PRD §3.9: "Summing the three exact tier fees and rounding once at the end is not an admissible implementation and produces a different number of cents."

    Design: Difficulty/combinatorial_formula/fee_tier_prorate_rounding_order_and_residual_split
    """
    env = _billable_account()

    invoice = _invoice_straddling_all_three_tiers(api, env)

    assert invoice["gross_fee_cents"] == 289725
    assert invoice["gross_fee_cents"] == (
        invoice["tier1_fee_cents"]
        + invoice["tier2_fee_cents"]
        + invoice["tier3_fee_cents"]
    )
    assert invoice["gross_fee_cents"] != 289726, (
        "289726 is what summing the three exact tier fees and rounding once at "
        "the end produces; each tier must be rounded before the sum is taken"
    )


def test_the_manager_share_is_the_exact_residual_of_the_two_rounded_shares(api):
    """PRD §3.9: "`sponsor_share_cents` is `gross_fee_cents` multiplied by the sponsor's `revenue_share_bps`, divided by 10000, rounded half up."
    PRD §3.9: "`platform_share_cents` is `gross_fee_cents` multiplied by the platform's own fixed 500-basis-point cut, divided by 10000, rounded half up."
    PRD §3.9: "`manager_share_cents` is then simply what is left: `gross_fee_cents` minus the sponsor's share minus the platform's share."
    PRD §3.9: "Rounding the manager's share directly is not admissible, because the residual is what guarantees the invariant that the three shares always add back to exactly `gross_fee_cents`."

    Design: Difficulty/combinatorial_formula/fee_tier_prorate_rounding_order_and_residual_split
    """
    env = _billable_account()

    invoice = _invoice_straddling_all_three_tiers(api, env)

    assert invoice["sponsor_share_cents"] == 96565
    assert invoice["platform_share_cents"] == 14486
    assert invoice["manager_share_cents"] == 178674
    assert invoice["manager_share_cents"] != 178673, (
        "178673 is what rounding the manager's own 6167 bps slice directly "
        "produces; the manager's share must be taken as the exact residual"
    )
    assert invoice["gross_fee_cents"] == (
        invoice["sponsor_share_cents"]
        + invoice["platform_share_cents"]
        + invoice["manager_share_cents"]
    )


def test_the_capping_loop_reruns_until_no_free_sleeve_breaches_its_cap(api):
    """PRD §3.5: "Each sleeve also has a cap, which is the smaller of the sleeve's own `max_position_bps` and the `max_position_bps` of an `ACTIVE` `MAX_POSITION` restriction on that account and security; where no such restriction exists, the restriction side of that comparison is treated as 10000, which is to say it never binds."
    PRD §3.5: "The residual is 10000 minus the sum of the effective weights of every pinned sleeve. The pool is the sum of the base weights of the free sleeves. Each free sleeve's effective weight is set to the residual multiplied by that sleeve's base weight, divided by the pool, rounded **down** to a whole basis point."
    PRD §3.5: "Finally the pass looks for free sleeves whose newly computed weight now exceeds their cap; if there are none, the loop stops. Otherwise each breached sleeve's weight is set to exactly its cap, that sleeve is pinned, and the next pass runs."

    Design: Difficulty/combinatorial_formula/effective_weight_capping_fixed_point_evaluation_order
    """
    env = _capped_drifted_account()
    account_id = env["account"]["id"]

    assert env["rebalance_result"]["generated_order_count"] == 3

    alfa = _proposed_order(account_id, env["securities"]["ALFA"]["id"])
    beta = _proposed_order(account_id, env["securities"]["BETA"]["id"])
    ceta = _proposed_order(account_id, env["securities"]["CETA"]["id"])

    assert alfa["effective_weight_bps"] == 3000
    assert beta["effective_weight_bps"] == 4000
    assert ceta["effective_weight_bps"] == 3000

    assert beta["effective_weight_bps"] != 4200, (
        "4200 is what a single non-iterative pass leaves on BETA after ALFA is "
        "pinned; BETA breaches its own 4000 cap and a further pass must run"
    )
    assert ceta["effective_weight_bps"] != 2800, (
        "2800 is what a single non-iterative pass leaves on CETA; the residual "
        "freed by pinning BETA at its cap must be redistributed"
    )


def test_the_capped_weights_drive_the_two_ordered_share_conversions(api):
    """PRD §3.5: "The cash reserve held back from investment is the larger of one hundred dollars — that is, 10000 cents — and the account's `cash_reserve_bps` applied to market value, computed as market value multiplied by `cash_reserve_bps`, divided by 10000, rounded down to whole cents."
    PRD §3.5: "The target share count is computed with two rounding steps applied strictly in this order: first the investable amount multiplied by the effective weight, divided by 10000, rounded **down** to whole cents; then that cent figure divided by the security's `last_price_cents`, again rounded **down**, to whole shares."
    PRD §3.5: "The account's current holding is the sum of `shares_open` across its `OPEN` tax lots of that security, and the delta is the target share count minus that current holding."

    Design: Difficulty/combinatorial_formula/effective_weight_capping_fixed_point_evaluation_order
    """
    env = _capped_drifted_account()
    account_id = env["account"]["id"]

    alfa = _proposed_order(account_id, env["securities"]["ALFA"]["id"])
    beta = _proposed_order(account_id, env["securities"]["BETA"]["id"])
    ceta = _proposed_order(account_id, env["securities"]["CETA"]["id"])

    assert alfa["side"] == "SELL"
    assert alfa["shares"] == 508
    assert alfa["target_shares"] == 742

    assert beta["side"] == "BUY"
    assert beta["shares"] == 480
    assert beta["target_shares"] == 1980

    assert ceta["side"] == "BUY"
    assert ceta["shares"] == 1970
    assert ceta["target_shares"] == 2970
