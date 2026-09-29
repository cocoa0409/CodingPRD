"""Escrow deposits, the closing waterfall and the holdback release (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    ESCROW_FUNDER_USER_ID,
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
    assert_ratio_4dp,
)

BROKER = TEST_USERS["broker_headers"]
FUNDER = make_escrow_agent_headers(ESCROW_FUNDER_USER_ID)
RELEASER = make_escrow_agent_headers(ESCROW_RELEASER_USER_ID)


class TestDepositArithmeticDrivesTheTransition:
    def test_a_short_deposit_is_a_self_transition_and_only_the_exact_top_up_funds_the_deal(self, api):
        """The same endpoint produces two different outcomes from the same state, decided purely by
        whether the running total reaches the target; the funder stamp belongs to the first deposit
        and a later depositor does not overwrite it.

        PRD §3.8: "A deposit that leaves the balance short of the target leaves the escrow `OPEN`,
        awaiting more; a deposit that lands the balance exactly on `target_amount_cents` moves the
        escrow to `FUNDED` and cascades the deal from `FINANCING_APPROVED` to `ESCROW_FUNDED`".
        PRD §3.8: "The first deposit against an escrow stamps `funded_by_user_id` with the acting
        escrow agent's `X-User-ID`".

        Design: Corner/state_machines/partial_escrow_deposit_is_a_self_transition_then_the_exact_top_up_funds_it
        """
        ctx = fx.financing_approved_deal(api)
        escrow_id = fx.escrow_for_deal(api, ctx.deal["id"])["id"]

        validate_success(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(100000), FUNDER), 201
        )
        partial = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert partial["status"] == "OPEN"
        assert_cents(partial["funded_amount_cents"], 100000, "funded amount")
        assert_cents(partial["undisbursed_balance_cents"], 100000, "undisbursed balance")
        assert_cents(partial["holdback_balance_cents"], 0, "holdback balance")
        assert partial["funded_by_user_id"] == ESCROW_FUNDER_USER_ID
        assert validate_success(api.get_deal(ctx.deal["id"], BROKER))["status"] == "FINANCING_APPROVED"

        validate_success(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(71000), RELEASER), 201
        )
        funded = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert funded["status"] == "FUNDED"
        assert_cents(funded["funded_amount_cents"], 171000, "funded amount")
        assert_cents(funded["undisbursed_balance_cents"], 171000, "undisbursed balance")
        assert funded["funded_by_user_id"] == ESCROW_FUNDER_USER_ID
        assert validate_success(api.get_deal(ctx.deal["id"], BROKER))["status"] == "ESCROW_FUNDED"

    def test_the_overshoot_guard_and_the_status_guard_are_different_rules(self, api):
        """One cent over the target is refused as an overshoot and leaves no trace at all; the exact
        amount funds the escrow; the very next cent is refused by the status rule instead, so the
        two rules are visibly distinct.

        PRD §3.8: "`funded_amount_cents` plus the new `amount_cents` must not exceed
        `target_amount_cents`, and an overshoot is `ERR_ESCROW_OVERFUNDED` rather than a partial
        acceptance, so the buyer must size its final deposit exactly."
        PRD §3.8: "The escrow must be `OPEN` with `deposits_blocked` false, and anything else — a
        `FUNDED`, `PARTIALLY_RELEASED`, `RELEASED` or `REFUNDED` escrow ... — is
        `ERR_ESCROW_NOT_OPEN`."

        Design: Corner/validations/escrow_deposit_one_cent_over_target_rejected_then_the_exact_amount_passes
        """
        ctx = fx.financing_approved_deal(api)
        escrow_id = fx.escrow_for_deal(api, ctx.deal["id"])["id"]

        validate_error(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(171001), FUNDER),
            ApiErrorId.ERR_ESCROW_OVERFUNDED,
            422,
        )
        untouched = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(untouched["funded_amount_cents"], 0, "funded amount")
        assert_cents(untouched["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert untouched["status"] == "OPEN"
        assert untouched["funded_by_user_id"] is None

        validate_success(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(171000), FUNDER), 201
        )
        funded = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert funded["status"] == "FUNDED"
        assert_cents(funded["funded_amount_cents"], 171000, "funded amount")

        validate_error(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(1), FUNDER),
            ApiErrorId.ERR_ESCROW_NOT_OPEN,
            409,
        )
        assert validate_success(api.get_deal(ctx.deal["id"], BROKER))["status"] == "ESCROW_FUNDED"

    def test_the_escrow_status_gate_answers_ahead_of_both_money_rules(self, api):
        """A release attempted on an `OPEN` escrow violates the timing rule as well, and a deposit
        into a `FUNDED` or `PARTIALLY_RELEASED` escrow violates nothing else at all: all three
        answer with the status error.

        PRD §3.8: "The escrow must be `OPEN` with `deposits_blocked` false, and anything else — a
        `FUNDED`, `PARTIALLY_RELEASED`, `RELEASED` or `REFUNDED` escrow ... — is
        `ERR_ESCROW_NOT_OPEN`."
        PRD §3.9: "The escrow agent releases it with no request body, from a `PARTIALLY_RELEASED`
        escrow whose deal is `CLOSED`".

        Design: Corner/errors/depositing_into_a_funded_escrow_and_releasing_from_an_open_one_rejected
        """
        ctx = fx.financing_approved_deal(api)
        deal_id = ctx.deal["id"]
        escrow = fx.escrow_for_deal(api, deal_id)
        escrow_id = escrow["id"]
        assert escrow["status"] == "OPEN"
        assert escrow["scheduled_holdback_release_utc"] is None

        validate_error(
            api.release_holdback(escrow_id, RELEASER), ApiErrorId.ERR_ESCROW_NOT_OPEN, 409
        )

        validate_success(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(171000), FUNDER), 201
        )
        funded = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert funded["status"] == "FUNDED"
        assert_cents(funded["funded_amount_cents"], 171000, "funded amount")
        assert funded["funded_by_user_id"] == ESCROW_FUNDER_USER_ID
        assert validate_success(api.get_deal(deal_id, BROKER))["status"] == "ESCROW_FUNDED"

        validate_error(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(1), FUNDER),
            ApiErrorId.ERR_ESCROW_NOT_OPEN,
            409,
        )
        assert_cents(
            validate_success(api.get_escrow_account(escrow_id, BROKER))["funded_amount_cents"],
            171000,
            "funded amount",
        )

        fx.introduce(api, ctx.a2["id"], deal_id, "2026-08-01", ctx.seller)
        fx.introduce(api, ctx.a1["id"], deal_id, "2026-08-01", ctx.seller)
        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"
        after_close = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert after_close["status"] == "PARTIALLY_RELEASED"
        assert_cents(after_close["holdback_balance_cents"], 51000, "holdback balance")

        validate_error(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(1), FUNDER),
            ApiErrorId.ERR_ESCROW_NOT_OPEN,
            409,
        )


class TestClosingWritesFourEntityFamiliesAtOnce:
    def test_one_close_call_moves_the_deal_the_stops_the_escrow_and_the_listing(self, api):
        """Every branch of the closing side-effect set is read back from the single call: the frozen
        calendar, the frozen money, the customer hand-over, the escrow waterfall and the parent
        listing's terminal status.

        PRD §3.8: "`closed_at_utc` and `guarantee_start_utc` are both set to the logical clock.
        `guarantee_end_utc` and `holdback_release_utc` are both set to the clock advanced by
        `retention_guarantee_days` calendar days ... `replacement_deadline_utc` is
        `guarantee_end_utc` advanced by a further fourteen days".
        PRD §3.8: "`commission_cents` is the greater of that raw fee and 50,000 cents" and
        "`clawback_cap_cents` is twenty percent of the deal's `current_offer_price_cents`".
        PRD §3.8: "Every account of the deal in `INTRODUCED` moves to `TRANSFERRED` and has its
        `current_mrr_cents` initialised to its `verified_recurring_mrr_cents`".
        PRD §3.8: "Bucket one pays the brokerage the lesser of the available cash and
        `commission_cents` ... Bucket two pays the entire remaining available cash to the seller ...
        Bucket three sets `holdback_balance_cents` to `holdback_amount_cents` ... Bucket four sets
        `undisbursed_balance_cents` to zero".
        PRD §3.8: "`effective_multiple_at_close` is copied from the listing's non-superseded
        `VERIFIED_BASIS` valuation" — which stands at 11.0 for the two-account verified base.

        Design: Corner/state_machines/deal_close_executes_the_full_cross_entity_side_effect_set
        """
        ctx = fx.escrow_funded_deal(api)
        fx.set_clock(api, "2026-09-01T00:00:00Z")

        closed = validate_success(api.close_deal(ctx.deal["id"], BROKER))
        assert closed["status"] == "CLOSED"
        assert_instant_equals(closed["closed_at_utc"], "2026-09-01T00:00:00Z", "closed at")
        assert_instant_equals(closed["guarantee_start_utc"], "2026-09-01T00:00:00Z", "guarantee start")
        assert_instant_equals(closed["guarantee_end_utc"], "2026-11-30T00:00:00Z", "guarantee end")
        assert_instant_equals(closed["holdback_release_utc"], "2026-11-30T00:00:00Z", "holdback release")
        assert_instant_equals(
            closed["replacement_deadline_utc"], "2026-12-14T00:00:00Z", "replacement deadline"
        )
        assert_cents(closed["commission_cents"], 50000, "commission")
        assert_cents(closed["clawback_cap_cents"], 68000, "clawback cap")
        assert_multiple_1dp(closed["effective_multiple_at_close"], "11.0", "frozen multiple")
        assert_cents(closed["guaranteed_mrr_cents"], 30318, "guaranteed mrr")
        assert_cents(closed["retained_mrr_cents"], 30318, "retained mrr")
        assert_cents(closed["attrited_mrr_cents"], 0, "attrited mrr")
        assert_cents(closed["replacement_mrr_cents"], 0, "replacement mrr")
        assert_cents(closed["net_attrition_mrr_cents"], 0, "net attrition mrr")
        assert_ratio_4dp(closed["attrition_pct"], "0.0000", "attrition pct")
        assert_cents(closed["allowance_mrr_cents"], 1516, "allowance mrr")
        assert closed["clawback_status"] == "MONITORING"

        escrow = fx.escrow_for_deal(api, ctx.deal["id"])
        assert escrow["status"] == "PARTIALLY_RELEASED"
        assert_cents(escrow["disbursed_to_broker_cents"], 50000, "broker disbursement")
        assert_cents(escrow["disbursed_to_seller_cents"], 70000, "seller disbursement")
        assert_cents(escrow["disbursed_to_buyer_cents"], 0, "buyer disbursement")
        assert_cents(escrow["holdback_balance_cents"], 51000, "holdback balance")
        assert_cents(escrow["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_instant_equals(
            escrow["scheduled_holdback_release_utc"], "2026-11-30T00:00:00Z", "scheduled release"
        )
        assert_escrow_cash_conservation(escrow)

        a1 = validate_success(api.get_service_account(ctx.a1["id"], BROKER))
        assert a1["transfer_status"] == "TRANSFERRED"
        assert_cents(a1["current_mrr_cents"], 16000, "A1 current mrr")

        assert validate_success(api.get_route_listing(ctx.listing["id"], BROKER))["status"] == "CLOSED"

    def test_the_closed_deal_reads_back_its_whole_derived_guarantee_window(self, api):
        """Five instants and five money figures are derived from one clock reading and are all
        readable afterwards without any further write; the guarantee runs from the close, not from
        the acceptance a month earlier.

        PRD §3.8: "`guarantee_end_utc` and `holdback_release_utc` are both set to the clock advanced
        by `retention_guarantee_days` calendar days — the retention guarantee and the holdback are
        released on the same instant by construction."
        PRD §3.8: "The deal's `guaranteed_mrr_cents` is the sum of those accounts'
        `verified_recurring_mrr_cents`, `retained_mrr_cents` is set equal to it, `attrited_mrr_cents`
        is set to zero, `allowance_mrr_cents` is five percent of `guaranteed_mrr_cents` rounded half
        up to whole cents, and `clawback_status` becomes `MONITORING`."

        Design: Corner/endpoints/closed_deal_read_returns_the_whole_derived_guarantee_window
        """
        ctx = fx.closed_deal(api)
        deal = validate_success(api.get_deal(ctx.deal["id"], BROKER))

        assert deal["status"] == "CLOSED"
        assert deal["clawback_status"] == "MONITORING"
        assert deal["accepted_on"] == "2026-08-01"
        assert_instant_equals(deal["closed_at_utc"], "2026-09-01T00:00:00Z", "closed at")
        assert_instant_equals(deal["guarantee_start_utc"], "2026-09-01T00:00:00Z", "guarantee start")
        assert_instant_equals(deal["guarantee_end_utc"], "2026-11-30T00:00:00Z", "guarantee end")
        assert_instant_equals(deal["holdback_release_utc"], "2026-11-30T00:00:00Z", "holdback release")
        assert_instant_equals(
            deal["replacement_deadline_utc"], "2026-12-14T00:00:00Z", "replacement deadline"
        )
        assert_multiple_1dp(deal["effective_multiple_at_close"], "11.0", "frozen multiple")
        assert_cents(deal["guaranteed_mrr_cents"], 30318, "guaranteed mrr")
        assert_cents(deal["allowance_mrr_cents"], 1516, "allowance mrr")
        assert_cents(deal["retained_mrr_cents"], 30318, "retained mrr")
        assert_cents(deal["attrited_mrr_cents"], 0, "attrited mrr")
        assert_cents(deal["net_attrition_mrr_cents"], 0, "net attrition mrr")
        assert_ratio_4dp(deal["attrition_pct"], "0.0000", "attrition pct")

        escrow = fx.escrow_for_deal(api, deal["id"])
        assert escrow["status"] == "PARTIALLY_RELEASED"
        assert_cents(escrow["funded_amount_cents"], 171000, "funded amount")
        assert_cents(escrow["disbursed_to_broker_cents"], 50000, "broker disbursement")
        assert_cents(escrow["disbursed_to_seller_cents"], 70000, "seller disbursement")
        assert_cents(escrow["holdback_balance_cents"], 51000, "holdback balance")
        assert_cents(escrow["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_instant_equals(
            escrow["scheduled_holdback_release_utc"], "2026-11-30T00:00:00Z", "scheduled release"
        )
        assert_escrow_cash_conservation(escrow)

    def test_the_middle_commission_tier_and_the_absolute_holdback_cap_bind_together(self, api):
        """A two-million-cent CASH purchase lands on the eight percent tier and simultaneously
        overruns the holdback ceiling, so the tier boundary, the cap and the full-cash minimum are
        all pinned by one close — and the waterfall still conserves every cent.

        PRD §3.8: "the rate is chosen from the gross alone: ten percent when the gross is below
        1,500,000 cents, eight percent when it is at or above 1,500,000 cents and below 4,000,000
        cents, and six percent when it is at or above 4,000,000 cents."
        PRD §3.5: "`holdback_cents` is fifteen percent of the standing price, rounded half up to
        whole cents *first*, and then capped at two thousand dollars ... with the rounding strictly
        preceding the cap."
        PRD §3.5: "a `CASH` purchase must have the entire price in cash".

        Design: Corner/calculations/commission_tier_and_cash_holdback_cap_constants_applied
        """
        cash_deal = dict(
            offer_price_cents=2000000, financing_type="CASH", down_payment_cents=2000000,
            note_principal_cents=0, retention_guarantee_days=90,
        )
        ctx = fx.nv_deal_route(
            api, region_code="LV-BIG", stops=(fx.nv_stop("BIG-1", "TUE", 20000),),
            listed_mrr_cents=20000, asking_price_cents=2000000, deal=cash_deal,
            stop_after="escrow_funded",
        )
        assert_cents(ctx.deal["holdback_cents"], 200000, "capped holdback")
        assert_cents(ctx.deal["escrow_target_amount_cents"], 2200000, "escrow target")

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        closed = validate_success(api.close_deal(ctx.deal["id"], BROKER))
        assert closed["status"] == "CLOSED"
        assert closed["financing_type"] == "CASH"
        assert_cents(closed["down_payment_cents"], 2000000, "cash down payment")
        assert_cents(closed["commission_cents"], 160000, "eight percent commission")
        assert_cents(closed["holdback_cents"], 200000, "capped holdback")
        assert_cents(closed["escrow_target_amount_cents"], 2200000, "escrow target")
        assert_cents(closed["clawback_cap_cents"], 400000, "clawback cap")

        escrow = fx.escrow_for_deal(api, ctx.deal["id"])
        assert escrow["status"] == "PARTIALLY_RELEASED"
        assert_cents(escrow["funded_amount_cents"], 2200000, "funded amount")
        assert_cents(escrow["disbursed_to_broker_cents"], 160000, "broker disbursement")
        assert_cents(escrow["disbursed_to_seller_cents"], 1840000, "seller disbursement")
        assert_cents(escrow["holdback_balance_cents"], 200000, "holdback balance")
        assert_cents(escrow["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_escrow_cash_conservation(escrow)


class TestClosingRequiresEveryIncludedStop:
    def test_completeness_is_measured_over_the_included_stops_only(self, api):
        """The excluded stop never has to be handed over, but the one still pending blocks the close
        until it is introduced; the close then flips both introduced stops and leaves the excluded
        one exactly as it was.

        PRD §3.8: "Every account of the listing whose `verification_status` is not `EXCLUDED` must
        have `transfer_status` of `INTRODUCED` or `TRANSFERRED`; an outstanding `PENDING` stop is
        `ERR_INTRODUCTIONS_INCOMPLETE`."
        PRD §3.8: "assigns `introduction_sequence_no` as the listing's
        `introductions_completed_count` plus one".

        Design: Corner/errors/closing_with_an_unintroduced_account_rejected
        """
        ctx = fx.escrow_funded_deal(api, introduce_accounts=False)
        deal_id = ctx.deal["id"]
        fx.introduce(api, ctx.a2["id"], deal_id, "2026-08-01", ctx.seller)
        fx.set_clock(api, "2026-09-01T00:00:00Z")

        validate_error(
            api.close_deal(deal_id, BROKER), ApiErrorId.ERR_INTRODUCTIONS_INCOMPLETE, 422
        )
        blocked = validate_success(api.get_deal(deal_id, BROKER))
        assert blocked["status"] == "ESCROW_FUNDED"
        assert blocked["closed_at_utc"] is None

        introduced = validate_success(
            api.introduce_service_account(
                ctx.a1["id"], f.introduce_account_payload(deal_id, "2026-09-01"),
                make_seller_headers(ctx.seller["id"]),
            )
        )
        assert introduced["introduction_sequence_no"] == 2
        assert introduced["transfer_status"] == "INTRODUCED"

        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"
        assert_instant_equals(closed["closed_at_utc"], "2026-09-01T00:00:00Z", "closed at")

        accounts, meta = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": ctx.listing["id"]})
        )
        assert meta["total_count"] == 3
        by_ref = {a["customer_ref"]: a for a in accounts}
        assert by_ref["A1-SUNRISE"]["transfer_status"] == "TRANSFERRED"
        assert by_ref["A2-MESA"]["transfer_status"] == "TRANSFERRED"
        assert by_ref["A3-GILBERT"]["verification_status"] == "EXCLUDED"
        assert by_ref["A3-GILBERT"]["transfer_status"] == "PENDING"


class TestHoldbackReleaseTiming:
    def test_one_second_early_is_refused_and_the_scheduled_instant_itself_pays_out(self, api):
        """The release gate is inclusive at its lower end; on the instant itself the reserve reaches
        the seller, the escrow closes empty and the deal is absorbed, with the cash identity still
        exact.

        PRD §3.9: "`scheduled_holdback_release_utc` must be non-null, the logical clock must be at or
        after it — one second early is refused, exactly on the instant is allowed — and
        `holdback_release_blocked` must be false".
        PRD §3.9: "On success `disbursed_to_seller_cents` grows by the whole
        `holdback_balance_cents`, that balance drops to zero, the escrow's `status` becomes
        `RELEASED`, and the deal cascades from `CLOSED` to `GUARANTEE_CLOSED`."

        Design: Corner/validations/holdback_release_on_the_scheduled_instant_passes
        """
        ctx = fx.closed_deal(api)
        escrow = fx.escrow_for_deal(api, ctx.deal["id"])
        escrow_id = escrow["id"]
        assert escrow["holdback_release_blocked"] is False
        assert_cents(escrow["holdback_balance_cents"], 51000, "holdback balance")

        fx.set_clock(api, "2026-11-29T23:59:59Z")
        validate_error(
            api.release_holdback(escrow_id, RELEASER),
            ApiErrorId.ERR_HOLDBACK_NOT_RELEASABLE,
            422,
        )

        fx.set_clock(api, "2026-11-30T00:00:00Z")
        validate_success(api.release_holdback(escrow_id, RELEASER), 201)

        released = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert released["status"] == "RELEASED"
        assert_cents(released["holdback_balance_cents"], 0, "holdback balance")
        assert_cents(released["disbursed_to_seller_cents"], 121000, "seller disbursement")
        assert_cents(released["disbursed_to_broker_cents"], 50000, "broker disbursement")
        assert_cents(released["disbursed_to_buyer_cents"], 0, "buyer disbursement")
        assert_cents(released["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_cents(released["funded_amount_cents"], 171000, "funded amount")
        assert_escrow_cash_conservation(released)

        deal = validate_success(api.get_deal(ctx.deal["id"], BROKER))
        assert deal["status"] == "GUARANTEE_CLOSED"
        assert deal["clawback_status"] == "MONITORING"


def introduced_but_underfunded(api, funded_cents: int):
    """A FINANCING_APPROVED deal whose permits and introductions are done but whose escrow is short.

    Everything except the money is in place: both AZ permits are `APPROVED`, both
    non-excluded stops are `INTRODUCED`, and the escrow holds `funded_cents`
    against its 171000-cent target.
    """
    ctx = fx.financing_approved_deal(api)
    if funded_cents:
        ctx["escrow"] = fx.fund_escrow(api, ctx["escrow"]["id"], funded_cents)
    ctx["a2"] = fx.introduce(api, ctx["a2"]["id"], ctx["deal"]["id"], "2026-08-01", ctx["seller"])
    ctx["a1"] = fx.introduce(api, ctx["a1"]["id"], ctx["deal"]["id"], "2026-08-01", ctx["seller"])
    assert ctx["deal"]["status"] == "FINANCING_APPROVED"
    return ctx


class TestTheDealStatusGateOutranksTheShortfallGateOnClose:
    def test_a_partial_deposit_answers_with_the_state_error_not_the_shortfall_error(self, api):
        """One partial deposit violates two different closing conditions at once — the deal is not yet
        `ESCROW_FUNDED` and the escrow is 71000 cents short — and the deal-status answer is the one
        reported; the control top-up proves the shortfall condition was genuinely co-violated rather
        than unreachable.

        PRD §3.8: "The brokerage closes a deal from `ESCROW_FUNDED`; a deal in any earlier status is
        `ERR_DEAL_NOT_FUNDED`."
        PRD §3.8: "And the escrow's `funded_amount_cents` must be at least its `target_amount_cents`,
        a shortfall being `ERR_ESCROW_UNDERFUNDED`. Note that a deal that is not `ESCROW_FUNDED`
        necessarily has an underfunded escrow as well, and in that case the deal-status answer is the
        one reported."

        Design: Difficulty/priority_pair_validation_conflict/pair_a_state_beats_fiscal_on_close
        """
        ctx = introduced_but_underfunded(api, 100000)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]
        assert_cents(ctx["escrow"]["target_amount_cents"], 171000, "escrow target")
        assert_cents(ctx["escrow"]["funded_amount_cents"], 100000, "escrow funded")
        assert ctx["escrow"]["status"] == "OPEN"

        response = api.close_deal(deal_id, BROKER)
        body = validate_error(response, ApiErrorId.ERR_DEAL_NOT_FUNDED, 409)
        assert body["error_id"] != ApiErrorId.ERR_ESCROW_UNDERFUNDED.value, (
            "the shortfall diagnosis must not win over the deal-status diagnosis"
        )

        refused = validate_success(api.get_deal(deal_id, BROKER))
        assert refused["status"] == "FINANCING_APPROVED"
        assert refused["closed_at_utc"] is None
        untouched = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert untouched["status"] == "OPEN"
        assert_cents(untouched["disbursed_to_broker_cents"], 0, "broker bucket")
        assert_escrow_cash_conservation(untouched)

        fx.fund_escrow(api, escrow_id, 71000)
        funded = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert funded["status"] == "FUNDED"
        assert validate_success(api.get_deal(deal_id, BROKER))["status"] == "ESCROW_FUNDED"
        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"

    def test_every_funding_level_below_the_target_gives_the_same_state_answer(self, api):
        """Three different shortfalls — nothing deposited, most of it deposited and one cent missing —
        all answer with the deal-status error, because the escrow only reaches `FUNDED` on the exact
        target; the one-cent gap also proves the shortfall is real, since a two-cent deposit overshoots
        it.

        PRD §3.8: "A deposit that leaves the balance short of the target leaves the escrow `OPEN`,
        awaiting more; a deposit that lands the balance exactly on `target_amount_cents` moves the
        escrow to `FUNDED` and cascades the deal from `FINANCING_APPROVED` to `ESCROW_FUNDED`,
        incrementing the deal's `version`."
        PRD §3.8: "The deposit may not overshoot: `funded_amount_cents` plus the new `amount_cents`
        must not exceed `target_amount_cents`, and an overshoot is `ERR_ESCROW_OVERFUNDED` rather than
        a partial acceptance, so the buyer must size its final deposit exactly."

        Design: Difficulty/priority_pair_validation_conflict/pair_a_state_beats_fiscal_on_close
        """
        ctx = introduced_but_underfunded(api, 0)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]

        for deposit in (None, 100000, 70999):
            if deposit is not None:
                fx.fund_escrow(api, escrow_id, deposit)
            validate_error(api.close_deal(deal_id, BROKER), ApiErrorId.ERR_DEAL_NOT_FUNDED, 409)

        short = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(short["funded_amount_cents"], 170999, "escrow funded")
        assert short["status"] == "OPEN"
        assert_escrow_cash_conservation(short)

        validate_error(
            api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(2), FUNDER),
            ApiErrorId.ERR_ESCROW_OVERFUNDED,
            422,
        )
        validate_error(api.close_deal(deal_id, BROKER), ApiErrorId.ERR_DEAL_NOT_FUNDED, 409)

        fx.fund_escrow(api, escrow_id, 1)
        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"
        assert_cents(closed["commission_cents"], 50000, "commission")


def one_permit_short_funded_deal(api):
    """A fully funded canonical deal whose PESTICIDE_APPLICATOR permit cleared and whose
    BUSINESS_TAX permit was never filed, so the sibling set is not yet terminal."""
    ctx = fx.accepted_deal(api)
    ctx["pesticide_transfer"] = fx.approve_permit(api, ctx["pesticide_transfer"]["id"],
                                                  ctx["buyer"], "2026-08-01")
    ctx = fx.diligence_cleared_deal(api, ctx)
    ctx = fx.financing_approved_deal(api, ctx)
    ctx = fx.escrow_funded_deal(api, ctx, introduce_accounts=False)
    assert ctx["deal"]["status"] == "ESCROW_FUNDED"
    outstanding = validate_success(
        api.get_license_transfer(ctx["business_tax_transfer"]["id"], BROKER)
    )
    assert outstanding["status"] == "NOT_STARTED"
    return ctx


class TestClosingJoinsOverTheWholePermitFanOut:
    def test_one_cleared_permit_out_of_two_is_still_a_refusal(self, api):
        """The AZ regime fans two permits out of one acceptance, and closing joins over both of them:
        with one `APPROVED` and one never filed the close is refused and no cent moves, and the second
        approval — a call that names neither the deal nor the escrow — is what lets the same close
        through once the customers have been handed over.

        PRD §3.8: "Every permit transfer of the deal must be `APPROVED` or `WAIVED` — the join over the
        fan-out of §3.7, where the last permit to clear is what makes the deal closable."
        PRD §3.8: "Every one of the deal's permit transfers must have cleared to `APPROVED` or
        `WAIVED`, and an outstanding permit is `ERR_LICENSE_NOT_TRANSFERRED`."
        PRD §3.8: "Every account of the listing whose `verification_status` is not `EXCLUDED` must have
        `transfer_status` of `INTRODUCED` or `TRANSFERRED`; an outstanding `PENDING` stop is
        `ERR_INTRODUCTIONS_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/deal_close_blocked_until_every_required_permit_is_terminal
        """
        ctx = one_permit_short_funded_deal(api)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]

        validate_error(api.close_deal(deal_id, BROKER), ApiErrorId.ERR_LICENSE_NOT_TRANSFERRED, 422)
        blocked = validate_success(api.get_deal(deal_id, BROKER))
        assert blocked["status"] == "ESCROW_FUNDED"
        assert blocked["closed_at_utc"] is None
        held = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(held["disbursed_to_broker_cents"], 0, "broker bucket")
        assert_cents(held["undisbursed_balance_cents"], 171000, "undisbursed balance")

        cleared = fx.approve_permit(api, ctx["business_tax_transfer"]["id"], ctx["buyer"],
                                    "2026-08-01")
        assert cleared["status"] == "APPROVED"
        unchanged = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(unchanged["undisbursed_balance_cents"], 171000, "undisbursed balance")
        assert validate_success(api.get_deal(deal_id, BROKER))["status"] == "ESCROW_FUNDED"

        validate_error(api.close_deal(deal_id, BROKER), ApiErrorId.ERR_INTRODUCTIONS_INCOMPLETE, 422)
        fx.introduce(api, ctx["a2"]["id"], deal_id, "2026-08-01", ctx["seller"])
        fx.introduce(api, ctx["a1"]["id"], deal_id, "2026-08-01", ctx["seller"])

        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"
        listing = validate_success(api.get_route_listing(ctx["listing"]["id"], BROKER))
        assert listing["status"] == "CLOSED"

    def test_the_last_permit_to_clear_releases_the_whole_hundred_seventy_one_thousand(self, api):
        """Once the join is satisfied the deferred close runs in full at the very same clock it was
        refused at: the calendar is frozen off 2026-08-01, the waterfall assigns every one of the
        171000 funded cents, and the excluded Wednesday stop is the only one left behind.

        PRD §3.8: "`closed_at_utc` and `guarantee_start_utc` are both set to the logical clock.
        `guarantee_end_utc` and `holdback_release_utc` are both set to the clock advanced by
        `retention_guarantee_days` calendar days ... `replacement_deadline_utc` is `guarantee_end_utc`
        advanced by a further fourteen days".
        PRD §3.8: "The available cash is `funded_amount_cents` minus `holdback_amount_cents` — the
        holdback is reserved before anyone is paid. Bucket one pays the brokerage the lesser of the
        available cash and `commission_cents` ... Bucket two pays the entire remaining available cash
        to the seller ... Bucket three sets `holdback_balance_cents` to `holdback_amount_cents` ...
        Bucket four sets `undisbursed_balance_cents` to zero".
        PRD §3.8: "The escrow moves from `FUNDED` to `PARTIALLY_RELEASED` and its
        `scheduled_holdback_release_utc` is set to the deal's `holdback_release_utc`."

        Design: Difficulty/cross_entity_state_dependency/deal_close_blocked_until_every_required_permit_is_terminal
        """
        ctx = one_permit_short_funded_deal(api)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]
        validate_error(api.close_deal(deal_id, BROKER), ApiErrorId.ERR_LICENSE_NOT_TRANSFERRED, 422)

        fx.approve_permit(api, ctx["business_tax_transfer"]["id"], ctx["buyer"], "2026-08-01")
        fx.introduce(api, ctx["a2"]["id"], deal_id, "2026-08-01", ctx["seller"])
        fx.introduce(api, ctx["a1"]["id"], deal_id, "2026-08-01", ctx["seller"])

        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert_instant_equals(closed["closed_at_utc"], "2026-08-01T00:00:00Z", "closed_at_utc")
        assert_instant_equals(closed["guarantee_start_utc"], "2026-08-01T00:00:00Z",
                              "guarantee_start_utc")
        assert_instant_equals(closed["guarantee_end_utc"], "2026-10-30T00:00:00Z",
                              "guarantee_end_utc")
        assert_instant_equals(closed["replacement_deadline_utc"], "2026-11-13T00:00:00Z",
                              "replacement_deadline_utc")
        assert_cents(closed["commission_cents"], 50000, "commission")
        assert_cents(closed["holdback_cents"], 51000, "holdback")

        escrow = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(escrow["disbursed_to_broker_cents"], 50000, "broker bucket")
        assert_cents(escrow["disbursed_to_seller_cents"], 70000, "seller bucket")
        assert_cents(escrow["holdback_balance_cents"], 51000, "holdback balance")
        assert_cents(escrow["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert escrow["status"] == "PARTIALLY_RELEASED"
        assert_instant_equals(escrow["scheduled_holdback_release_utc"], "2026-10-30T00:00:00Z",
                              "scheduled_holdback_release_utc")
        assert_escrow_cash_conservation(escrow)

        for key, expected in (("a1", "TRANSFERRED"), ("a2", "TRANSFERRED"), ("a3", "PENDING")):
            stop = validate_success(api.get_service_account(ctx[key]["id"], BROKER))
            assert stop["transfer_status"] == expected, (
                f"stop {key} should be {expected} after closing"
            )


class TestTerminationIsTheCompensatingActionForFunding:
    def test_the_refund_moves_the_whole_funded_amount_without_creating_or_destroying_a_cent(self, api):
        """The cash identity is exact on both sides of the compensation: before the refund all 171000
        cents sit unassigned, after it all 171000 sit in the buyer's bucket, and the funding record
        itself is not erased — `funded_amount_cents` still reads 171000 on a `REFUNDED` escrow.

        PRD §2.10: "For every escrow account, the total ever funded equals the sum of everything
        assigned out of it plus everything still sitting in it: `funded_amount_cents` equals
        `disbursed_to_broker_cents` plus `disbursed_to_seller_cents` plus `disbursed_to_buyer_cents`
        plus `holdback_balance_cents` plus `undisbursed_balance_cents`."
        PRD §3.5: "The escrow account refunds every funded cent to the buyer:
        `disbursed_to_buyer_cents` grows by the whole `funded_amount_cents`, `holdback_balance_cents`
        and `undisbursed_balance_cents` are both set to zero, and its `status` becomes `REFUNDED`".

        Design: Difficulty/compensating_invariant/terminate_funded_deal_conserves_escrow_cash
        """
        ctx = fx.escrow_funded_deal(api)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]

        before = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(before["funded_amount_cents"], 171000, "funded amount")
        assert_cents(before["undisbursed_balance_cents"], 171000, "undisbursed balance")
        assert_cents(before["holdback_balance_cents"], 0, "holdback balance")
        assert_cents(before["disbursed_to_buyer_cents"], 0, "buyer bucket")
        assert_escrow_cash_conservation(before)

        terminated = validate_success(
            api.terminate_deal(deal_id, f.terminate_deal_payload(), BROKER)
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason_code"] == "BUYER_WITHDREW"

        after = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert after["status"] == "REFUNDED"
        assert_cents(after["funded_amount_cents"], 171000, "funded amount")
        assert_cents(after["disbursed_to_buyer_cents"], 171000, "buyer bucket")
        assert_cents(after["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_cents(after["disbursed_to_broker_cents"], 0, "broker bucket")
        assert_cents(after["disbursed_to_seller_cents"], 0, "seller bucket")
        assert_cents(after["holdback_balance_cents"], 0, "holdback balance")
        assert_escrow_cash_conservation(after)

    def test_the_unwind_returns_the_stops_and_the_route_but_keeps_the_diligence_work(self, api):
        """Termination walks back exactly the deal-scoped effects — two introduced stops, the listing's
        introduction counter and its market status — while the verification work that produced the
        30318-cent verified roll-up survives untouched, and the permits that had already cleared are
        left as they are.

        PRD §3.5: "Every stop of the deal whose transfer dimension is `INTRODUCED` returns to `PENDING`
        with its `deal_id`, `introduced_on` and `introduction_sequence_no` all cleared to null, and the
        listing's `introductions_completed_count` is recomputed accordingly. The listing returns from
        `UNDER_CONTRACT` to `LISTED`, putting the route back on the market."
        PRD §3.5: "Every permit transfer of the deal sitting in `NOT_STARTED`, `APPLIED` or `DENIED`
        moves to `CANCELLED`, while ones already `APPROVED` or `WAIVED` are left alone".

        Design: Difficulty/compensating_invariant/terminate_funded_deal_conserves_escrow_cash
        """
        ctx = fx.escrow_funded_deal(api)
        deal_id = ctx["deal"]["id"]
        listing_id = ctx["listing"]["id"]
        assert ctx["a2"]["introduction_sequence_no"] == 1
        assert ctx["a1"]["introduction_sequence_no"] == 2

        before = validate_success(api.get_route_listing(listing_id, BROKER))
        assert before["status"] == "UNDER_CONTRACT"
        assert before["introductions_completed_count"] == 2
        assert_cents(before["verified_recurring_mrr_cents"], 30318, "verified recurring mrr")

        validate_success(api.terminate_deal(deal_id, f.terminate_deal_payload(), BROKER))

        for key in ("a1", "a2"):
            stop = validate_success(api.get_service_account(ctx[key]["id"], BROKER))
            assert stop["transfer_status"] == "PENDING", f"stop {key} should return to PENDING"
            assert stop["deal_id"] is None
            assert stop["introduced_on"] is None
            assert stop["introduction_sequence_no"] is None
            assert stop["verification_status"] == "VERIFIED"

        after = validate_success(api.get_route_listing(listing_id, BROKER))
        assert after["introductions_completed_count"] == 0
        assert after["status"] == "LISTED"
        assert_cents(after["verified_recurring_mrr_cents"], 30318, "verified recurring mrr")
        assert after["verified_account_count"] == 2

        for transfer_id in (ctx["pesticide_transfer"]["id"], ctx["business_tax_transfer"]["id"]):
            transfer = validate_success(api.get_license_transfer(transfer_id, BROKER))
            assert transfer["status"] == "APPROVED", (
                "a permit that had already cleared is left alone by the unwind"
            )
