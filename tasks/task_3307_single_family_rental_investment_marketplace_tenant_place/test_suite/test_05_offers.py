"""Offer negotiation: rounds, expiry sweeps, funds checks, and validation order."""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    assert_instants_equal,
    create_offer_for,
    get_success_data,
    make_buyer_headers,
    make_seller_headers,
    set_clock,
    setup_buyer,
    setup_certified_listing,
    setup_listed_listing,
    submit_offer,
    validate_error,
    validate_success,
)


class TestOfferNegotiationCycle:
    def test_counter_resubmit_cycle_tracks_rounds_and_amount(self, api):
        """PRD §3.6: "The seller counters a `SUBMITTED` offer (`SUBMITTED` →
        `COUNTERED`) with a `counter_amount_cents` strictly greater than zero,
        which increments `round_number` by 1. The buyer then resubmits
        (`COUNTERED` → `SUBMITTED`) with a new `amount_cents` in the payload,
        which replaces the offer's amount, refreshes `expires_at` to the logical
        clock plus 72 hours, and is subject to the same guards as the initial
        submission — the listing must still be in `LISTED` or `OFFER_PENDING`,
        and the funds checks (the earnest floor and, for cash offers, proof of
        funds covering the new amount) are re-evaluated."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle
        """
        ctx = setup_listed_listing()
        buyer = setup_buyer()
        offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"])
        offer = submit_offer(buyer, offer)
        assert offer["round_number"] == 1
        seller_h = make_seller_headers(ctx["seller"]["id"])
        buyer_h = make_buyer_headers(buyer["id"])
        # Cycle 1: counter -> resubmit
        countered = get_success_data(
            api.transition_offer(offer["id"], {"action": "COUNTER", "counter_amount_cents": 9_500_000}, seller_h)
        )
        assert countered["round_number"] == 2
        resubmitted = get_success_data(
            api.transition_offer(offer["id"], {"action": "RESUBMIT", "amount_cents": 9_400_000}, buyer_h)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["amount_cents"] == 9_400_000
        # Cycle 2: counter -> resubmit
        countered = get_success_data(
            api.transition_offer(offer["id"], {"action": "COUNTER", "counter_amount_cents": 9_600_000}, seller_h)
        )
        assert countered["round_number"] == 3
        resubmitted = get_success_data(
            api.transition_offer(offer["id"], {"action": "RESUBMIT", "amount_cents": 9_550_000}, buyer_h)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["round_number"] == 3
        assert resubmitted["amount_cents"] == 9_550_000

    def test_resubmit_refreshes_expiry_from_logical_clock(self, api):
        """PRD §3.6: "The buyer then resubmits (`COUNTERED` → `SUBMITTED`) with a
        new `amount_cents` in the payload, which replaces the offer's amount,
        refreshes `expires_at` to the logical clock plus 72 hours, and is subject
        to the same guards as the initial submission — the listing must still be
        in `LISTED` or `OFFER_PENDING`, and the funds checks (the earnest floor
        and, for cash offers, proof of funds covering the new amount) are
        re-evaluated."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_listed_listing()
        buyer = setup_buyer()
        offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"])
        offer = submit_offer(buyer, offer)
        assert_instants_equal(offer["expires_at"], "2026-09-04T00:00:00Z", "initial expires_at")
        seller_h = make_seller_headers(ctx["seller"]["id"])
        get_success_data(
            api.transition_offer(
                offer["id"], {"action": "COUNTER", "counter_amount_cents": 9_500_000}, seller_h
            )
        )
        set_clock("2026-09-03T00:00:00Z")
        resubmitted = get_success_data(
            api.transition_offer(
                offer["id"],
                {"action": "RESUBMIT", "amount_cents": 9_400_000},
                make_buyer_headers(buyer["id"]),
            )
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert_instants_equal(resubmitted["expires_at"], "2026-09-06T00:00:00Z", "refreshed expires_at")

    def test_resubmit_at_round_five_rejected(self, api):
        """PRD §3.6: "Resubmission is capped: when `round_number` has reached 5,
        further resubmission is rejected with `ERR_NEGOTIATION_ROUND_EXCEEDED`."

        Design: Corner/errors/error_negotiation_round_exceeded
        """
        ctx = setup_listed_listing()
        buyer = setup_buyer()
        offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"])
        offer = submit_offer(buyer, offer)
        seller_h = make_seller_headers(ctx["seller"]["id"])
        buyer_h = make_buyer_headers(buyer["id"])
        # round_number starts at 1 on creation (PRD §3.6); each COUNTER adds 1.
        for i in range(3):
            get_success_data(
                api.transition_offer(
                    offer["id"], {"action": "COUNTER", "counter_amount_cents": 9_100_000 + i * 100_000}, seller_h
                )
            )
            get_success_data(
                api.transition_offer(
                    offer["id"], {"action": "RESUBMIT", "amount_cents": 9_050_000 + i * 100_000}, buyer_h
                )
            )
        # Fourth counter brings round_number to 5.
        countered = get_success_data(
            api.transition_offer(offer["id"], {"action": "COUNTER", "counter_amount_cents": 9_500_000}, seller_h)
        )
        assert countered["round_number"] == 5
        assert countered["status"] == "COUNTERED"
        resp = api.transition_offer(offer["id"], {"action": "RESUBMIT", "amount_cents": 9_450_000}, buyer_h)
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_EXCEEDED)
        offer_now = get_success_data(api.get_offer(offer["id"], buyer_h))
        assert offer_now["round_number"] == 5
        assert offer_now["status"] == "COUNTERED"


class TestOfferExpirySweep:
    def test_clock_set_expires_submitted_offer_but_not_countered(self, api):
        """PRD §2.4: "A `PlatformAdmin` may advance the logical clock to a
        supplied `to_iso8601` instant through an admin-only test-driving
        capability; setting the clock runs the offer-expiry sweep (every offer
        still `SUBMITTED` whose `expires_at` has been reached or passed moves to
        `EXPIRED`) and the guarantee-expiry sweep (every `ACTIVE` guarantee
        whose claim window has passed moves to `EXPIRED`)."

        Design: Corner/calculations/offer_expiry_sweep_on_clock_set
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer1 = setup_buyer(legal_name="Sweep B1")
        buyer2 = setup_buyer(legal_name="Sweep B2")
        offer1 = create_offer_for(buyer1, ctx["listing"]["id"], ctx["listing"]["version"])
        listing = get_success_data(
            api.get_listing(ctx["listing"]["id"], make_seller_headers(ctx["seller"]["id"]))
        )
        offer2 = create_offer_for(
            buyer2, ctx["listing"]["id"], listing["version"], amount_cents=9_900_000
        )
        submit_offer(buyer1, offer1)
        submit_offer(buyer2, offer2)
        seller_h = make_seller_headers(ctx["seller"]["id"])
        get_success_data(
            api.transition_offer(offer2["id"], {"action": "COUNTER", "counter_amount_cents": 9_950_000}, seller_h)
        )
        set_clock("2026-09-05T00:00:00Z")
        o1 = get_success_data(api.get_offer(offer1["id"], make_buyer_headers(buyer1["id"])))
        o2 = get_success_data(api.get_offer(offer2["id"], make_buyer_headers(buyer2["id"])))
        assert o1["status"] == "EXPIRED"
        assert o2["status"] == "COUNTERED"

    def test_submitted_offer_expiry_stamps_from_default_clock(self, api):
        """PRD §2.4: "Before any call sets it, the logical clock reads exactly
        `2026-09-01T00:00:00Z`."
        PRD §3.6: "Submission stamps `expires_at` to the logical clock plus 72
        hours and moves a `LISTED` listing to `OFFER_PENDING`."

        Design: Corner/endpoints/clock_default_is_fixed_not_wallclock
        """
        # No clock set anywhere in this test — the default 2026-09-01 applies.
        ctx = setup_listed_listing()
        buyer = setup_buyer()
        offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"])
        offer = submit_offer(buyer, offer)
        assert_instants_equal(offer["expires_at"], "2026-09-04T00:00:00Z", "expires_at")
        listing = get_success_data(
            api.get_listing(ctx["listing"]["id"], make_seller_headers(ctx["seller"]["id"]))
        )
        assert listing["status"] == "OFFER_PENDING"


class TestOfferSubmitGuards:
    def test_submit_on_certified_listing_rejected(self, api):
        """PRD §3.6: "Submitting the offer (`DRAFT` → `SUBMITTED`) is the buyer's
        action and is permitted only while the listing is `LISTED` or
        `OFFER_PENDING`; earnest money must be at least 50000 cents (a 500-dollar
        floor), and when `financing_type` is `CASH` the buyer's
        `proof_of_funds_cents` must be at least the offer's `amount_cents` — a
        shortfall on either check is rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/cross_entity_state_dependency/offer_submit_depends_on_listing_state
        """
        ctx = setup_certified_listing()  # CERTIFIED, not yet published
        buyer = setup_buyer()
        offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"])
        resp = api.transition_offer(offer["id"], {"action": "SUBMIT"}, make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_PRECONDITION)
        offer_now = get_success_data(api.get_offer(offer["id"], make_buyer_headers(buyer["id"])))
        assert offer_now["status"] == "DRAFT"

    def test_cash_offer_above_proof_of_funds_rejected(self, api):
        """PRD §3.6: "Submitting the offer (`DRAFT` → `SUBMITTED`) is the buyer's
        action and is permitted only while the listing is `LISTED` or
        `OFFER_PENDING`; earnest money must be at least 50000 cents (a 500-dollar
        floor), and when `financing_type` is `CASH` the buyer's
        `proof_of_funds_cents` must be at least the offer's `amount_cents` — a
        shortfall on either check is rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Corner/validations/cash_offer_exceeding_proof_of_funds_rejected
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer = setup_buyer(legal_name="Thin Buyer", proof_of_funds_cents=5_000_000)
        offer = create_offer_for(
            buyer, ctx["listing"]["id"], ctx["listing"]["version"], amount_cents=10_000_000
        )
        resp = api.transition_offer(offer["id"], {"action": "SUBMIT"}, make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS, expected_status=402)

    def test_conventional_offer_bypasses_proof_of_funds_floor(self, api):
        """PRD §3.6: "when `financing_type` is `CASH` the buyer's
        `proof_of_funds_cents` must be at least the offer's `amount_cents` — a
        shortfall on either check is rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Corner/validations/cash_offer_exceeding_proof_of_funds_rejected
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer = setup_buyer(legal_name="Thin Buyer", proof_of_funds_cents=5_000_000)
        offer = create_offer_for(
            buyer,
            ctx["listing"]["id"],
            ctx["listing"]["version"],
            amount_cents=10_000_000,
            financing_type="CONVENTIONAL",
        )
        offer = submit_offer(buyer, offer)
        assert offer["status"] == "SUBMITTED"


    def test_offer_submit_on_listed_listing_flips_to_offer_pending(self, api):
        """PRD §3.6: "Submission stamps `expires_at` to the logical clock plus 72
        hours and moves a `LISTED` listing to `OFFER_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/offer_submit_depends_on_listing_state
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer = setup_buyer()
        offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"])
        offer = submit_offer(buyer, offer)
        assert offer["status"] == "SUBMITTED"
        listing = get_success_data(
            api.get_listing(ctx["listing"]["id"], make_seller_headers(ctx["seller"]["id"]))
        )
        assert listing["status"] == "OFFER_PENDING"


class TestOfferValidationOrder:
    def test_listing_state_precondition_surfaces_before_funds_shortfall(self, api):
        """PRD §2.8: "Every request is checked against a fixed priority order,
        so that a request failing several checks surfaces the earliest failure
        rather than an arbitrary one."
        PRD §3.6: "Submitting the offer (`DRAFT` → `SUBMITTED`) is the buyer's
        action and is permitted only while the listing is `LISTED` or
        `OFFER_PENDING`; earnest money must be at least 50000 cents (a 500-dollar
        floor), and when `financing_type` is `CASH` the buyer's
        `proof_of_funds_cents` must be at least the offer's `amount_cents` — a
        shortfall on either check is rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_offer_submit
        """
        from test_helpers import setup_draft_listing, setup_seller

        seller = setup_seller()
        buyer = setup_buyer()
        listing = setup_draft_listing(seller, address_line="43 Fiscal St")
        offer = create_offer_for(
            buyer, listing["id"], listing["version"], earnest_money_cents=1_000
        )
        resp = api.transition_offer(offer["id"], {"action": "SUBMIT"}, make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_PRECONDITION)
        offer_now = get_success_data(api.get_offer(offer["id"], make_buyer_headers(buyer["id"])))
        assert offer_now["status"] == "DRAFT"

    def test_earnest_below_floor_rejected_on_listed_listing(self, api):
        """PRD §3.6: "earnest money must be at least 50000 cents (a 500-dollar
        floor), and when `financing_type` is `CASH` the buyer's
        `proof_of_funds_cents` must be at least the offer's `amount_cents` — a
        shortfall on either check is rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_offer_submit
        """
        ctx = setup_listed_listing()
        buyer = setup_buyer()
        offer = create_offer_for(
            buyer, ctx["listing"]["id"], ctx["listing"]["version"], earnest_money_cents=1_000
        )
        resp = api.transition_offer(offer["id"], {"action": "SUBMIT"}, make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS, expected_status=402)
        offer_now = get_success_data(api.get_offer(offer["id"], make_buyer_headers(buyer["id"])))
        assert offer_now["status"] == "DRAFT"


class TestOfferCreateOcc:
    def test_second_offer_with_stale_listing_version_rejected(self, api):
        """PRD §2.6: "Creating an offer against a listing requires
        `expected_listing_version` as a non-optional input carrying the buyer's
        last observed `version` of the listing. If the listing's current
        `version` has advanced since the client last read it — for example
        because another offer's creation bumped the listing version,
        invalidating the buyer's underwriting basis — the create is rejected with
        `ERR_STALE_LISTING_VERSION` (HTTP 412); the writer must re-read the
        listing and retry with the fresh version. Offer creation itself
        increments the listing's `version` by 1."

        Design: Corner/endpoints/occ_offer_create_stale_listing_version
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer1 = setup_buyer(legal_name="OCC B1")
        buyer2 = setup_buyer(legal_name="OCC B2")
        observed_version = ctx["listing"]["version"]
        offer1 = create_offer_for(buyer1, ctx["listing"]["id"], observed_version)
        assert offer1["status"] == "DRAFT"
        resp = api.create_offer(
            ctx["listing"]["id"],
            {
                "buyer_id": buyer2["id"],
                "amount_cents": 10_000_000,
                "earnest_money_cents": 50_000,
                "financing_type": "CASH",
                "expected_listing_version": observed_version,
            },
            make_buyer_headers(buyer2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_LISTING_VERSION, expected_status=412)

    def test_offer_create_with_fresh_version_succeeds(self, api):
        """PRD §2.6: "If the listing's current `version` has advanced since the
        client last read it — for example because another offer's creation bumped
        the listing version, invalidating the buyer's underwriting basis — the
        create is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412); the
        writer must re-read the listing and retry with the fresh version. Offer
        creation itself increments the listing's `version` by 1."

        Design: Corner/endpoints/occ_offer_create_stale_listing_version
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer1 = setup_buyer(legal_name="OCC B1")
        buyer2 = setup_buyer(legal_name="OCC B2")
        create_offer_for(buyer1, ctx["listing"]["id"], ctx["listing"]["version"])
        listing = get_success_data(
            api.get_listing(ctx["listing"]["id"], make_buyer_headers(buyer2["id"]))
        )
        offer2 = create_offer_for(
            buyer2, ctx["listing"]["id"], listing["version"], amount_cents=9_900_000
        )
        assert offer2["status"] == "DRAFT"


class TestOfferAcceptCascade:
    def test_accept_expires_sibling_offers(self, api):
        """PRD §3.6: "Acceptance cascades: the listing moves from
        `OFFER_PENDING` to `UNDER_CONTRACT`, every sibling offer still in
        `SUBMITTED` or `COUNTERED` moves to `EXPIRED`, and an escrow is created
        for the accepted offer in `OPENED` status with `remote_signing_required`
        derived from the offer's pinned `is_out_of_state`."

        Design: Corner/state_machines/offer_accept_expires_sibling_offers
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer1 = setup_buyer(legal_name="B One")
        buyer2 = setup_buyer(legal_name="B Two")
        offer1 = create_offer_for(buyer1, ctx["listing"]["id"], ctx["listing"]["version"])
        listing = get_success_data(
            api.get_listing(ctx["listing"]["id"], make_seller_headers(ctx["seller"]["id"]))
        )
        offer2 = create_offer_for(
            buyer2, ctx["listing"]["id"], listing["version"], amount_cents=9_900_000
        )
        submit_offer(buyer1, offer1)
        submit_offer(buyer2, offer2)
        seller_h = make_seller_headers(ctx["seller"]["id"])
        accepted = get_success_data(
            api.transition_offer(offer1["id"], {"action": "ACCEPT"}, seller_h)
        )
        assert accepted["status"] == "ACCEPTED"
        sibling = get_success_data(api.get_offer(offer2["id"], make_buyer_headers(buyer2["id"])))
        assert sibling["status"] == "EXPIRED"
        listing = get_success_data(api.get_listing(ctx["listing"]["id"], seller_h))
        assert listing["status"] == "UNDER_CONTRACT"

    def test_accept_creates_single_escrow_in_opened(self, api):
        """PRD §3.7: "Exactly one escrow exists per accepted offer, created at
        acceptance in `OPENED` status."

        Design: Corner/state_machines/offer_accept_expires_sibling_offers
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_listed_listing()
        buyer = setup_buyer()
        offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"])
        submit_offer(buyer, offer)
        seller_h = make_seller_headers(ctx["seller"]["id"])
        get_success_data(api.transition_offer(offer["id"], {"action": "ACCEPT"}, seller_h))
        escrow = get_success_data(api.get_offer_escrow(offer["id"], make_buyer_headers(buyer["id"])))
        assert isinstance(escrow, list) and len(escrow) == 1
        assert escrow[0]["status"] == "OPENED"
