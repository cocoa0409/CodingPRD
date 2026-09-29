"""Who may act: exclusive roles, shared operations and the three segregation-of-duties clauses (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    BROKER_VERIFIER_USER_ID,
    ESCROW_FUNDER_USER_ID,
    ESCROW_RELEASER_USER_ID,
    TEST_USERS,
    make_broker_headers,
    make_buyer_headers,
    make_escrow_agent_headers,
    make_seller_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_ratio_4dp

BROKER = TEST_USERS["broker_headers"]
ALT_BROKER = TEST_USERS["broker_ops_alt_headers"]
DILIGENCE_BROKER = TEST_USERS["broker_diligence_headers"]
FUNDER = make_escrow_agent_headers(ESCROW_FUNDER_USER_ID)
RELEASER = make_escrow_agent_headers(ESCROW_RELEASER_USER_ID)


class TestMoneyMovesAreTheEscrowAgentsAlone:
    def test_broker_seller_and_buyer_are_all_refused_on_the_cash_endpoints(self, api):
        """The broker who runs the deal, the seller who receives the proceeds and the buyer whose money
        it is are all refused on the two cash endpoints, and the role check answers before the escrow
        state check that an authorised caller would have met on this `OPEN` escrow; reads stay open to
        everyone and the escrow agent's own deposit funds it.

        PRD §2.1: "There is no hierarchical override anywhere in this API. `PlatformAdmin` cannot
        accept a deal on a seller's behalf, and `Broker` cannot deposit into escrow."
        PRD §2.9: "`ERR_UNAUTHORIZED` — the role is not authorised for this operation." listed at 2,
        ahead of "`ERR_ESCROW_NOT_OPEN`".
        PRD §3.8: "The first deposit against an escrow stamps `funded_by_user_id` with the acting
        escrow agent's `X-User-ID`".

        Design: Corner/rbac/escrow_agent_exclusive_money_moves_are_forbidden_to_every_other_role
        """
        ctx = fx.financing_approved_deal(api)
        escrow_id = ctx.escrow["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])
        deposit = f.escrow_deposit_payload(171000)

        for headers in (BROKER, seller_headers):
            validate_error(
                api.create_escrow_deposit(escrow_id, deposit, headers),
                ApiErrorId.ERR_UNAUTHORIZED,
                403,
            )
        validate_error(
            api.release_holdback(escrow_id, buyer_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        readable = validate_success(api.get_escrow_account(escrow_id, seller_headers))
        assert_cents(readable["funded_amount_cents"], 0, "funded amount")
        assert readable["status"] == "OPEN"

        validate_success(api.create_escrow_deposit(escrow_id, deposit, FUNDER), 201)
        funded = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert funded["status"] == "FUNDED"
        assert funded["funded_by_user_id"] == ESCROW_FUNDER_USER_ID
        assert_cents(funded["funded_amount_cents"], 171000, "funded amount")


class TestTheNegotiatingPartiesArePeers:
    def test_each_side_of_the_negotiation_is_closed_to_the_other(self, api):
        """Both parties are authorised on this very deal, yet neither may play the other's move: the
        buyer cannot counter its own offer upward or accept on the seller's behalf, and the seller
        cannot re-offer downward.

        PRD §2.1: "There is no hierarchical override anywhere in this API."
        PRD §2.9: "`ERR_UNAUTHORIZED` — the role is not authorised for this operation."
        PRD §3.5: "The owning seller may counter upward from `OFFER_SUBMITTED`, supplying a
        `counter_price_cents` ... The buyer may then re-offer downward from `COUNTERED`, supplying a
        fresh `offer_price_cents` together with a fresh `down_payment_cents` and
        `note_principal_cents`".
        PRD §3.5: "Only the owning seller may accept, only from `OFFER_SUBMITTED`".

        Design: Corner/rbac/seller_and_buyer_negotiation_endpoints_are_mutually_forbidden
        """
        ctx = fx.offer_submitted_deal(api)
        deal_id = ctx.deal["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])

        validate_error(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(360000), buyer_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.accept_deal(deal_id, f.accept_deal_payload(90), buyer_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        countered = validate_success(
            api.counter_offer_deal(deal_id, f.counter_offer_payload(360000), seller_headers)
        )
        assert countered["status"] == "COUNTERED"
        assert_cents(countered["current_offer_price_cents"], 360000, "standing price")
        assert countered["offer_round"] == 2

        reoffer = f.reoffer_payload(350000, 130000, 220000)
        validate_error(
            api.reoffer_deal(deal_id, reoffer, seller_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        reoffered = validate_success(api.reoffer_deal(deal_id, reoffer, buyer_headers))
        assert reoffered["status"] == "OFFER_SUBMITTED"
        assert_cents(reoffered["current_offer_price_cents"], 350000, "standing price")
        assert reoffered["offer_round"] == 3


class TestSharedOperationsAcceptEitherAuthorizedRole:
    def test_three_endpoints_with_several_authorized_roles_accept_a_different_one_each(self, api):
        """Where the endpoint lists more than one role, each of them really works: the brokerage opens
        the offer on the buyer's behalf, the buyer walks away from that same deal, and the owning
        seller withdraws the listing — three roles, three writes, no role error.

        PRD §4: "POST `/deals` ... Buyer, Broker".
        PRD §4: "POST `/deals/{id}/terminate` ... Broker, Seller, Buyer".
        PRD §4: "POST `/route-listings/{id}/withdraw` ... Broker, Seller".

        Design: Corner/rbac/shared_operations_accept_either_authorized_role
        """
        ctx = fx.listed_route(api)
        listing_id = ctx.listing["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])

        deal = validate_success(
            api.create_deal(f.deal_payload(listing_id, ctx.buyer["id"]), BROKER), 201
        )
        assert deal["status"] == "OFFER_SUBMITTED"
        assert deal["buyer_id"] == ctx.buyer["id"]

        terminated = validate_success(
            api.terminate_deal(deal["id"], f.terminate_deal_payload(), buyer_headers)
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason_code"] == "BUYER_WITHDREW"

        withdrawn = validate_success(
            api.withdraw_route_listing(
                listing_id,
                f.withdraw_listing_payload(withdrawal_reason_code="SELLER_RETIRED"),
                seller_headers,
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason_code"] == "SELLER_RETIRED"

        readable = validate_success(api.get_route_listing(listing_id, seller_headers))
        assert readable["claimed_account_count"] == 3


class TestTheSecondAuthorizedRoleIsRecorded:
    def test_the_seller_may_upload_evidence_and_the_buyer_may_report_its_own_churn(self, api):
        """Two shared write endpoints record which of their roles was used: the seller's own export is
        stored as a seller upload with its derived collection columns, and the buyer's attrition report
        is stamped with the buyer role — which is what later makes the segregation clauses checkable.

        PRD §3.3: "A `source` of `SELLER_UPLOAD` is the seller's own export from its billing software".
        PRD §3.3: "`collection_rate` is `collected_cents` divided by the total of the three billed
        amounts, taken to four decimal places rounded half up ... `recurring_collected_cents` is the
        month's recurring invoice ... multiplied by that month's `collection_rate` and rounded half up
        to whole cents."
        PRD §3.9: "Its `recorded_by_role` is stamped by the server from the acting `X-User-Role`, so an
        event recorded by the buyer and an identical event recorded by the brokerage are
        distinguishable afterwards."
        PRD §3.9: "buyer-fault churn never enters the net figure at all, because a customer the buyer
        drove away is not the seller's problem."

        Design: Corner/rbac/billing_rows_and_attrition_events_accept_their_second_authorized_role
        """
        ctx = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="closed")
        deal_id = ctx.deal["id"]
        seller_headers = make_seller_headers(ctx.seller["id"])
        buyer_headers = make_buyer_headers(ctx.buyer["id"])
        assert_cents(ctx.deal["guaranteed_mrr_cents"], 20000, "guaranteed mrr")
        assert_cents(ctx.deal["allowance_mrr_cents"], 1000, "allowance mrr")

        row = validate_success(
            api.create_billing_history_record(
                f.billing_history_record_payload(
                    ctx.account["id"], "2026-08", billed_service_cents=20000,
                    billed_chemical_cents=0, billed_repair_cents=0, collected_cents=19000,
                    source="SELLER_UPLOAD",
                ),
                seller_headers,
            ),
            201,
        )
        assert row["source"] == "SELLER_UPLOAD"
        assert_ratio_4dp(row["collection_rate"], "0.9500", "collection rate")
        assert_cents(row["recurring_collected_cents"], 19000, "recurring collected")
        assert_cents(row["repair_collected_cents"], 0, "repair collected")

        event = validate_success(
            api.create_attrition_event(
                f.attrition_event_payload(
                    deal_id, ctx.account["id"], "DOWNGRADED", "2026-09-15", -600,
                    "BUYER_SERVICE_FAILURE", fx.deal_version(api, deal_id),
                ),
                buyer_headers,
            ),
            201,
        )
        assert event["recorded_by_role"] == "Buyer"

        ledger = validate_success(api.get_deal(deal_id, buyer_headers))
        assert_cents(ledger["attrited_mrr_cents"], 600, "attrited mrr")
        assert_cents(ledger["retained_mrr_cents"], 19400, "retained mrr")
        assert_cents(ledger["net_attrition_mrr_cents"], 0, "net attrition")
        assert_ratio_4dp(ledger["attrition_pct"], "0.0000", "attrition pct")
        assert ledger["clawback_status"] == "MONITORING"


class TestTheVerifierMayNotCertifyItsOwnWork:
    def test_the_collision_is_on_the_human_identity_not_on_the_role(self, api):
        """The refused caller carries the broker role, addresses a deal in exactly the right status and
        names the current frozen snapshot; the only thing wrong with it is that the same user id
        verified the stops. A different broker clears the identical body immediately afterwards.

        PRD §2.1: "Second, the `X-User-ID` that verified a service account may not sign off due
        diligence on a deal covering that account. ... In all three cases the role is correct and the
        actor does own the resource; only the human identity collides."
        PRD §3.6: "the user certifying diligence may not be a user who personally verified any of the
        accounts covered by the deal's listing, as recorded in each account's `verified_by_user_id`. A
        broker who verified even one stop is refused with `ERR_SEGREGATION_OF_DUTIES`, and a different
        broker must sign off."

        Design: Corner/rbac/the_verifier_cannot_clear_diligence_on_a_deal_covering_that_account
        """
        ctx = fx.accepted_deal(api)
        deal_id = ctx.deal["id"]
        signoff = f.clear_diligence_payload(ctx.verified_valuation["id"])
        assert ctx.a1["verified_by_user_id"] == BROKER_VERIFIER_USER_ID
        assert_cents(ctx.verified_valuation["valuation_cents"], 343725, "verified valuation")

        validate_error(
            api.clear_diligence(deal_id, signoff, make_broker_headers(BROKER_VERIFIER_USER_ID)),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert validate_success(api.get_deal(deal_id, BROKER))["status"] == "ACCEPTED"

        cleared = validate_success(api.clear_diligence(deal_id, signoff, DILIGENCE_BROKER))
        assert cleared["status"] == "DILIGENCE_CLEARED"


class TestTheFunderMayNotPayTheMoneyOut:
    def test_the_stamp_the_depositor_wrote_is_what_refuses_it_later(self, api):
        """Every timing condition on the release is satisfied and the caller is an escrow agent, but the
        escrow remembers who funded it, so the release needs a second agent; the balance is untouched
        by the refusal and the second agent drains it.

        PRD §2.1: "Third, the `X-User-ID` recorded in an escrow account's `funded_by_user_id` may
        neither release that escrow's holdback nor settle a clawback out of it."
        PRD §3.9: "The escrow agent releases it with no request body, from a `PARTIALLY_RELEASED`
        escrow whose deal is `CLOSED`, and the acting `X-User-ID` must again differ from
        `funded_by_user_id`."
        PRD §3.9: "On success `disbursed_to_seller_cents` grows by the whole `holdback_balance_cents`,
        that balance drops to zero, the escrow's `status` becomes `RELEASED`, and the deal cascades
        from `CLOSED` to `GUARANTEE_CLOSED`."

        Design: Corner/rbac/the_escrow_funder_cannot_release_the_holdback_it_funded
        """
        ctx = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="closed")
        deal_id = ctx.deal["id"]
        escrow_id = ctx.escrow["id"]
        assert ctx.deal["clawback_status"] == "MONITORING"

        fx.set_clock(api, "2026-11-30T00:00:00Z")
        validate_error(
            api.release_holdback(escrow_id, FUNDER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        held = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert_cents(held["holdback_balance_cents"], 27000, "holdback balance")
        assert held["status"] == "PARTIALLY_RELEASED"
        assert held["funded_by_user_id"] == ESCROW_FUNDER_USER_ID
        assert held["holdback_release_blocked"] is False

        validate_success(api.release_holdback(escrow_id, RELEASER), 201)
        released = validate_success(api.get_escrow_account(escrow_id, BROKER))
        assert released["status"] == "RELEASED"
        assert_cents(released["holdback_balance_cents"], 0, "holdback balance")
        assert_cents(released["disbursed_to_seller_cents"], 37000, "disbursed to seller")

        deal = validate_success(api.get_deal(deal_id, BROKER))
        assert deal["status"] == "GUARANTEE_CLOSED"
        assert deal["clawback_status"] == "MONITORING"


class TestOneSettlementNeedsThreeDistinctIdentities:
    def test_the_recorder_may_not_price_the_loss_and_the_funder_may_not_pay_it(self, api):
        """Two of the three clauses bite at two different steps of one settlement, so reaching a settled
        state takes three separate humans: the broker who logged the churn, a second broker to price it
        and a second escrow agent to move the money.

        PRD §2.1: "First, the `X-User-ID` that recorded any attrition event on a deal may not propose
        that deal's clawback settlement. ... Third, the `X-User-ID` recorded in an escrow account's
        `funded_by_user_id` may neither release that escrow's holdback nor settle a clawback out of it."
        PRD §3.9: "The proposing user may not be a user who recorded any attrition event on the deal,
        or the answer is `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "the acting `X-User-ID` must differ from the escrow's `funded_by_user_id`, or the
        answer is `ERR_SEGREGATION_OF_DUTIES`: the party that put the money in may not be the party
        that pays it out."

        Design: Corner/rbac/the_attrition_recorder_cannot_propose_and_the_funder_cannot_settle
        """
        ctx = fx.nv_deal_route(api, region_code="LV-WEST", stop_after="closed")
        deal_id = ctx.deal["id"]
        fx.set_clock(api, "2026-10-01T00:00:00Z")
        validate_success(
            api.create_attrition_event(
                f.attrition_event_payload(
                    deal_id, ctx.account["id"], "CANCELLED", "2026-09-15", -20000, "NATURAL",
                    fx.deal_version(api, deal_id),
                ),
                BROKER,
            ),
            201,
        )
        triggered = validate_success(api.get_deal(deal_id, BROKER))
        assert triggered["clawback_status"] == "CLAWBACK_TRIGGERED"
        assert_cents(triggered["clawback_cap_cents"], 36000, "clawback cap")

        settlement = validate_success(
            api.create_clawback_settlement(f.clawback_settlement_payload(deal_id), BROKER), 201
        )
        settlement_id = settlement["id"]
        assert_cents(settlement["adjustment_cents"], 36000, "adjustment")

        validate_error(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(36000), BROKER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert validate_success(
            api.get_clawback_settlement(settlement_id, BROKER)
        )["status"] == "DRAFT"

        proposed = validate_success(
            api.propose_clawback_settlement(
                settlement_id, f.propose_settlement_payload(36000), ALT_BROKER
            )
        )
        assert proposed["status"] == "PROPOSED"

        validate_error(
            api.settle_clawback_settlement(
                settlement_id, f.settle_settlement_payload(36000), FUNDER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        settled = validate_success(
            api.settle_clawback_settlement(
                settlement_id, f.settle_settlement_payload(36000), RELEASER
            )
        )
        assert settled["status"] == "SETTLED"
        assert_cents(settled["from_holdback_cents"], 27000, "from holdback")
        assert_cents(settled["from_note_principal_cents"], 9000, "from note principal")
