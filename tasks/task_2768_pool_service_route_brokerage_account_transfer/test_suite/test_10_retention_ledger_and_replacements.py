"""The retention guarantee: the attrition ledger, its version guard and replacement stops (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    ESCROW_RELEASER_USER_ID,
    TEST_USERS,
    make_escrow_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_instant_equals,
    assert_multiple_1dp,
    assert_ratio_4dp,
)

BROKER = TEST_USERS["broker_headers"]
RELEASER = make_escrow_agent_headers(ESCROW_RELEASER_USER_ID)


class TestGuaranteeWindowBoundaries:
    def test_the_half_open_window_refuses_both_of_its_ends_without_touching_the_version(self, api):
        """The window's own end instant is outside it and the day before its start is outside it, and
        the last day inside it is accepted with the very version captured before the two refusals —
        so neither refusal wrote anything at all.

        PRD §3.9: "the `effective_date` must fall inside the guarantee window, which is half-open
        from `guarantee_start_utc` to `guarantee_end_utc` with the event taken at midnight UTC of its
        date: a date exactly on `guarantee_end_utc`'s date is **outside** the window and is refused
        with `ERR_ATTRITION_OUTSIDE_GUARANTEE`, while the closing date itself is inside it."
        PRD §3.9: "A `DOWNGRADED` event leaves the account `TRANSFERRED` and sets its
        `current_mrr_cents` to the greater of zero and its current value minus the absolute value of
        the delta".

        Design: Corner/validations/attrition_event_on_the_guarantee_end_instant_rejected
        """
        ctx = fx.closed_deal(api)
        deal_id = ctx.deal["id"]
        assert_cents(ctx.deal["guaranteed_mrr_cents"], 30318, "guaranteed mrr")
        assert_cents(ctx.deal["allowance_mrr_cents"], 1516, "allowance mrr")
        assert_instant_equals(ctx.deal["guarantee_start_utc"], "2026-09-01T00:00:00Z", "start")
        assert_instant_equals(ctx.deal["guarantee_end_utc"], "2026-11-30T00:00:00Z", "end")

        fx.set_clock(api, "2026-11-29T00:00:00Z")
        deal_v = fx.deal_version(api, deal_id)

        def downgrade(effective_date):
            return f.attrition_event_payload(
                deal_id, ctx.a1["id"], "DOWNGRADED", effective_date, -500, "NATURAL", deal_v
            )

        for outside in ("2026-11-30", "2026-08-31"):
            validate_error(
                api.create_attrition_event(downgrade(outside), BROKER),
                ApiErrorId.ERR_ATTRITION_OUTSIDE_GUARANTEE,
                422,
            )

        validate_success(api.create_attrition_event(downgrade("2026-11-29"), BROKER), 201)

        ledger = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(ledger["attrited_mrr_cents"], 500, "attrited mrr")
        assert_cents(ledger["retained_mrr_cents"], 29818, "retained mrr")
        assert_cents(ledger["replacement_mrr_cents"], 0, "replacement mrr")
        assert_cents(ledger["net_attrition_mrr_cents"], 500, "net attrition")
        assert_ratio_4dp(ledger["attrition_pct"], "0.0165", "attrition pct")
        assert ledger["clawback_status"] == "MONITORING"

        account = validate_success(api.get_service_account(ctx.a1["id"], BROKER))
        assert_cents(account["current_mrr_cents"], 15500, "current mrr")
        assert account["transfer_status"] == "TRANSFERRED"


class TestLedgerOperationsRequireAClosedDeal:
    def test_a_fully_funded_deal_is_not_yet_a_guaranteed_one(self, api):
        """The escrow is full and the customer is introduced, yet the retention clock has not started:
        both ledger entry points answer with the not-closed code — on the attrition append that code
        wins over the window rule the same date would also break — and both succeed the moment the
        deal closes.

        PRD §3.9: "The deal must have reached `CLOSED` or `GUARANTEE_CLOSED`, since there is no
        guarantee to draw on before closing, and an earlier status is `ERR_GUARANTEE_NOT_STARTED`".
        PRD §2.9: "`ERR_GUARANTEE_NOT_STARTED` — a post-close operation was attempted on a deal that
        has not closed." listed at 32, ahead of "`ERR_ATTRITION_OUTSIDE_GUARANTEE`" at 49 and
        "`ERR_NO_CLAWBACK_DUE` — the deal's retention ledger has not triggered a clawback." at 56.
        PRD §2.9: "Every write is evaluated as a single ordered sequence of checks. **The first check
        that fails determines the response, and no later check is evaluated.**"

        Design: Corner/errors/attrition_and_settlement_before_the_deal_closes_rejected
        """
        ctx = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="escrow_funded")
        deal_id = ctx.deal["id"]
        account_id = ctx.account["id"]

        validate_error(
            api.create_attrition_event(
                f.attrition_event_payload(
                    deal_id, account_id, "CANCELLED", "2026-08-15", -20000, "NATURAL",
                    fx.deal_version(api, deal_id),
                ),
                BROKER,
            ),
            ApiErrorId.ERR_GUARANTEE_NOT_STARTED,
            409,
        )
        validate_error(
            api.create_clawback_settlement(f.clawback_settlement_payload(deal_id), BROKER),
            ApiErrorId.ERR_GUARANTEE_NOT_STARTED,
            409,
        )

        before = validate_success(api.get_deal(deal_id, BROKER))
        assert before["status"] == "ESCROW_FUNDED"
        assert before["clawback_status"] == "NOT_APPLICABLE"
        assert before["guarantee_start_utc"] is None
        assert_cents(before["attrited_mrr_cents"], 0, "attrited mrr")

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"
        assert closed["clawback_status"] == "MONITORING"
        assert_instant_equals(closed["guarantee_start_utc"], "2026-09-01T00:00:00Z", "start")
        assert_instant_equals(closed["guarantee_end_utc"], "2026-11-30T00:00:00Z", "end")

        validate_success(
            api.create_attrition_event(
                f.attrition_event_payload(
                    deal_id, account_id, "CANCELLED", "2026-09-15", -20000, "NATURAL",
                    fx.deal_version(api, deal_id),
                ),
                BROKER,
            ),
            201,
        )
        after = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(after["attrited_mrr_cents"], 20000, "attrited mrr")
        assert after["clawback_status"] == "CLAWBACK_TRIGGERED"


class TestLedgerVersionGuard:
    def test_a_replayed_append_is_refused_and_the_refreshed_version_lands(self, api):
        """An append-only ledger has no state precondition to lean on, so the parent version is the
        only guard: the identical legitimate downgrade is refused when it carries the version the
        first append already consumed, and accepted when it carries the refreshed one.

        PRD §2.8: "**Appending an attrition event** requires `expected_deal_version`, carrying the
        client's last observed `version` of the referenced `Deal`. If it does not equal that deal's
        current `version`, the append is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412) and
        nothing is appended ... Every accepted append advances `Deal.version`, so the next append
        must carry the new value."
        PRD §3.9: "Attrition events carry only an `id` and a `created_at`; they are never edited or
        deleted, and a correction is expressed as a further event rather than a rewrite."

        Design: Corner/complexity_layers/stale_expected_deal_version_after_the_first_attrition_event
        """
        ctx = fx.closed_deal(api)
        deal_id = ctx.deal["id"]
        fx.set_clock(api, "2026-10-01T00:00:00Z")
        dv1 = fx.deal_version(api, deal_id)

        def downgrade(version):
            return f.attrition_event_payload(
                deal_id, ctx.a1["id"], "DOWNGRADED", "2026-09-15", -500, "NATURAL", version
            )

        validate_success(api.create_attrition_event(downgrade(dv1), BROKER), 201)
        validate_error(
            api.create_attrition_event(downgrade(dv1), BROKER),
            ApiErrorId.ERR_STALE_DEAL_VERSION,
            412,
        )

        dv2 = fx.deal_version(api, deal_id)
        assert dv2 == dv1 + 1

        validate_success(api.create_attrition_event(downgrade(dv2), BROKER), 201)

        ledger = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(ledger["attrited_mrr_cents"], 1000, "attrited mrr")
        assert_cents(ledger["retained_mrr_cents"], 29318, "retained mrr")
        assert_cents(ledger["net_attrition_mrr_cents"], 1000, "net attrition")
        assert_ratio_4dp(ledger["attrition_pct"], "0.0330", "attrition pct")
        assert ledger["clawback_status"] == "MONITORING"

        account = validate_success(api.get_service_account(ctx.a1["id"], BROKER))
        assert_cents(account["current_mrr_cents"], 15000, "current mrr")
        assert account["transfer_status"] == "TRANSFERRED"

        events, meta = validate_paginated(
            api.list_attrition_events(BROKER, params={"deal_id": deal_id})
        )
        assert meta["total_count"] == 2
        assert all(event["event_type"] == "DOWNGRADED" for event in events)


REP_DEAL = dict(offer_price_cents=300000, financing_type="SELLER_NOTE",
                down_payment_cents=90000, note_principal_cents=210000,
                retention_guarantee_days=90)


def triggered_two_stop_deal(api):
    """A closed 300000 NV deal whose small Monday stop was cancelled, so a clawback is live.

    The route carries a 30000 Tuesday stop and a 2000 Monday stop, both verified at
    their claimed figures, so the guarantee is 32000 with a 1600 allowance.
    """
    ctx = fx.nv_deal_route(
        api,
        region_code="PHX-REP",
        stops=(fx.nv_stop("B1-SCOTTSDALE", "TUE", 30000), fx.nv_stop("B2-TEMPE", "MON", 2000)),
        listed_mrr_cents=32000,
        asking_price_cents=300000,
        deal=REP_DEAL,
        stop_after="closed",
    )
    ctx["b1"] = fx.account_by_ref(ctx, "B1-SCOTTSDALE")
    ctx["b2"] = fx.account_by_ref(ctx, "B2-TEMPE")
    assert ctx.deal["status"] == "CLOSED"
    assert_cents(ctx.deal["guaranteed_mrr_cents"], 32000, "guaranteed mrr")
    assert_cents(ctx.deal["allowance_mrr_cents"], 1600, "allowance mrr")
    assert_multiple_1dp(ctx.deal["effective_multiple_at_close"], "11.0", "close multiple")
    assert_instant_equals(ctx.deal["replacement_deadline_utc"], "2026-12-14T00:00:00Z", "deadline")

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    validate_success(
        api.create_attrition_event(
            f.attrition_event_payload(
                ctx.deal["id"], ctx["b2"]["id"], "CANCELLED", "2026-09-15", -2000, "NATURAL",
                fx.deal_version(api, ctx.deal["id"]),
            ),
            BROKER,
        ),
        201,
    )
    ctx["deal"] = validate_success(api.get_deal(ctx.deal["id"], BROKER))
    assert ctx.deal["clawback_status"] == "CLAWBACK_TRIGGERED"
    assert_cents(ctx.deal["net_attrition_mrr_cents"], 2000, "net attrition")
    ctx["escrow"] = fx.escrow_for_deal(api, ctx.deal["id"])
    assert ctx.escrow["holdback_release_blocked"] is True
    assert ctx.escrow["scheduled_holdback_release_utc"] is None
    return ctx


class TestReplacementCreditReversesATrigger:
    def test_a_credit_capped_at_half_the_churn_still_unblocks_the_holdback(self, api):
        """The loss itself is never erased — the attrited figure stays where it was — but the ledger is
        recomputed from scratch, and a substitute stop worth the whole lost customer earns only half
        of it as credit. Half is enough here: the net drops back under the allowance and the frozen
        holdback release date is restored from the deal.

        PRD §3.9: "The credit cap is fifty percent of the sum of the offset natural loss and the
        offset solicited loss, rounded half up to whole cents, and the credit applied is the lesser
        of `replacement_mrr_cents` and that cap".
        PRD §3.9: "A `RECOVERED` event, or a replacement stop, that brings `net_attrition_mrr_cents`
        back to or below the allowance returns `clawback_status` to `MONITORING`, returns
        `holdback_release_blocked` to false, and restores `scheduled_holdback_release_utc` from the
        deal's `holdback_release_utc`".
        PRD §3.9: "the lost stop moves to `REPLACED`, which is absorbing, and a new `ServiceAccount`
        is created on the same `listing_id` and the same `deal_id` with `replaced_account_id` pointing
        at the stop it stands in for, `verification_status` of `VERIFIED`, `transfer_status` of
        `TRANSFERRED`, and `verified_recurring_mrr_cents` set equal to its own
        `claimed_recurring_mrr_cents`".

        Design: Corner/calculations/replacement_credit_moves_the_ledger_from_triggered_back_to_monitoring
        """
        ctx = triggered_two_stop_deal(api)
        deal_id = ctx.deal["id"]

        substitute = validate_success(
            api.replace_service_account(
                ctx["b2"]["id"],
                f.replacement_account_payload(
                    customer_ref="B2-TEMPE-SUBSTITUTE", route_day="MON",
                    monthly_service_fee_cents=2000,
                ),
                BROKER,
            ),
            201,
        )
        assert substitute["replaced_account_id"] == ctx["b2"]["id"]
        assert substitute["deal_id"] == deal_id
        assert substitute["listing_id"] == ctx.listing["id"]
        assert substitute["route_day"] == "MON"
        assert_cents(substitute["claimed_recurring_mrr_cents"], 2000, "substitute claimed mrr")
        assert_cents(substitute["verified_recurring_mrr_cents"], 2000, "substitute verified mrr")
        assert substitute["verification_status"] == "VERIFIED"
        assert substitute["transfer_status"] == "TRANSFERRED"

        ledger = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(ledger["attrited_mrr_cents"], 2000, "attrited mrr")
        assert_cents(ledger["retained_mrr_cents"], 30000, "retained mrr")
        assert_cents(ledger["replacement_mrr_cents"], 2000, "replacement mrr")
        assert_cents(ledger["net_attrition_mrr_cents"], 1000, "net attrition")
        assert_ratio_4dp(ledger["attrition_pct"], "0.0313", "attrition pct")
        assert ledger["clawback_status"] == "MONITORING"

        escrow = fx.escrow_for_deal(api, deal_id)
        assert escrow["holdback_release_blocked"] is False
        assert_instant_equals(
            escrow["scheduled_holdback_release_utc"], "2026-11-30T00:00:00Z", "release"
        )
        assert_cents(escrow["holdback_balance_cents"], 45000, "holdback balance")
        assert escrow["status"] == "PARTIALLY_RELEASED"

        replaced = validate_success(api.get_service_account(ctx["b2"]["id"], BROKER))
        assert replaced["transfer_status"] == "REPLACED"
        assert_cents(replaced["current_mrr_cents"], 0, "lost stop current mrr")


class TestReplacementMustMatchTheRouteDay:
    def test_the_same_substitute_on_the_wrong_day_is_refused_and_the_stop_stays_retryable(self, api):
        """A substitute must be servable on the round the lost customer sat on, so the identical
        2000-cent stop is refused on Tuesday and accepted on Monday; the refusal neither consumed the
        lost account nor created a row.

        PRD §3.9: "The substitute must be a real customer on the same day of the route: its computed
        `claimed_recurring_mrr_cents` must be strictly greater than zero and its `route_day` must
        equal the replaced stop's `route_day`, and a violation of either is
        `ERR_REPLACEMENT_TARGET_INVALID`."
        PRD §2.9: "`ERR_REPLACEMENT_TARGET_INVALID` — the substitute stop offered does not qualify as
        a replacement."
        PRD §2.7: "A cascade is all-or-nothing. If any check fails, nothing at all is written — not
        the primary mutation, not the roll-up recomputation, and not any downstream hop."

        Design: Corner/validations/replacement_on_a_different_route_day_rejected
        """
        ctx = triggered_two_stop_deal(api)
        deal_id = ctx.deal["id"]
        lost_id = ctx["b2"]["id"]

        def substitute(route_day):
            return f.replacement_account_payload(
                customer_ref="B2-TEMPE-SUBSTITUTE", route_day=route_day,
                monthly_service_fee_cents=2000,
            )

        validate_error(
            api.replace_service_account(lost_id, substitute("TUE"), BROKER),
            ApiErrorId.ERR_REPLACEMENT_TARGET_INVALID,
            422,
        )

        still_lost = validate_success(api.get_service_account(lost_id, BROKER))
        assert still_lost["transfer_status"] == "LOST"
        unchanged = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(unchanged["replacement_mrr_cents"], 0, "replacement mrr")
        assert_cents(unchanged["net_attrition_mrr_cents"], 2000, "net attrition")
        assert unchanged["clawback_status"] == "CLAWBACK_TRIGGERED"

        accepted = validate_success(
            api.replace_service_account(lost_id, substitute("MON"), BROKER), 201
        )
        assert accepted["route_day"] == "MON"
        assert_cents(accepted["claimed_recurring_mrr_cents"], 2000, "substitute claimed mrr")
        assert accepted["transfer_status"] == "TRANSFERRED"

        accounts, meta = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": ctx.listing["id"]})
        )
        assert meta["total_count"] == 3
        assert len([a for a in accounts if a["replaced_account_id"] is not None]) == 1


class TestReplacementDeadlineIsInclusive:
    def test_the_deadline_instant_itself_is_allowed_and_one_second_later_is_not(self, api):
        """Two stops of the same deal are lost and both are replaceable in principle; the clock alone
        separates them, one landing on the deadline instant and the other a second past it. The
        accepted substitute is credited only up to half the churn, so the clawback stays triggered.

        PRD §3.9: "The logical clock must be at or before the deal's `replacement_deadline_utc`;
        exactly on that instant is allowed and one second past it is
        `ERR_REPLACEMENT_DEADLINE_PASSED`."
        PRD §2.11: "**Inclusive deadline instants** — a deadline expressed as an instant is satisfied
        at that instant ... a replacement is permitted exactly on the replacement deadline instant and
        refused one second later."
        PRD §3.8: "`replacement_deadline_utc` is `guarantee_end_utc` advanced by a further fourteen
        days, giving the seller a two-week grace period after the guarantee ends in which substitute
        customers still count."

        Design: Corner/errors/replacement_exactly_on_the_deadline_passes_one_second_later_it_does_not
        """
        ctx = fx.nv_deal_route(
            api,
            region_code="LV-CENTRAL",
            stops=(fx.nv_stop("LVC-TUE", "TUE", 20000), fx.nv_stop("LVC-MON", "MON", 5000)),
            listed_mrr_cents=25000,
            stop_after="closed",
        )
        deal_id = ctx.deal["id"]
        big = fx.account_by_ref(ctx, "LVC-TUE")
        small = fx.account_by_ref(ctx, "LVC-MON")
        assert_cents(ctx.deal["guaranteed_mrr_cents"], 25000, "guaranteed mrr")
        assert_cents(ctx.deal["allowance_mrr_cents"], 1250, "allowance mrr")
        assert_instant_equals(ctx.deal["guarantee_end_utc"], "2026-11-30T00:00:00Z", "end")
        assert_instant_equals(ctx.deal["replacement_deadline_utc"], "2026-12-14T00:00:00Z", "deadline")

        for account, delta, effective in ((big, -20000, "2026-09-15"), (small, -5000, "2026-09-16")):
            validate_success(
                api.create_attrition_event(
                    f.attrition_event_payload(
                        deal_id, account["id"], "CANCELLED", effective, delta, "NATURAL",
                        fx.deal_version(api, deal_id),
                    ),
                    BROKER,
                ),
                201,
            )
        triggered = validate_success(api.get_deal(deal_id, BROKER))
        assert triggered["clawback_status"] == "CLAWBACK_TRIGGERED"

        fx.set_clock(api, "2026-12-14T00:00:00Z")
        substitute = validate_success(
            api.replace_service_account(
                big["id"],
                f.replacement_account_payload(
                    customer_ref="LVC-TUE-SUBSTITUTE", route_day="TUE",
                    monthly_service_fee_cents=20000,
                ),
                BROKER,
            ),
            201,
        )
        assert substitute["route_day"] == "TUE"
        assert_cents(substitute["claimed_recurring_mrr_cents"], 20000, "substitute claimed mrr")
        assert substitute["transfer_status"] == "TRANSFERRED"
        assert substitute["replaced_account_id"] == big["id"]

        ledger = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(ledger["attrited_mrr_cents"], 25000, "attrited mrr")
        assert_cents(ledger["replacement_mrr_cents"], 20000, "replacement mrr")
        assert_cents(ledger["net_attrition_mrr_cents"], 12500, "net attrition")
        assert_cents(ledger["retained_mrr_cents"], 0, "retained mrr")
        assert_ratio_4dp(ledger["attrition_pct"], "0.5000", "attrition pct")
        assert ledger["clawback_status"] == "CLAWBACK_TRIGGERED"

        fx.set_clock(api, "2026-12-14T00:00:01Z")
        validate_error(
            api.replace_service_account(
                small["id"],
                f.replacement_account_payload(
                    customer_ref="LVC-MON-SUBSTITUTE", route_day="MON",
                    monthly_service_fee_cents=5000,
                ),
                BROKER,
            ),
            ApiErrorId.ERR_REPLACEMENT_DEADLINE_PASSED,
            422,
        )
        untouched = validate_success(api.get_service_account(small["id"], BROKER))
        assert untouched["transfer_status"] == "LOST"
        assert_cents(untouched["current_mrr_cents"], 0, "lost stop current mrr")


class TestTheStopCanReEnterTransferredThroughTheLedger:
    def test_a_cancellation_and_a_recovery_walk_the_stop_out_of_and_back_into_transferred(self, api):
        """`TRANSFERRED` is not a terminal state: the stop leaves it for `LOST` on an appended
        cancellation and re-enters it on an appended recovery, with no endpoint on the account itself
        involved. The recovery restores exactly the verified revenue and no more, and both appends
        survive as separate immutable rows.

        PRD §3.9: "A `CANCELLED` event drives the account from `TRANSFERRED` to `LOST` and sets its
        `current_mrr_cents` to zero — the customer is gone entirely."
        PRD §3.9: "A `RECOVERED` event drives the account from `LOST` back to `TRANSFERRED` and sets
        its `current_mrr_cents` to the lesser of its `verified_recurring_mrr_cents` and its current
        value plus the delta, so a recovery can never restore more revenue than the account was
        verified at."
        PRD §3.9: "Attrition events carry only an `id` and a `created_at`; they are never edited or
        deleted, and a correction is expressed as a further event rather than a rewrite."

        Design: Difficulty/non_linear_state_machine/service_account_transferred_lost_recovered_transfer_cycle
        """
        ctx = fx.closed_deal(api)
        deal_id = ctx["deal"]["id"]
        a2_id = ctx["a2"]["id"]
        assert ctx["deal"]["clawback_status"] == "MONITORING"
        assert_cents(ctx["deal"]["guaranteed_mrr_cents"], 30318, "guaranteed mrr")

        fx.set_clock(api, "2026-10-01T00:00:00Z")
        fx.append_attrition(api, deal_id, a2_id, "CANCELLED", "2026-10-01", -14318)
        lost = validate_success(api.get_service_account(a2_id, BROKER))
        assert lost["transfer_status"] == "LOST"
        assert_cents(lost["current_mrr_cents"], 0, "current mrr")
        mid = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(mid["attrited_mrr_cents"], 14318, "attrited mrr")
        assert_cents(mid["net_attrition_mrr_cents"], 14318, "net attrition")
        assert mid["clawback_status"] == "CLAWBACK_TRIGGERED"

        fx.append_attrition(api, deal_id, a2_id, "RECOVERED", "2026-10-01", 14318)
        back = validate_success(api.get_service_account(a2_id, BROKER))
        assert back["transfer_status"] == "TRANSFERRED"
        assert_cents(back["current_mrr_cents"], 14318, "current mrr")

        after = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(after["attrited_mrr_cents"], 0, "attrited mrr")
        assert_cents(after["retained_mrr_cents"], 30318, "retained mrr")
        assert_cents(after["net_attrition_mrr_cents"], 0, "net attrition")
        assert_ratio_4dp(after["attrition_pct"], "0.0000", "attrition pct")
        assert after["clawback_status"] == "MONITORING"

        events, meta = validate_paginated(
            api.list_attrition_events(BROKER, params={"deal_id": deal_id})
        )
        assert meta["total_count"] == 2
        assert sorted(e["event_type"] for e in events) == ["CANCELLED", "RECOVERED"]

    def test_re_entering_transferred_unfreezes_the_holdback_the_exit_had_frozen(self, api):
        """The cycle's return edge is a genuine compensation on the escrow as well as on the account:
        the release instant that the cancellation cleared to null comes back as the deal's own
        `holdback_release_utc`, and the release the freeze would have refused then pays out in full at
        that very instant.

        PRD §3.9: "the deal's `clawback_status` becomes `CLAWBACK_TRIGGERED` and the escrow account's
        `holdback_release_blocked` is set to true with its `scheduled_holdback_release_utc` cleared to
        null: the retention holdback is frozen until the parties settle."
        PRD §3.9: "A `RECOVERED` event, or a replacement stop, that brings `net_attrition_mrr_cents`
        back to or below the allowance returns `clawback_status` to `MONITORING`, returns
        `holdback_release_blocked` to false, and restores `scheduled_holdback_release_utc` from the
        deal's `holdback_release_utc`".
        PRD §3.9: "On success `disbursed_to_seller_cents` grows by the whole `holdback_balance_cents`,
        that balance drops to zero, the escrow's `status` becomes `RELEASED`, and the deal cascades
        from `CLOSED` to `GUARANTEE_CLOSED`."

        Design: Difficulty/non_linear_state_machine/service_account_transferred_lost_recovered_transfer_cycle
        """
        ctx = fx.closed_deal(api)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]
        assert_instant_equals(ctx["deal"]["holdback_release_utc"], "2026-11-30T00:00:00Z",
                              "holdback_release_utc")

        opening = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert opening["holdback_release_blocked"] is False
        assert_instant_equals(opening["scheduled_holdback_release_utc"], "2026-11-30T00:00:00Z",
                              "scheduled_holdback_release_utc")
        assert_cents(opening["holdback_balance_cents"], 51000, "holdback balance")

        fx.set_clock(api, "2026-10-01T00:00:00Z")
        fx.append_attrition(api, deal_id, ctx["a2"]["id"], "CANCELLED", "2026-10-01", -14318)
        frozen = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert frozen["holdback_release_blocked"] is True
        assert frozen["scheduled_holdback_release_utc"] is None

        fx.append_attrition(api, deal_id, ctx["a2"]["id"], "RECOVERED", "2026-10-01", 14318)
        thawed = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert thawed["holdback_release_blocked"] is False
        assert_instant_equals(thawed["scheduled_holdback_release_utc"], "2026-11-30T00:00:00Z",
                              "scheduled_holdback_release_utc")
        assert_cents(thawed["holdback_balance_cents"], 51000, "holdback balance")

        fx.set_clock(api, "2026-11-30T00:00:00Z")
        released = validate_success(api.release_holdback(escrow_id, RELEASER), 201)
        assert released["status"] == "RELEASED"
        assert_cents(released["holdback_balance_cents"], 0, "holdback balance")
        assert_cents(released["disbursed_to_seller_cents"], 121000, "seller bucket")
        assert validate_success(api.get_deal(deal_id, BROKER))["status"] == "GUARANTEE_CLOSED"


class TestOneCancellationTravelsFourHops:
    def test_the_chain_reaches_the_escrow_from_an_append_on_a_closed_deal(self, api):
        """One appended cancellation moves four records in one call: the stop, then the deal's whole
        recomputed ledger, then the clawback flag, then the escrow's release schedule — and the last hop
        is a field being cleared to null rather than set. The surviving stop and the deal's own
        lifecycle status are left exactly where they were.

        PRD §3.9: "A `CANCELLED` event drives the account from `TRANSFERRED` to `LOST` and sets its
        `current_mrr_cents` to zero — the customer is gone entirely."
        PRD §3.9: "`retained_mrr_cents` is `guaranteed_mrr_cents` minus `attrited_mrr_cents`, which
        keeps the retention identity of §2.10 exact at every append."
        PRD §3.9: "`clawback_status` becomes `CLAWBACK_TRIGGERED` when `net_attrition_mrr_cents` is
        **strictly greater** than `allowance_mrr_cents`, and `MONITORING` otherwise".
        PRD §3.9: "the escrow account's `holdback_release_blocked` is set to true with its
        `scheduled_holdback_release_utc` cleared to null: the retention holdback is frozen until the
        parties settle."

        Design: Difficulty/transitive_cascade/cancelled_account_four_hop_holdback_block_cascade
        """
        ctx = fx.closed_deal(api)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]
        assert_cents(ctx["deal"]["allowance_mrr_cents"], 1516, "allowance mrr")

        fx.set_clock(api, "2026-10-01T00:00:00Z")
        fx.append_attrition(api, deal_id, ctx["a2"]["id"], "CANCELLED", "2026-10-01", -14318)

        hop_one = validate_success(api.get_service_account(ctx["a2"]["id"], BROKER))
        assert hop_one["transfer_status"] == "LOST"
        assert_cents(hop_one["current_mrr_cents"], 0, "current mrr")

        hop_two = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(hop_two["attrited_mrr_cents"], 14318, "attrited mrr")
        assert_cents(hop_two["retained_mrr_cents"], 16000, "retained mrr")
        assert_cents(hop_two["net_attrition_mrr_cents"], 14318, "net attrition")
        assert_ratio_4dp(hop_two["attrition_pct"], "0.4723", "attrition pct")

        assert hop_two["clawback_status"] == "CLAWBACK_TRIGGERED"
        hop_four = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert hop_four["holdback_release_blocked"] is True
        assert hop_four["scheduled_holdback_release_utc"] is None

        assert hop_two["status"] == "CLOSED"
        survivor = validate_success(api.get_service_account(ctx["a1"]["id"], BROKER))
        assert survivor["transfer_status"] == "TRANSFERRED"
        assert_cents(survivor["current_mrr_cents"], 16000, "current mrr")

    def test_the_cleared_release_instant_is_what_refuses_the_holdback_release(self, api):
        """The cascade's terminal hop has teeth: with the schedule cleared, the release is refused on the
        day it would have paid out and stays refused a month later, so the refusal is the freeze and not
        a timing accident. The reserve is still sitting in escrow, untouched.

        PRD §3.9: "Three timing conditions apply, all of them reported as
        `ERR_HOLDBACK_NOT_RELEASABLE`: `scheduled_holdback_release_utc` must be non-null, the logical
        clock must be at or after it — one second early is refused, exactly on the instant is allowed —
        and `holdback_release_blocked` must be false, which is what a triggered clawback sets."

        Design: Difficulty/transitive_cascade/cancelled_account_four_hop_holdback_block_cascade
        """
        ctx = fx.clawback_triggered_deal(api)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]
        assert ctx["deal"]["clawback_status"] == "CLAWBACK_TRIGGERED"

        for clock in ("2026-11-30T00:00:00Z", "2026-12-31T00:00:00Z"):
            fx.set_clock(api, clock)
            validate_error(
                api.release_holdback(escrow_id, RELEASER),
                ApiErrorId.ERR_HOLDBACK_NOT_RELEASABLE,
                422,
            )

        held = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(held["holdback_balance_cents"], 51000, "holdback balance")
        assert held["status"] == "PARTIALLY_RELEASED"
        assert held["scheduled_holdback_release_utc"] is None
        assert validate_success(api.get_deal(deal_id, BROKER))["status"] == "CLOSED"


class TestTheAllowanceIsAnExclusiveThresholdOnTheAccumulatedNet:
    def test_net_attrition_equal_to_the_allowance_does_not_trigger_and_one_cent_more_does(self, api):
        """Two downgrades, neither of them large, accumulate across the boundary: at exactly the
        1516-cent allowance nothing triggers, and the next single cent flips the flag. The rounded
        percentage reads 0.0500 on both sides, so it cannot be what the trigger is measured on, and
        neither downgrade costs its stop its `TRANSFERRED` standing.

        PRD §3.9: "`clawback_status` becomes `CLAWBACK_TRIGGERED` when `net_attrition_mrr_cents` is
        **strictly greater** than `allowance_mrr_cents`, and `MONITORING` otherwise, so net attrition
        exactly equal to the allowance does not trigger anything."
        PRD §3.9: "The `allowance_mrr_cents` is five percent of `guaranteed_mrr_cents` rounded half up
        to whole cents, and `attrition_pct` is `net_attrition_mrr_cents` divided by
        `guaranteed_mrr_cents`, rounded half up to four decimal places".
        PRD §3.9: "A `DOWNGRADED` event leaves the account `TRANSFERRED` and sets its
        `current_mrr_cents` to the greater of zero and its current value minus the absolute value of
        the delta".

        Design: Difficulty/boundary_precision_check/clawback_allowance_strictly_greater_boundary
        """
        ctx = fx.closed_deal(api)
        deal_id = ctx["deal"]["id"]
        escrow_id = ctx["escrow"]["id"]
        assert_cents(ctx["deal"]["guaranteed_mrr_cents"], 30318, "guaranteed mrr")
        assert_cents(ctx["deal"]["allowance_mrr_cents"], 1516, "allowance mrr")

        fx.set_clock(api, "2026-10-01T00:00:00Z")
        fx.append_attrition(api, deal_id, ctx["a1"]["id"], "DOWNGRADED", "2026-10-01", -1516)
        on_the_line = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(on_the_line["net_attrition_mrr_cents"], 1516, "net attrition")
        assert on_the_line["clawback_status"] == "MONITORING"
        assert_ratio_4dp(on_the_line["attrition_pct"], "0.0500", "attrition pct")
        quiet = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert quiet["holdback_release_blocked"] is False
        assert_instant_equals(quiet["scheduled_holdback_release_utc"], "2026-11-30T00:00:00Z",
                              "scheduled_holdback_release_utc")

        fx.append_attrition(api, deal_id, ctx["a2"]["id"], "DOWNGRADED", "2026-10-01", -1)
        over_the_line = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(over_the_line["net_attrition_mrr_cents"], 1517, "net attrition")
        assert over_the_line["clawback_status"] == "CLAWBACK_TRIGGERED"
        assert_ratio_4dp(over_the_line["attrition_pct"], "0.0500", "attrition pct")
        blocked = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert blocked["holdback_release_blocked"] is True

        first = validate_success(api.get_service_account(ctx["a1"]["id"], BROKER))
        assert_cents(first["current_mrr_cents"], 14484, "current mrr")
        assert first["transfer_status"] == "TRANSFERRED"
        second = validate_success(api.get_service_account(ctx["a2"]["id"], BROKER))
        assert_cents(second["current_mrr_cents"], 14317, "current mrr")
        assert second["transfer_status"] == "TRANSFERRED"

    def test_the_settlement_endpoint_is_shut_on_the_allowance_and_open_one_cent_past_it(self, api):
        """The same boundary decides whether a settlement may be opened at all, and the single cent that
        crosses it is exactly what becomes compensable: an eleven-cent adjustment on an eleven-times
        multiple, from a ledger whose losses run to 1517 cents.

        PRD §3.9: "The deal's `clawback_status` must be `CLAWBACK_TRIGGERED`, or the answer is
        `ERR_NO_CLAWBACK_DUE`."
        PRD §3.9: "`compensable_natural_mrr_cents` is the greater of zero and the credited natural
        loss minus `allowance_mrr_cents`: the free allowance shelters natural churn only."
        PRD §3.9: "The raw adjustment is `compensable_natural_mrr_cents` multiplied by the deal's
        `effective_multiple_at_close`, rounded half up to whole cents".

        Design: Difficulty/boundary_precision_check/clawback_allowance_strictly_greater_boundary
        """
        ctx = fx.closed_deal(api)
        deal_id = ctx["deal"]["id"]
        assert_multiple_1dp(ctx["deal"]["effective_multiple_at_close"], "11.0",
                            "effective multiple at close")

        fx.set_clock(api, "2026-10-01T00:00:00Z")
        fx.append_attrition(api, deal_id, ctx["a1"]["id"], "DOWNGRADED", "2026-10-01", -1516)
        validate_error(
            api.create_clawback_settlement(f.clawback_settlement_payload(deal_id), BROKER),
            ApiErrorId.ERR_NO_CLAWBACK_DUE,
            422,
        )

        fx.append_attrition(api, deal_id, ctx["a2"]["id"], "DOWNGRADED", "2026-10-01", -1)
        settlement = validate_success(
            api.create_clawback_settlement(f.clawback_settlement_payload(deal_id), BROKER), 201
        )
        assert settlement["status"] == "DRAFT"
        assert settlement["remedy_basis"] == "REPLACEMENT_BASIS"
        assert_cents(settlement["lost_natural_mrr_cents"], 1517, "lost natural mrr")
        assert_cents(settlement["allowance_mrr_cents"], 1516, "settlement allowance")
        assert_cents(settlement["compensable_natural_mrr_cents"], 1, "compensable natural mrr")
        assert_cents(settlement["compensable_solicited_mrr_cents"], 0, "compensable solicited mrr")
        assert_cents(settlement["adjustment_cents"], 11, "adjustment")
        assert_cents(settlement["from_holdback_cents"], 11, "from holdback")
        assert_cents(settlement["seller_direct_due_cents"], 0, "seller direct due")
