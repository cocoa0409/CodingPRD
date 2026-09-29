"""Handing the customers over: the introduction queue, its cap and its window (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_ratio_4dp

BROKER = TEST_USERS["broker_headers"]


def queue_of_three(api):
    """The canonical AZ route accepted with nothing excluded, so all three stops queue up."""
    ctx = fx.route_with_billing_history(api)
    for key in ("a1", "a2", "a3"):
        ctx[key] = fx.verify_account(api, ctx[key]["id"])
    return fx.introduction_ready_deal(api, ctx)


class TestIntroductionQueueOrder:
    def test_the_queue_is_ordered_by_route_day_not_by_creation_order(self, api):
        """The Tuesday stop was created first and is still refused, because the Monday stop outranks
        it; a refusal leaves the named account completely untouched.

        PRD §3.8: "Those accounts are ordered by their `route_day`, taking Monday as rank 1, Tuesday
        2, Wednesday 3, Thursday 4 and Friday 5; then by `service_start_date` ascending ... then by
        `created_at` ascending as the final tie-break."
        PRD §3.8: "Only the first account of that ordering may be introduced next: naming a
        Wednesday stop while untouched Tuesday stops remain is `ERR_INTRODUCTION_OUT_OF_SEQUENCE`."

        Design: Corner/validations/introducing_an_account_that_is_not_the_queue_head_rejected
        """
        ctx = queue_of_three(api)
        deal_id = ctx.deal["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])

        for out_of_turn in (ctx.a3, ctx.a1):
            validate_error(
                api.introduce_service_account(
                    out_of_turn["id"], f.introduce_account_payload(deal_id, "2026-08-01"),
                    seller_headers,
                ),
                ApiErrorId.ERR_INTRODUCTION_OUT_OF_SEQUENCE,
                422,
            )

        head = validate_success(
            api.introduce_service_account(
                ctx.a2["id"], f.introduce_account_payload(deal_id, "2026-08-01"), seller_headers
            )
        )
        assert head["introduction_sequence_no"] == 1

        untouched = validate_success(api.get_service_account(ctx.a1["id"], BROKER))
        assert untouched["transfer_status"] == "PENDING"
        assert untouched["introduced_on"] is None
        assert untouched["introduction_sequence_no"] is None

    def test_the_per_date_cap_is_an_aggregate_over_the_deal_not_the_account(self, api):
        """The third stop is the queue head and the window is open, so only the two-per-date cap can
        explain the refusal; the same stop lands on the next date and the refused attempt never
        touched the listing's counter.

        PRD §3.8: "At most two introductions may be recorded for one deal on one `introduced_on`
        date; the third on the same date is `ERR_INTRODUCTION_LIMIT_REACHED`, and the count is per
        deal and per date, so a fresh date resets the allowance."

        Design: Corner/validations/third_introduction_on_the_same_date_rejected
        """
        ctx = queue_of_three(api)
        deal_id = ctx.deal["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])

        first = validate_success(
            api.introduce_service_account(
                ctx.a2["id"], f.introduce_account_payload(deal_id, "2026-08-01"), seller_headers
            )
        )
        assert first["introduction_sequence_no"] == 1
        second = validate_success(
            api.introduce_service_account(
                ctx.a1["id"], f.introduce_account_payload(deal_id, "2026-08-01"), seller_headers
            )
        )
        assert second["introduction_sequence_no"] == 2

        validate_error(
            api.introduce_service_account(
                ctx.a3["id"], f.introduce_account_payload(deal_id, "2026-08-01"), seller_headers
            ),
            ApiErrorId.ERR_INTRODUCTION_LIMIT_REACHED,
            422,
        )

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        third = validate_success(
            api.introduce_service_account(
                ctx.a3["id"], f.introduce_account_payload(deal_id, "2026-08-02"), seller_headers
            )
        )
        assert third["introduction_sequence_no"] == 3
        assert third["transfer_status"] == "INTRODUCED"

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert listing["introductions_completed_count"] == 3


class TestIntroductionSideEffectsAreImmediate:
    def test_the_write_response_already_carries_every_stamp_the_listing_reflects(self, api):
        """Three entities move in one call and the response body already shows the account's share of
        it; the listing's counter is incremented by the time the very next read arrives, so no lag
        window exists in which the two disagree.

        PRD §3.8: "A successful introduction sets the account's `transfer_status` to `INTRODUCED`,
        writes the `deal_id` onto the account, stores `introduced_on` as the supplied
        `introduction_date`, and assigns `introduction_sequence_no` as the listing's
        `introductions_completed_count` plus one ... The listing's `introductions_completed_count`
        then increments and its `version` increments by one."
        PRD §2.7: "Whenever a fact underneath them changes, the roll-up above them is recomputed from
        scratch over the current membership, the owning record's `updated_at` is refreshed, and its
        `version` increments by exactly 1."

        Design: Corner/consistency_model/introduction_side_effects_are_visible_in_the_write_response_itself
        """
        ctx = fx.escrow_funded_deal(api, introduce_accounts=False)
        deal_id = ctx.deal["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])

        before = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert before["introductions_completed_count"] == 0

        first = validate_success(
            api.introduce_service_account(
                ctx.a2["id"], f.introduce_account_payload(deal_id, "2026-08-01"), seller_headers
            )
        )
        assert first["transfer_status"] == "INTRODUCED"
        assert first["deal_id"] == deal_id
        assert first["introduced_on"] == "2026-08-01"
        assert first["introduction_sequence_no"] == 1

        after_first = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert after_first["introductions_completed_count"] == 1

        second = validate_success(
            api.introduce_service_account(
                ctx.a1["id"], f.introduce_account_payload(deal_id, "2026-08-01"), seller_headers
            )
        )
        assert second["introduction_sequence_no"] == 2

        after_second = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert after_second["introductions_completed_count"] == 2
        assert after_second["verified_account_count"] == 2

        reread = validate_success(api.get_service_account(ctx.a2["id"], BROKER))
        assert reread["introduction_sequence_no"] == 1
        assert reread["verification_status"] == "VERIFIED"


class TestTheTransferDimensionIsCheckedPerEndpoint:
    def test_one_status_rule_serves_two_endpoints_with_two_different_required_statuses(self, api):
        """The same stop is refused by introduce because it is no longer `PENDING` and by replace
        because it is not yet `LOST`, and on replace that status rule answers ahead of the
        has-not-closed rule; after closing, a `TRANSFERRED` stop is still not replaceable and no
        substitute row was ever created.

        PRD §3.8: "The account's `transfer_status` must be exactly `PENDING`, and anything else is
        `ERR_ACCOUNT_NOT_INTRODUCIBLE` — which means introducing the same customer twice is refused
        rather than silently ignored".
        PRD §3.9: "The account being replaced must have `transfer_status` of `LOST` and the deal must
        be `CLOSED`."
        PRD §2.9: "`ERR_ACCOUNT_NOT_INTRODUCIBLE` — the addressed account's transfer dimension is in
        the wrong state for an introduction or a replacement."

        Design: Corner/errors/introducing_an_introduced_account_and_replacing_a_live_one_rejected
        """
        ctx = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="escrow_funded")
        deal_id = ctx.deal["id"]
        account_id = ctx.account["id"]
        assert ctx.deal["status"] == "ESCROW_FUNDED"
        assert ctx.account["transfer_status"] == "INTRODUCED"
        assert ctx.account["introduced_on"] == "2026-08-01"

        substitute = f.replacement_account_payload(
            customer_ref="LV-WEST-SUBSTITUTE", route_day="TUE", monthly_service_fee_cents=20000
        )
        validate_error(
            api.introduce_service_account(
                account_id, f.introduce_account_payload(deal_id, "2026-08-01"), BROKER
            ),
            ApiErrorId.ERR_ACCOUNT_NOT_INTRODUCIBLE,
            409,
        )
        validate_error(
            api.replace_service_account(account_id, substitute, BROKER),
            ApiErrorId.ERR_ACCOUNT_NOT_INTRODUCIBLE,
            409,
        )

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"
        transferred = validate_success(api.get_service_account(account_id, BROKER))
        assert transferred["transfer_status"] == "TRANSFERRED"

        validate_error(
            api.replace_service_account(account_id, substitute, BROKER),
            ApiErrorId.ERR_ACCOUNT_NOT_INTRODUCIBLE,
            409,
        )

        accounts, meta = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": ctx.listing["id"]})
        )
        assert meta["total_count"] == 1
        assert accounts[0]["replaced_account_id"] is None


class TestTheAccountToDealJoinIsRecheckedOnEveryPath:
    def test_a_foreign_stop_is_refused_on_introduce_and_again_as_an_attrition_subject(self, api):
        """The foreign stop is a perfectly valid `PENDING` account of a `LISTED` listing owned by the
        same seller, and both the pre-close introduce path and the post-close attrition path refuse
        it on the join alone; the deal's own stop is accepted by the very same append.

        PRD §3.8: "The account's `listing_id` must equal the deal's `listing_id`, since a stop from a
        different route cannot be delivered under this deal; a mismatch is
        `ERR_ACCOUNT_LISTING_MISMATCH`."
        PRD §3.9: "The account must belong to the same listing as the deal, or the answer is
        `ERR_ACCOUNT_LISTING_MISMATCH`."
        PRD §2.9: "`ERR_ACCOUNT_LISTING_MISMATCH` — the account and the deal belong to different
        routes."

        Design: Corner/errors/introducing_or_attriting_an_account_from_another_listing_rejected
        """
        one = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="escrow_funded")
        other = fx.nv_deal_route(
            api,
            region_code="LV-EAST",
            stops=(fx.nv_stop("EAST-1", "MON", 20000),),
            stop_after="listed",
            profile=one.profile,
            seller=one.seller,
            buyer=one.buyer,
        )
        deal_id = one.deal["id"]
        foreign_id = other.account["id"]
        assert other.listing["status"] == "LISTED"

        validate_error(
            api.introduce_service_account(
                foreign_id, f.introduce_account_payload(deal_id, "2026-08-01"), BROKER
            ),
            ApiErrorId.ERR_ACCOUNT_LISTING_MISMATCH,
            422,
        )

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        closed = validate_success(api.close_deal(deal_id, BROKER))
        assert closed["status"] == "CLOSED"
        assert_cents(closed["guaranteed_mrr_cents"], 20000, "guaranteed mrr")

        validate_error(
            api.create_attrition_event(
                f.attrition_event_payload(
                    deal_id, foreign_id, "CANCELLED", "2026-09-15", -20000, "NATURAL",
                    fx.deal_version(api, deal_id),
                ),
                BROKER,
            ),
            ApiErrorId.ERR_ACCOUNT_LISTING_MISMATCH,
            422,
        )

        validate_success(
            api.create_attrition_event(
                f.attrition_event_payload(
                    deal_id, one.account["id"], "CANCELLED", "2026-09-15", -20000, "NATURAL",
                    fx.deal_version(api, deal_id),
                ),
                BROKER,
            ),
            201,
        )
        ledger = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(ledger["attrited_mrr_cents"], 20000, "attrited mrr")
        assert_cents(ledger["retained_mrr_cents"], 0, "retained mrr")
        assert_cents(ledger["net_attrition_mrr_cents"], 20000, "net attrition")
        assert_ratio_4dp(ledger["attrition_pct"], "1.0000", "attrition pct")
        assert ledger["clawback_status"] == "CLAWBACK_TRIGGERED"

        untouched = validate_success(api.get_service_account(foreign_id, BROKER))
        assert untouched["transfer_status"] == "PENDING"
        assert untouched["verification_status"] == "UNVERIFIED"


class TestThePermitGateOutranksTheIntroductionWindow:
    def test_an_outstanding_permit_answers_ahead_of_a_closed_window(self, api):
        """The clock sits five days past the end of the introduction window and neither permit has been
        filed, so two of the eight conditions are broken at once; both would answer 422, so only the
        `error_id` distinguishes them, and it is the permit answer. Clearing just the permits leaves the
        very same call refused by the window instead, which proves the window rule was live all along.

        PRD §3.8: "Every one of the deal's permit transfers must have cleared to `APPROVED` or
        `WAIVED`, and an outstanding permit is `ERR_LICENSE_NOT_TRANSFERRED`."
        PRD §3.8: "The logical clock must fall inside the introduction window, which is half-open and
        runs from midnight UTC of the deal's `accepted_on` date for forty-five days: the instant
        forty-five days after that midnight is already outside, and a clock at that instant is
        `ERR_INTRODUCTION_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/pair_b_safety_beats_temporal_on_introduce
        """
        ctx = fx.accepted_deal(api)
        deal_id = ctx["deal"]["id"]
        seller_headers = make_seller_headers(ctx["seller"]["id"])
        assert ctx["deal"]["accepted_on"] == "2026-08-01"
        assert ctx["pesticide_transfer"]["status"] == "NOT_STARTED"
        assert ctx["business_tax_transfer"]["status"] == "NOT_STARTED"
        assert ctx["a2"]["verification_status"] == "VERIFIED"
        assert ctx["a2"]["transfer_status"] == "PENDING"

        fx.set_clock(api, "2026-09-20T00:00:00Z")
        body = validate_error(
            api.introduce_service_account(
                ctx["a2"]["id"], f.introduce_account_payload(deal_id, "2026-09-20"), seller_headers
            ),
            ApiErrorId.ERR_LICENSE_NOT_TRANSFERRED,
            422,
        )
        assert body["error_id"] != ApiErrorId.ERR_INTRODUCTION_WINDOW_CLOSED.value, (
            "the permit condition must answer ahead of the window condition"
        )
        still_pending = validate_success(api.get_service_account(ctx["a2"]["id"], BROKER))
        assert still_pending["transfer_status"] == "PENDING"
        assert still_pending["introduction_sequence_no"] is None

        for transfer in (ctx["pesticide_transfer"], ctx["business_tax_transfer"]):
            cleared = fx.approve_permit(api, transfer["id"], ctx["buyer"], "2026-09-20")
            assert cleared["status"] == "APPROVED"

        validate_error(
            api.introduce_service_account(
                ctx["a2"]["id"], f.introduce_account_payload(deal_id, "2026-09-20"), seller_headers
            ),
            ApiErrorId.ERR_INTRODUCTION_WINDOW_CLOSED,
            422,
        )
        after = validate_success(api.get_service_account(ctx["a2"]["id"], BROKER))
        assert after["transfer_status"] == "PENDING"
        listing = validate_success(api.get_route_listing(ctx["listing"]["id"], BROKER))
        assert listing["introductions_completed_count"] == 0

    def test_with_the_permits_cleared_the_window_alone_decides_the_answer(self, api):
        """Both permits are `APPROVED` from the start, so the temporal condition is the only one left
        that can speak: one second before the forty-five-day mark the hand-over is recorded, and at the
        mark itself the next hand-over is refused.

        PRD §2.11: "Half-open `[start, end)` — the start instant or date is inside the window and the
        end is outside. This governs a listing's exclusive representation window, the post-acceptance
        introduction window, and a deal's retention guarantee window."
        PRD §3.8: "The logical clock must fall inside the introduction window, which is half-open and
        runs from midnight UTC of the deal's `accepted_on` date for forty-five days: the instant
        forty-five days after that midnight is already outside, and a clock at that instant is
        `ERR_INTRODUCTION_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/pair_b_safety_beats_temporal_on_introduce
        """
        ctx = fx.permits_approved_deal(api)
        deal_id = ctx["deal"]["id"]
        seller_headers = make_seller_headers(ctx["seller"]["id"])
        assert ctx["deal"]["accepted_on"] == "2026-08-01"

        fx.set_clock(api, "2026-09-14T23:59:59Z")
        inside = validate_success(
            api.introduce_service_account(
                ctx["a2"]["id"], f.introduce_account_payload(deal_id, "2026-09-14"), seller_headers
            )
        )
        assert inside["transfer_status"] == "INTRODUCED"
        assert inside["introduction_sequence_no"] == 1

        fx.set_clock(api, "2026-09-15T00:00:00Z")
        validate_error(
            api.introduce_service_account(
                ctx["a1"]["id"], f.introduce_account_payload(deal_id, "2026-09-15"), seller_headers
            ),
            ApiErrorId.ERR_INTRODUCTION_WINDOW_CLOSED,
            422,
        )
        blocked = validate_success(api.get_service_account(ctx["a1"]["id"], BROKER))
        assert blocked["transfer_status"] == "PENDING"
        assert blocked["deal_id"] is None
        listing = validate_success(api.get_route_listing(ctx["listing"]["id"], BROKER))
        assert listing["introductions_completed_count"] == 1
