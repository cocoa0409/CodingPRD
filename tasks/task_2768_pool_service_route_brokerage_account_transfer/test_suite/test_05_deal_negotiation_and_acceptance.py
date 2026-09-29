"""Offers, the haggling cycle and the acceptance fan-out (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_buyer_headers,
    make_seller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_deal,
    assert_fresh_escrow_zeroed,
    assert_fresh_license_transfer,
    assert_ratio_4dp,
)

BROKER = TEST_USERS["broker_headers"]


def one_stop_listed_route(api, region_code, monthly_service_fee_cents=20000, **buyer_overrides):
    """A published one-stop AZ route plus an approved buyer, ready to take offers."""
    ctx = fx.tier_route(api, region_code, monthly_service_fee_cents)
    ctx["listed_valuation"] = fx.create_valuation(api, ctx["listing"]["id"], "LISTED_BASIS")
    ctx["listing"] = fx.publish_listing(api, ctx["listing"]["id"])
    ctx["buyer"] = fx.qualified_buyer(api, **buyer_overrides)
    return ctx


class TestOfferSubmission:
    def test_a_fresh_offer_holds_nothing_acceptance_or_closing_would_write(self, api):
        """The initial state is asserted by absence as well as by status: round 1, the standing
        price equal to the submitted one, a not-applicable clawback flag, and every acceptance and
        closing field still empty.

        PRD §3.5: "An opened deal begins at `OFFER_SUBMITTED` with `offer_round` at 1,
        `current_offer_price_cents` equal to the submitted `offer_price_cents`, and
        `clawback_status` at `NOT_APPLICABLE`."
        PRD §3.5: "while `attrited_mrr_cents`, `replacement_mrr_cents` and
        `net_attrition_mrr_cents` sit at zero and `attrition_pct` sits at `0.0000`."
        PRD §3.5: "It creates exactly one `EscrowAccount` for the deal, in status `OPEN`".

        Design: Corner/state_machines/new_deal_starts_in_offer_submitted_initial_state
        """
        ctx = fx.listed_route(api)
        deal = validate_success(
            api.create_deal(
                f.deal_payload(ctx.listing["id"], ctx.buyer["id"]),
                make_buyer_headers(ctx.buyer["id"]),
            ),
            201,
        )
        assert_deal(deal)
        assert deal["status"] == "OFFER_SUBMITTED"
        assert deal["offer_round"] == 1
        assert_cents(deal["current_offer_price_cents"], 340000, "standing price")
        assert deal["clawback_status"] == "NOT_APPLICABLE"
        assert deal["version"] == 1

        for null_field in (
            "accepted_on", "non_solicitation_executed_on", "non_solicitation_end_date",
            "commission_cents", "holdback_cents", "escrow_target_amount_cents",
            "clawback_cap_cents", "closed_at_utc", "guarantee_start_utc", "guarantee_end_utc",
            "holdback_release_utc", "replacement_deadline_utc", "guaranteed_mrr_cents",
            "allowance_mrr_cents", "effective_multiple_at_close", "retained_mrr_cents",
            "lender_name", "approved_amount_cents", "repricing_reason_code",
            "termination_reason_code",
        ):
            assert deal[null_field] is None, f"{null_field} should be null on a fresh offer"

        assert_cents(deal["attrited_mrr_cents"], 0, "attrited mrr")
        assert_cents(deal["replacement_mrr_cents"], 0, "replacement mrr")
        assert_cents(deal["net_attrition_mrr_cents"], 0, "net attrition mrr")
        assert_ratio_4dp(deal["attrition_pct"], "0.0000", "attrition pct")

        escrows, meta = validate_paginated(
            api.list_escrow_accounts(BROKER, params={"deal_id": deal["id"]})
        )
        assert escrows == []
        assert meta["total_count"] == 0

    def test_the_prequalification_ceiling_is_inclusive_to_the_cent(self, api):
        """Against a buyer prequalified to exactly 180000 an offer of 180001 is refused and
        180000 lands, with the financing split kept exact in both bodies so the arithmetic rule
        cannot be what fires.

        PRD §3.5: "The price on the table may not exceed the buyer's `prequalified_amount_cents`;
        the comparison is inclusive, so an offer landing exactly on the prequalified amount is
        accepted, and one cent above it is `ERR_BUYER_PREQUAL_EXCEEDED`."

        Design: Corner/validations/offer_exactly_at_the_buyer_prequalification_ceiling_passes
        """
        ctx = one_stop_listed_route(
            api, "PHX-W", legal_name="Tight Budget Pools", prequalified_amount_cents=180000
        )
        buyer_headers = make_buyer_headers(ctx.buyer["id"])

        validate_error(
            api.create_deal(
                f.deal_payload(
                    ctx.listing["id"], ctx.buyer["id"], offer_price_cents=180001,
                    down_payment_cents=60001, note_principal_cents=120000,
                ),
                buyer_headers,
            ),
            ApiErrorId.ERR_BUYER_PREQUAL_EXCEEDED,
            422,
        )

        deal = validate_success(
            api.create_deal(
                f.deal_payload(
                    ctx.listing["id"], ctx.buyer["id"], offer_price_cents=180000,
                    down_payment_cents=60000, note_principal_cents=120000,
                ),
                buyer_headers,
            ),
            201,
        )
        assert_cents(deal["current_offer_price_cents"], 180000, "standing price")
        assert deal["offer_round"] == 1

        _, meta = validate_paginated(
            api.list_deals(BROKER, params={"listing_id": ctx.listing["id"]})
        )
        assert meta["total_count"] == 1

    def test_the_financing_split_must_partition_the_price_the_request_establishes(self, api):
        """One cent short and one cent long are both refused on the same offer, and the rule is
        re-checked on a re-offer against the new price rather than the old one.

        PRD §3.5: "the financing split must partition the price exactly: `down_payment_cents`
        plus `note_principal_cents` must equal the price the same request establishes, and a
        mismatch is `ERR_FINANCING_SPLIT_MISMATCH`."
        PRD §3.5: "The buyer may then re-offer downward from `COUNTERED`, supplying a fresh
        `offer_price_cents` together with a fresh `down_payment_cents` and `note_principal_cents`;
        that rewrites all three figures, increments `offer_round` by one, and returns the deal to
        `OFFER_SUBMITTED`."

        Design: Corner/validations/offer_whose_down_payment_and_note_do_not_sum_to_the_price_rejected
        """
        ctx = fx.listed_route(api)
        buyer_headers = make_buyer_headers(ctx.buyer["id"])
        seller_headers = make_seller_headers(ctx.seller["id"])

        for note in (219999, 220001):
            validate_error(
                api.create_deal(
                    f.deal_payload(
                        ctx.listing["id"], ctx.buyer["id"], offer_price_cents=340000,
                        down_payment_cents=120000, note_principal_cents=note,
                    ),
                    buyer_headers,
                ),
                ApiErrorId.ERR_FINANCING_SPLIT_MISMATCH,
                422,
            )

        deal = validate_success(
            api.create_deal(
                f.deal_payload(ctx.listing["id"], ctx.buyer["id"]), buyer_headers
            ),
            201,
        )
        assert_cents(deal["current_offer_price_cents"], 340000, "standing price")

        countered = validate_success(
            api.counter_offer_deal(deal["id"], f.counter_offer_payload(350000), seller_headers)
        )
        assert countered["status"] == "COUNTERED"
        assert countered["offer_round"] == 2

        validate_error(
            api.reoffer_deal(deal["id"], f.reoffer_payload(345000, 120000, 220000), buyer_headers),
            ApiErrorId.ERR_FINANCING_SPLIT_MISMATCH,
            422,
        )

        reoffered = validate_success(
            api.reoffer_deal(deal["id"], f.reoffer_payload(345000, 125000, 220000), buyer_headers)
        )
        assert reoffered["status"] == "OFFER_SUBMITTED"
        assert_cents(reoffered["current_offer_price_cents"], 345000, "standing price")
        assert reoffered["offer_round"] == 3

    def test_offers_need_a_listed_route_and_stops_need_one_that_is_not_under_contract(self, api):
        """The same listing-status rule cuts both ways: a DRAFT listing takes stops and valuations
        but refuses offers, and once acceptance has moved it to UNDER_CONTRACT the stop write that
        was legal in DRAFT is refused instead.

        PRD §3.5: "A deal may only be opened against a `LISTED` route; any other listing status
        answers `ERR_LISTING_NOT_LISTED`."
        PRD §3.2: "stops may only be added while the listing is in `DRAFT` or `LISTED` — an
        `UNDER_CONTRACT`, `CLOSED` or `WITHDRAWN` listing answers `ERR_LISTING_NOT_LISTED`."

        Design: Corner/validations/offer_on_a_draft_listing_rejected_then_accepted_once_published
        """
        ctx = fx.draft_route_with_three_stops(api)
        fx.create_valuation(api, ctx.listing["id"], "LISTED_BASIS")
        offer = f.deal_payload(ctx.listing["id"], ctx.buyer["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])

        validate_error(
            api.create_deal(offer, buyer_headers), ApiErrorId.ERR_LISTING_NOT_LISTED, 409
        )

        published = validate_success(api.publish_route_listing(ctx.listing["id"], BROKER))
        assert published["status"] == "LISTED"

        deal = validate_success(api.create_deal(offer, buyer_headers), 201)

        accepted = validate_success(
            api.accept_deal(
                deal["id"], f.accept_deal_payload(90), make_seller_headers(ctx.seller["id"])
            )
        )
        assert accepted["status"] == "ACCEPTED"
        under_contract = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert under_contract["status"] == "UNDER_CONTRACT"

        validate_error(
            api.create_service_account(
                f.service_account_payload(ctx.listing["id"], customer_ref="A4-LATE"), BROKER
            ),
            ApiErrorId.ERR_LISTING_NOT_LISTED,
            409,
        )

    def test_a_buyer_still_pending_qualification_cannot_bid(self, api):
        """Prequalification money and the brokerage's own verdict are independent gates: a
        LICENSED buyer prequalified far above the offer is refused until APPROVE is recorded.

        PRD §3.5: "The buyer must have `qualification_status` of `APPROVED`, or the answer is
        `ERR_BUYER_NOT_QUALIFIED`."
        PRD §3.1: "a `decision` of `APPROVE` moves `qualification_status` to `APPROVED` and stamps
        `qualified_on` with the logical clock's calendar date".

        Design: Corner/errors/offer_from_a_buyer_still_pending_qualification_rejected
        """
        ctx = fx.listed_route(api)
        pending = fx.seed_buyer(
            api, decision=None, legal_name="Sonora Route Partners",
            prequalified_amount_cents=30000000,
        )
        assert pending["qualification_status"] == "PENDING"
        offer = f.deal_payload(ctx.listing["id"], pending["id"])
        buyer_headers = make_buyer_headers(pending["id"])

        validate_error(
            api.create_deal(offer, buyer_headers), ApiErrorId.ERR_BUYER_NOT_QUALIFIED, 422
        )
        _, meta = validate_paginated(api.list_deals(BROKER))
        assert meta["total_count"] == 0

        qualified = validate_success(
            api.qualify_buyer(pending["id"], f.qualify_buyer_payload("APPROVE"), BROKER)
        )
        assert qualified["qualification_status"] == "APPROVED"
        assert qualified["qualified_on"] == "2026-08-01"

        deal = validate_success(api.create_deal(offer, buyer_headers), 201)
        assert deal["status"] == "OFFER_SUBMITTED"
        assert_cents(deal["current_offer_price_cents"], 340000, "standing price")


class TestAcceptanceGates:
    def test_the_seller_note_minimum_is_measured_to_the_cent_at_acceptance(self, api):
        """Two offers differing by a single cent of cash sit side by side in OFFER_SUBMITTED; the
        gate only fires on accept, and the acceptance that succeeds kills the other deal.

        PRD §3.5: "That minimum is a percentage of the standing `current_offer_price_cents`,
        rounded half up to whole cents, and the percentage is chosen by `financing_type`: ...
        a `SELLER_NOTE` deal must have thirty percent down ... A `down_payment_cents` at or above
        that figure passes; one cent below it is `ERR_DOWN_PAYMENT_INSUFFICIENT`."
        PRD §3.5: "Every *other* deal on that same listing sitting in `OFFER_SUBMITTED`,
        `COUNTERED` or `REPRICE_REQUIRED` is moved to `TERMINATED` with
        `termination_reason_code` set to `COMPETING_OFFER_ACCEPTED`".

        Design: Corner/validations/down_payment_exactly_at_the_seller_note_minimum_passes
        """
        ctx = one_stop_listed_route(api, "PHX-SE")
        buyer_headers = make_buyer_headers(ctx.buyer["id"])
        seller_headers = make_seller_headers(ctx.seller["id"])

        low = validate_success(
            api.create_deal(
                f.deal_payload(
                    ctx.listing["id"], ctx.buyer["id"], offer_price_cents=180000,
                    down_payment_cents=53999, note_principal_cents=126001,
                ),
                buyer_headers,
            ),
            201,
        )
        ok = validate_success(
            api.create_deal(
                f.deal_payload(
                    ctx.listing["id"], ctx.buyer["id"], offer_price_cents=180000,
                    down_payment_cents=54000, note_principal_cents=126000,
                ),
                buyer_headers,
            ),
            201,
        )
        assert low["status"] == "OFFER_SUBMITTED"
        assert ok["status"] == "OFFER_SUBMITTED"

        validate_error(
            api.accept_deal(low["id"], f.accept_deal_payload(90), seller_headers),
            ApiErrorId.ERR_DOWN_PAYMENT_INSUFFICIENT,
            422,
        )

        accepted = validate_success(
            api.accept_deal(ok["id"], f.accept_deal_payload(90), seller_headers)
        )
        assert accepted["status"] == "ACCEPTED"
        assert_cents(accepted["holdback_cents"], 27000, "holdback")
        assert_cents(accepted["escrow_target_amount_cents"], 81000, "escrow target")
        assert accepted["accepted_on"] == "2026-08-01"
        assert accepted["non_solicitation_executed_on"] == "2026-08-01"
        assert accepted["non_solicitation_end_date"] == "2026-10-30"

        killed = validate_success(api.get_deal(low["id"], BROKER))
        assert killed["status"] == "TERMINATED"
        assert killed["termination_reason_code"] == "COMPETING_OFFER_ACCEPTED"

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert listing["status"] == "UNDER_CONTRACT"

    def test_the_covenant_floor_and_the_field_range_answer_with_different_codes(self, api):
        """A guarantee of 45 days is a legal deal and an illegal acceptance; 59 is refused by the
        covenant rule, 366 by the field range, and only the one acceptance that passes mints an
        escrow.

        PRD §3.5: "Although a deal may be *opened* with a guarantee as short as thirty days,
        acceptance holds the seller to a longer floor: `retention_guarantee_days` must be at least
        60 and at most 365 at acceptance, so fifty-nine days is refused with
        `ERR_COVENANT_TERMS_INSUFFICIENT`, exactly sixty passes, exactly three hundred and
        sixty-five passes, and three hundred and sixty-six is refused."
        PRD §3.5: "`non_solicitation_end_date` is that date advanced by
        `retention_guarantee_days` calendar days".

        Design: Corner/errors/acceptance_with_a_retention_guarantee_under_sixty_days_rejected
        """
        ctx = fx.listed_route(api)
        deal = validate_success(
            api.create_deal(
                f.deal_payload(ctx.listing["id"], ctx.buyer["id"], retention_guarantee_days=45),
                make_buyer_headers(ctx.buyer["id"]),
            ),
            201,
        )
        assert deal["retention_guarantee_days"] == 45
        seller_headers = make_seller_headers(ctx.seller["id"])

        for short_days in (45, 59):
            validate_error(
                api.accept_deal(deal["id"], f.accept_deal_payload(short_days), seller_headers),
                ApiErrorId.ERR_COVENANT_TERMS_INSUFFICIENT,
                422,
            )
        validate_error(
            api.accept_deal(deal["id"], f.accept_deal_payload(366), seller_headers),
            ApiErrorId.ERR_VALIDATION,
            400,
        )

        accepted = validate_success(
            api.accept_deal(deal["id"], f.accept_deal_payload(60), seller_headers)
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["retention_guarantee_days"] == 60
        assert accepted["accepted_on"] == "2026-08-01"
        assert accepted["non_solicitation_executed_on"] == "2026-08-01"
        assert accepted["non_solicitation_end_date"] == "2026-09-30"

        escrows, meta = validate_paginated(
            api.list_escrow_accounts(BROKER, params={"deal_id": deal["id"]})
        )
        assert meta["total_count"] == 1
        assert_cents(escrows[0]["target_amount_cents"], 171000, "escrow target")

    def test_acceptance_instantiates_one_escrow_and_only_the_required_permits(self, api):
        """The fan-out is sized by the state profile, not by the permit enum: CONTRACTOR is a legal
        permit type that the AZ regime does not require, so no row exists for it.

        PRD §3.5: "It creates exactly one `EscrowAccount` for the deal, in status `OPEN`, with its
        `target_amount_cents` copied from the deal's `escrow_target_amount_cents`, its
        `holdback_amount_cents` copied from the deal's `holdback_cents`, and every cash counter ...
        at zero".
        PRD §3.5: "one `LicenseTransfer` in status `NOT_STARTED` is created for each entry of the
        `required_permit_types` list belonging to the `StateLicenseProfile` whose `state_code`
        matches the listing's `state_code`. Each carries the `deal_id`, the `state_profile_id` of
        that profile, and the `permit_type` it covers, with `attempt_count` at zero".
        PRD §3.5: "`commission_cents` ... `clawback_cap_cents`, `guaranteed_mrr_cents`,
        `retained_mrr_cents`, `allowance_mrr_cents` ... are all null at that point" — closing, not
        acceptance, is what fills them in.

        Design: Corner/endpoints/accepting_a_deal_links_one_escrow_and_one_transfer_per_required_permit
        """
        ctx = fx.accepted_deal(api)
        deal_id = ctx.deal["id"]

        escrows, escrow_meta = validate_paginated(
            api.list_escrow_accounts(BROKER, params={"deal_id": deal_id})
        )
        assert escrow_meta["total_count"] == 1
        escrow = escrows[0]
        assert_fresh_escrow_zeroed(escrow)
        assert_cents(escrow["target_amount_cents"], 171000, "escrow target")
        assert_cents(escrow["holdback_amount_cents"], 51000, "escrow holdback")

        transfers, transfer_meta = validate_paginated(
            api.list_license_transfers(BROKER, params={"deal_id": deal_id})
        )
        assert transfer_meta["total_count"] == 2
        assert sorted(t["permit_type"] for t in transfers) == ["BUSINESS_TAX", "PESTICIDE_APPLICATOR"]
        for transfer in transfers:
            assert_fresh_license_transfer(transfer)
            assert transfer["attempt_count"] == 0
            assert transfer["applied_on"] is None
            assert transfer["state_profile_id"] == ctx.profile["id"]
            assert transfer["deal_id"] == deal_id

        contractor, contractor_meta = validate_paginated(
            api.list_license_transfers(
                BROKER, params={"deal_id": deal_id, "permit_type": "CONTRACTOR"}
            )
        )
        assert contractor == []
        assert contractor_meta["total_count"] == 0

        deal = validate_success(api.get_deal(deal_id, BROKER))
        assert_cents(deal["escrow_target_amount_cents"], 171000, "deal escrow target")
        assert_cents(deal["holdback_cents"], 51000, "deal holdback")
        assert deal["accepted_on"] == "2026-08-01"
        assert deal["non_solicitation_end_date"] == "2026-10-30"
        for closing_only in (
            "commission_cents", "clawback_cap_cents", "guaranteed_mrr_cents",
            "allowance_mrr_cents", "retained_mrr_cents", "effective_multiple_at_close",
            "closed_at_utc",
        ):
            assert deal[closing_only] is None, f"{closing_only} is written at closing, not acceptance"


class TestAbandonmentAndAbsorbingStatuses:
    def test_a_terminated_deal_refuses_every_entry_point_with_one_code(self, api):
        """Four different transitions all answer `ERR_DEAL_TERMINAL` rather than the generic
        invalid-transition code, and the second termination attempt does not overwrite the stored
        reason or re-release the listing.

        PRD §3.5: "Any of the brokerage, the owning seller or the owning buyer may terminate a deal
        from any live status, supplying a `termination_reason_code` which is stored on the deal;
        `CLOSED`, `GUARANTEE_CLOSED` and `TERMINATED` deals refuse it with `ERR_DEAL_TERMINAL`."

        Design: Corner/state_machines/terminated_deal_refuses_every_further_transition_terminal_lockdown
        """
        ctx = fx.accepted_deal(api)
        deal_id = ctx.deal["id"]
        buyer_headers = make_buyer_headers(ctx.buyer["id"])
        seller_headers = make_seller_headers(ctx.seller["id"])

        terminated = validate_success(
            api.terminate_deal(deal_id, f.terminate_deal_payload(), BROKER)
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason_code"] == "BUYER_WITHDREW"

        validate_error(
            api.terminate_deal(
                deal_id,
                f.terminate_deal_payload(termination_reason_code="SELLER_CHANGED_MIND"),
                BROKER,
            ),
            ApiErrorId.ERR_DEAL_TERMINAL,
            409,
        )
        validate_error(
            api.accept_deal(deal_id, f.accept_deal_payload(90), seller_headers),
            ApiErrorId.ERR_DEAL_TERMINAL,
            409,
        )
        validate_error(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(350000), seller_headers),
            ApiErrorId.ERR_DEAL_TERMINAL,
            409,
        )
        validate_error(
            api.reoffer_deal(deal_id, f.reoffer_payload(330000, 110000, 220000), buyer_headers),
            ApiErrorId.ERR_DEAL_TERMINAL,
            409,
        )

        deal = validate_success(api.get_deal(deal_id, BROKER))
        assert deal["status"] == "TERMINATED"
        assert deal["termination_reason_code"] == "BUYER_WITHDREW"
        assert_cents(deal["current_offer_price_cents"], 340000, "standing price")
        assert deal["offer_round"] == 1

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert listing["status"] == "LISTED"

    def test_withdrawal_sweeps_the_live_negotiations_and_leaves_the_dead_ones_alone(self, api):
        """The already-terminated deal keeps its own reason code, the live one is stamped
        `LISTING_WITHDRAWN`, and the customer stop is untouched by the listing's death.

        PRD §3.2: "every deal on that listing sitting in `OFFER_SUBMITTED`, `COUNTERED` or
        `REPRICE_REQUIRED` is moved to `TERMINATED` with its `termination_reason_code` set to
        `LISTING_WITHDRAWN`, while deals already in an absorbing status are left exactly as
        they are."

        Design: Corner/state_machines/withdraw_listing_terminates_only_the_non_terminal_deals
        """
        ctx = one_stop_listed_route(api, "PHX-SW")
        second_buyer = fx.qualified_buyer(api, legal_name="Copper State Route Group")
        listing_id = ctx.listing["id"]

        live = validate_success(
            api.create_deal(
                f.deal_payload(
                    listing_id, ctx.buyer["id"], offer_price_cents=180000,
                    down_payment_cents=60000, note_principal_cents=120000,
                ),
                make_buyer_headers(ctx.buyer["id"]),
            ),
            201,
        )
        dead = validate_success(
            api.create_deal(
                f.deal_payload(
                    listing_id, second_buyer["id"], offer_price_cents=180000,
                    down_payment_cents=60000, note_principal_cents=120000,
                ),
                make_buyer_headers(second_buyer["id"]),
            ),
            201,
        )
        validate_success(api.terminate_deal(dead["id"], f.terminate_deal_payload(), BROKER))

        withdrawn = validate_success(
            api.withdraw_route_listing(
                listing_id,
                f.withdraw_listing_payload(withdrawal_reason_code="SELLER_RETIRED"),
                make_seller_headers(ctx.seller["id"]),
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason_code"] == "SELLER_RETIRED"

        swept = validate_success(api.get_deal(live["id"], BROKER))
        assert swept["status"] == "TERMINATED"
        assert swept["termination_reason_code"] == "LISTING_WITHDRAWN"

        untouched = validate_success(api.get_deal(dead["id"], BROKER))
        assert untouched["status"] == "TERMINATED"
        assert untouched["termination_reason_code"] == "BUYER_WITHDREW"

        account = validate_success(api.get_service_account(ctx.account["id"], BROKER))
        assert account["verification_status"] == "UNVERIFIED"
        assert account["transfer_status"] == "PENDING"


class TestTheHagglingCycleIsATrueTwoCycle:
    def test_the_deal_returns_to_the_status_it_started_in_with_only_the_round_advancing(self, api):
        """A seller counter and a buyer re-offer bring the deal back to `OFFER_SUBMITTED`, so the status
        is no witness of progress at all; `offer_round` is the only monotone quantity, moving 1 to 2 to
        3, and the re-offer rewrote all three money figures at once.

        PRD §3.5: "The owning seller may counter upward from `OFFER_SUBMITTED`, supplying a
        `counter_price_cents`; the counter rewrites `current_offer_price_cents`, increments `offer_round`
        by one, moves the deal to `COUNTERED`, and increments the deal's `version` by one. The buyer may
        then re-offer downward from `COUNTERED`, supplying a fresh `offer_price_cents` together with a
        fresh `down_payment_cents` and `note_principal_cents`; that rewrites all three figures,
        increments `offer_round` by one, and returns the deal to `OFFER_SUBMITTED`."
        PRD §3.5: "The cycle `OFFER_SUBMITTED → COUNTERED → OFFER_SUBMITTED` is unbounded in rounds".

        Design: Difficulty/non_linear_state_machine/deal_offer_countered_offer_negotiation_cycle
        """
        ctx = fx.offer_submitted_deal(api)
        deal_id = ctx.deal["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])
        assert ctx.deal["status"] == "OFFER_SUBMITTED"
        assert ctx.deal["offer_round"] == 1
        assert_cents(ctx.deal["current_offer_price_cents"], 340000, "standing price")

        countered = validate_success(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(360000), seller_headers)
        )
        assert_deal(countered)
        assert countered["status"] == "COUNTERED"
        assert_cents(countered["current_offer_price_cents"], 360000, "standing price")
        assert countered["offer_round"] == 2

        reoffered = validate_success(
            api.reoffer_deal(deal_id, f.reoffer_payload(350000, 130000, 220000), buyer_headers)
        )
        assert reoffered["status"] == "OFFER_SUBMITTED"
        assert_cents(reoffered["current_offer_price_cents"], 350000, "standing price")
        assert_cents(reoffered["down_payment_cents"], 130000, "down payment")
        assert_cents(reoffered["note_principal_cents"], 220000, "note principal")
        assert reoffered["offer_round"] == 3

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert listing["status"] == "LISTED"

    def test_re_entry_is_gated_so_the_cycle_cannot_spin_on_the_standing_price(self, api):
        """Having come back to `OFFER_SUBMITTED` at 350000, the seller repeats that exact price: the
        counter is refused and leaves no trace on the status, the round or the standing price, and a
        counter that genuinely moves upward is accepted immediately afterwards.

        PRD §3.5: "what stops it spinning forever is that each side must actually move: a seller's
        counter must be strictly greater than the standing `current_offer_price_cents`, and a buyer's
        re-offer from `COUNTERED` must be strictly less than it. Repeating the standing price, or moving
        it the wrong way, is `ERR_COUNTER_NOT_IMPROVED`."
        PRD §2.9: "`ERR_COUNTER_NOT_IMPROVED` — a counter or re-offer does not move the price in the
        required direction."

        Design: Difficulty/non_linear_state_machine/deal_offer_countered_offer_negotiation_cycle
        """
        ctx = fx.offer_submitted_deal(api)
        deal_id = ctx.deal["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])

        validate_success(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(360000), seller_headers)
        )
        validate_success(
            api.reoffer_deal(deal_id, f.reoffer_payload(350000, 130000, 220000), buyer_headers)
        )

        validate_error(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(350000), seller_headers),
            ApiErrorId.ERR_COUNTER_NOT_IMPROVED,
            422,
        )
        untouched = validate_success(api.get_deal(deal_id, BROKER))
        assert untouched["status"] == "OFFER_SUBMITTED"
        assert untouched["offer_round"] == 3
        assert_cents(untouched["current_offer_price_cents"], 350000, "standing price")

        validate_error(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(349999), seller_headers),
            ApiErrorId.ERR_COUNTER_NOT_IMPROVED,
            422,
        )
        still_untouched = validate_success(api.get_deal(deal_id, BROKER))
        assert still_untouched["offer_round"] == 3
        assert_cents(still_untouched["current_offer_price_cents"], 350000, "standing price")

        moved = validate_success(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(350001), seller_headers)
        )
        assert moved["status"] == "COUNTERED"
        assert_cents(moved["current_offer_price_cents"], 350001, "standing price")
        assert moved["offer_round"] == 4

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert listing["status"] == "LISTED"
