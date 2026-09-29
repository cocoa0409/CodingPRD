"""The two conserved quantities under a forward operation and its compensation.

Both invariants are asserted three times per scenario: on the untouched baseline,
after the forward operation has moved money, and after the compensating operation
has moved it back. Because the roll-up counters are recomputed in full from their
source rows rather than adjusted by a delta, the second reading of the baseline
must be exact rather than merely close, while the audit trail — statuses, counts
and version counters — still records that both operations happened.
"""

from test_helpers import (
    FINANCE_USER_ID,
    OFFICER_USER_ID,
    ApiErrorId,
    api_client,
    assert_agency,
    assert_bidder,
    assert_deposit_custody_invariant,
    assert_invoice_money_lines,
    assert_proceeds_distribution,
    assert_proceeds_ledger_invariant,
    assert_proceeds_net,
    assert_sale_invoice,
    calculate_distribution,
    create_payment_payload,
    make_bidder_headers,
    make_disposal_officer_headers,
    make_finance_controller_headers,
    make_program_admin_headers,
    place_bid,
    post_distribution,
    read_agency,
    read_bidder,
    read_distribution,
    read_invoice,
    read_lot,
    register_bidder,
    register_venue,
    set_clock,
    setup_assessed_assets,
    setup_closed_met_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER_HEADERS = make_disposal_officer_headers(OFFICER_USER_ID)
FINANCE_HEADERS = make_finance_controller_headers(FINANCE_USER_ID)
ADMIN_HEADERS = make_program_admin_headers()


def _ledger_snapshot(api):
    """Every organisation row and every distribution row, for the ledger identity."""
    agencies, _ = validate_paginated(api.list_agencies(ADMIN_HEADERS))
    distributions, _ = validate_paginated(
        api.list_proceeds_distributions(FINANCE_HEADERS)
    )
    return agencies, distributions


def _assert_ledger_identity(api):
    agencies, distributions = _ledger_snapshot(api)
    assert_proceeds_ledger_invariant(agencies, distributions)
    return agencies, distributions


def _two_sold_pallets():
    """One organisation's two pallets, each sold at auction to the same buyer, so
    two independent distributions can be computed against one beneficiary ledger.

    Both lots share one window at a venue that admits two concurrent lots, and the
    disposal officer closes them so the finance controller who posts afterwards
    stays on the far side of the segregation-of-duties barrier.
    """
    scenario = setup_assessed_assets(
        [
            {"kind": "furniture", "overrides": {"description": "File cabinets, pallet 1"}},
            {"kind": "furniture", "overrides": {"description": "File cabinets, pallet 2"}},
        ]
    )
    venue = register_venue(
        name="Austin Surplus Yard", venue_code="AUS-01", concurrent_lot_capacity=2
    )
    lots = []
    for asset in scenario["assets"]:
        lots.append(
            validate_success(
                api_client.create_auction_lot(
                    {
                        "asset_id": asset["id"],
                        "venue_id": venue["id"],
                        "opens_at": "2026-09-01T00:00:00Z",
                        "closes_at": "2026-09-05T00:00:00Z",
                    },
                    OFFICER_HEADERS,
                ),
                201,
            )
        )

    bidder = register_bidder()
    set_clock("2026-09-01T00:00:00Z")
    for lot in lots:
        validate_success(api_client.open_auction_lot(lot["id"], OFFICER_HEADERS), 200)
    place_bid(lots[0]["id"], bidder["id"], 20000)
    place_bid(lots[1]["id"], bidder["id"], 32000)

    set_clock("2026-09-05T00:00:00Z")
    closed = [
        validate_success(api_client.close_auction_lot(lot["id"], OFFICER_HEADERS), 200)
        for lot in lots
    ]
    for lot in closed:
        assert lot["status"] == "CLOSED_MET", (
            f"both lots must close with the reserve met, got {lot['status']}"
        )
    return {
        "agency": read_agency(scenario["agency"]["id"]),
        "venue": venue,
        "bidder": read_bidder(bidder["id"]),
        "assets": scenario["assets"],
        "lots": closed,
    }


class TestProceedsLedgerPostThenReverseRestoresBalance:
    """A post credits the beneficiary's ledger and its reversal recomputes the
    balance from the distributions that remain `POSTED`, so the prior value is
    restored exactly rather than approximately."""

    def test_post_then_reverse_restores_the_ledger_balance_exactly(self, api):
        """PRD §2.13: "**Proceeds ledger.** The sum of `proceeds_account_balance_cents`
        across all `Agency` rows always equals the sum of `net_to_agency_cents` across all
        `ProceedsDistribution` rows whose `status` is `POSTED`. Distributions in
        `CALCULATED`, `SUPERSEDED` or `REVERSED` contribute nothing. Because the agency
        balance is recomputed in full from the posted set rather than adjusted by a delta,
        a post followed by its reversal returns the balance to its exact prior value."
        PRD §3.9: "The post stamps `posted_by_user_id` and `posted_at`, moves the row to
        `POSTED`, and in a second hop caused by that stamping recomputes the beneficiary
        agency's `proceeds_account_balance_cents` and `posted_distribution_count`."
        PRD §3.9: "Otherwise the row moves to `REVERSED` with `reversal_reason` stored, and
        a second hop recomputes the beneficiary's `proceeds_account_balance_cents` and
        `posted_distribution_count` from the distributions that remain `POSTED`, restoring
        the pre-post values exactly."
        PRD §2.9: "Derived roll-up counters are always **fully recomputed** from their
        source rows rather than incrementally adjusted, so that a compensating operation
        restores the previous value exactly rather than leaving an accumulated drift."

        Design: Difficulty/compensating_invariant/ci_agency_proceeds_ledger_post_then_reverse_restores_balance
        """
        scenario = _two_sold_pallets()
        agency_id = scenario["agency"]["id"]
        first_lot, second_lot = scenario["lots"]

        baseline = read_agency(agency_id)
        assert_agency(baseline)
        assert baseline["proceeds_account_balance_cents"] == 0, (
            "nothing has been posted yet; got "
            f"{baseline['proceeds_account_balance_cents']}"
        )
        assert baseline["posted_distribution_count"] == 0
        _assert_ledger_identity(api)

        first = calculate_distribution(first_lot["id"], first_lot["version"])
        second = calculate_distribution(second_lot["id"], second_lot["version"])
        for row, base, fee in ((first, 20000, 2500), (second, 32000, 4000)):
            assert_proceeds_distribution(row)
            assert row["basis"] == "ACCRUAL"
            assert row["beneficiary_agency_id"] == agency_id, (
                "both pallets came from the same relinquishing organisation; got "
                f"{row['beneficiary_agency_id']}"
            )
            assert row["distributable_base_cents"] == base, (
                "the accrual base is the price the lot achieved; got "
                f"{row['distributable_base_cents']} instead of {base}"
            )
            assert row["service_fee_cents"] == fee, (
                f"the first fee slice charges {base} at 0.125, giving {fee}; got "
                f"{row['service_fee_cents']}"
            )
            assert row["cost_recovery_cents"] == 0, (
                "a furniture pallet carries no clearance certificates, so nothing is "
                f"recovered; got {row['cost_recovery_cents']}"
            )
            assert_proceeds_net(row)
        assert first["net_to_agency_cents"] == 17500, (
            "a 20000-cent accrual base less a 2500-cent service fee nets 17500; got "
            f"{first['net_to_agency_cents']}"
        )
        assert second["net_to_agency_cents"] == 28000, (
            "a 32000-cent accrual base less a 4000-cent service fee nets 28000; got "
            f"{second['net_to_agency_cents']}"
        )
        assert read_agency(agency_id)["proceeds_account_balance_cents"] == 0, (
            "a CALCULATED distribution contributes nothing to the ledger"
        )
        _assert_ledger_identity(api)

        # Forward operation, in two posts.
        posted_first = post_distribution(first["id"])
        after_first = read_agency(agency_id)
        assert posted_first["status"] == "POSTED"
        assert after_first["proceeds_account_balance_cents"] == 17500, (
            "the first post credits 17500 cents; got "
            f"{after_first['proceeds_account_balance_cents']}"
        )
        assert after_first["posted_distribution_count"] == 1, (
            f"one distribution is posted; got {after_first['posted_distribution_count']}"
        )
        _assert_ledger_identity(api)

        post_distribution(second["id"])
        after_second = read_agency(agency_id)
        assert after_second["proceeds_account_balance_cents"] == 45500, (
            "the two posts together credit 17500 + 28000 = 45500 cents; got "
            f"{after_second['proceeds_account_balance_cents']}"
        )
        assert after_second["posted_distribution_count"] == 2, (
            f"two distributions are posted; got {after_second['posted_distribution_count']}"
        )
        _assert_ledger_identity(api)

        # Compensating operation.
        reversed_row = validate_success(
            api.reverse_proceeds_distribution(
                first["id"], "Winning bidder disputed the sale", FINANCE_HEADERS
            ),
            200,
        )
        assert_proceeds_distribution(reversed_row)
        assert reversed_row["status"] == "REVERSED", (
            f"the reversal moves the row to REVERSED, got {reversed_row['status']}"
        )
        assert reversed_row["reversal_reason"] == "Winning bidder disputed the sale", (
            f"the reversal reason is stored verbatim; got {reversed_row['reversal_reason']}"
        )
        assert reversed_row["net_to_agency_cents"] == 17500, (
            "the reversal does not rewrite the computed figures, it only stops them "
            f"counting; got {reversed_row['net_to_agency_cents']}"
        )

        restored = read_agency(agency_id)
        assert restored["proceeds_account_balance_cents"] == 28000, (
            "the balance is recomputed from the one distribution that remains POSTED, "
            f"which is 28000 cents exactly; got {restored['proceeds_account_balance_cents']}"
        )
        assert restored["posted_distribution_count"] == 1, (
            "the count is recomputed over the remaining POSTED rows; got "
            f"{restored['posted_distribution_count']}"
        )
        _assert_ledger_identity(api)

        assert read_distribution(second["id"])["status"] == "POSTED", (
            "reversing one distribution leaves the other posted"
        )

    def test_reversal_leaves_a_complete_audit_trail(self, api):
        """PRD §3.9: "The post stamps `posted_by_user_id` and `posted_at`, moves the row to
        `POSTED`, and in a second hop caused by that stamping recomputes the beneficiary
        agency's `proceeds_account_balance_cents` and `posted_distribution_count`."
        PRD §3.9: "Both the distribution's and the agency's `version` increment by 1."
        PRD §3.9: "Otherwise the row moves to `REVERSED` with `reversal_reason` stored, and
        a second hop recomputes the beneficiary's `proceeds_account_balance_cents` and
        `posted_distribution_count` from the distributions that remain `POSTED`, restoring
        the pre-post values exactly. Both versions increment by 1."
        PRD §2.13: "Distributions in `CALCULATED`, `SUPERSEDED` or `REVERSED` contribute
        nothing."

        Design: Difficulty/compensating_invariant/ci_agency_proceeds_ledger_post_then_reverse_restores_balance
        """
        scenario = _two_sold_pallets()
        agency_id = scenario["agency"]["id"]
        first_lot = scenario["lots"][0]

        calculated = calculate_distribution(first_lot["id"], first_lot["version"])
        assert calculated["status"] == "CALCULATED", (
            f"a new distribution lands in CALCULATED, got {calculated['status']}"
        )
        assert calculated["posted_by_user_id"] is None
        assert calculated["posted_at"] is None
        assert calculated["reversal_reason"] is None
        assert calculated["version"] == 1, (
            f"the distribution row is freshly inserted; got {calculated['version']}"
        )
        assert calculated["beneficiary_agency_id"] == agency_id, (
            "the beneficiary is the organisation that relinquished the property; got "
            f"{calculated['beneficiary_agency_id']}"
        )
        agency_before_post = read_agency(agency_id)

        posted = validate_success(
            api.post_proceeds_distribution(calculated["id"], FINANCE_HEADERS), 200
        )
        assert posted["status"] == "POSTED"
        assert posted["posted_by_user_id"] == FINANCE_USER_ID, (
            "posted_by_user_id is stamped from the posting controller's X-User-ID; got "
            f"{posted['posted_by_user_id']}"
        )
        assert posted["posted_at"] is not None, (
            "the post stamps posted_at from the logical clock"
        )
        assert posted["posted_at"].startswith("2026-09-05T00:00:00"), (
            "the logical clock stands at the lots' closing instant; got "
            f"{posted['posted_at']}"
        )
        assert posted["version"] == calculated["version"] + 1, (
            f"the post increments the distribution's version by 1; got {posted['version']}"
        )
        agency_after_post = read_agency(agency_id)
        assert agency_after_post["version"] == agency_before_post["version"] + 1, (
            "the ledger hop increments the organisation's version by 1; got "
            f"{agency_after_post['version']}"
        )

        reversed_row = validate_success(
            api.reverse_proceeds_distribution(
                calculated["id"], "Sale rescinded on appeal", FINANCE_HEADERS
            ),
            200,
        )
        assert reversed_row["status"] == "REVERSED"
        assert reversed_row["posted_by_user_id"] == FINANCE_USER_ID, (
            "the reversal retains the posting stamp for audit; got "
            f"{reversed_row['posted_by_user_id']}"
        )
        assert reversed_row["posted_at"] == posted["posted_at"], (
            "the reversal retains posted_at for audit; got "
            f"{reversed_row['posted_at']}"
        )
        assert reversed_row["reversal_reason"] == "Sale rescinded on appeal"
        assert reversed_row["version"] == posted["version"] + 1, (
            f"the reversal increments the distribution's version by 1; got {reversed_row['version']}"
        )

        agency_after_reversal = read_agency(agency_id)
        assert agency_after_reversal["proceeds_account_balance_cents"] == 0, (
            "no POSTED distribution remains, so the balance returns to its pre-post "
            f"value of 0; got {agency_after_reversal['proceeds_account_balance_cents']}"
        )
        assert agency_after_reversal["posted_distribution_count"] == 0, (
            f"got {agency_after_reversal['posted_distribution_count']}"
        )
        assert agency_after_reversal["version"] == agency_after_post["version"] + 1, (
            "the reversal's ledger hop increments the organisation's version by 1; got "
            f"{agency_after_reversal['version']}"
        )
        _assert_ledger_identity(api)

    def test_reposting_a_reversed_distribution_is_refused(self, api):
        """PRD §3.9: "Otherwise the row moves to `REVERSED` with `reversal_reason` stored,
        and a second hop recomputes the beneficiary's `proceeds_account_balance_cents` and
        `posted_distribution_count` from the distributions that remain `POSTED`, restoring
        the pre-post values exactly. Both versions increment by 1. `SUPERSEDED` and
        `REVERSED` are terminal."
        PRD §2.12: "Generic state preconditions, including every attempt from a terminal
        state and every repeat of an already-applied trigger: `ERR_INVALID_STATE` (409),
        followed by the specialised state codes `ERR_TURN_IN_NOT_DRAFT`,
        `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`, `ERR_BIDDER_NOT_REGISTERED`,
        `ERR_AGENCY_SUSPENDED`, `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."
        PRD §3.9: "The distribution must be `CALCULATED`, and no other distribution for the
        same `auction_lot_id` may be `POSTED`, otherwise
        `ERR_DISTRIBUTION_ALREADY_POSTED`."

        Design: Difficulty/compensating_invariant/ci_agency_proceeds_ledger_post_then_reverse_restores_balance
        """
        scenario = _two_sold_pallets()
        agency_id = scenario["agency"]["id"]
        first_lot = scenario["lots"][0]

        distribution = calculate_distribution(first_lot["id"], first_lot["version"])
        post_distribution(distribution["id"])
        reversed_row = validate_success(
            api.reverse_proceeds_distribution(
                distribution["id"], "Duplicate settlement", FINANCE_HEADERS
            ),
            200,
        )
        balance_after_reversal = read_agency(agency_id)

        # REVERSED is terminal, and no other distribution for this lot is POSTED,
        # so the refusal is the generic terminal-state one.
        resp = api.post_proceeds_distribution(distribution["id"], FINANCE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        unchanged = read_distribution(distribution["id"])
        assert unchanged["status"] == "REVERSED", (
            f"the refused re-post leaves the row REVERSED, got {unchanged['status']}"
        )
        assert unchanged["version"] == reversed_row["version"], (
            "the refused re-post applies none of its hops, so the row's version is "
            f"unchanged at {reversed_row['version']}; got {unchanged['version']}"
        )
        after = read_agency(agency_id)
        assert after["proceeds_account_balance_cents"] == 0, (
            "the refused re-post credits nothing; got "
            f"{after['proceeds_account_balance_cents']}"
        )
        assert after["posted_distribution_count"] == 0
        assert after["version"] == balance_after_reversal["version"], (
            "the refused re-post does not touch the organisation row"
        )
        _assert_ledger_identity(api)

        second_reversal = api.reverse_proceeds_distribution(
            distribution["id"], "Second attempt at the same reversal", FINANCE_HEADERS
        )
        validate_error(second_reversal, ApiErrorId.ERR_INVALID_STATE)
        _assert_ledger_identity(api)


class TestBidderDepositCustodyApplyThenVoidConservesTotal:
    """Applying a deposit to an invoice and then voiding that invoice moves money
    between the custody buckets in both directions while `deposit_paid_cents`
    never changes."""

    def _sold_lot_with_a_deposit_on_file(self):
        """A pallet sold for 250000 cents to a buyer holding 90000 cents on deposit."""
        scenario = setup_closed_met_lot(
            bid_amount_cents=250000, deposit_cents=90000, kind="furniture"
        )
        invoice = scenario["invoice"]
        assert invoice is not None, "the close must have issued an invoice"
        assert_sale_invoice(invoice)
        assert invoice["hammer_price_cents"] == 250000, (
            f"the hammer price is the winning bid; got {invoice['hammer_price_cents']}"
        )
        assert invoice["buyer_premium_cents"] == 26250, (
            "the premium is 250000 at 0.105 rounded half up; got "
            f"{invoice['buyer_premium_cents']}"
        )
        assert invoice["sales_tax_cents"] == 17542, (
            "the tax is (250000 + 26250) at 0.0635 rounded half up on its own line; got "
            f"{invoice['sales_tax_cents']}"
        )
        assert invoice["total_due_cents"] == 293792, (
            "the total is the exact sum of the three lines, 250000 + 26250 + 17542; got "
            f"{invoice['total_due_cents']}"
        )
        return scenario

    def test_apply_then_void_conserves_the_deposit_custody_total(self, api):
        """PRD §2.13: "**Deposit custody.** For every `Bidder`, `deposit_paid_cents` — the
        cumulative cash the bidder has ever deposited — always equals the sum of
        `deposit_held_cents`, `deposit_applied_cents` and `deposit_forfeited_cents`.
        `deposit_paid_cents` is monotonically non-decreasing: it grows when a deposit is
        recorded and is never reduced by anything, not by an application to an invoice, not
        by a forfeiture and not by a void. Money moves only between the other three
        buckets."
        PRD §3.7: "Where `use_deposit` is true, the deposit moves first, before the cash is
        applied: the smaller of the bidder's `deposit_held_cents` and the invoice's
        `balance_due_cents` moves out of `deposit_held_cents` and into
        `deposit_applied_cents` on both the `Bidder` and the `SaleInvoice`, and the moved
        amount counts as payment in its own right."
        PRD §3.7: "The void stores `void_reason`, returns the invoice's
        `deposit_applied_cents` to the bidder's `deposit_held_cents`, and zeroes both the
        invoice's `deposit_applied_cents` and its `amount_paid_cents`; cash refunds are
        handled outside this API."
        PRD §2.9: "Derived roll-up counters are always **fully recomputed** from their
        source rows rather than incrementally adjusted, so that a compensating operation
        restores the previous value exactly rather than leaving an accumulated drift."

        Design: Difficulty/compensating_invariant/ci_bidder_deposit_custody_apply_then_void_conserves_total
        """
        scenario = self._sold_lot_with_a_deposit_on_file()
        bidder_id = scenario["bidder"]["id"]
        invoice = scenario["invoice"]

        baseline = read_bidder(bidder_id)
        assert_bidder(baseline)
        assert baseline["deposit_paid_cents"] == 90000, (
            f"the buyer lodged 90000 cents; got {baseline['deposit_paid_cents']}"
        )
        assert baseline["deposit_held_cents"] == 90000, (
            f"all of it is still held; got {baseline['deposit_held_cents']}"
        )
        assert baseline["deposit_applied_cents"] == 0
        assert baseline["deposit_forfeited_cents"] == 0
        assert_deposit_custody_invariant(baseline)
        assert invoice["balance_due_cents"] == 293792, (
            f"a freshly issued invoice owes its whole total; got {invoice['balance_due_cents']}"
        )
        assert invoice["deposit_applied_cents"] == 0
        assert invoice["amount_paid_cents"] == 0

        # Forward operation: the deposit moves first, then 10000 cents of cash.
        paid = validate_success(
            api.pay_sale_invoice(
                invoice["id"],
                create_payment_payload(10000, use_deposit=True),
                make_bidder_headers(bidder_id),
            ),
            200,
        )
        assert_sale_invoice(paid)
        assert paid["deposit_applied_cents"] == 90000, (
            "the smaller of the held deposit and the balance moves across, which is the "
            f"whole 90000 cents; got {paid['deposit_applied_cents']}"
        )
        assert paid["amount_paid_cents"] == 100000, (
            "amount_paid_cents is the 10000 cents of cash plus the invoice's own "
            f"90000 cents of applied deposit; got {paid['amount_paid_cents']}"
        )
        assert paid["balance_due_cents"] == 193792, (
            "the balance is re-derived as 293792 - 100000; got "
            f"{paid['balance_due_cents']}"
        )
        assert paid["status"] == "PARTIALLY_PAID", (
            f"a payment that leaves a balance moves the invoice to PARTIALLY_PAID, got {paid['status']}"
        )
        assert_invoice_money_lines(paid)

        during = read_bidder(bidder_id)
        assert during["deposit_paid_cents"] == 90000, (
            "an application to an invoice never reduces deposit_paid_cents; got "
            f"{during['deposit_paid_cents']}"
        )
        assert during["deposit_held_cents"] == 0, (
            f"the whole deposit left the held bucket; got {during['deposit_held_cents']}"
        )
        assert during["deposit_applied_cents"] == 90000, (
            f"and arrived in the applied bucket; got {during['deposit_applied_cents']}"
        )
        assert during["deposit_forfeited_cents"] == 0, (
            "an application is not a forfeiture"
        )
        assert_deposit_custody_invariant(during)

        # Compensating operation.
        voided = validate_success(
            api.void_sale_invoice(
                invoice["id"], "Sale rescinded before collection", FINANCE_HEADERS
            ),
            200,
        )
        assert_sale_invoice(voided)
        assert voided["status"] == "VOIDED", (
            f"the void moves the invoice to VOIDED, got {voided['status']}"
        )
        assert voided["void_reason"] == "Sale rescinded before collection", (
            f"the void reason is stored verbatim; got {voided['void_reason']}"
        )
        assert voided["deposit_applied_cents"] == 0, (
            f"the void zeroes the invoice's applied deposit; got {voided['deposit_applied_cents']}"
        )
        assert voided["amount_paid_cents"] == 0, (
            f"the void zeroes the invoice's amount_paid_cents; got {voided['amount_paid_cents']}"
        )
        assert voided["balance_due_cents"] == 293792, (
            "the balance is re-derived from a zeroed amount_paid_cents and so returns to "
            f"the full total; got {voided['balance_due_cents']}"
        )
        assert voided["total_due_cents"] == 293792, (
            "the void does not rewrite the priced money lines"
        )
        assert_invoice_money_lines(voided)

        restored = read_bidder(bidder_id)
        assert restored["deposit_paid_cents"] == 90000, (
            "a void never reduces deposit_paid_cents either; got "
            f"{restored['deposit_paid_cents']}"
        )
        assert restored["deposit_held_cents"] == 90000, (
            "the applied deposit is returned to the held bucket exactly; got "
            f"{restored['deposit_held_cents']}"
        )
        assert restored["deposit_applied_cents"] == 0, (
            f"nothing remains applied; got {restored['deposit_applied_cents']}"
        )
        assert restored["deposit_forfeited_cents"] == 0, (
            "a void is a refund to custody, not a forfeiture; got "
            f"{restored['deposit_forfeited_cents']}"
        )
        assert_deposit_custody_invariant(restored)
        assert restored["deposit_held_cents"] == baseline["deposit_held_cents"], (
            "the compensating operation restores the pre-payment custody split exactly"
        )

    def test_void_leaves_a_complete_audit_trail(self, api):
        """PRD §3.7: "Each payment increments the `version` of both the invoice and the
        bidder by 1."
        PRD §2.9: "Each hop that mutates a row refreshes that row's `updated_at` and
        increments its `version` by 1, so a cascade that touches an invoice, a lot, an
        asset and a bidder bumps four version counters."
        PRD §3.7: "The void stores `void_reason`, returns the invoice's
        `deposit_applied_cents` to the bidder's `deposit_held_cents`, and zeroes both the
        invoice's `deposit_applied_cents` and its `amount_paid_cents`; cash refunds are
        handled outside this API."
        PRD §3.7: "The transitions from `PENDING` to `REGISTERED`, between `REGISTERED` and
        `SUSPENDED`, and a mere suspension all leave existing bids exactly as they stand;
        only debarment retracts them."

        Design: Difficulty/compensating_invariant/ci_bidder_deposit_custody_apply_then_void_conserves_total
        """
        scenario = self._sold_lot_with_a_deposit_on_file()
        bidder_id = scenario["bidder"]["id"]
        invoice = scenario["invoice"]

        baseline_bidder = read_bidder(bidder_id)
        assert baseline_bidder["winning_lot_count"] == 1, (
            "the close incremented the winner's lot count; got "
            f"{baseline_bidder['winning_lot_count']}"
        )
        assert invoice["due_at"].startswith("2026-09-12T00:00:00"), (
            "due_at is the closing instant of 2026-09-05T00:00:00Z plus seven whole "
            f"days; got {invoice['due_at']}"
        )

        paid = validate_success(
            api.pay_sale_invoice(
                invoice["id"],
                create_payment_payload(10000, use_deposit=True),
                make_bidder_headers(bidder_id),
            ),
            200,
        )
        bidder_after_payment = read_bidder(bidder_id)
        assert paid["version"] == invoice["version"] + 1, (
            f"the payment increments the invoice's version by 1; got {paid['version']}"
        )
        assert bidder_after_payment["version"] == baseline_bidder["version"] + 1, (
            "the payment increments the bidder's version by 1; got "
            f"{bidder_after_payment['version']}"
        )

        voided = validate_success(
            api.void_sale_invoice(
                invoice["id"], "Buyer withdrew before collection", FINANCE_HEADERS
            ),
            200,
        )
        bidder_after_void = read_bidder(bidder_id)
        assert voided["version"] == paid["version"] + 1, (
            "the void is another mutation of the invoice row; got "
            f"{voided['version']}"
        )
        assert bidder_after_void["version"] == bidder_after_payment["version"] + 1, (
            "returning the deposit to the held bucket is a hop that mutates the bidder "
            f"row; got {bidder_after_void['version']}"
        )
        assert bidder_after_void["winning_lot_count"] == 1, (
            "only debarment unwinds a win, so voiding the invoice leaves the winning lot "
            f"count where it stood; got {bidder_after_void['winning_lot_count']}"
        )
        assert bidder_after_void["status"] == "REGISTERED", (
            f"the buyer is still a registered bidder; got {bidder_after_void['status']}"
        )
        assert bidder_after_void["deposit_paid_cents"] == 90000, (
            "the cumulative deposit figure is the audit trail of cash received and is "
            f"monotonically non-decreasing; got {bidder_after_void['deposit_paid_cents']}"
        )
        assert_deposit_custody_invariant(bidder_after_void)

        lot = read_lot(scenario["lot"]["id"])
        assert lot["status"] == "CLOSED_MET", (
            "voiding the invoice does not revert the lot's own outcome; got "
            f"{lot['status']}"
        )
        assert lot["high_bid_cents"] == 250000, (
            f"the lot's achieved price is unchanged; got {lot['high_bid_cents']}"
        )

    def test_paying_a_voided_invoice_is_refused_and_custody_is_untouched(self, api):
        """PRD §3.7: "`PAID`, `DEFAULTED` and `VOIDED` are all terminal for an invoice."
        PRD §2.12: "Generic state preconditions, including every attempt from a terminal
        state and every repeat of an already-applied trigger: `ERR_INVALID_STATE` (409),
        followed by the specialised state codes `ERR_TURN_IN_NOT_DRAFT`,
        `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`, `ERR_BIDDER_NOT_REGISTERED`,
        `ERR_AGENCY_SUSPENDED`, `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."
        PRD §2.13: "`deposit_paid_cents` is monotonically non-decreasing: it grows when a
        deposit is recorded and is never reduced by anything, not by an application to an
        invoice, not by a forfeiture and not by a void."

        Design: Difficulty/compensating_invariant/ci_bidder_deposit_custody_apply_then_void_conserves_total
        """
        scenario = self._sold_lot_with_a_deposit_on_file()
        bidder_id = scenario["bidder"]["id"]
        invoice = scenario["invoice"]

        validate_success(
            api.pay_sale_invoice(
                invoice["id"],
                create_payment_payload(10000, use_deposit=True),
                make_bidder_headers(bidder_id),
            ),
            200,
        )
        voided = validate_success(
            api.void_sale_invoice(
                invoice["id"], "Sale rescinded before collection", FINANCE_HEADERS
            ),
            200,
        )
        bidder_after_void = read_bidder(bidder_id)

        # Re-running the forward operation against the compensated invoice.
        resp = api.pay_sale_invoice(
            invoice["id"],
            create_payment_payload(10000, use_deposit=True),
            make_bidder_headers(bidder_id),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        unchanged_invoice = read_invoice(invoice["id"])
        assert unchanged_invoice["status"] == "VOIDED", (
            f"the refused payment leaves the invoice VOIDED, got {unchanged_invoice['status']}"
        )
        assert unchanged_invoice["amount_paid_cents"] == 0, (
            f"nothing was collected; got {unchanged_invoice['amount_paid_cents']}"
        )
        assert unchanged_invoice["deposit_applied_cents"] == 0
        assert unchanged_invoice["balance_due_cents"] == 293792
        assert unchanged_invoice["version"] == voided["version"], (
            "the refused payment applies none of its hops, so the invoice's version is "
            f"unchanged at {voided['version']}; got {unchanged_invoice['version']}"
        )

        unchanged_bidder = read_bidder(bidder_id)
        assert unchanged_bidder["deposit_paid_cents"] == 90000
        assert unchanged_bidder["deposit_held_cents"] == 90000, (
            "the deposit stays in custody after the refusal; got "
            f"{unchanged_bidder['deposit_held_cents']}"
        )
        assert unchanged_bidder["deposit_applied_cents"] == 0
        assert unchanged_bidder["deposit_forfeited_cents"] == 0
        assert unchanged_bidder["version"] == bidder_after_void["version"], (
            "the refused payment does not touch the bidder row"
        )
        assert_deposit_custody_invariant(unchanged_bidder)

        second_void = api.void_sale_invoice(
            invoice["id"], "Second attempt at the same void", FINANCE_HEADERS
        )
        validate_error(second_void, ApiErrorId.ERR_INVALID_STATE)
        assert_deposit_custody_invariant(read_bidder(bidder_id))
