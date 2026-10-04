"""Manufacturing dual-variant units, replacement spare invariants,
localization windows, distributor allocation timing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_pledge,
    book_freight,
    charge_pledge,
    create_charged_pledge,
    create_distributor_allocation,
    create_localization_agreement,
    create_pledge,
    create_quote,
    create_replacement_request,
    create_run,
    get_campaign,
    refund_pledge,
    set_clock,
    setup_campaign_in_production,
    setup_closed_success_campaign,
    setup_delivered_pledge,
    setup_live_campaign,
    submit_quote,
    validate_error,
    validate_success,
)

OWNER = TEST_USERS["campaign_owner_headers"]
FACTORY = TEST_USERS["factory_coordinator_headers"]
LOCAL = TEST_USERS["localization_partner_headers"]
FULFILL = TEST_USERS["fulfillment_operator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestManufacturingDualVariant:

    def test_provisional_counts_pending_pledges_at_creation(self, api):
        """PRD §3.4: "The provisional variant — used while a quote is
        `PROVISIONAL` or `SUBMITTED` — counts pledges whose `charge_status`
        is `PENDING` or `CHARGED`".

        Design: Difficulty/dual_variant_calc/manufacturing_quote_provisional_differs_from_final
        """
        campaign = setup_live_campaign(closes_at="2026-09-05T00:00:00Z")
        create_pledge(campaign["id"], backer_user_id="b1", backer_email="b1@x")
        create_pledge(campaign["id"], backer_user_id="b2", backer_email="b2@x")
        # One charged pledge (5,000c >= goal 1,000c) so the campaign closes
        # CLOSED_SUCCESS; on CLOSED_FAILED all pledges cascade to REFUNDED
        # (PRD §3.2) and would no longer count as PENDING.
        create_charged_pledge(campaign["id"], backer_user_id="b3", backer_email="b3@x")
        set_clock("2026-09-06T00:00:00Z")
        campaign = get_campaign(campaign["id"])
        assert campaign["status"] == "CLOSED_SUCCESS"
        quote = create_quote(campaign["id"])
        assert quote["provisional_units"] == 3


class TestReplacementSpares:
    def test_replacement_approve_reopen_conserves_spare_pool(self, api):
        """PRD §3.9: "Approval earmarks the units by setting
        `spare_units_debited` to the `quantity`. Reopening (`APPROVED →
        PENDING`) resets `spare_units_debited` to zero, a compensating action
        that leaves the available spare pool unchanged across an
        approve-then-reopen pair."

        Design: Difficulty/compensating_invariant/replacement_approve_reopen_conserves_spare_pool
        """
        bundle = setup_delivered_pledge(_signed_commitments=80)
        campaign = bundle["campaign"]
        run = bundle["run"]
        pledge = bundle["pledge"]
        spares_before = validate_success(
            api.get_production_run(run["id"], ADMIN)
        )["spare_units_by_region"]

        request = create_replacement_request(
            campaign["id"], pledge["id"], pledge["backer_user_id"]
        )
        resp = api.transition_replacement_request(
            request["id"], {"action": "approve"}, OWNER
        )
        approved = validate_success(resp)
        assert approved["spare_units_debited"] == 1

        mid = validate_success(api.get_production_run(run["id"], ADMIN))
        assert mid["spare_units_by_region"] == spares_before

        resp = api.transition_replacement_request(
            request["id"], {"action": "reopen"}, OWNER
        )
        reopened = validate_success(resp)
        assert reopened["spare_units_debited"] == 0
        assert reopened["status"] == "PENDING"

        after = validate_success(api.get_production_run(run["id"], ADMIN))
        assert after["spare_units_by_region"] == spares_before

    def test_replacement_reopen_is_cyclic_and_reapprovable(self, api):
        """PRD §3.9: "Reopening (`APPROVED → PENDING`) resets
        `spare_units_debited` to zero, a compensating action that leaves the
        available spare pool unchanged across an approve-then-reopen pair."

        Design: Difficulty/compensating_invariant/replacement_approve_reopen_conserves_spare_pool
        """
        bundle = setup_delivered_pledge(_signed_commitments=80)
        campaign = bundle["campaign"]
        pledge = bundle["pledge"]
        request = create_replacement_request(
            campaign["id"], pledge["id"], pledge["backer_user_id"]
        )
        validate_success(
            api.transition_replacement_request(
                request["id"], {"action": "approve"}, OWNER
            )
        )
        validate_success(
            api.transition_replacement_request(
                request["id"], {"action": "reopen"}, OWNER
            )
        )
        # After the compensating pair the request is PENDING again with a
        # zeroed earmark.
        current = validate_success(
            api.get_replacement_request(request["id"], ADMIN)
        )
        assert current["status"] == "PENDING"
        assert current["spare_units_debited"] == 0

    def test_err_pledge_not_delivered_on_replacement(self, api):
        """PRD §3.9: "The pledge's fulfillment must be `DELIVERED` at filing
        (otherwise `ERR_PLEDGE_NOT_DELIVERED`)".

        Design: Corner/errors/err_pledge_not_delivered_on_replacement
        """
        campaign = setup_live_campaign()
        pledge = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        from test_helpers import make_backer_headers

        resp = api.create_replacement_request(
            {
                "campaign_id": campaign["id"],
                "pledge_id": pledge["id"],
                "component_sku": "base",
                "quantity": 1,
            },
            make_backer_headers("b1"),
        )
        validate_error(resp, ApiErrorId.ERR_PLEDGE_NOT_DELIVERED)


class TestLocalization:
    def test_localization_cyclic_renegotiation(self, api):
        """PRD §3.10: "Renegotiation (`SIGNED → NEGOTIATING`) is allowed
        while the campaign is `CLOSED_SUCCESS` or `IN_PRODUCTION` and removes
        the commitment from quote computations, making the sign/renegotiate
        pair a cyclic loop."

        Design: Difficulty/non_linear_state_machine/localization_cyclic_renegotiation
        """
        campaign = setup_closed_success_campaign()
        agreement = create_localization_agreement(campaign["id"])
        resp = api.transition_localization_agreement(
            agreement["id"], {"action": "sign"}, LOCAL
        )
        assert validate_success(resp)["status"] == "SIGNED"
        resp = api.transition_localization_agreement(
            agreement["id"], {"action": "renegotiate"}, LOCAL
        )
        assert validate_success(resp)["status"] == "NEGOTIATING"
        resp = api.transition_localization_agreement(
            agreement["id"], {"action": "sign"}, LOCAL
        )
        assert validate_success(resp)["status"] == "SIGNED"

    def test_localization_second_sign_after_renegotiate_succeeds(self, api):
        """PRD §3.10: "Signing (`NEGOTIATING → SIGNED`) is the moment the
        partner's `print_commitment_units` begin counting into manufacturing
        quote computations".

        Design: Difficulty/non_linear_state_machine/localization_cyclic_renegotiation
        """
        campaign = setup_closed_success_campaign()
        agreement = create_localization_agreement(campaign["id"])
        for action in ("sign", "renegotiate", "sign"):
            resp = api.transition_localization_agreement(
                agreement["id"], {"action": action}, LOCAL
            )
            validate_success(resp)
        final = validate_success(
            api.get_localization_agreement(agreement["id"], ADMIN)
        )
        assert final["status"] == "SIGNED"

    def test_localization_window_vs_freight_window_overlap(self, api):
        """PRD §3.10: "the print window must not overlap the sailing window
        of any shipment on the same campaign in `BOOKED`, `IN_TRANSIT`,
        `CUSTOMS_HOLD`, `DUTY_ASSESSED`, or `CLEARED` status — half-open
        semantics make adjacency legal — or the signing is rejected with
        `ERR_PRINT_WINDOW_OVERLAP`."

        Freight BOOKED [10-15, 11-15): print window [10-01, 11-01) overlaps
        → rejected; print window [11-15, 12-15) is adjacent → signs.

        Design: Difficulty/resource_temporal_overlap/localization_window_vs_freight_window_overlap
        """
        campaign = setup_closed_success_campaign()
        quote = create_quote(campaign["id"])
        submit_quote(quote["id"])
        api.transition_manufacturing_quote(
            quote["id"], {"action": "finalize"}, FACTORY
        )
        run = create_run(campaign["id"], quote["id"])
        book_freight(
            run["id"],
            departs_at="2026-10-15T00:00:00Z",
            arrives_at="2026-11-15T00:00:00Z",
        )
        overlapping = create_localization_agreement(
            campaign["id"],
            language_code="fr",
            print_window_start="2026-10-01T00:00:00Z",
            print_window_end="2026-11-01T00:00:00Z",
        )
        adjacent = create_localization_agreement(
            campaign["id"],
            language_code="de",
            print_window_start="2026-11-15T00:00:00Z",
            print_window_end="2026-12-15T00:00:00Z",
        )
        resp = api.transition_localization_agreement(
            overlapping["id"], {"action": "sign"}, LOCAL
        )
        validate_error(resp, ApiErrorId.ERR_PRINT_WINDOW_OVERLAP)
        resp = api.transition_localization_agreement(
            adjacent["id"], {"action": "sign"}, LOCAL
        )
        assert validate_success(resp)["status"] == "SIGNED"

    def test_localization_sign_rejects_contained_print_window(self, api):
        """PRD §3.10: "the print window must not overlap the sailing window
        of any shipment on the same campaign in `BOOKED`, `IN_TRANSIT`,
        `CUSTOMS_HOLD`, `DUTY_ASSESSED`, or `CLEARED` status — half-open
        semantics make adjacency legal — or the signing is rejected with
        `ERR_PRINT_WINDOW_OVERLAP`."

        A print window fully inside an active freight sailing window
        overlaps and is rejected.

        Design: Difficulty/resource_temporal_overlap/localization_window_vs_freight_window_overlap
        """
        campaign = setup_closed_success_campaign()
        quote = create_quote(campaign["id"])
        submit_quote(quote["id"])
        api.transition_manufacturing_quote(
            quote["id"], {"action": "finalize"}, FACTORY
        )
        run = create_run(campaign["id"], quote["id"])
        book_freight(
            run["id"],
            departs_at="2026-10-15T00:00:00Z",
            arrives_at="2026-11-15T00:00:00Z",
        )
        contained = create_localization_agreement(
            campaign["id"],
            language_code="fr",
            print_window_start="2026-10-20T00:00:00Z",
            print_window_end="2026-10-25T00:00:00Z",
        )
        resp = api.transition_localization_agreement(
            contained["id"], {"action": "sign"}, LOCAL
        )
        validate_error(resp, ApiErrorId.ERR_PRINT_WINDOW_OVERLAP)


class TestDistributorRetailRelease:
    def test_err_retail_release_too_early(self, api):
        """PRD §3.8: "Shipping a confirmed allocation (`CONFIRMED →
        SHIPPED`, by a `FulfillmentOperator`) is gated on retail timing: the
        campaign's `retail_release_at` must be set and the logical clock must
        have reached it, otherwise `ERR_RETAIL_RELEASE_TOO_EARLY`."
        PRD §3.6: "Until every wave is dispatched, `retail_release_at` is
        null."

        Design: Corner/errors/err_retail_release_too_early
        """
        from test_helpers import (
            create_wave,
            make_distributor_headers,
            open_wave,
            refund_pledge,
            setup_campaign_with_cleared_freight,
        )

        bundle = setup_campaign_with_cleared_freight()
        campaign = bundle["campaign"]
        wave = create_wave(campaign["id"])
        open_wave(wave["id"])
        # Campaign is FULFILLING; no wave dispatched yet → retail_release_at null.
        # planned_units is 2 and the fixture charged one pledge; refunding it
        # (allowed in FULFILLING per PRD §3.3) opens pool room for a 1-unit
        # reservation.
        refund_pledge(bundle["charged_pledge"]["id"])
        allocation = create_distributor_allocation(
            campaign["id"], bundle["run"]["id"], units_reserved=1
        )
        resp = api.transition_distributor_allocation(
            allocation["id"],
            {"action": "confirm"},
            make_distributor_headers(allocation["distributor_user_id"]),
        )
        validate_success(resp)
        resp = api.transition_distributor_allocation(
            allocation["id"], {"action": "ship"}, FULFILL
        )
        validate_error(resp, ApiErrorId.ERR_RETAIL_RELEASE_TOO_EARLY)
