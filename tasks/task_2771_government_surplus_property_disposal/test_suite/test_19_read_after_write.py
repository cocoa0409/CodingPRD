"""Read-your-writes and cross-aggregate visibility.

The PRD exposes no refresh, recompute or settle endpoint anywhere. Every derived
figure — an asset's valuation, a lot's reserve and roll-ups, the invoice the close
cascade raises, an agency's proceeds ledger — is produced as a side effect of the
business write that caused it, and must therefore be readable by the immediately
following request, including through the list filters the PRD names.
"""

from test_helpers import (
    CLOCK_EPOCH,
    api_client,
    assert_agency,
    assert_auction_lot,
    assert_proceeds_distribution,
    assert_proceeds_ledger_invariant,
    assert_sale_invoice,
    assert_surplus_asset,
    assert_timestamp_format,
    assert_transfer_order,
    assert_turn_in,
    create_agency_payload,
    create_asset_payload,
    create_auction_lot_payload,
    create_bid_payload,
    create_bidder_payload,
    create_condition_assessment_payload,
    create_payment_payload,
    create_proceeds_distribution_payload,
    create_turn_in_payload,
    create_venue_payload,
    get_success_data,
    make_agency_officer_headers,
    make_bidder_headers,
    make_disposal_officer_headers,
    make_finance_controller_headers,
    make_program_admin_headers,
    make_surplus_assessor_headers,
    read_agency,
    read_asset,
    read_lot,
    set_clock,
    setup_acknowledged_transfer_order,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers()
ASSESSOR = make_surplus_assessor_headers()
OFFICER = make_disposal_officer_headers()
FINANCE = make_finance_controller_headers()


def _sale_chain_preconditions() -> dict:
    """One ACTIVE organisation with a SUBMITTED turn-in holding a FURNITURE asset
    acquired 2024-05-20 for 104500 cents, one ACTIVE venue and one REGISTERED
    bidder, with the logical clock at 2026-08-01T00:00:00Z."""
    set_clock(CLOCK_EPOCH)
    agency = get_success_data(
        api_client.create_agency(create_agency_payload(), ADMIN)
    )
    agency_headers = make_agency_officer_headers(agency["id"])
    turn_in = get_success_data(
        api_client.create_turn_in(
            create_turn_in_payload(agency["id"], custody_location="Austin Yard 4"),
            agency_headers,
        )
    )
    asset = get_success_data(
        api_client.create_asset(
            create_asset_payload(
                turn_in["id"], description="Lateral file cabinets, single pallet"
            ),
            agency_headers,
        )
    )
    get_success_data(api_client.submit_turn_in(turn_in["id"], agency_headers))
    venue = get_success_data(
        api_client.create_venue(
            create_venue_payload(name="Austin Auction Yard"), ADMIN
        )
    )
    bidder = get_success_data(
        api_client.create_bidder(
            create_bidder_payload(
                legal_name="Cedar Ridge Salvage LLC",
                email="bids@cedarridge.example",
            ),
            ADMIN,
        )
    )
    bidder = get_success_data(
        api_client.set_bidder_status(bidder["id"], "REGISTERED", ADMIN)
    )
    return {
        "agency": agency,
        "agency_headers": agency_headers,
        "turn_in": turn_in,
        "asset": asset,
        "venue": venue,
        "bidder": bidder,
        "bidder_headers": make_bidder_headers(bidder["id"]),
    }


class TestDerivedValuesAreReadableImmediatelyAfterTheWrite:
    """Every derived money field in the sale chain is visible to the next request."""

    def test_valuation_is_on_the_asset_in_the_read_after_the_assessment(self):
        """The GET straight after the assessment already carries the valuation.

        "Multiply `acquisition_cost_cents` by the condition factor, the age factor
        and the functional factor, and round that single product half up to whole
        cents."

        "The first assessment on an asset drives `disposition_status` from `INTAKE`
        to `ASSESSED`."

        Design: Corner/consistency_model/cm_derived_values_are_readable_immediately_after_the_write_that_produces_them
        """
        setup = _sale_chain_preconditions()
        asset = setup["asset"]
        assert asset["fair_market_value_cents"] is None, (
            "the valuation stays null until the first assessment exists"
        )

        validate_success(
            api_client.create_condition_assessment(
                asset["id"],
                create_condition_assessment_payload(
                    asset["version"],
                    condition_code="C6",
                    functional=True,
                    repair_cost_estimate_cents=0,
                    assessed_on="2026-07-31",
                ),
                ASSESSOR,
            ),
            201,
        )

        seen = validate_success(api_client.get_asset(asset["id"], OFFICER))
        assert_surplus_asset(seen)
        assert seen["fair_market_value_cents"] == 12540, (
            "104500 cents at the C6 factor of fifteen hundredths and the two-full-"
            f"year age factor, got {seen['fair_market_value_cents']}"
        )
        assert seen["condition_code"] == "C6", (
            "the governing assessment's condition code is copied onto the asset"
        )
        assert seen["disposition_status"] == "ASSESSED"

    def test_reserve_and_deposit_appear_on_the_lot_at_creation_and_on_the_next_read(self):
        """The create response and the following GET carry identical derived figures.

        "By default the reserve is derived from the asset's stored valuation: take
        sixty hundredths of `fair_market_value_cents`, round that product half up to
        whole cents, and use the larger of that figure and twenty-five dollars."

        "Where the `DisposalOfficer` supplies a `reserve_price_cents` in the request,
        that value is stored verbatim without any formula being applied, and the lot
        records `reserve_source` as `OFFICER_OVERRIDE`; where the officer supplies
        nothing, the computed figure is stored and `reserve_source` is `COMPUTED`."

        "A reserve below five thousand dollars requires no deposit at all and
        `required_deposit_cents` is 0."

        Design: Corner/consistency_model/cm_derived_values_are_readable_immediately_after_the_write_that_produces_them
        """
        setup = _sale_chain_preconditions()
        asset = setup["asset"]
        validate_success(
            api_client.create_condition_assessment(
                asset["id"],
                create_condition_assessment_payload(
                    asset["version"],
                    condition_code="C6",
                    functional=True,
                    repair_cost_estimate_cents=0,
                    assessed_on="2026-07-31",
                ),
                ASSESSOR,
            ),
            201,
        )
        get_success_data(
            api_client.review_turn_in(
                setup["turn_in"]["id"], {"decision": "ACCEPT"}, OFFICER
            )
        )

        created = validate_success(
            api_client.create_auction_lot(
                create_auction_lot_payload(
                    asset["id"],
                    setup["venue"]["id"],
                    opens_at="2026-08-02T00:00:00Z",
                    closes_at="2026-08-03T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        assert_auction_lot(created)
        assert created["reserve_price_cents"] == 7524, (
            "sixty hundredths of the 12540-cent valuation, got "
            f"{created['reserve_price_cents']}"
        )
        assert created["reserve_source"] == "COMPUTED"
        assert created["required_deposit_cents"] == 0, (
            "a 7524-cent reserve is below the five-thousand-dollar threshold, got "
            f"{created['required_deposit_cents']}"
        )

        seen = validate_success(api_client.get_auction_lot(created["id"], FINANCE))
        assert seen["reserve_price_cents"] == created["reserve_price_cents"]
        assert seen["reserve_source"] == created["reserve_source"]
        assert seen["required_deposit_cents"] == created["required_deposit_cents"]
        assert seen["high_bid_cents"] == 0 and seen["bid_count"] == 0

    def test_the_whole_sale_chain_is_readable_one_request_at_a_time(self):
        """Valuation, roll-ups, invoice, settlement and ledger each land at once.

        "An accepted bid is created in `status` `ACTIVE` with `placed_at` stamped
        from the logical clock, and it recomputes two roll-ups on the lot:
        `high_bid_cents` becomes the largest `amount_cents` among the lot's bids
        whose `status` is `ACTIVE` or `WINNING`, and 0 when that set is empty;
        `bid_count` becomes the number of the lot's bids whose `status` is `ACTIVE`,
        `WINNING` or `OUTBID`, which deliberately excludes retracted ones."

        "They may be read individually or listed narrowed by `auction_lot_id`, by
        `bidder_id` or by `status`, and that listing is the only discovery channel
        for the invoice the close cascade produces."

        "A payment that leaves a balance moves the invoice `ISSUED` →
        `PARTIALLY_PAID`, or holds it at `PARTIALLY_PAID` on later instalments; a
        payment that brings `amount_paid_cents` exactly up to `total_due_cents`
        moves it to `PAID`, and that settlement in turn moves the lot `CLOSED_MET`
        → `SETTLED`."

        "The post stamps `posted_by_user_id` and `posted_at`, moves the row to
        `POSTED`, and in a second hop caused by that stamping recomputes the
        beneficiary agency's `proceeds_account_balance_cents` and
        `posted_distribution_count`."

        Design: Corner/consistency_model/cm_derived_values_are_readable_immediately_after_the_write_that_produces_them
        """
        setup = _sale_chain_preconditions()
        asset = setup["asset"]
        bidder = setup["bidder"]

        validate_success(
            api_client.create_condition_assessment(
                asset["id"],
                create_condition_assessment_payload(
                    asset["version"],
                    condition_code="C6",
                    functional=True,
                    repair_cost_estimate_cents=0,
                    assessed_on="2026-07-31",
                ),
                ASSESSOR,
            ),
            201,
        )
        assert read_asset(asset["id"])["fair_market_value_cents"] == 12540

        get_success_data(
            api_client.review_turn_in(
                setup["turn_in"]["id"], {"decision": "ACCEPT"}, OFFICER
            )
        )
        lot = get_success_data(
            api_client.create_auction_lot(
                create_auction_lot_payload(
                    asset["id"],
                    setup["venue"]["id"],
                    opens_at="2026-08-02T00:00:00Z",
                    closes_at="2026-08-03T00:00:00Z",
                ),
                OFFICER,
            )
        )

        set_clock("2026-08-02T00:00:00Z")
        get_success_data(api_client.open_auction_lot(lot["id"], OFFICER))
        validate_success(
            api_client.place_bid(
                lot["id"],
                create_bid_payload(bidder["id"], 10_000),
                setup["bidder_headers"],
            ),
            201,
        )

        after_bid = validate_success(api_client.get_auction_lot(lot["id"], FINANCE))
        assert after_bid["high_bid_cents"] == 10_000, (
            "the bid's roll-up must be readable with no intervening write, got "
            f"{after_bid['high_bid_cents']}"
        )
        assert after_bid["bid_count"] == 1, (
            f"one live bid on the lot, got {after_bid['bid_count']}"
        )

        set_clock("2026-08-03T00:00:00Z")
        get_success_data(api_client.close_auction_lot(lot["id"], OFFICER))

        rows, meta = validate_paginated(
            api_client.list_sale_invoices(
                FINANCE, params={"auction_lot_id": lot["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "the cascade-created invoice is filterable at once, got "
            f"{meta['total_count']}"
        )
        invoice = rows[0]
        assert_sale_invoice(invoice)
        assert invoice["total_due_cents"] == 11752, (
            "10000 hammer plus 1050 premium plus 702 tax, got "
            f"{invoice['total_due_cents']}"
        )
        assert invoice["status"] == "ISSUED"

        validate_success(
            api_client.pay_sale_invoice(
                invoice["id"], create_payment_payload(11752), setup["bidder_headers"]
            )
        )
        paid = validate_success(
            api_client.get_sale_invoice(invoice["id"], FINANCE)
        )
        assert paid["status"] == "PAID", (
            f"a payment covering the whole total settles the invoice, got {paid['status']}"
        )
        assert paid["balance_due_cents"] == 0
        settled = validate_success(api_client.get_auction_lot(lot["id"], FINANCE))
        assert settled["status"] == "SETTLED", (
            f"settlement moves the lot to SETTLED, got {settled['status']}"
        )

        distribution = validate_success(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot["id"], settled["version"], basis="ACCRUAL"
                ),
                FINANCE,
            ),
            201,
        )
        assert_proceeds_distribution(distribution)
        assert distribution["distributable_base_cents"] == 10_000
        assert distribution["service_fee_cents"] == 1250, (
            "10000 wholly inside the first slice at twelve and a half hundredths, "
            f"got {distribution['service_fee_cents']}"
        )
        assert distribution["net_to_agency_cents"] == 8750

        before = read_agency(setup["agency"]["id"])
        assert before["proceeds_account_balance_cents"] == 0, (
            "a merely calculated distribution moves no money"
        )
        assert before["posted_distribution_count"] == 0

        validate_success(
            api_client.post_proceeds_distribution(distribution["id"], FINANCE)
        )
        after = validate_success(
            api_client.get_agency(setup["agency"]["id"], FINANCE)
        )
        assert_agency(after)
        assert after["proceeds_account_balance_cents"] == 8750, (
            "the ledger recompute is part of the posting request, got "
            f"{after['proceeds_account_balance_cents']}"
        )
        assert after["posted_distribution_count"] == 1, (
            f"one posted distribution, got {after['posted_distribution_count']}"
        )

    def test_posting_leaves_the_proceeds_ledger_balanced_on_the_next_read(self):
        """The ledger identity holds against the very next read of both sides.

        "The `net_to_agency_cents` is the larger of zero and the base less the
        service fee less the cost recovery."

        "The post stamps `posted_by_user_id` and `posted_at`, moves the row to
        `POSTED`, and in a second hop caused by that stamping recomputes the
        beneficiary agency's `proceeds_account_balance_cents` and
        `posted_distribution_count`."

        Design: Corner/consistency_model/cm_derived_values_are_readable_immediately_after_the_write_that_produces_them
        """
        setup = _sale_chain_preconditions()
        asset = setup["asset"]

        validate_success(
            api_client.create_condition_assessment(
                asset["id"],
                create_condition_assessment_payload(
                    asset["version"],
                    condition_code="C6",
                    functional=True,
                    repair_cost_estimate_cents=0,
                    assessed_on="2026-07-31",
                ),
                ASSESSOR,
            ),
            201,
        )
        get_success_data(
            api_client.review_turn_in(
                setup["turn_in"]["id"], {"decision": "ACCEPT"}, OFFICER
            )
        )
        lot = get_success_data(
            api_client.create_auction_lot(
                create_auction_lot_payload(
                    asset["id"],
                    setup["venue"]["id"],
                    opens_at="2026-08-02T00:00:00Z",
                    closes_at="2026-08-03T00:00:00Z",
                ),
                OFFICER,
            )
        )
        set_clock("2026-08-02T00:00:00Z")
        get_success_data(api_client.open_auction_lot(lot["id"], OFFICER))
        get_success_data(
            api_client.place_bid(
                lot["id"],
                create_bid_payload(setup["bidder"]["id"], 10_000),
                setup["bidder_headers"],
            )
        )
        set_clock("2026-08-03T00:00:00Z")
        get_success_data(api_client.close_auction_lot(lot["id"], OFFICER))

        distribution = get_success_data(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot["id"], read_lot(lot["id"])["version"], basis="ACCRUAL"
                ),
                FINANCE,
            )
        )
        posted = validate_success(
            api_client.post_proceeds_distribution(distribution["id"], FINANCE)
        )
        assert posted["status"] == "POSTED"
        assert_timestamp_format(posted["posted_at"])

        agencies, _ = validate_paginated(api_client.list_agencies(FINANCE))
        distributions, _ = validate_paginated(
            api_client.list_proceeds_distributions(FINANCE)
        )
        assert_proceeds_ledger_invariant(agencies, distributions)
        assert sum(
            a["proceeds_account_balance_cents"] for a in agencies
        ) == 8750, "the whole net lands on the beneficiary's ledger"


class TestCascadedCrossAggregateStateIsVisibleToTheNextRequest:
    """One release moves the asset, its transfer order and its turn-in at once."""

    @staticmethod
    def _acknowledged_transfer_of_a_state_agency_asset() -> dict:
        """A FURNITURE asset acquired 2026-01-10 for 1000000 cents, assessed C1 and
        awarded to a second STATE_AGENCY on an ACKNOWLEDGED transfer order, with the
        logical clock at 2026-08-02T00:00:00Z."""
        return setup_acknowledged_transfer_order(
            recipient_kind="state_agency",
            kind="furniture",
            clock="2026-08-02T00:00:00Z",
            asset_overrides={
                "description": "Modular workstation cluster",
                "acquisition_cost_cents": 1_000_000,
                "acquisition_date": "2026-01-10",
            },
            assessment_overrides={
                "condition_code": "C1",
                "functional": True,
                "repair_cost_estimate_cents": 0,
                "assessed_on": "2026-07-30",
            },
        )

    def test_release_response_already_reports_the_released_asset(self):
        """The releasing call's own response carries the new state and stamp.

        "A successful release stores `released_at` from the logical clock along with
        the supplied `odometer_disclosure_reading`, `lien_release_reference` and
        `title_recipient_name`, and moves the asset to `RELEASED`."

        Design: Corner/consistency_model/cm_cascaded_cross_aggregate_state_is_visible_to_the_next_request
        """
        scenario = self._acknowledged_transfer_of_a_state_agency_asset()
        asset = scenario["asset"]
        assert asset["disposition_status"] == "AWARDED_TRANSFER"
        assert asset["clearance_status"] == "NOT_REQUIRED", (
            "furniture is neither data-bearing nor restricted, so its gate is open"
        )
        assert asset["released_at"] is None

        released = validate_success(
            api_client.release_asset(asset["id"], {}, OFFICER)
        )
        assert_surplus_asset(released)
        assert released["disposition_status"] == "RELEASED", (
            f"the release response itself must report RELEASED, got "
            f"{released['disposition_status']}"
        )
        assert_timestamp_format(released["released_at"])
        assert released["released_at"][:19] == "2026-08-02T00:00:00", (
            "released_at is stamped from the logical clock, got "
            f"{released['released_at']}"
        )

    def test_transfer_order_and_turn_in_are_current_on_the_next_direct_reads(self):
        """Two aggregates the release never addressed are already up to date.

        "From `AWARDED_TRANSFER`, a second hop caused by the asset leaving custody
        moves the asset's `ACKNOWLEDGED` `TransferOrder` to `COMPLETED` and, where
        the asset's `federal_source` is true, computes that order's
        `use_period_end_on` by adding the asset category's use-period months to the
        calendar date of the order's `acknowledged_at`, with the same day-of-month
        clamping described in §2.4 — the recipient inherits an obligation of its
        own, counted from when it accepted the paperwork rather than from when the
        property moved."

        "A final hop bubbles upward exactly as destruction does: when every asset of
        the parent turn-in has reached a terminal disposition, the turn-in moves
        `ACCEPTED` → `CLOSED`."

        "First, read the recipient's discount factor from its `agency_type`: a
        `STATE_AGENCY` pays twenty-five hundredths of value, a `LOCAL_GOVERNMENT`
        pays fifty hundredths, and an `ELIGIBLE_NONPROFIT` pays ten hundredths."

        Design: Corner/consistency_model/cm_cascaded_cross_aggregate_state_is_visible_to_the_next_request
        """
        scenario = self._acknowledged_transfer_of_a_state_agency_asset()
        order = scenario["transfer_order"]
        recipient_headers = make_agency_officer_headers(scenario["recipient"]["id"])
        assert order["status"] == "ACKNOWLEDGED"

        validate_success(
            api_client.release_asset(scenario["asset"]["id"], {}, OFFICER)
        )

        seen_order = validate_success(
            api_client.get_transfer_order(order["id"], recipient_headers)
        )
        assert_transfer_order(seen_order)
        assert seen_order["status"] == "COMPLETED", (
            "the release completes the acknowledged order without the order ever "
            f"being addressed, got {seen_order['status']}"
        )
        assert seen_order["base_transfer_cents"] == 250_000, (
            "twenty-five hundredths of the 1000000-cent valuation, got "
            f"{seen_order['base_transfer_cents']}"
        )
        assert seen_order["handling_fee_cents"] == 12500, (
            "a base of 250000 sits in the middle handling band, got "
            f"{seen_order['handling_fee_cents']}"
        )
        assert seen_order["transfer_price_cents"] == 262_500, (
            "250000 base plus the 12500 handling fee, got "
            f"{seen_order['transfer_price_cents']}"
        )
        assert seen_order["use_period_end_on"] is None, (
            "the asset is not federal_source, so no use period is inherited"
        )

        seen_turn_in = validate_success(
            api_client.get_turn_in(
                scenario["turn_in"]["id"],
                make_agency_officer_headers(scenario["agency"]["id"]),
            )
        )
        assert_turn_in(seen_turn_in)
        assert seen_turn_in["status"] == "CLOSED", (
            "the turn-in's only asset reached a terminal disposition, got "
            f"{seen_turn_in['status']}"
        )

    def test_the_cascaded_statuses_are_filterable_immediately(self):
        """The new statuses are indexed for list filters, not just direct reads.

        "Orders may be listed narrowed by `asset_id`, by `recipient_agency_id`, by
        `screening_request_id` or by `status`."

        "Turn-in listings may be narrowed by `turning_in_agency_id` or by `status`."

        "Asset listings may be narrowed by `turn_in_id`, by `component_of_asset_id`,
        by `category`, by `disposition_status` or by `clearance_status`."

        Design: Corner/consistency_model/cm_cascaded_cross_aggregate_state_is_visible_to_the_next_request
        """
        scenario = self._acknowledged_transfer_of_a_state_agency_asset()
        asset_id = scenario["asset"]["id"]

        validate_success(api_client.release_asset(asset_id, {}, OFFICER))

        rows, meta = validate_paginated(
            api_client.list_transfer_orders(
                FINANCE, params={"asset_id": asset_id, "status": "COMPLETED"}
            )
        )
        assert meta["total_count"] == 1, (
            "the completed order must be filterable at once, got "
            f"{meta['total_count']}"
        )
        assert rows[0]["id"] == scenario["transfer_order"]["id"]

        rows, meta = validate_paginated(
            api_client.list_turn_ins(
                ADMIN,
                params={
                    "turning_in_agency_id": scenario["agency"]["id"],
                    "status": "CLOSED",
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"the closed turn-in must be filterable at once, got {meta['total_count']}"
        )
        assert rows[0]["id"] == scenario["turn_in"]["id"]

        rows, meta = validate_paginated(
            api_client.list_assets(ADMIN, params={"disposition_status": "RELEASED"})
        )
        assert meta["total_count"] == 1, (
            f"exactly one released asset exists, got {meta['total_count']}"
        )
        assert rows[0]["id"] == asset_id

    def test_the_pre_release_filters_return_nothing_for_the_new_statuses(self):
        """Before the release the same filters are empty, so the reads are meaningful.

        "An acknowledged order reaches `COMPLETED`, its other terminal state, only
        as a consequence of release."

        "Whenever an operation leaves every one of an `ACCEPTED` turn-in's assets in
        a terminal `disposition_status` — that is, every asset is `RELEASED`,
        `RETAINED` or `DESTROYED` — the turn-in moves from `ACCEPTED` to `CLOSED` on
        the server's own initiative, its `appraised_total_cents` freezes at its
        then-current value, and its `version` increments by 1."

        Design: Corner/consistency_model/cm_cascaded_cross_aggregate_state_is_visible_to_the_next_request
        """
        scenario = self._acknowledged_transfer_of_a_state_agency_asset()

        _, meta = validate_paginated(
            api_client.list_transfer_orders(FINANCE, params={"status": "COMPLETED"})
        )
        assert meta["total_count"] == 0, (
            "no order is completed while the asset is still in custody"
        )
        _, meta = validate_paginated(
            api_client.list_turn_ins(ADMIN, params={"status": "CLOSED"})
        )
        assert meta["total_count"] == 0, (
            "the turn-in only closes once its asset reaches a terminal disposition"
        )
        _, meta = validate_paginated(
            api_client.list_assets(ADMIN, params={"disposition_status": "RELEASED"})
        )
        assert meta["total_count"] == 0

        validate_success(
            api_client.release_asset(scenario["asset"]["id"], {}, OFFICER)
        )

        for params, endpoint in (
            ({"status": "COMPLETED"}, api_client.list_transfer_orders),
            ({"status": "CLOSED"}, api_client.list_turn_ins),
            ({"disposition_status": "RELEASED"}, api_client.list_assets),
        ):
            headers = FINANCE if endpoint is api_client.list_transfer_orders else ADMIN
            _, meta = validate_paginated(endpoint(headers, params=params))
            assert meta["total_count"] == 1, (
                f"{params} must match exactly one row straight after the release, "
                f"got {meta['total_count']}"
            )
