"""Clawback settlements: when one may be opened, and who gets to choose the number (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    ESCROW_RELEASER_USER_ID,
    TEST_USERS,
    make_escrow_agent_headers,
    make_seller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_escrow_cash_conservation,
    assert_instant_equals,
    assert_multiple_1dp,
)

BROKER = TEST_USERS["broker_headers"]
ALT_BROKER = TEST_USERS["broker_ops_alt_headers"]
RELEASER = make_escrow_agent_headers(ESCROW_RELEASER_USER_ID)


def cancel_whole_base(api, ctx):
    """Cancel the deal's only customer inside the guarantee, which triggers the clawback."""
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    validate_success(
        api.create_attrition_event(
            f.attrition_event_payload(
                ctx.deal["id"], ctx.account["id"], "CANCELLED", "2026-09-15", -20000, "NATURAL",
                fx.deal_version(api, ctx.deal["id"]),
            ),
            BROKER,
        ),
        201,
    )
    return validate_success(api.get_deal(ctx.deal["id"], BROKER))


def triggered_nv_deal(api, region_code="LV-WEST"):
    """A closed 180000 NV deal whose whole 20000 base was cancelled: a clawback is due."""
    ctx = fx.nv_deal_route(api, region_code=region_code, stop_after="closed")
    assert_cents(ctx.deal["guaranteed_mrr_cents"], 20000, "guaranteed mrr")
    assert_cents(ctx.deal["allowance_mrr_cents"], 1000, "allowance mrr")
    assert_cents(ctx.deal["clawback_cap_cents"], 36000, "clawback cap")
    assert_multiple_1dp(ctx.deal["effective_multiple_at_close"], "10.0", "close multiple")
    ctx["deal"] = cancel_whole_base(api, ctx)
    assert ctx.deal["clawback_status"] == "CLAWBACK_TRIGGERED"
    return ctx


class TestSettlementNeedsATriggeredLedger:
    def test_a_monitoring_deal_holding_a_live_holdback_is_still_not_settleable(self, api):
        """Closing alone does not open the settlement path: the escrow is holding a live 27000 holdback
        and the guarantee window is open, yet the identical settlement body is refused until an
        attrition event actually pushes the loss past the allowance.

        PRD §3.9: "The deal's `clawback_status` must be `CLAWBACK_TRIGGERED`, or the answer is
        `ERR_NO_CLAWBACK_DUE`."
        PRD §3.9: "When a cancellation pushes the net past the allowance, the deal's
        `clawback_status` becomes `CLAWBACK_TRIGGERED`".

        Design: Corner/errors/settlement_on_a_monitoring_deal_with_nothing_lost_rejected
        """
        ctx = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="closed")
        deal_id = ctx.deal["id"]
        assert ctx.deal["clawback_status"] == "MONITORING"
        escrow = fx.escrow_for_deal(api, deal_id)
        assert escrow["status"] == "PARTIALLY_RELEASED"
        assert_cents(escrow["holdback_balance_cents"], 27000, "holdback balance")

        proposal = f.clawback_settlement_payload(deal_id)
        validate_error(
            api.create_clawback_settlement(proposal, BROKER),
            ApiErrorId.ERR_NO_CLAWBACK_DUE,
            422,
        )

        triggered = cancel_whole_base(api, ctx)
        assert triggered["clawback_status"] == "CLAWBACK_TRIGGERED"
        assert_cents(triggered["net_attrition_mrr_cents"], 20000, "net attrition")

        settlement = validate_success(api.create_clawback_settlement(proposal, BROKER), 201)
        assert settlement["status"] == "DRAFT"
        assert_cents(settlement["guaranteed_mrr_cents"], 20000, "snapshot guaranteed mrr")
        assert_cents(settlement["adjustment_cents"], 36000, "adjustment")


class TestOnlyOneLiveSettlementPerDeal:
    def test_all_three_live_statuses_block_a_second_settlement_and_settling_changes_the_answer(self, api):
        """The uniqueness rule covers the whole live cycle, so the second settlement is refused while
        the first is a draft, while it is proposed and while it is disputed; once the first settles the
        refusal changes code entirely, because the deal itself has left the triggered state.

        PRD §3.9: "At most one settlement per deal may be live at a time, a live settlement being one
        in `DRAFT`, `PROPOSED` or `DISPUTED`; a second is `ERR_DUPLICATE_ACTIVE_SETTLEMENT`, while a
        `SETTLED` or `VOID` predecessor does not block a new one."
        PRD §3.9: "**Disputing** is the seller's rejection: from `PROPOSED` only, supplying a
        `dispute_reason_code` which is stored, the settlement returns to `DISPUTED`."
        PRD §3.9: "Because the holdback balance has reached zero, the deal cascades from `CLOSED` to
        `GUARANTEE_CLOSED` and its `clawback_status` becomes `SETTLED`."

        Design: Corner/errors/a_second_active_settlement_on_the_same_deal_rejected
        """
        ctx = triggered_nv_deal(api)
        deal_id = ctx.deal["id"]
        proposal = f.clawback_settlement_payload(deal_id)
        seller_headers = make_seller_headers(ctx.seller["id"])

        first = validate_success(api.create_clawback_settlement(proposal, BROKER), 201)
        assert first["status"] == "DRAFT"
        assert_cents(first["adjustment_cents"], 36000, "adjustment")

        def duplicate_is_refused():
            validate_error(
                api.create_clawback_settlement(proposal, BROKER),
                ApiErrorId.ERR_DUPLICATE_ACTIVE_SETTLEMENT,
                409,
            )

        duplicate_is_refused()

        proposed = validate_success(
            api.propose_clawback_settlement(
                first["id"], f.propose_settlement_payload(36000), ALT_BROKER
            )
        )
        assert proposed["status"] == "PROPOSED"
        duplicate_is_refused()

        disputed = validate_success(
            api.dispute_clawback_settlement(
                first["id"], f.dispute_settlement_payload(), seller_headers
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason_code"] == "VALUATION_DISPUTED"
        duplicate_is_refused()

        reproposed = validate_success(
            api.propose_clawback_settlement(
                first["id"], f.propose_settlement_payload(36000), ALT_BROKER
            )
        )
        assert reproposed["status"] == "PROPOSED"

        settled = validate_success(
            api.settle_clawback_settlement(
                first["id"], f.settle_settlement_payload(36000), RELEASER
            )
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_at_utc"] is not None

        validate_error(
            api.create_clawback_settlement(proposal, BROKER),
            ApiErrorId.ERR_NO_CLAWBACK_DUE,
            422,
        )
        deal = validate_success(api.get_deal(deal_id, BROKER))
        assert deal["clawback_status"] == "SETTLED"
        assert deal["status"] == "GUARANTEE_CLOSED"


class TestTheNamedEscrowMustBelongToTheDeal:
    def test_a_sibling_deals_live_escrow_is_refused_and_the_deals_own_one_derives_everything(self, api):
        """The other deal's escrow is real, funded and holding its own live 27000 holdback, so nothing
        but the join can explain the refusal; the same body naming this deal's escrow opens a draft
        that carries the whole derivation, capped adjustment and sourcing waterfall at once.

        PRD §3.9: "A supplied `escrow_id` must belong to the same deal, or the answer is
        `ERR_ESCROW_DEAL_MISMATCH`."
        PRD §3.9: "`compensable_natural_mrr_cents` is the greater of zero and the credited natural loss
        minus `allowance_mrr_cents` ... Both buckets then feed a basis-specific
        `raw_adjustment_cents`, and `adjustment_cents` is the lesser of that raw figure and the deal's
        `clawback_cap_cents`."
        PRD §3.9: "`from_holdback_cents` is the lesser of `adjustment_cents` and the escrow's
        `holdback_balance_cents` ... `from_note_principal_cents` is the lesser of what remains of the
        adjustment after the holdback and the deal's `note_principal_cents` ... And
        `holdback_release_to_seller_cents` is the escrow's `holdback_balance_cents` minus
        `from_holdback_cents`".

        Design: Corner/errors/settlement_referencing_another_deals_escrow_rejected
        """
        one = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="escrow_funded")
        two = fx.nv_deal_route(
            api,
            region_code="LV-EAST",
            stops=(fx.nv_stop("EAST-1", "MON", 20000),),
            stop_after="escrow_funded",
            profile=one.profile,
            seller=one.seller,
            buyer=one.buyer,
        )
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        for ctx in (one, two):
            ctx["deal"] = validate_success(api.close_deal(ctx.deal["id"], BROKER))
            assert ctx.deal["status"] == "CLOSED"

        foreign_escrow = fx.escrow_for_deal(api, two.deal["id"])
        assert foreign_escrow["status"] == "PARTIALLY_RELEASED"
        assert_cents(foreign_escrow["holdback_balance_cents"], 27000, "sibling holdback")

        one["deal"] = cancel_whole_base(api, one)
        assert one.deal["clawback_status"] == "CLAWBACK_TRIGGERED"

        validate_error(
            api.create_clawback_settlement(
                f.clawback_settlement_payload(one.deal["id"], escrow_id=foreign_escrow["id"]),
                BROKER,
            ),
            ApiErrorId.ERR_ESCROW_DEAL_MISMATCH,
            422,
        )

        own_escrow = fx.escrow_for_deal(api, one.deal["id"])
        settlement = validate_success(
            api.create_clawback_settlement(
                f.clawback_settlement_payload(one.deal["id"], escrow_id=own_escrow["id"]), BROKER
            ),
            201,
        )
        assert settlement["status"] == "DRAFT"
        assert settlement["remedy_basis"] == "REPLACEMENT_BASIS"
        assert_cents(settlement["guaranteed_mrr_cents"], 20000, "snapshot guaranteed mrr")
        assert_cents(settlement["lost_natural_mrr_cents"], 20000, "lost natural")
        assert_cents(settlement["lost_solicited_mrr_cents"], 0, "lost solicited")
        assert_cents(settlement["recovered_mrr_cents"], 0, "recovered")
        assert_cents(settlement["replacement_credit_cap_cents"], 10000, "replacement credit cap")
        assert_cents(settlement["replacement_credit_mrr_cents"], 0, "replacement credit")
        assert_cents(settlement["allowance_mrr_cents"], 1000, "allowance")
        assert_cents(settlement["compensable_natural_mrr_cents"], 19000, "compensable natural")
        assert_cents(settlement["compensable_solicited_mrr_cents"], 0, "compensable solicited")
        assert_cents(settlement["raw_adjustment_cents"], 190000, "raw adjustment")
        assert_cents(settlement["adjustment_cents"], 36000, "capped adjustment")
        assert_cents(settlement["from_holdback_cents"], 27000, "from holdback")
        assert_cents(settlement["from_note_principal_cents"], 9000, "from note principal")
        assert_cents(settlement["seller_direct_due_cents"], 0, "seller direct due")
        assert_cents(settlement["holdback_release_to_seller_cents"], 0, "holdback to seller")

        _, meta = validate_paginated(
            api.list_clawback_settlements(BROKER, params={"deal_id": two.deal["id"]})
        )
        assert meta["total_count"] == 0


class TestTheProposedFigureIsAConfirmationNotAnInput:
    def test_only_the_recomputed_capped_figure_passes_and_settling_re_derives_it(self, api):
        """The raw uncapped figure is refused, and so are the two amounts one cent either side of the
        cap, so the server is not accepting anything the proposer chooses; the settle step re-derives
        the number instead of trusting the proposed row, and the executed waterfall drains the escrow
        to nothing while the note principal absorbs the rest.

        PRD §3.9: "The submitted `adjustment_cents` must then equal the recomputed capped figure
        exactly; a mismatch is `ERR_SETTLEMENT_AMOUNT_MISMATCH`, which makes the submitted number a
        confirmation of the server's arithmetic rather than an input to it."
        PRD §3.9: "The request restates `adjustment_cents`, which must match the recomputed figure as
        at proposal."
        PRD §3.9: "The escrow then pays `from_holdback_cents` against the adjustment and
        `holdback_release_to_seller_cents` to the seller, its `holdback_balance_cents` drops to zero
        and its `status` becomes `RELEASED`."
        PRD §2.10: "`funded_amount_cents` equals `disbursed_to_broker_cents` plus
        `disbursed_to_seller_cents` plus `disbursed_to_buyer_cents` plus `holdback_balance_cents` plus
        `undisbursed_balance_cents`."

        Design: Corner/errors/settlement_proposal_must_equal_the_recomputed_capped_adjustment
        """
        ctx = triggered_nv_deal(api)
        deal_id = ctx.deal["id"]
        settlement = validate_success(
            api.create_clawback_settlement(f.clawback_settlement_payload(deal_id), BROKER), 201
        )
        settlement_id = settlement["id"]

        for wrong in (190000, 36001, 35999):
            validate_error(
                api.propose_clawback_settlement(
                    settlement_id, f.propose_settlement_payload(wrong), ALT_BROKER
                ),
                ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH,
                422,
            )

        proposed = validate_success(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(36000), ALT_BROKER
            )
        )
        assert proposed["status"] == "PROPOSED"
        assert_cents(proposed["raw_adjustment_cents"], 190000, "raw adjustment")
        assert_cents(proposed["adjustment_cents"], 36000, "capped adjustment")

        validate_error(
            api.settle_clawback_settlement(
                settlement_id, f.settle_settlement_payload(35999), RELEASER
            ),
            ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH,
            422,
        )
        assert validate_success(
            api.get_clawback_settlement(settlement_id, BROKER)
        )["status"] == "PROPOSED"

        settled = validate_success(
            api.settle_clawback_settlement(
                settlement_id, f.settle_settlement_payload(36000), RELEASER
            )
        )
        assert settled["status"] == "SETTLED"
        assert_cents(settled["from_holdback_cents"], 27000, "from holdback")
        assert_cents(settled["from_note_principal_cents"], 9000, "from note principal")
        assert_cents(settled["holdback_release_to_seller_cents"], 0, "holdback to seller")

        escrow = fx.escrow_for_deal(api, deal_id)
        assert escrow["status"] == "RELEASED"
        assert_cents(escrow["holdback_balance_cents"], 0, "holdback balance")
        assert_cents(escrow["disbursed_to_buyer_cents"], 27000, "disbursed to buyer")
        assert_cents(escrow["disbursed_to_broker_cents"], 50000, "disbursed to broker")
        assert_cents(escrow["disbursed_to_seller_cents"], 10000, "disbursed to seller")
        assert_cents(escrow["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_cents(escrow["funded_amount_cents"], 87000, "funded amount")
        assert_escrow_cash_conservation(escrow)

        deal = validate_success(api.get_deal(deal_id, BROKER))
        assert deal["status"] == "GUARANTEE_CLOSED"
        assert deal["clawback_status"] == "SETTLED"


def twin_nv_deals_with_identical_churn(api):
    """Two structurally identical closed NV routes for one seller, each having lost 3000 of MRR.

    Both deals guarantee 20000 cents at a 10.0 multiple against a 180000-cent
    price, and each carries one `DOWNGRADED` / `NATURAL` event of -3000, so the
    two ledgers are numerically indistinguishable and only the remedy basis can
    make their settlements differ.
    """
    first = fx.nv_deal_route(api, region_code="NV-LV1", stop_after="escrow_funded")
    second = fx.nv_deal_route(
        api,
        region_code="NV-LV2",
        stops=(fx.nv_stop("LV2-1", "TUE", 20000),),
        stop_after="escrow_funded",
        profile=first.profile,
        seller=first.seller,
        buyer=first.buyer,
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    for ctx in (first, second):
        ctx["deal"] = validate_success(api.close_deal(ctx.deal["id"], BROKER))
        assert_cents(ctx.deal["guaranteed_mrr_cents"], 20000, "guaranteed mrr")
        assert_cents(ctx.deal["allowance_mrr_cents"], 1000, "allowance mrr")
        assert_cents(ctx.deal["clawback_cap_cents"], 36000, "clawback cap")
        assert_multiple_1dp(ctx.deal["effective_multiple_at_close"], "10.0", "close multiple")

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    for ctx in (first, second):
        fx.append_attrition(api, ctx.deal["id"], ctx.account["id"], "DOWNGRADED", "2026-10-01",
                            -3000)
        ctx["deal"] = validate_success(api.get_deal(ctx.deal["id"], BROKER))
        assert_cents(ctx.deal["net_attrition_mrr_cents"], 3000, "net attrition")
        assert ctx.deal["clawback_status"] == "CLAWBACK_TRIGGERED"
    return first, second


class TestTheRemedyBasisIsASubstantiveChoice:
    def test_the_same_two_thousand_of_compensable_churn_prices_two_thousand_cents_apart(self, api):
        """Two identical ledgers, one switch: pricing the loss off the closing multiple asks the seller
        for 20000 cents while pro-rating the whole purchase price asks for 18000, and the divergence is
        not a rounding artefact — the compensable bucket is the same 2000 cents in both snapshots.

        PRD §3.9: "The raw adjustment is `compensable_natural_mrr_cents` multiplied by the deal's
        `effective_multiple_at_close`, rounded half up to whole cents, plus
        `compensable_solicited_mrr_cents` multiplied by `effective_multiple_at_close` and then by a
        solicitation penalty factor of one and a half, also rounded half up to whole cents."
        PRD §3.9: "A natural percentage is `compensable_natural_mrr_cents` divided by
        `guaranteed_mrr_cents`, rounded half up to four decimal places ... The raw adjustment is the
        deal's `current_offer_price_cents` multiplied by the natural percentage, rounded half up to
        whole cents".

        Design: Difficulty/dual_variant_calc/clawback_replacement_versus_price_adjustment_basis
        """
        first, second = twin_nv_deals_with_identical_churn(api)

        replacement = validate_success(
            api.create_clawback_settlement(
                f.clawback_settlement_payload(first.deal["id"], "REPLACEMENT_BASIS"), BROKER
            ),
            201,
        )
        price = validate_success(
            api.create_clawback_settlement(
                f.clawback_settlement_payload(second.deal["id"], "PRICE_ADJUSTMENT_BASIS"), BROKER
            ),
            201,
        )

        for snapshot in (replacement, price):
            assert snapshot["status"] == "DRAFT"
            assert_cents(snapshot["guaranteed_mrr_cents"], 20000, "snapshot guaranteed mrr")
            assert_cents(snapshot["lost_natural_mrr_cents"], 3000, "lost natural")
            assert_cents(snapshot["allowance_mrr_cents"], 1000, "snapshot allowance")
            assert_cents(snapshot["compensable_natural_mrr_cents"], 2000, "compensable natural")
            assert_cents(snapshot["compensable_solicited_mrr_cents"], 0, "compensable solicited")

        assert replacement["remedy_basis"] == "REPLACEMENT_BASIS"
        assert_cents(replacement["raw_adjustment_cents"], 20000, "raw adjustment")
        assert_cents(replacement["adjustment_cents"], 20000, "adjustment")
        assert_cents(replacement["from_holdback_cents"], 20000, "from holdback")
        assert_cents(replacement["from_note_principal_cents"], 0, "from note principal")
        assert_cents(replacement["seller_direct_due_cents"], 0, "seller direct due")
        assert_cents(replacement["holdback_release_to_seller_cents"], 7000, "holdback to seller")

        assert price["remedy_basis"] == "PRICE_ADJUSTMENT_BASIS"
        assert_cents(price["raw_adjustment_cents"], 18000, "raw adjustment")
        assert_cents(price["adjustment_cents"], 18000, "adjustment")
        assert_cents(price["from_holdback_cents"], 18000, "from holdback")
        assert_cents(price["holdback_release_to_seller_cents"], 9000, "holdback to seller")

        assert replacement["adjustment_cents"] - price["adjustment_cents"] == 2000, (
            "the same attrition must price 2000 cents apart under the two bases"
        )

    def test_the_two_bases_hand_the_seller_back_different_slices_of_one_holdback(self, api):
        """The divergence is not cosmetic: settling both deals drains two identical 27000-cent holdbacks
        into different splits, and the 2000-cent gap between the bases is exactly what the seller keeps
        or loses. Neither settlement touches the note, so the difference lands entirely in cash.

        PRD §3.9: "The escrow then pays `from_holdback_cents` against the adjustment and
        `holdback_release_to_seller_cents` to the seller, its `holdback_balance_cents` drops to zero
        and its `status` becomes `RELEASED`."
        PRD §3.9: "And `holdback_release_to_seller_cents` is the escrow's `holdback_balance_cents`
        minus `from_holdback_cents`: whatever survives the clawback goes back to the seller".

        Design: Difficulty/dual_variant_calc/clawback_replacement_versus_price_adjustment_basis
        """
        first, second = twin_nv_deals_with_identical_churn(api)

        outcomes = {}
        for ctx, basis, amount in ((first, "REPLACEMENT_BASIS", 20000),
                                   (second, "PRICE_ADJUSTMENT_BASIS", 18000)):
            settlement = validate_success(
                api.create_clawback_settlement(
                    f.clawback_settlement_payload(ctx.deal["id"], basis), BROKER
                ),
                201,
            )
            validate_success(
                api.propose_clawback_settlement(
                    settlement["id"], f.propose_settlement_payload(amount), ALT_BROKER
                )
            )
            settled = validate_success(
                api.settle_clawback_settlement(
                    settlement["id"], f.settle_settlement_payload(amount), RELEASER
                )
            )
            assert settled["status"] == "SETTLED"
            outcomes[basis] = fx.escrow_for_deal(api, ctx.deal["id"])
            assert_cents(validate_success(api.get_deal(ctx.deal["id"], BROKER))["note_principal_cents"],
                         120000, "note principal")

        replacement_escrow = outcomes["REPLACEMENT_BASIS"]
        price_escrow = outcomes["PRICE_ADJUSTMENT_BASIS"]
        for escrow in (replacement_escrow, price_escrow):
            assert escrow["status"] == "RELEASED"
            assert_cents(escrow["funded_amount_cents"], 87000, "funded amount")
            assert_cents(escrow["holdback_balance_cents"], 0, "holdback balance")
            assert_cents(escrow["disbursed_to_broker_cents"], 50000, "broker bucket")
            assert_escrow_cash_conservation(escrow)

        assert_cents(replacement_escrow["disbursed_to_buyer_cents"], 20000, "buyer bucket")
        assert_cents(replacement_escrow["disbursed_to_seller_cents"], 17000, "seller bucket")
        assert_cents(price_escrow["disbursed_to_buyer_cents"], 18000, "buyer bucket")
        assert_cents(price_escrow["disbursed_to_seller_cents"], 19000, "seller bucket")
        assert (price_escrow["disbursed_to_seller_cents"]
                - replacement_escrow["disbursed_to_seller_cents"]) == 2000


class TestTheReplacementCreditCapIsTakenFromThePreCreditLedger:
    def test_a_twelve_thousand_substitute_is_admitted_only_up_to_half_the_churn(self, api):
        """The cap is measured against the losses as they stand before any credit is applied, so half of
        the 14318-cent cancellation is the most the seller may substitute away; the surplus 4841 cents of
        replacement revenue is discarded rather than carried, and the net lands on 7159 instead of the
        2318 an after-the-credit cap would have produced.

        PRD §3.9: "The deal's `replacement_mrr_cents` is the sum of `claimed_recurring_mrr_cents` over
        the accounts of this deal that have a non-null `replaced_account_id` and a `transfer_status` of
        `TRANSFERRED`".
        PRD §3.9: "The credit cap is fifty percent of the sum of the offset natural loss and the offset
        solicited loss, rounded half up to whole cents, and the credit applied is the lesser of
        `replacement_mrr_cents` and that cap: a seller cannot substitute its way out of more than half
        of the churn."
        PRD §3.9: "On success the lost stop moves to `REPLACED`, which is absorbing, and a new
        `ServiceAccount` is created on the same `listing_id` and the same `deal_id` with
        `replaced_account_id` pointing at the stop it stands in for".

        Design: Difficulty/combinatorial_formula/settlement_credit_cap_evaluated_before_credit_is_applied
        """
        ctx = fx.replacement_recorded_deal(api)
        deal = validate_success(api.get_deal(ctx["deal"]["id"], BROKER))
        assert_cents(deal["attrited_mrr_cents"], 14318, "attrited mrr")
        assert_cents(deal["retained_mrr_cents"], 16000, "retained mrr")
        assert_cents(deal["replacement_mrr_cents"], 12000, "replacement mrr")
        assert_cents(deal["net_attrition_mrr_cents"], 7159, "net attrition")
        assert deal["clawback_status"] == "CLAWBACK_TRIGGERED"

        replaced = validate_success(api.get_service_account(ctx["a2"]["id"], BROKER))
        assert replaced["transfer_status"] == "REPLACED"
        substitute = validate_success(api.get_service_account(ctx["replacement"]["id"], BROKER))
        assert substitute["route_day"] == "MON"
        assert substitute["replaced_account_id"] == ctx["a2"]["id"]
        assert substitute["transfer_status"] == "TRANSFERRED"
        assert substitute["verification_status"] == "VERIFIED"
        assert_cents(substitute["claimed_recurring_mrr_cents"], 12000, "substitute claimed mrr")
        assert_cents(substitute["verified_recurring_mrr_cents"], 12000, "substitute verified mrr")

    def test_the_capped_credit_is_what_the_settlement_snapshot_prices(self, api):
        """The settlement records both halves of the order of evaluation — a 7159-cent cap and a
        7159-cent credit against a 12000-cent substitution — and prices the 5643 cents left after the
        allowance at eleven times, which the sourcing waterfall then splits between the whole holdback
        and the note.

        PRD §3.9: "`replacement_credit_cap_cents` is fifty percent of the sum of the two offset losses
        rounded half up, `replacement_credit_mrr_cents` is the lesser of the deal's
        `replacement_mrr_cents` and that cap, and `allowance_mrr_cents` is snapshotted from the deal."
        PRD §3.9: "`from_note_principal_cents` is the lesser of what remains of the adjustment after
        the holdback and the deal's `note_principal_cents`, so a financed deal can settle by writing
        down the note."
        PRD §3.9: "The `from_note_principal_cents` portion reduces the deal's `note_principal_cents`,
        and `seller_direct_due_cents` is owed by the seller in cash outside the platform."

        Design: Difficulty/combinatorial_formula/settlement_credit_cap_evaluated_before_credit_is_applied
        """
        ctx = fx.replacement_recorded_deal(api)
        deal_id = ctx["deal"]["id"]
        settlement = validate_success(
            api.create_clawback_settlement(f.clawback_settlement_payload(deal_id), BROKER), 201
        )
        assert_cents(settlement["lost_natural_mrr_cents"], 14318, "lost natural")
        assert_cents(settlement["lost_solicited_mrr_cents"], 0, "lost solicited")
        assert_cents(settlement["recovered_mrr_cents"], 0, "recovered")
        assert_cents(settlement["replacement_credit_cap_cents"], 7159, "replacement credit cap")
        assert_cents(settlement["replacement_credit_mrr_cents"], 7159, "replacement credit")
        assert settlement["replacement_credit_mrr_cents"] != 12000, (
            "the cap comes from the pre-credit ledger, so the surplus substitution is discarded"
        )
        assert_cents(settlement["allowance_mrr_cents"], 1516, "snapshot allowance")
        assert_cents(settlement["compensable_natural_mrr_cents"], 5643, "compensable natural")
        assert_cents(settlement["compensable_solicited_mrr_cents"], 0, "compensable solicited")
        assert_cents(settlement["raw_adjustment_cents"], 62073, "raw adjustment")
        assert_cents(settlement["adjustment_cents"], 62073, "adjustment")
        assert_cents(settlement["from_holdback_cents"], 51000, "from holdback")
        assert_cents(settlement["from_note_principal_cents"], 11073, "from note principal")
        assert_cents(settlement["seller_direct_due_cents"], 0, "seller direct due")
        assert_cents(settlement["holdback_release_to_seller_cents"], 0, "holdback to seller")

        validate_success(
            api.propose_clawback_settlement(
                settlement["id"], f.propose_settlement_payload(62073), ALT_BROKER
            )
        )
        settled = validate_success(
            api.settle_clawback_settlement(
                settlement["id"], f.settle_settlement_payload(62073), RELEASER
            )
        )
        assert settled["status"] == "SETTLED"

        after = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(after["note_principal_cents"], 208927, "note principal")
        assert after["clawback_status"] == "SETTLED"
        escrow = fx.escrow_for_deal(api, deal_id)
        assert_cents(escrow["disbursed_to_buyer_cents"], 51000, "buyer bucket")
        assert_cents(escrow["holdback_balance_cents"], 0, "holdback balance")
        assert_escrow_cash_conservation(escrow)


def small_downgrade_settlement(api):
    """The canonical AZ deal after a 3000-cent downgrade, with a DRAFT settlement worth 16324."""
    ctx = fx.closed_deal(api)
    deal_id = ctx["deal"]["id"]
    assert_cents(ctx["deal"]["allowance_mrr_cents"], 1516, "allowance mrr")
    assert_multiple_1dp(ctx["deal"]["effective_multiple_at_close"], "11.0", "close multiple")

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    fx.append_attrition(api, deal_id, ctx["a1"]["id"], "DOWNGRADED", "2026-10-01", -3000)
    ctx["deal"] = validate_success(api.get_deal(deal_id, BROKER))
    assert_cents(ctx["deal"]["net_attrition_mrr_cents"], 3000, "net attrition")
    assert ctx["deal"]["clawback_status"] == "CLAWBACK_TRIGGERED"

    ctx["settlement"] = validate_success(
        api.create_clawback_settlement(f.clawback_settlement_payload(deal_id), BROKER), 201
    )
    assert ctx["settlement"]["status"] == "DRAFT"
    assert_cents(ctx["settlement"]["adjustment_cents"], 16324, "adjustment")
    return ctx


class TestTheSettlementNegotiationIsATrueCycle:
    def test_proposed_disputed_and_proposed_again_re_enters_a_state_it_already_held(self, api):
        """The settlement returns to a status it has already occupied, and the re-proposal re-asserts the
        very same recomputed figure because the ledger has not moved; nothing is settled by any of the
        three calls, so the holdback is still sitting in escrow untouched and the deal is still `CLOSED`
        with its clawback triggered.

        PRD §3.9: "The brokerage submits an `adjustment_cents` from `DRAFT` or from `DISPUTED` — a
        disputed settlement is re-proposed through the same operation — and anything else is
        `ERR_SETTLEMENT_NOT_PROPOSED`."
        PRD §3.9: "The escrow holdback stays blocked while the dispute is open, and the cycle
        `PROPOSED → DISPUTED → PROPOSED` may repeat without bound, each re-proposal recomputing from
        the live ledger."

        Design: Difficulty/non_linear_state_machine/clawback_settlement_proposed_disputed_reproposed_cycle
        """
        ctx = small_downgrade_settlement(api)
        settlement_id = ctx["settlement"]["id"]
        escrow_id = ctx["escrow"]["id"]
        seller_headers = make_seller_headers(ctx["seller"]["id"])

        proposed = validate_success(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), ALT_BROKER
            )
        )
        assert proposed["status"] == "PROPOSED"
        assert_cents(proposed["adjustment_cents"], 16324, "adjustment")

        disputed = validate_success(
            api.dispute_clawback_settlement(
                settlement_id, f.dispute_settlement_payload(), seller_headers
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason_code"] == "VALUATION_DISPUTED"

        reproposed = validate_success(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), ALT_BROKER
            )
        )
        assert reproposed["status"] == "PROPOSED"
        assert_cents(reproposed["adjustment_cents"], 16324, "adjustment")

        for snapshot in (proposed, disputed, reproposed):
            assert snapshot["settled_at_utc"] is None

        escrow = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(escrow["holdback_balance_cents"], 51000, "holdback balance")
        assert_cents(escrow["disbursed_to_buyer_cents"], 0, "buyer bucket")
        assert_escrow_cash_conservation(escrow)
        deal = validate_success(api.get_deal(ctx["deal"]["id"], BROKER))
        assert deal["status"] == "CLOSED"
        assert deal["clawback_status"] == "CLAWBACK_TRIGGERED"

    def test_the_loop_only_turns_when_the_two_sides_act_in_strict_alternation(self, api):
        """Each edge of the loop belongs to exactly one party and exactly one starting status: the seller
        cannot dispute a draft, cannot propose at all, the brokerage cannot dispute its own proposal, and
        the user who recorded the churn cannot be the one to put a number to it.

        PRD §3.9: "The proposing user may not be a user who recorded any attrition event on the deal, or
        the answer is `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "**Disputing** is the seller's rejection: from `PROPOSED` only, supplying a
        `dispute_reason_code` which is stored, the settlement returns to `DISPUTED`."
        PRD §2.1: "If the role is recognised but is not one of the roles authorised for the endpoint
        being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)".

        Design: Difficulty/non_linear_state_machine/clawback_settlement_proposed_disputed_reproposed_cycle
        """
        ctx = small_downgrade_settlement(api)
        settlement_id = ctx["settlement"]["id"]
        seller_headers = make_seller_headers(ctx["seller"]["id"])

        validate_error(
            api.dispute_clawback_settlement(
                settlement_id, f.dispute_settlement_payload(), seller_headers
            ),
            ApiErrorId.ERR_SETTLEMENT_NOT_PROPOSED,
            409,
        )
        validate_error(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), seller_headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), BROKER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert validate_success(
            api.get_clawback_settlement(settlement_id, BROKER)
        )["status"] == "DRAFT"

        validate_success(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), ALT_BROKER
            )
        )
        validate_error(
            api.dispute_clawback_settlement(
                settlement_id, f.dispute_settlement_payload(), ALT_BROKER
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), ALT_BROKER
            ),
            ApiErrorId.ERR_SETTLEMENT_NOT_PROPOSED,
            409,
        )
        assert validate_success(
            api.get_clawback_settlement(settlement_id, BROKER)
        )["status"] == "PROPOSED"


class TestSettlingPartitionsTheHoldbackExactly:
    def test_the_fifty_one_thousand_reserve_is_split_never_created_or_destroyed(self, api):
        """The holdback is partitioned rather than refunded: 16324 cents answer the clawback and the
        remaining 34676 go back to the seller, the two adding to exactly the reserve. The escrow-wide
        identity still totals the original 171000 after a third disbursement event, and the balance lands
        on zero rather than drifting.

        PRD §2.10: "For every escrow account, the total ever funded equals the sum of everything
        assigned out of it plus everything still sitting in it: `funded_amount_cents` equals
        `disbursed_to_broker_cents` plus `disbursed_to_seller_cents` plus `disbursed_to_buyer_cents`
        plus `holdback_balance_cents` plus `undisbursed_balance_cents`."
        PRD §3.9: "The escrow then pays `from_holdback_cents` against the adjustment and
        `holdback_release_to_seller_cents` to the seller, its `holdback_balance_cents` drops to zero and
        its `status` becomes `RELEASED`."
        PRD §3.9: "Because the holdback balance has reached zero, the deal cascades from `CLOSED` to
        `GUARANTEE_CLOSED` and its `clawback_status` becomes `SETTLED`."

        Design: Difficulty/compensating_invariant/settlement_disbursement_conserves_the_retention_holdback
        """
        ctx = small_downgrade_settlement(api)
        settlement_id = ctx["settlement"]["id"]
        escrow_id = ctx["escrow"]["id"]

        before = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(before["funded_amount_cents"], 171000, "funded amount")
        assert_cents(before["disbursed_to_broker_cents"], 50000, "broker bucket")
        assert_cents(before["disbursed_to_seller_cents"], 70000, "seller bucket")
        assert_cents(before["disbursed_to_buyer_cents"], 0, "buyer bucket")
        assert_cents(before["holdback_balance_cents"], 51000, "holdback balance")
        assert_cents(before["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_escrow_cash_conservation(before)

        proposed = validate_success(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), ALT_BROKER
            )
        )
        assert_cents(proposed["from_holdback_cents"], 16324, "from holdback")
        assert_cents(proposed["from_note_principal_cents"], 0, "from note principal")
        assert_cents(proposed["seller_direct_due_cents"], 0, "seller direct due")
        assert_cents(proposed["holdback_release_to_seller_cents"], 34676, "holdback to seller")
        assert (proposed["from_holdback_cents"]
                + proposed["holdback_release_to_seller_cents"]) == 51000

        settled = validate_success(
            api.settle_clawback_settlement(
                settlement_id, f.settle_settlement_payload(16324), RELEASER
            )
        )
        assert settled["status"] == "SETTLED"
        assert_instant_equals(settled["settled_at_utc"], "2026-10-01T00:00:00Z", "settled_at_utc")

        after = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(after["disbursed_to_buyer_cents"], 16324, "buyer bucket")
        assert_cents(after["disbursed_to_seller_cents"], 104676, "seller bucket")
        assert_cents(after["disbursed_to_broker_cents"], 50000, "broker bucket")
        assert_cents(after["holdback_balance_cents"], 0, "holdback balance")
        assert_cents(after["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_cents(after["funded_amount_cents"], 171000, "funded amount")
        assert after["status"] == "RELEASED"
        assert_escrow_cash_conservation(after)

        deal = validate_success(api.get_deal(ctx["deal"]["id"], BROKER))
        assert deal["status"] == "GUARANTEE_CLOSED"
        assert deal["clawback_status"] == "SETTLED"

    def test_a_drained_holdback_cannot_be_paid_out_by_either_path_twice(self, api):
        """Once the reserve has been partitioned there is nothing left to disburse, and both routes to it
        are shut: settling again is refused on the settlement's absorbing status and the ordinary holdback
        release is refused on the escrow's, with every bucket left exactly where the settlement put it.

        PRD §3.9: "On success the settlement moves to `SETTLED`, which is absorbing, and `settled_at_utc`
        is stamped from the logical clock; a second attempt to settle is refused by the status check."
        PRD §3.9: "The escrow agent releases it with no request body, from a `PARTIALLY_RELEASED` escrow
        whose deal is `CLOSED`".

        Design: Difficulty/compensating_invariant/settlement_disbursement_conserves_the_retention_holdback
        """
        ctx = small_downgrade_settlement(api)
        settlement_id = ctx["settlement"]["id"]
        escrow_id = ctx["escrow"]["id"]

        validate_success(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(16324), ALT_BROKER
            )
        )
        validate_success(
            api.settle_clawback_settlement(
                settlement_id, f.settle_settlement_payload(16324), RELEASER
            )
        )

        validate_error(
            api.settle_clawback_settlement(
                settlement_id, f.settle_settlement_payload(16324), RELEASER
            ),
            ApiErrorId.ERR_SETTLEMENT_NOT_PROPOSED,
            409,
        )
        validate_error(
            api.release_holdback(escrow_id, RELEASER), ApiErrorId.ERR_ESCROW_NOT_OPEN, 409
        )

        escrow = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert escrow["status"] == "RELEASED"
        assert_cents(escrow["holdback_balance_cents"], 0, "holdback balance")
        assert_cents(escrow["disbursed_to_buyer_cents"], 16324, "buyer bucket")
        assert_cents(escrow["disbursed_to_seller_cents"], 104676, "seller bucket")
        assert_escrow_cash_conservation(escrow)
        assert validate_success(
            api.get_clawback_settlement(settlement_id, BROKER)
        )["status"] == "SETTLED"
