"""Diligence sign-off, exclusions and the repricing cascade (PRD §3.6)."""
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
from test_helpers.assertions import assert_cents, assert_multiple_1dp

BROKER = TEST_USERS["broker_headers"]
DILIGENCE_BROKER = TEST_USERS["broker_diligence_headers"]


class TestSignOffRequiresAnAcceptedDeal:
    def test_progression_endpoints_refuse_an_offer_that_has_not_been_accepted(self, api):
        """A perfectly good verified-basis valuation is supplied and still both progression
        endpoints answer with the transition error, so the transition check runs before any
        valuation reasoning; the identical body succeeds the moment the seller accepts.

        PRD §3.6: "The broker names a `valuation_id` and the deal moves from `ACCEPTED` to
        `DILIGENCE_CLEARED`."
        PRD §2.9: "`ERR_INVALID_DEAL_TRANSITION` — the requested deal transition is not declared
        for the deal's current status."

        Design: Corner/state_machines/clear_diligence_on_an_offer_submitted_deal_invalid_transition_rejected
        """
        ctx = fx.verified_route_with_deal(api)
        deal_id = ctx.deal["id"]
        signoff = f.clear_diligence_payload(ctx.verified_valuation["id"])
        assert ctx.verified_valuation["is_superseded"] is False
        assert_cents(ctx.verified_valuation["valuation_cents"], 343725, "verified valuation")

        validate_error(
            api.clear_diligence(deal_id, signoff, DILIGENCE_BROKER),
            ApiErrorId.ERR_INVALID_DEAL_TRANSITION,
            409,
        )
        validate_error(
            api.approve_financing(deal_id, f.approve_financing_payload(220000), BROKER),
            ApiErrorId.ERR_INVALID_DEAL_TRANSITION,
            409,
        )

        accepted = validate_success(
            api.accept_deal(
                deal_id, f.accept_deal_payload(90), make_seller_headers(ctx.seller["id"])
            )
        )
        assert accepted["status"] == "ACCEPTED"

        cleared = validate_success(api.clear_diligence(deal_id, signoff, DILIGENCE_BROKER))
        assert cleared["status"] == "DILIGENCE_CLEARED"


class TestSignOffSelectsTheVerifiedVariant:
    def test_the_live_listed_basis_snapshot_is_refused_and_only_the_verified_one_clears(self, api):
        """Both snapshots are live, belong to this listing and were computed at the same instant;
        the basis alone decides, and the two bases disagree on membership, on the multiple and on
        the total.

        PRD §3.6: "The named valuation must belong to the deal's own listing, must have `basis` of
        `VERIFIED_BASIS`, and must not be superseded".
        PRD §2.9: "`ERR_VALUATION_SUPERSEDED` — the named valuation is not a live verified-basis
        snapshot of the deal's listing."
        PRD §3.4: "`VERIFIED_BASIS` ... input set is only those stops that are `VERIFIED`, each
        contributing its `verified_recurring_mrr_cents` and its `verified_repair_mrr_cents`."

        Design: Corner/calculations/clear_diligence_refuses_a_listed_basis_valuation_variant
        """
        ctx = fx.verified_route_with_deal(api)
        listed = fx.create_valuation(api, ctx.listing["id"], "LISTED_BASIS")
        assert_cents(listed["valuation_cents"], 351500, "post-exclusion listed valuation")
        assert listed["is_superseded"] is False
        ctx["deal"] = fx.accept_deal(api, ctx.deal["id"], ctx.seller, 90)

        validate_error(
            api.clear_diligence(
                ctx.deal["id"], f.clear_diligence_payload(listed["id"]), DILIGENCE_BROKER
            ),
            ApiErrorId.ERR_VALUATION_SUPERSEDED,
            409,
        )

        verified = validate_success(
            api.get_route_valuation(ctx.verified_valuation["id"], BROKER)
        )
        assert verified["basis"] == "VERIFIED_BASIS"
        assert verified["is_superseded"] is False
        assert_cents(verified["recurring_mrr_cents"], 30318, "verified recurring")
        assert verified["account_count"] == 2
        assert_multiple_1dp(verified["effective_multiple"], "11.0", "verified multiple")
        assert_cents(verified["valuation_cents"], 343725, "verified valuation")

        cleared = validate_success(
            api.clear_diligence(
                ctx.deal["id"], f.clear_diligence_payload(verified["id"]), DILIGENCE_BROKER
            )
        )
        assert cleared["status"] == "DILIGENCE_CLEARED"

    def test_only_the_latest_of_two_identical_verified_snapshots_is_signable(self, api):
        """Two back-to-back verified-basis snapshots hold byte-identical money, so nothing but the
        supersession flag can explain the opposite verdicts.

        PRD §3.4: "Creating a snapshot marks every earlier snapshot of the *same* listing and the
        *same* basis as superseded by setting its `is_superseded` to true".
        PRD §3.6: "signing off against a snapshot whose `is_superseded` is true is
        `ERR_VALUATION_SUPERSEDED`".

        Design: Corner/errors/clear_diligence_with_a_superseded_valuation_snapshot_rejected
        """
        ctx = fx.verified_route_with_deal(api)
        old_id = ctx.verified_valuation["id"]
        new_valuation = fx.create_valuation(api, ctx.listing["id"], "VERIFIED_BASIS")
        ctx["deal"] = fx.accept_deal(api, ctx.deal["id"], ctx.seller, 90)

        validate_error(
            api.clear_diligence(
                ctx.deal["id"], f.clear_diligence_payload(old_id), DILIGENCE_BROKER
            ),
            ApiErrorId.ERR_VALUATION_SUPERSEDED,
            409,
        )

        old = validate_success(api.get_route_valuation(old_id, BROKER))
        assert old["is_superseded"] is True
        assert old["basis"] == "VERIFIED_BASIS"
        assert_cents(old["valuation_cents"], 343725, "superseded valuation")

        current = validate_success(api.get_route_valuation(new_valuation["id"], BROKER))
        assert current["is_superseded"] is False
        assert_cents(current["valuation_cents"], 343725, "current valuation")

        cleared = validate_success(
            api.clear_diligence(
                ctx.deal["id"], f.clear_diligence_payload(current["id"]), DILIGENCE_BROKER
            )
        )
        assert cleared["status"] == "DILIGENCE_CLEARED"
        assert validate_success(api.get_deal(ctx.deal["id"], BROKER))["status"] == "DILIGENCE_CLEARED"


class TestSignOffRequiresAFreshSnapshot:
    def test_a_snapshot_taken_before_the_offer_existed_cannot_certify_it(self, api):
        """The only verified-basis snapshot on the route is live, correct and unsuperseded, and is
        still refused because it predates the deal; a numerically identical snapshot taken after a
        fresh offer clears immediately.

        PRD §3.6: "the absence of any eligible verified-basis snapshot, or one that predates the
        deal's own `created_at` and so was computed before this buyer was in the picture, is
        `ERR_VERIFIED_VALUATION_MISSING`."

        Design: Corner/errors/clear_diligence_without_a_valuation_computed_after_the_offer_rejected
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.seed_nv_profile(api)
        seller = fx.seed_seller(api)
        buyer = fx.seed_buyer(api, prequalified_amount_cents=30000000)
        listing = fx.seed_listing(
            api, seller["id"], region_code="LV-NORTH", state_code="NV",
            asking_price_cents=200000, listed_mrr_cents=20000, listed_account_count=1,
        )
        stop = fx.nv_stop("LV1-SUMMERLIN", "TUE", 20000)
        account = fx.add_account(api, listing["id"], **stop)
        fx.add_billing_months(
            api, account["id"], billed_service_cents=20000, billed_chemical_cents=0,
            billed_repair_cents=0, collected_cents=20000,
        )
        fx.verify_account(api, account["id"])
        early = fx.create_valuation(api, listing["id"], "VERIFIED_BASIS")
        fx.create_valuation(api, listing["id"], "LISTED_BASIS")
        fx.publish_listing(api, listing["id"])

        offer = f.deal_payload(
            listing["id"], buyer["id"], offer_price_cents=180000,
            down_payment_cents=60000, note_principal_cents=120000,
        )
        buyer_headers = make_buyer_headers(buyer["id"])
        seller_headers = make_seller_headers(seller["id"])
        first = validate_success(api.create_deal(offer, buyer_headers), 201)
        fx.accept_deal(api, first["id"], seller, 90)

        validate_error(
            api.clear_diligence(
                first["id"], f.clear_diligence_payload(early["id"]), DILIGENCE_BROKER
            ),
            ApiErrorId.ERR_VERIFIED_VALUATION_MISSING,
            422,
        )
        stale = validate_success(api.get_route_valuation(early["id"], BROKER))
        assert stale["is_superseded"] is False
        assert stale["basis"] == "VERIFIED_BASIS"
        assert_cents(stale["recurring_mrr_cents"], 20000, "verified recurring")
        assert_cents(stale["valuation_cents"], 200000, "pre-offer valuation")

        validate_success(api.terminate_deal(first["id"], f.terminate_deal_payload(), BROKER))
        assert validate_success(api.get_route_listing(listing["id"], BROKER))["status"] == "LISTED"

        second = validate_success(api.create_deal(offer, buyer_headers), 201)
        fresh = validate_success(
            api.create_route_valuation(
                listing["id"],
                f.route_valuation_payload("VERIFIED_BASIS", fx.listing_version(api, listing["id"])),
                BROKER,
            ),
            201,
        )
        assert_cents(fresh["valuation_cents"], 200000, "post-offer valuation")
        assert fresh["is_superseded"] is False

        accepted = validate_success(
            api.accept_deal(second["id"], f.accept_deal_payload(90), seller_headers)
        )
        assert accepted["status"] == "ACCEPTED"
        cleared = validate_success(
            api.clear_diligence(
                second["id"], f.clear_diligence_payload(fresh["id"]), DILIGENCE_BROKER
            )
        )
        assert cleared["status"] == "DILIGENCE_CLEARED"


class TestSignOffMeasuresTheAdvertisedClaim:
    def test_the_seventy_percent_floor_moves_with_the_listed_figure_not_the_verified_one(self, api):
        """The verified base is 30318 cents in both halves of the test; only the seller's own
        advertised figure changes, and that alone flips the verdict.

        PRD §3.6: "`verified_recurring_mrr_cents` must be at least seventy percent of the listing's
        `listed_mrr_cents`, that threshold being seventy percent of the listed figure rounded half
        up to whole cents, and a shortfall is `ERR_VERIFIED_MRR_SHORTFALL`. Note that the
        seventy-percent floor is measured against the *listed* asking figure the seller advertised,
        not against the claimed roll-up of the stops."

        Design: Corner/validations/diligence_blocked_until_the_listed_mrr_claim_is_substantiated
        """
        inflated = fx.draft_route_with_three_stops(api, listed_mrr_cents=60000)
        ctx = fx.accepted_deal(
            api,
            fx.verified_route_with_deal(
                api, fx.offer_submitted_deal(api, fx.listed_route(api, fx.route_with_billing_history(api, inflated)))
            ),
        )
        listing_id = ctx.listing["id"]
        signoff = f.clear_diligence_payload(ctx.verified_valuation["id"])

        validate_error(
            api.clear_diligence(ctx.deal["id"], signoff, DILIGENCE_BROKER),
            ApiErrorId.ERR_VERIFIED_MRR_SHORTFALL,
            422,
        )

        validate_success(api.terminate_deal(ctx.deal["id"], f.terminate_deal_payload(), BROKER))
        assert validate_success(api.get_route_listing(listing_id, BROKER))["status"] == "LISTED"

        repriced = validate_success(
            api.update_route_listing(listing_id, {"listed_mrr_cents": 43000}, BROKER)
        )
        assert_cents(repriced["listed_mrr_cents"], 43000, "listed mrr")
        assert_cents(repriced["verified_recurring_mrr_cents"], 30318, "verified recurring")
        assert_cents(repriced["claimed_recurring_mrr_cents"], 31000, "claimed recurring")

        deal = validate_success(
            api.create_deal(
                f.deal_payload(listing_id, ctx.buyer["id"]), make_buyer_headers(ctx.buyer["id"])
            ),
            201,
        )
        valuation = validate_success(
            api.create_route_valuation(
                listing_id,
                f.route_valuation_payload("VERIFIED_BASIS", fx.listing_version(api, listing_id)),
                BROKER,
            ),
            201,
        )
        assert_cents(valuation["valuation_cents"], 343725, "verified valuation")
        assert valuation["is_superseded"] is False

        accepted = validate_success(
            api.accept_deal(
                deal["id"], f.accept_deal_payload(90), make_seller_headers(ctx.seller["id"])
            )
        )
        assert accepted["status"] == "ACCEPTED"
        cleared = validate_success(
            api.clear_diligence(
                deal["id"], f.clear_diligence_payload(valuation["id"]), DILIGENCE_BROKER
            )
        )
        assert cleared["status"] == "DILIGENCE_CLEARED"


class TestRepriceRequiredIsStructurallyMasked:
    def test_a_repriced_deal_never_reports_the_reprice_error_and_only_a_new_offer_frees_it(self, api):
        """Excluding the second verified stop drives the deal into `REPRICE_REQUIRED`, and from
        there every progression endpoint answers with the error its own earlier check raises — the
        transition error on three of them and the funding error on close — so the reprice code is
        unreachable. The buyer's fresh offer is the only exit.

        PRD §3.6: "The fourth hop is the deal: every deal on that listing sitting in `ACCEPTED` or
        `DILIGENCE_CLEARED` whose price no longer stands up against the new valuation is moved to
        `REPRICE_REQUIRED`, its `repricing_reason_code` is set to `VERIFIED_VALUATION_BELOW_OFFER`".
        PRD §3.6: "The threshold is ninety percent of the deal's standing
        `current_offer_price_cents`, rounded half up to whole cents. The deal is repriced when the
        freshly computed verified-basis `valuation_cents` is **strictly less than** that threshold".
        PRD §3.8: "The brokerage closes a deal from `ESCROW_FUNDED`; a deal in any earlier status is
        `ERR_DEAL_NOT_FUNDED`."
        PRD §3.5: "it is the only way a deal escapes `REPRICE_REQUIRED` ... That edge also clears
        `repricing_reason_code` back to null".

        Design: Corner/errors/reprice_required_deal_answers_with_the_lower_priority_error_everywhere
        """
        ctx = fx.accepted_deal(api)
        deal_id = ctx.deal["id"]
        fx.exclude_account(api, ctx.a2["id"])

        live, _ = validate_paginated(
            api.list_route_valuations(
                BROKER,
                params={
                    "listing_id": ctx.listing["id"],
                    "basis": "VERIFIED_BASIS",
                    "is_superseded": "false",
                },
            )
        )
        assert len(live) == 1
        assert_cents(live[0]["valuation_cents"], 164500, "re-valued verified basis")

        repriced = validate_success(api.get_deal(deal_id, BROKER))
        assert repriced["status"] == "REPRICE_REQUIRED"
        assert repriced["repricing_reason_code"] is not None

        seller_headers = make_seller_headers(ctx.seller["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])

        validate_error(
            api.clear_diligence(
                deal_id, f.clear_diligence_payload(live[0]["id"]), DILIGENCE_BROKER
            ),
            ApiErrorId.ERR_INVALID_DEAL_TRANSITION,
            409,
        )
        validate_error(
            api.approve_financing(deal_id, f.approve_financing_payload(220000), BROKER),
            ApiErrorId.ERR_INVALID_DEAL_TRANSITION,
            409,
        )
        validate_error(
            api.close_deal(deal_id, BROKER), ApiErrorId.ERR_DEAL_NOT_FUNDED, 409
        )
        validate_error(
            api.accept_deal(deal_id, f.accept_deal_payload(90), seller_headers),
            ApiErrorId.ERR_INVALID_DEAL_TRANSITION,
            409,
        )

        reoffered = validate_success(
            api.reoffer_deal(deal_id, f.reoffer_payload(180000, 60000, 120000), buyer_headers)
        )
        assert reoffered["status"] == "OFFER_SUBMITTED"
        assert_cents(reoffered["current_offer_price_cents"], 180000, "standing price")
        assert reoffered["offer_round"] == 2
        assert reoffered["repricing_reason_code"] is None


class TestExcludingAVerifiedStopRunsFiveHopsDeep:
    def test_the_first_three_hops_reach_the_account_the_listing_and_a_new_snapshot(self, api):
        """One exclude call rewrites the stop, recomputes both dimensions of the listing, retires the
        live verified-basis snapshot and computes a replacement over the shrunken route — whose smaller
        base drops a whole tier while the older survivor keeps its age premium; the stop that was left
        alone is not disturbed.

        PRD §3.6: "The first hop is the account itself: `verification_status` becomes `EXCLUDED` and
        the `exclusion_reason_code` is recorded. The second hop is the listing:
        `verified_recurring_mrr_cents`, `verified_repair_mrr_cents`, `verified_account_count`,
        `claimed_recurring_mrr_cents`, `claimed_repair_mrr_cents`, `claimed_account_count` and
        `verification_posture` are all recomputed over the surviving stops, and the listing's `version`
        increments. The third hop is the valuation: if the listing has a non-superseded `VERIFIED_BASIS`
        valuation, that snapshot's `is_superseded` is set to true and a brand-new `VERIFIED_BASIS`
        valuation is computed over the reduced verified set exactly as §3.4 prescribes"
        PRD §3.2: "It reaches `COMPLETE` only when every stop of the listing is either `VERIFIED` or
        `EXCLUDED` **and** `verified_account_count` is at least one."
        PRD §3.4: "A route billing less than three hundred dollars a month in recurring revenue is
        valued at nine times that monthly figure."

        Design: Difficulty/transitive_cascade/exclude_verified_account_five_hop_reprice_cascade
        """
        ctx = fx.accepted_deal(api)
        listing_id = ctx.listing["id"]
        original = validate_success(api.get_route_valuation(ctx.verified_valuation["id"], BROKER))
        assert original["is_superseded"] is False
        assert_cents(original["valuation_cents"], 343725, "pre-exclusion verified valuation")

        excluded = fx.exclude_account(
            api, ctx.a2["id"], exclusion_reason_code="SELLER_WITHDREW_STOP"
        )
        assert excluded["verification_status"] == "EXCLUDED"
        assert excluded["exclusion_reason_code"] == "SELLER_WITHDREW_STOP"

        listing = validate_success(api.get_route_listing(listing_id, BROKER))
        assert_cents(listing["verified_recurring_mrr_cents"], 16000, "verified recurring")
        assert_cents(listing["verified_repair_mrr_cents"], 1500, "verified repair")
        assert listing["verified_account_count"] == 1
        assert_cents(listing["claimed_recurring_mrr_cents"], 16000, "claimed recurring")
        assert listing["claimed_account_count"] == 1
        assert listing["verification_posture"] == "COMPLETE"

        retired = validate_success(api.get_route_valuation(original["id"], BROKER))
        assert retired["is_superseded"] is True

        live, meta = validate_paginated(
            api.list_route_valuations(
                BROKER,
                params={"listing_id": listing_id, "basis": "VERIFIED_BASIS",
                        "is_superseded": "false"},
            )
        )
        assert meta["total_count"] == 1
        replacement = live[0]
        assert replacement["id"] != original["id"]
        assert_cents(replacement["recurring_mrr_cents"], 16000, "recurring base")
        assert replacement["weighted_avg_account_age_months"] == 88
        assert_multiple_1dp(replacement["base_multiple"], "9.0", "base multiple")
        assert_multiple_1dp(replacement["age_adjustment"], "1.0", "age adjustment")
        assert_multiple_1dp(replacement["effective_multiple"], "10.0", "effective multiple")
        assert_cents(replacement["recurring_component_cents"], 160000, "recurring component")
        assert_cents(replacement["repair_component_cents"], 4500, "repair component")
        assert_cents(replacement["valuation_cents"], 164500, "post-exclusion verified valuation")

        survivor = validate_success(api.get_service_account(ctx.a1["id"], BROKER))
        assert survivor["verification_status"] == "VERIFIED"
        assert_cents(survivor["verified_recurring_mrr_cents"], 16000, "A1 verified recurring")

    def test_the_last_two_hops_reprice_the_deal_and_durably_freeze_its_escrow(self, api):
        """The recomputed 164500 is below ninety percent of the standing 340000, so the same call runs
        on into the deal and then into the escrow it created: the target is zeroed and deposits are
        blocked, no cash counter moves, and a one-cent deposit is refused afterwards — the freeze is
        real and not a display flag.

        PRD §3.6: "The fourth hop is the deal: every deal on that listing sitting in `ACCEPTED` or
        `DILIGENCE_CLEARED` whose price no longer stands up against the new valuation is moved to
        `REPRICE_REQUIRED`, its `repricing_reason_code` is set to `VERIFIED_VALUATION_BELOW_OFFER`, and
        its `version` increments. The fifth hop is that deal's escrow account: an `OPEN` escrow has its
        `target_amount_cents` set to zero and its `deposits_blocked` set to true, and its `version`
        increments"
        PRD §3.6: "The threshold is ninety percent of the deal's standing `current_offer_price_cents`,
        rounded half up to whole cents. The deal is repriced when the freshly computed verified-basis
        `valuation_cents` is **strictly less than** that threshold".
        PRD §3.8: "The escrow must be `OPEN` with `deposits_blocked` false, and anything else — a
        `FUNDED`, `PARTIALLY_RELEASED`, `RELEASED` or `REFUNDED` escrow, or an `OPEN` one frozen by the
        repricing cascade of §3.6 — is `ERR_ESCROW_NOT_OPEN`."

        Design: Difficulty/transitive_cascade/exclude_verified_account_five_hop_reprice_cascade
        """
        ctx = fx.accepted_deal(api)
        deal_id = ctx.deal["id"]
        escrow_before = fx.escrow_for_deal(api, deal_id)
        assert escrow_before["status"] == "OPEN"
        assert_cents(escrow_before["target_amount_cents"], 171000, "escrow target")
        assert_cents(escrow_before["funded_amount_cents"], 0, "funded amount")
        assert escrow_before["deposits_blocked"] is False
        assert_cents(ctx.deal["current_offer_price_cents"], 340000, "standing price")

        fx.exclude_account(api, ctx.a2["id"], exclusion_reason_code="SELLER_WITHDREW_STOP")

        deal = validate_success(api.get_deal(deal_id, BROKER))
        assert deal["status"] == "REPRICE_REQUIRED"
        assert deal["repricing_reason_code"] == "VERIFIED_VALUATION_BELOW_OFFER"

        escrow = validate_success(api.get_escrow_account(escrow_before["id"], BROKER))
        assert_cents(escrow["target_amount_cents"], 0, "escrow target")
        assert escrow["deposits_blocked"] is True
        assert escrow["status"] == "OPEN"
        assert_cents(escrow["funded_amount_cents"], 0, "funded amount")
        assert_cents(escrow["undisbursed_balance_cents"], 0, "undisbursed balance")
        assert_cents(escrow["holdback_balance_cents"], 0, "holdback balance")

        validate_error(
            api.create_escrow_deposit(
                escrow["id"], f.escrow_deposit_payload(1), TEST_USERS["escrow_agent_headers"]
            ),
            ApiErrorId.ERR_ESCROW_NOT_OPEN,
            409,
        )
        after = validate_success(api.get_escrow_account(escrow["id"], BROKER))
        assert_cents(after["funded_amount_cents"], 0, "funded amount")
        assert after["deposits_blocked"] is True
