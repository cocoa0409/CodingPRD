"""The three multi-input money formulas: deposit, filing fee, commission.

Each combines several inputs in an order that is normative, so a rounding step
or a tier lookup applied one stage early or late produces a different number.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_ledger_balance_projection,
    assert_ledger_entry,
    draft_agreement,
    issue_deficiency,
    ledger_rows,
    read_agreement,
    read_application,
    read_listing,
    resubmit_application,
    settle_escrow,
    setup_closed_agreement,
    setup_scenario,
    validate_error,
)


def test_deposit_requirement_rounds_inside_the_clamp_in_the_linear_region():
    """Offered rate plus class surcharge plus scarcity contribution, rounded.

    PRD: "A **class surcharge** in basis points is looked up from the license
    class of the listed license: 300 basis points for `CLASS_47_ONSALE_GENERAL`,
    200 for `CLASS_21_OFFSALE_GENERAL`, and none at all for
    `CLASS_41_ONSALE_BEER_WINE`."

    PRD: "A **scarcity contribution** is the listing's frozen
    `scarcity_bps_at_activation` divided by five with the fractional part
    discarded — the snapshot value, never a live recomputation of the county's
    current position."

    PRD: "That raw amount is rounded half up to whole cents, and only then is it
    clamped: the result is at least 500000 cents and at most 7500000 cents."

    PRD: "The `contingency_deadline_at` is computed as `closing_window_start`
    advanced by `contingency_days` days, and it is the exclusive end of the
    transfer window this agreement reserves on the license."

    An empty county freezes the uplift at zero, so the effective rate is
    1000 + 300 + 0 = 1300 bps. 18500010 * 1300 / 10000 = 2405001.3, which rounds
    half up to 2405001 — comfortably between the floor and the cap.

    Design: Difficulty/combinatorial_formula/escrow_deposit_nested_clamp_mode_a
    """
    scenario = setup_scenario(
        stage="listing_active",
        county_overrides={"quota_licenses_total": 100},
    )
    assert scenario["listing"]["scarcity_bps_at_activation"] == 0

    agreement = draft_agreement(
        scenario["listing_id"],
        scenario["buyer_id"],
        scenario["premises_id"],
        scenario["listing"]["version"],
        scenario["brokerage_id"],
        purchase_price_cents=18500010,
        deposit_pct_bps=1000,
        closing_window_start="2026-09-01T00:00:00Z",
        contingency_days=30,
    )

    assert agreement["required_deposit_cents"] == 2405001
    assert_instant_equals(
        agreement["contingency_deadline_at"],
        "2026-10-01T00:00:00Z",
        "contingency_deadline_at",
    )
    assert agreement["escrow_balance_cents"] == 0
    assert agreement["agreement_status"] == "DRAFT"
    assert agreement["escrow_status"] == "AWAITING_DEPOSIT"


def test_deposit_requirement_caps_the_rate_then_caps_the_amount():
    """Both clamps bite on the second offer against the same listing.

    PRD: "The buyer's offered `deposit_pct_bps`, the class surcharge and the
    scarcity contribution are added together, and the sum is capped at 3500 basis
    points; that capped figure is the effective deposit rate, and it is why the
    raw offered rate may itself be no more than 3500 even though the surcharges
    can push the sum above it."

    PRD: "The rounding happens inside the clamp, never after it."

    PRD: "The parent listing's `open_offer_count` rises by one and its `version`
    advances by one, which is what makes a replayed `expected_listing_version`
    fail."

    3300 + 300 + 0 = 3600 bps is capped to 3500, and 30000000 * 3500 / 10000 =
    10500000 is then capped to the 7500000 ceiling. Two competing draft offers
    on one active listing are legitimate, so the listing ends at
    `open_offer_count` 2.

    Design: Difficulty/combinatorial_formula/escrow_deposit_nested_clamp_mode_a
    """
    scenario = setup_scenario(
        stage="listing_active",
        county_overrides={"quota_licenses_total": 100},
    )
    first = draft_agreement(
        scenario["listing_id"], scenario["buyer_id"], scenario["premises_id"],
        scenario["listing"]["version"], scenario["brokerage_id"],
        purchase_price_cents=18500010, deposit_pct_bps=1000,
        closing_window_start="2026-09-01T00:00:00Z", contingency_days=30,
    )
    assert first["required_deposit_cents"] == 2405001

    moved_listing = read_listing(scenario["listing_id"])
    second = draft_agreement(
        scenario["listing_id"], scenario["buyer_id"], scenario["premises_id"],
        moved_listing["version"], scenario["brokerage_id"],
        purchase_price_cents=30000000, deposit_pct_bps=3300,
        closing_window_start="2026-10-01T00:00:00Z", contingency_days=30,
    )

    assert second["required_deposit_cents"] == 7500000
    assert second["required_deposit_cents"] != 10500000
    assert read_listing(scenario["listing_id"])["open_offer_count"] == 2


def test_original_filing_fee_tiers_on_the_subtotal_not_on_the_total():
    """A 165000-cent subtotal attracts 500 basis points, giving 173250.

    PRD: "Step one sums an exact integer subtotal: a filing base of 30000 cents,
    plus a class fee determined by the license class — 120000 cents for
    `CLASS_47_ONSALE_GENERAL`, 90000 cents for `CLASS_21_OFFSALE_GENERAL`, 45000
    cents for `CLASS_41_ONSALE_BEER_WINE` — plus a posting fee of 15000 cents,
    plus 30000 cents for each deficiency round already recorded on the
    application."

    PRD: "Step two selects an expedite surcharge rate **from that step-one
    subtotal, not from the final fee**: a subtotal of 200000 cents or more
    attracts 800 basis points, otherwise a subtotal of 120000 cents or more
    attracts 500 basis points, otherwise the rate is 200 basis points."

    PRD: "Its `fee_paid_total_cents` is initialised to the amount just tendered."

    30000 + 120000 + 15000 + 0 = 165000; 165000 * 500 / 10000 = 8250; the fee is
    173250.

    Design: Difficulty/combinatorial_formula/transfer_filing_fee_pinned_evaluation_order_mode_c
    """
    scenario = setup_scenario(
        stage="application_filed",
        county_overrides={"quota_licenses_total": 100, "protest_window_days": 15},
        represents_buyer=True,
        deposit_by_buyer=True,
        application_fee=173250,
    )
    application = scenario["application"]

    assert application["status"] == "SUBMITTED"
    assert application["filing_fee_cents"] == 173250
    assert application["fee_paid_total_cents"] == 173250
    assert application["deficiency_round_count"] == 0
    assert application["last_deficiency_codes"] is None
    assert application["decision"] is None


def test_resubmission_fee_tiers_on_the_grown_subtotal_and_rejects_the_naive_total():
    """Round one costs 204750, never the 210600 the self-referential reading gives.

    PRD: "The deficiency round count used in step one is the count **as it
    stands at the moment the fee is computed** — zero on the original filing, one
    after the first deficiency notice, two after the second — so the
    resubmission fee is strictly larger than the original."

    PRD: "Tiering on the final total rather than on the subtotal produces a
    different number whenever the subtotal sits just below a tier edge, and that
    reading is wrong."

    PRD: "The `fee_paid_cents` tendered must equal the computed fee exactly, on
    the original filing and on every resubmission alike; any difference is
    refused with `ERR_FILING_FEE_MISMATCH`."

    PRD: "A successful refiling recomputes and rewrites `filing_fee_cents` at the
    current round count, adds the newly tendered `fee_paid_cents` to the running
    `fee_paid_total_cents`, and deliberately **retains**
    `accepted_by_analyst_id`, so the segregation-of-duties comparand survives the
    revision loop and the accepting analyst cannot recover decision authority by
    sending the application through the cycle again."

    The round-one subtotal is 195000, still below the 200000 tier edge, so the
    rate stays 500 basis points and the fee is 195000 + 9750 = 204750. Tiering
    the 204750-plus total at 800 basis points would have produced 210600, which
    is refused as a mismatch. Paid totals accumulate: 173250 + 204750 = 378000.

    Design: Difficulty/combinatorial_formula/transfer_filing_fee_pinned_evaluation_order_mode_c
    """
    scenario = setup_scenario(
        stage="application_under_review",
        county_overrides={"quota_licenses_total": 100, "protest_window_days": 15},
        represents_buyer=True,
        deposit_by_buyer=True,
        application_fee=173250,
    )
    application_id = scenario["application_id"]
    accepting_analyst = scenario["application"]["accepted_by_analyst_id"]

    deficient = issue_deficiency(application_id, ["MISSING_FINANCIALS"])
    assert deficient["status"] == "DEFICIENT"
    assert deficient["deficiency_round_count"] == 1

    naive = api_client.resubmit_application(
        application_id, {"fee_paid_cents": 210600}, scenario["broker_headers"]
    )
    validate_error(naive, ApiErrorId.ERR_FILING_FEE_MISMATCH.value, 422)

    resubmitted = resubmit_application(
        application_id, 204750, scenario["brokerage_id"]
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["filing_fee_cents"] == 204750
    assert resubmitted["filing_fee_cents"] != 210600
    assert resubmitted["fee_paid_total_cents"] == 378000
    assert resubmitted["deficiency_round_count"] == 1
    assert resubmitted["accepted_by_analyst_id"] == accepting_analyst

    stored = read_application(application_id)
    assert stored["filing_fee_cents"] == 204750
    assert stored["fee_paid_total_cents"] == 378000


def _dual_agency_closed_agreement():
    """An APPROVED transfer whose gross commission lands on a half cent."""
    return setup_closed_agreement(
        county_overrides={
            "quota_licenses_total": 100,
            "transfer_fee_bps": 150,
            "protest_window_days": 15,
        },
        brokerage_overrides={
            "commission_rate_bps": 575,
            "dual_agency_policy": "ALLOWED_WITH_DISCLOSURE",
        },
        represents_buyer=True,
        deposit_by_buyer=True,
    )


def test_release_rounds_each_commission_line_before_summing_them():
    """638250 + 425500 = 1063750, not the 1063751 of sum-then-round.

    PRD: "When `commission_mode` is `DUAL_AGENCY`, the gross is split into two
    lines: the seller-side line is the gross multiplied by six thousand and
    divided by ten thousand — that is, ten thousand less the dual-agency split of
    4000 basis points — rounded half up to whole cents; the buyer-side line is
    the gross multiplied by 4000 and divided by ten thousand, likewise rounded
    half up to whole cents; and `commission_total_cents` is the sum of those two
    already-rounded lines."

    PRD: "Rounding each line and then summing is normative; summing the exact
    lines and rounding the total is the wrong reading and yields a figure one
    cent different whenever both split lines land on a half cent, which is why
    the same price under the two commission modes can differ by exactly one
    cent."

    PRD: "Next, `county_transfer_fee_cents` is the `purchase_price_cents`
    multiplied by the county's `transfer_fee_bps` and divided by ten thousand,
    rounded half up to whole cents."

    PRD: "The waterfall then takes the county fee as bucket one, the commission
    total as bucket two, and leaves `seller_net_cents` as bucket three: the
    escrow balance held at settlement time, less the county fee, less the
    commission total."

    The gross on 18500010 at 575 basis points is exactly 1063750.575 cents:
    638250.345 and 425500.23 round to 638250 and 425500. The county fee is
    277500, so the seller takes 2405001 - 277500 - 1063750 = 1063751 — the
    displaced cent lands with the seller.

    Design: Difficulty/combinatorial_formula/commission_round_per_line_then_sum_mode_b
    """
    scenario = _dual_agency_closed_agreement()
    settled = settle_escrow(
        scenario["agreement_id"], "RELEASE", memo="closing disbursement"
    )

    assert settled["commission_mode"] == "DUAL_AGENCY"
    assert settled["commission_total_cents"] == 1063750
    assert settled["commission_total_cents"] != 1063751
    assert settled["county_transfer_fee_cents"] == 277500
    assert settled["seller_net_cents"] == 1063751
    assert settled["escrow_status"] == "RELEASED"
    assert settled["escrow_balance_cents"] == 0
    assert settled["settled_at"] is not None

    stored = read_agreement(scenario["agreement_id"])
    assert stored["commission_total_cents"] == 1063750
    assert stored["seller_net_cents"] == 1063751
    assert (
        stored["county_transfer_fee_cents"]
        + stored["commission_total_cents"]
        + stored["seller_net_cents"]
        == 2405001
    )


def test_release_appends_the_three_waterfall_rows_in_the_pinned_order():
    """The ledger walks the held balance down to zero in three negative rows.

    PRD: "On success the three bucket figures are written to the agreement and
    three ledger rows are appended **in this pinned order**: `RELEASE_COUNTY_FEE`,
    then `RELEASE_COMMISSION`, then `RELEASE_SELLER`."

    PRD: "Each carries a negative `amount_cents` and a `balance_after_cents`
    lower than the row before it, so the balance walks down to zero across the
    three rows."

    PRD: "After every append, the balance projection is replayed from scratch:
    the agreement's rows are ordered by `occurred_at` ascending with `created_at`
    ascending as the tie-break, a running total is accumulated across them in
    that order, each row's `balance_after_cents` is set to the running total as of
    that row, and the agreement's `escrow_balance_cents` is set to the final
    running total."

    The one-cent difference the per-line rounding produced is visible on the
    `RELEASE_COMMISSION` row itself: -1063750, leaving 1063751 for the seller.

    Design: Difficulty/combinatorial_formula/commission_round_per_line_then_sum_mode_b
    """
    scenario = _dual_agency_closed_agreement()
    settle_escrow(scenario["agreement_id"], "RELEASE", memo="closing disbursement")

    rows = ledger_rows(scenario["agreement_id"])
    assert len(rows) == 4
    assert [row["entry_type"] for row in rows] == [
        "DEPOSIT",
        "RELEASE_COUNTY_FEE",
        "RELEASE_COMMISSION",
        "RELEASE_SELLER",
    ]
    for row in rows:
        assert_ledger_entry(row)
    assert_ledger_balance_projection(rows)

    deposit, county_fee, commission, seller = rows
    assert deposit["amount_cents"] == 2405001
    assert deposit["balance_after_cents"] == 2405001
    assert county_fee["amount_cents"] == -277500
    assert county_fee["balance_after_cents"] == 2127501
    assert commission["amount_cents"] == -1063750
    assert commission["balance_after_cents"] == 1063751
    assert seller["amount_cents"] == -1063751
    assert seller["balance_after_cents"] == 0
