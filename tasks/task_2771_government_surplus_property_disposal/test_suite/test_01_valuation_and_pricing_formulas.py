"""Valuation and pricing arithmetic for the Government Surplus Property Disposal API.

Every figure asserted here is whole cents. The PRD pins both the rounding
placement and the input set of each formula, so the expectations below are exact
integer equalities and never approximations.
"""

from datetime import datetime, timezone

from test_helpers import (
    CLOCK_EPOCH,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    advance_tier,
    api_client,
    assert_auction_lot,
    assert_condition_assessment,
    assert_proceeds_distribution,
    assert_proceeds_net,
    assert_sale_invoice,
    assert_surplus_asset,
    assert_transfer_order,
    certify_clearance,
    create_lot,
    create_proceeds_distribution_payload,
    create_transfer_order_payload,
    file_screening_request,
    find_invoice_for_lot,
    get_success_data,
    list_lot_bids,
    make_agency_officer_headers,
    open_screening_cycle,
    pay_invoice,
    place_bid,
    read_agency,
    read_asset,
    read_distribution,
    read_invoice,
    read_lot,
    read_transfer_order,
    register_bidder,
    register_local_government,
    register_venue,
    set_clock,
    setup_assessed_assets,
    setup_auction_eligible_asset,
    setup_open_lot,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OFFICER = TEST_USERS["disposal_officer_headers"]
_FINANCE = TEST_USERS["finance_controller_headers"]


def _as_instant(value: str) -> datetime:
    """The PRD writes every instant as a UTC timestamp carrying three fractional
    digits, so stored instants are compared as instants rather than as strings."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

# ─── Shared scenario literals ─────────────────────────────────────────────

# A 2019 three-quarter ton pickup at C4 / functional with a 185000 repair
# estimate: 3217467 * 0.50 * 0.30 * 1.00 rounds to 482620, less 185000 leaves
# a fair_market_value_cents of 297620.
_PICKUP_ASSESSMENT = {
    "condition_code": "C4",
    "functional": True,
    "repair_cost_estimate_cents": 185000,
    "assessed_on": "2026-07-28",
}
_PICKUP_UNIT_1 = {
    "description": "2019 Ford F-250 three-quarter ton pickup, unit 1",
    "vin": "1FT7W2BT9KEB12345",
    "odometer_reading": 184320,
    "title_number": "TX-88231",
}
_PICKUP_UNIT_2 = {
    "description": "2019 Ford F-250 three-quarter ton pickup, unit 2",
    "vin": "1FT7W2BT9KEB12346",
    "odometer_reading": 179880,
    "title_number": "TX-88232",
}

# A 2023 rack server at C2 / functional with no repair estimate:
# 1449920 * 0.85 * 0.80 * 1.00 rounds to a fair_market_value_cents of 985946.
_SERVER_ASSESSMENT = {
    "condition_code": "C2",
    "functional": True,
    "repair_cost_estimate_cents": 0,
    "assessed_on": "2026-07-30",
}


# ─── Scenario builders ────────────────────────────────────────────────────

def _setup_twin_pickups_on_the_two_channels() -> dict:
    """Two structurally identical pickups on one ACCEPTED turn-in, both valued at
    297620 cents, one steered down the screening channel and one down the auction
    channel.

    Asset X is awarded to a CERTIFIED local government through the
    LOCAL_GOVERNMENT tier, so it sits at AWARDED_TRANSFER awaiting a transfer
    order. Asset Y walks the ladder to exhaustion, so it sits at
    AUCTION_ELIGIBLE awaiting a lot.
    """
    scenario = setup_assessed_assets(
        [
            {
                "kind": "vehicle",
                "overrides": _PICKUP_UNIT_1,
                "assessment": _PICKUP_ASSESSMENT,
            },
            {
                "kind": "vehicle",
                "overrides": _PICKUP_UNIT_2,
                "assessment": _PICKUP_ASSESSMENT,
            },
        ],
        clock=CLOCK_EPOCH,
    )
    asset_x, asset_y = scenario["assets"]

    recipient = register_local_government(
        federal_donee_status="CERTIFIED",
        donee_certification_expires_on="2027-03-31",
    )

    cycle_x = open_screening_cycle(
        asset_x["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
    )
    advance_tier(cycle_x["id"], 1)
    request_x = file_screening_request(cycle_x["id"], recipient["id"])
    get_success_data(
        api_client.award_screening_cycle(cycle_x["id"], request_x["id"], _OFFICER)
    )

    cycle_y = open_screening_cycle(
        asset_y["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
    )
    advance_tier(cycle_y["id"], 4)

    scenario["recipient"] = recipient
    scenario["asset_x"] = read_asset(asset_x["id"])
    scenario["asset_y"] = read_asset(asset_y["id"])
    scenario["request_x"] = request_x
    scenario["venue"] = register_venue()
    return scenario


def _setup_defaulted_invoice_on_a_settled_server_lot() -> dict:
    """One data-bearing rack server valued at 985946, carried to auction, sold at
    a hammer price of 640000 and then part-paid to 200000 before the buyer
    defaults.

    The 59157 deposit is applied first and topped up with 140843 cash, so the
    invoice freezes at amount_paid_cents 200000 against a total_due_cents of
    752107. The lot stays CLOSED_MET, which is what leaves both distribution
    bases available on identical lot data.
    """
    scenario = setup_auction_eligible_asset(
        kind="it_equipment",
        tier_window_days=3,
        clock=CLOCK_EPOCH,
        asset_overrides={
            "description": "Dell PowerEdge R740 rack server with 8 SAS drives",
            "is_data_bearing": True,
        },
        assessment_overrides=_SERVER_ASSESSMENT,
    )
    asset = scenario["asset"]

    # One verified sanitisation certificate, filed by a technician who never
    # appraised the item, so the cost-recovery count is exactly one.
    scenario["certificate"] = certify_clearance(
        asset["id"],
        technician_user_id=TECHNICIAN_USER_ID,
        cert_type="DATA_SANITIZATION",
        method="NIST_PURGE",
        serials_verified=True,
        certified_on="2026-07-31",
    )

    venue = register_venue()
    lot = create_lot(
        asset["id"], venue["id"],
        opens_at="2026-09-01T00:00:00Z", closes_at="2026-09-05T00:00:00Z",
    )

    set_clock("2026-09-01T00:00:00Z")
    get_success_data(api_client.open_auction_lot(lot["id"], _OFFICER))

    bidder = register_bidder(
        status="REGISTERED",
        deposit_cents=59157,
        legal_name="Lone Star Equipment LLC",
        email="bids@lonestar.example",
        bidder_type="BUSINESS",
    )
    place_bid(lot["id"], bidder["id"], 640000)

    set_clock("2026-09-05T00:00:00Z")
    get_success_data(api_client.close_auction_lot(lot["id"], _OFFICER))

    invoice = find_invoice_for_lot(lot["id"])
    assert invoice is not None, "the close cascade must issue a SaleInvoice"
    pay_invoice(invoice["id"], bidder["id"], 140843, use_deposit=True)

    set_clock("2026-09-13T00:00:00Z")
    get_success_data(
        api_client.default_sale_invoice(
            invoice["id"],
            "Seven-day payment term lapsed with 552107 outstanding",
            _FINANCE,
        )
    )

    scenario["venue"] = venue
    scenario["bidder"] = bidder
    scenario["lot"] = read_lot(lot["id"])
    scenario["invoice"] = read_invoice(invoice["id"])
    scenario["asset"] = read_asset(asset["id"])
    return scenario


def _setup_three_awarded_transfer_candidates() -> dict:
    """Three assets on one ACCEPTED turn-in, each awarded to the same CERTIFIED
    local government through its own screening cycle.

    Asset F is a federally sourced switch stack whose own use period ended
    2026-06-15, asset N is its non-federal twin, and asset B is a furniture
    cluster valued so that the LOCAL_GOVERNMENT base lands exactly on 100000.
    """
    scenario = setup_assessed_assets(
        [
            {
                "kind": "it_equipment",
                "overrides": {
                    "description": "Federal-donated switch stack",
                    "federal_source": True,
                    "federal_use_period_start_on": "2025-06-15",
                },
                "assessment": _SERVER_ASSESSMENT,
            },
            {
                "kind": "it_equipment",
                "overrides": {"description": "State-purchased switch stack"},
                "assessment": _SERVER_ASSESSMENT,
            },
            {
                "kind": "furniture",
                "overrides": {
                    "description": "Modular workstation cluster",
                    "acquisition_cost_cents": 400000,
                    "acquisition_date": "2026-01-10",
                },
                "assessment": {
                    "condition_code": "C4",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-30",
                },
            },
        ],
        clock=CLOCK_EPOCH,
    )
    asset_f, asset_n, asset_b = scenario["assets"]

    recipient = register_local_government(
        federal_donee_status="CERTIFIED",
        donee_certification_expires_on="2027-03-31",
    )

    requests = {}
    for key, asset, intended_use, justification in (
        ("f", asset_f, "Municipal network refresh",
         "City core switches are past end of support and unpatchable."),
        ("n", asset_n, "Municipal network refresh, second site",
         "Second city site needs the same switch generation for spares."),
        ("b", asset_b, "City hall front office refurnishing",
         "Existing workstations do not meet accessibility clearances."),
    ):
        cycle = open_screening_cycle(
            asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
        )
        advance_tier(cycle["id"], 1)
        request = file_screening_request(
            cycle["id"], recipient["id"],
            intended_use=intended_use, justification=justification,
            needed_by_date="2026-10-01",
        )
        get_success_data(
            api_client.award_screening_cycle(cycle["id"], request["id"], _OFFICER)
        )
        requests[key] = request

    scenario["recipient"] = recipient
    scenario["asset_f"] = read_asset(asset_f["id"])
    scenario["asset_n"] = read_asset(asset_n["id"])
    scenario["asset_b"] = read_asset(asset_b["id"])
    scenario["requests"] = requests
    return scenario


def _issue_transfer_order(asset_id: str, recipient_id: str, request_id: str) -> dict:
    return validate_success(
        api_client.create_transfer_order(
            create_transfer_order_payload(asset_id, recipient_id, request_id),
            _OFFICER,
        ),
        201,
    )


class TestAssetValueTransferBasisVersusAuctionReserve:
    """One stored valuation, two channel prices."""

    def test_transfer_basis_discounts_the_valuation_and_adds_a_handling_fee(self):
        """PRD §3.3: "Multiply `acquisition_cost_cents` by the condition factor, the age
        factor and the functional factor, and round that single product half up to whole
        cents."
        PRD §3.5: "First, read the recipient's discount factor from its `agency_type`: a
        `STATE_AGENCY` pays twenty-five hundredths of value, a `LOCAL_GOVERNMENT` pays
        fifty hundredths, and an `ELIGIBLE_NONPROFIT` pays ten hundredths."
        PRD §3.5: "Second, multiply the asset's stored `fair_market_value_cents` by that
        factor and round the product half up to whole cents; the result is stored as
        `base_transfer_cents`."
        PRD §3.5: "Third, select the `handling_fee_cents` from a three-band schedule keyed
        **only** on `base_transfer_cents`: a base below one thousand dollars draws a
        fifty-dollar fee; a base of one thousand dollars or more but below ten thousand
        dollars draws a one hundred twenty-five dollar fee; a base of ten thousand dollars
        or more draws a three hundred dollar fee."
        PRD §3.5: "Fourth, assemble `transfer_price_cents`: it is the `handling_fee_cents`
        alone when the asset's `federal_source` is true — federally donated property is
        passed on as a donation and its acquisition value is waived, but the agency's own
        handling cost is still owed — and it is `base_transfer_cents` plus
        `handling_fee_cents` when `federal_source` is false."

        Design: Difficulty/dual_variant_calc/dv_asset_value_transfer_basis_vs_auction_reserve
        """
        scenario = _setup_twin_pickups_on_the_two_channels()
        asset_x = scenario["asset_x"]

        assert asset_x["fair_market_value_cents"] == 297620, (
            "the 2019 pickup must be valued at 297620 cents, got "
            f"{asset_x['fair_market_value_cents']}"
        )

        order = _issue_transfer_order(
            asset_x["id"], scenario["recipient"]["id"], scenario["request_x"]["id"]
        )
        assert_transfer_order(order)

        assert order["base_transfer_cents"] == 148810, (
            "a LOCAL_GOVERNMENT recipient pays fifty hundredths of 297620, so "
            f"base_transfer_cents must be 148810, got {order['base_transfer_cents']}"
        )
        assert order["handling_fee_cents"] == 12500, (
            "a base of 148810 sits in the middle handling band, so handling_fee_cents "
            f"must be 12500, got {order['handling_fee_cents']}"
        )
        assert order["transfer_price_cents"] == 161310, (
            "a non-federal asset pays base plus fee, so transfer_price_cents must be "
            f"161310, got {order['transfer_price_cents']}"
        )

    def test_auction_reserve_takes_sixty_hundredths_of_the_same_valuation(self):
        """PRD §3.3: "Multiply `acquisition_cost_cents` by the condition factor, the age
        factor and the functional factor, and round that single product half up to whole
        cents."
        PRD §3.6: "By default the reserve is derived from the asset's stored valuation:
        take sixty hundredths of `fair_market_value_cents`, round that product half up to
        whole cents, and use the larger of that figure and twenty-five dollars."
        PRD §3.6: "Where the `DisposalOfficer` supplies a `reserve_price_cents` in the
        request, that value is stored verbatim without any formula being applied, and the
        lot records `reserve_source` as `OFFICER_OVERRIDE`; where the officer supplies
        nothing, the computed figure is stored and `reserve_source` is `COMPUTED`."
        PRD §3.6: "A reserve below five thousand dollars requires no deposit at all and
        `required_deposit_cents` is 0."

        Design: Difficulty/dual_variant_calc/dv_asset_value_transfer_basis_vs_auction_reserve
        """
        scenario = _setup_twin_pickups_on_the_two_channels()
        asset_y = scenario["asset_y"]

        assert asset_y["fair_market_value_cents"] == 297620, (
            "the twin pickup must carry the identical valuation of 297620 cents, got "
            f"{asset_y['fair_market_value_cents']}"
        )

        lot = validate_success(
            api_client.create_auction_lot(
                {
                    "asset_id": asset_y["id"],
                    "venue_id": scenario["venue"]["id"],
                    "opens_at": "2026-09-01T00:00:00Z",
                    "closes_at": "2026-09-05T00:00:00Z",
                },
                _OFFICER,
            ),
            201,
        )
        assert_auction_lot(lot)

        assert lot["reserve_price_cents"] == 178572, (
            "sixty hundredths of 297620 is 178572, so reserve_price_cents must be "
            f"178572, got {lot['reserve_price_cents']}"
        )
        assert lot["reserve_source"] == "COMPUTED", (
            "no reserve was supplied in the request, so reserve_source must be "
            f"COMPUTED, got {lot['reserve_source']}"
        )
        assert lot["required_deposit_cents"] == 0, (
            "a reserve of 178572 is below the five-thousand-dollar deposit threshold, "
            f"so required_deposit_cents must be 0, got {lot['required_deposit_cents']}"
        )

    def test_one_valuation_yields_two_different_channel_prices(self):
        """PRD §3.3: "That stored figure is the single valuation from which both disposal
        channels derive their prices, and they derive different numbers from it: the
        screening channel discounts it against the recipient's tier and adds a handling fee
        (§3.5), while the auction channel takes a fraction of it as a reserve (§3.6)."
        PRD §3.3: "The same item therefore carries two different disposal prices depending
        on which channel claims it."

        Design: Difficulty/dual_variant_calc/dv_asset_value_transfer_basis_vs_auction_reserve
        """
        scenario = _setup_twin_pickups_on_the_two_channels()
        asset_x, asset_y = scenario["asset_x"], scenario["asset_y"]

        assert asset_x["fair_market_value_cents"] == asset_y["fair_market_value_cents"] == 297620, (
            "both structurally identical pickups must hold fair_market_value_cents "
            f"297620, got {asset_x['fair_market_value_cents']} and "
            f"{asset_y['fair_market_value_cents']}"
        )

        order = _issue_transfer_order(
            asset_x["id"], scenario["recipient"]["id"], scenario["request_x"]["id"]
        )
        lot = validate_success(
            api_client.create_auction_lot(
                {
                    "asset_id": asset_y["id"],
                    "venue_id": scenario["venue"]["id"],
                    "opens_at": "2026-09-01T00:00:00Z",
                    "closes_at": "2026-09-05T00:00:00Z",
                },
                _OFFICER,
            ),
            201,
        )

        assert order["transfer_price_cents"] == 161310, (
            "the screening channel must price the transfer at 161310, got "
            f"{order['transfer_price_cents']}"
        )
        assert lot["reserve_price_cents"] == 178572, (
            "the auction channel must set the reserve at 178572, got "
            f"{lot['reserve_price_cents']}"
        )
        assert order["transfer_price_cents"] != lot["reserve_price_cents"], (
            "the two channels must derive different numbers from one identical "
            f"fair_market_value_cents; both came out as {order['transfer_price_cents']}"
        )

class TestProceedsAccrualVersusCashBasisOnADefaultedInvoice:
    """Identical lot data, two distributable bases."""

    def test_defaulted_invoice_freezes_the_collected_cash_below_the_hammer_price(self):
        """PRD §3.7: "The invoice moves to `DEFAULTED` with `default_reason` stored and
        `amount_paid_cents` frozen at whatever it had reached."
        PRD §3.7: "The invoice's `amount_paid_cents` therefore always equals the sum of
        every cash `amount_cents` received plus the invoice's own `deposit_applied_cents`,
        and `balance_due_cents` is re-derived as `total_due_cents` less
        `amount_paid_cents`."
        PRD §3.7: "The lot deliberately stays at `CLOSED_MET` rather than reverting, so that
        a cash-basis distribution of whatever money was actually collected can still be
        computed."

        Design: Difficulty/dual_variant_calc/dv_proceeds_accrual_vs_cash_basis_on_defaulted_invoice
        """
        scenario = _setup_defaulted_invoice_on_a_settled_server_lot()
        invoice, lot = scenario["invoice"], scenario["lot"]

        assert_sale_invoice(invoice)
        assert invoice["total_due_cents"] == 752107, (
            "a hammer price of 640000 with the venue's rates must total 752107, got "
            f"{invoice['total_due_cents']}"
        )
        assert invoice["amount_paid_cents"] == 200000, (
            "the 59157 deposit plus 140843 cash must freeze amount_paid_cents at 200000, "
            f"got {invoice['amount_paid_cents']}"
        )
        assert invoice["status"] == "DEFAULTED", (
            f"the invoice must be DEFAULTED, got {invoice['status']}"
        )
        assert lot["status"] == "CLOSED_MET", (
            "the lot must stay CLOSED_MET after the default so both bases remain "
            f"computable, got {lot['status']}"
        )
        assert lot["high_bid_cents"] == 640000, (
            f"the lot must record a high_bid_cents of 640000, got {lot['high_bid_cents']}"
        )

    def test_accrual_basis_distributes_the_price_the_lot_achieved(self):
        """PRD §3.9: "Under the `ACCRUAL` basis it is the price the lot achieved, the lot's
        `high_bid_cents`, whether or not the buyer ever paid a cent."
        PRD §3.9: "The first slice is the smaller of the base and five thousand dollars,
        charged at twelve and a half hundredths."
        PRD §3.9: "The second slice is the portion of the base above five thousand dollars
        up to fifty thousand dollars, and is zero when the base does not reach five thousand
        dollars, charged at eight hundred seventy-five ten-thousandths."
        PRD §3.9: "Each of the three products is rounded half up to whole cents
        independently, and `service_fee_cents` is the exact sum of those three integers."
        PRD §3.9: "The `cost_recovery_cents` is seventy-five dollars for each
        `DATA_SANITIZATION` certificate plus two hundred twenty-five dollars for each
        `DEMILITARIZATION` certificate, counted over the asset's clearance certificates
        whose `serials_verified` is true as they exist at the moment the distribution is
        created."
        PRD §3.9: "The `net_to_agency_cents` is the larger of zero and the base less the
        service fee less the cost recovery."

        Design: Difficulty/dual_variant_calc/dv_proceeds_accrual_vs_cash_basis_on_defaulted_invoice
        """
        scenario = _setup_defaulted_invoice_on_a_settled_server_lot()
        lot = read_lot(scenario["lot"]["id"])

        accrual = validate_success(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot["id"], lot["version"], "ACCRUAL"
                ),
                _FINANCE,
            ),
            201,
        )
        assert_proceeds_distribution(accrual)
        assert_proceeds_net(accrual)

        assert accrual["distributable_base_cents"] == 640000, (
            "the accrual base is the lot's high_bid_cents of 640000, got "
            f"{accrual['distributable_base_cents']}"
        )
        assert accrual["service_fee_cents"] == 74750, (
            "the marginal slices over a base of 640000 must add to 74750, got "
            f"{accrual['service_fee_cents']}"
        )
        assert accrual["cost_recovery_cents"] == 7500, (
            "one verified sanitisation certificate recovers 7500, got "
            f"{accrual['cost_recovery_cents']}"
        )
        assert accrual["net_to_agency_cents"] == 557750, (
            "640000 less 74750 less 7500 leaves 557750, got "
            f"{accrual['net_to_agency_cents']}"
        )
        assert accrual["status"] == "CALCULATED", (
            f"a new distribution must land in CALCULATED, got {accrual['status']}"
        )

    def test_cash_basis_distributes_only_the_money_that_actually_arrived(self):
        """PRD §3.9: "Under the `CASH` basis it is the money actually collected, the
        `amount_paid_cents` of the lot's non-`VOIDED` `SaleInvoice`, which already includes
        any deposit that was applied against it."
        PRD §3.9: "The first slice is the smaller of the base and five thousand dollars,
        charged at twelve and a half hundredths."
        PRD §3.9: "The second slice is the portion of the base above five thousand dollars
        up to fifty thousand dollars, and is zero when the base does not reach five thousand
        dollars, charged at eight hundred seventy-five ten-thousandths."
        PRD §3.9: "The `net_to_agency_cents` is the larger of zero and the base less the
        service fee less the cost recovery."

        Design: Difficulty/dual_variant_calc/dv_proceeds_accrual_vs_cash_basis_on_defaulted_invoice
        """
        scenario = _setup_defaulted_invoice_on_a_settled_server_lot()
        lot = read_lot(scenario["lot"]["id"])

        cash = validate_success(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(lot["id"], lot["version"], "CASH"),
                _FINANCE,
            ),
            201,
        )
        assert_proceeds_distribution(cash)
        assert_proceeds_net(cash)

        assert cash["distributable_base_cents"] == 200000, (
            "the cash base is the invoice's amount_paid_cents of 200000, got "
            f"{cash['distributable_base_cents']}"
        )
        assert cash["service_fee_cents"] == 25000, (
            "a base of 200000 falls entirely in the first slice, so the fee must be "
            f"25000, got {cash['service_fee_cents']}"
        )
        assert cash["cost_recovery_cents"] == 7500, (
            "cost recovery does not depend on the basis and must stay 7500, got "
            f"{cash['cost_recovery_cents']}"
        )
        assert cash["net_to_agency_cents"] == 167500, (
            "200000 less 25000 less 7500 leaves 167500, got "
            f"{cash['net_to_agency_cents']}"
        )

    def test_the_two_bases_diverge_and_the_later_draft_supersedes_the_earlier(self):
        """PRD §3.9: "For a defaulted invoice the two bases return materially different nets
        from identical lot data, which is exactly why both are offered: the accrual figure
        states what was owed, the cash figure states what arrived."
        PRD §3.9: "Creating it moves any earlier distribution for the same lot that is still
        `CALCULATED` to `SUPERSEDED`, so a lot never carries two live drafts, and — because
        the calculation reads the lot — the create also increments the `AuctionLot`'s
        `version` by 1, which means a second create against the same
        `expected_auction_lot_version` will be rejected as stale."
        PRD §3.9: "It is resolved at create time by walking from the lot to its asset, from
        the asset's `turn_in_id` to that turn-in, and from there to the turn-in's
        `turning_in_agency_id` — the organisation that relinquished the property, which may
        be quite different from anyone involved in the sale."
        PRD §3.9: "The `proceeds_account_balance_cents` of an agency is the sum of
        `net_to_agency_cents` over every `ProceedsDistribution` whose
        `beneficiary_agency_id` is that agency and whose `status` is `POSTED`, across all
        time with no window bounds, accumulated in `created_at` ascending order; rows in
        `CALCULATED`, `SUPERSEDED` or `REVERSED` are excluded, and `id` is never consulted
        as an ordering key."

        Design: Difficulty/dual_variant_calc/dv_proceeds_accrual_vs_cash_basis_on_defaulted_invoice
        """
        scenario = _setup_defaulted_invoice_on_a_settled_server_lot()
        lot_id = scenario["lot"]["id"]

        accrual = validate_success(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot_id, read_lot(lot_id)["version"], "ACCRUAL"
                ),
                _FINANCE,
            ),
            201,
        )
        cash = validate_success(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot_id, read_lot(lot_id)["version"], "CASH"
                ),
                _FINANCE,
            ),
            201,
        )

        assert accrual["distributable_base_cents"] == 640000, (
            "the accrual draft must state what was owed, 640000, got "
            f"{accrual['distributable_base_cents']}"
        )
        assert cash["distributable_base_cents"] == 200000, (
            "the cash draft must state what arrived, 200000, got "
            f"{cash['distributable_base_cents']}"
        )
        assert accrual["net_to_agency_cents"] == 557750, (
            f"the accrual net must be 557750, got {accrual['net_to_agency_cents']}"
        )
        assert cash["net_to_agency_cents"] == 167500, (
            f"the cash net must be 167500, got {cash['net_to_agency_cents']}"
        )
        assert accrual["net_to_agency_cents"] != cash["net_to_agency_cents"], (
            "the two bases must return materially different nets from identical lot "
            f"data; both came out as {accrual['net_to_agency_cents']}"
        )

        superseded = read_distribution(accrual["id"])
        assert superseded["status"] == "SUPERSEDED", (
            "the earlier CALCULATED draft must be SUPERSEDED once the second draft is "
            f"created, got {superseded['status']}"
        )
        assert cash["status"] == "CALCULATED", (
            f"the newer draft must stand at CALCULATED, got {cash['status']}"
        )

        beneficiary_id = scenario["agency"]["id"]
        assert cash["beneficiary_agency_id"] == beneficiary_id, (
            "the beneficiary must resolve to the turning-in organisation "
            f"{beneficiary_id}, got {cash['beneficiary_agency_id']}"
        )
        assert accrual["beneficiary_agency_id"] == beneficiary_id, (
            "both drafts must name the same turning-in organisation "
            f"{beneficiary_id}, got {accrual['beneficiary_agency_id']}"
        )

        agency = read_agency(beneficiary_id)
        assert agency["proceeds_account_balance_cents"] == 0, (
            "a CALCULATED draft may never reach the ledger, so the balance must still "
            f"be 0, got {agency['proceeds_account_balance_cents']}"
        )

# The two assets whose valuations pin the single-rounding placement.
_HALF_CENT_PICKUP = {
    "description": "2019 Ford F-250 half-tie unit",
    "acquisition_cost_cents": 3217450,
    "acquisition_date": "2019-03-15",
    "vin": "1FT7W2BT9KEB90001",
    "odometer_reading": 201455,
    "title_number": "TX-90001",
}
_SEIZED_ROLLER = {
    "description": "2020 Wacker roller, seized drum",
    "acquisition_cost_cents": 870401,
    "acquisition_date": "2020-06-30",
}


def _setup_two_appraised_assets_on_a_submitted_turn_in() -> dict:
    """One SUBMITTED turn-in carrying the two assets whose factor products land on
    the awkward boundaries: a half-cent product and a repair estimate larger than
    the rounded base.
    """
    scenario = setup_assessed_assets(
        [
            {
                "kind": "vehicle",
                "overrides": _HALF_CENT_PICKUP,
                "assessment": {
                    "condition_code": "C4",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-28",
                },
            },
            {
                "kind": "heavy_equipment",
                "overrides": _SEIZED_ROLLER,
                "assessment": {
                    "condition_code": "C5",
                    "functional": False,
                    "repair_cost_estimate_cents": 62700,
                    "assessed_on": "2026-07-28",
                },
            },
        ],
        clock=CLOCK_EPOCH,
        accept=False,
    )
    scenario["asset_h"], scenario["asset_z"] = scenario["assets"]
    scenario["assessment_h"], scenario["assessment_z"] = scenario["assessments"]
    return scenario


def _governing_assessment(asset_id: str, assessment_id: str) -> dict:
    rows = get_success_data(
        api_client.list_condition_assessments(asset_id, _ADMIN)
    )
    matches = [row for row in rows if row["id"] == assessment_id]
    assert matches, (
        f"the assessment {assessment_id} must be discoverable on asset {asset_id}"
    )
    return matches[0]


class TestFairMarketValueSingleRoundingOfTheFactorProduct:
    """The three factors are rounded once, together, and the repair estimate is
    deducted from the already rounded integer."""

    def test_a_product_landing_on_half_a_cent_rounds_up(self):
        """PRD §2.6: "Whenever a rate is multiplied into an amount, the result is converted
        back to whole cents by **rounding half up**: a fractional remainder of exactly one
        half cent rounds away from zero, to the larger magnitude."
        PRD §2.6: "Concretely, an acquisition cost of 3,217,450 cents multiplied by a
        condition factor of 0.50, an age factor of 0.30 and a functional factor of 1.00 is
        exactly 482,617.5 cents and must therefore round to 482,618, not 482,617."
        PRD §3.3: "The age factor is one minus ten hundredths for each of those full years,
        but never less than twenty hundredths — an item held twelve years and an item held
        twenty years are both floored at the same twenty hundredths of original value."
        PRD §3.3: "The **condition factor** is read from the governing assessment's
        `condition_code` against a fixed schedule: `C1` retains the full original value at
        one, `C2` retains eighty-five hundredths, `C3` seventy hundredths, `C4` fifty
        hundredths, `C5` thirty hundredths, `C6` fifteen hundredths, and `C7` five
        hundredths."
        PRD §3.3: "Multiply `acquisition_cost_cents` by the condition factor, the age factor
        and the functional factor, and round that single product half up to whole cents."
        PRD §3.3: "The first assessment on an asset drives `disposition_status` from `INTAKE`
        to `ASSESSED`."

        Design: Difficulty/combinatorial_formula/cf_fmv_nested_factor_product_single_rounding
        """
        scenario = _setup_two_appraised_assets_on_a_submitted_turn_in()
        asset_h = scenario["asset_h"]

        assert_surplus_asset(asset_h)
        assert asset_h["fair_market_value_cents"] == 482618, (
            "3217450 * 0.50 * 0.30 * 1.00 is exactly 482617.5, which must round up to "
            f"482618, got {asset_h['fair_market_value_cents']}"
        )
        assert asset_h["condition_code"] == "C4", (
            "the governing assessment's condition_code must be copied onto the asset, "
            f"expected C4, got {asset_h['condition_code']}"
        )
        assert asset_h["disposition_status"] == "ASSESSED", (
            "the first assessment must drive the asset from INTAKE to ASSESSED, got "
            f"{asset_h['disposition_status']}"
        )
        assert asset_h["version"] == 2, (
            "the assessment increments the asset's version from 1 to 2, got "
            f"{asset_h['version']}"
        )

        governing = _governing_assessment(asset_h["id"], scenario["assessment_h"]["id"])
        assert_condition_assessment(governing)
        assert governing["superseded"] is False, (
            "the only assessment on the asset governs, so superseded must be false, got "
            f"{governing['superseded']}"
        )

    def test_the_repair_deduction_comes_off_the_rounded_base_and_floors_at_zero(self):
        """PRD §3.3: "The **functional factor** is one when the governing assessment's
        `functional` flag is true, and sixty hundredths when it is false."
        PRD §3.3: "Multiply `acquisition_cost_cents` by the condition factor, the age factor
        and the functional factor, and round that single product half up to whole cents."
        PRD §3.3: "From the resulting whole-cent figure subtract the governing assessment's
        `repair_cost_estimate_cents`."
        PRD §3.3: "If the subtraction would go below zero the value is zero instead —
        repairs can drive an item's market value to nothing but never below it."
        PRD §3.3: "Note that the deduction is applied to the *already-rounded* integer, not
        folded into the product before rounding."

        Design: Difficulty/combinatorial_formula/cf_fmv_nested_factor_product_single_rounding
        """
        scenario = _setup_two_appraised_assets_on_a_submitted_turn_in()
        asset_z = scenario["asset_z"]

        assert_surplus_asset(asset_z)
        assert asset_z["fair_market_value_cents"] == 0, (
            "870401 * 0.30 * 0.40 * 0.60 rounds to 62669, and deducting the 62700 repair "
            "estimate would give -31, so the stored value must be floored at 0, got "
            f"{asset_z['fair_market_value_cents']}"
        )
        assert asset_z["condition_code"] == "C5", (
            f"the asset's condition_code must be C5, got {asset_z['condition_code']}"
        )
        assert asset_z["disposition_status"] == "ASSESSED", (
            "a valuation of zero is still an appraisal, so the asset must stand at "
            f"ASSESSED, got {asset_z['disposition_status']}"
        )
        assert asset_z["version"] == 2, (
            "the assessment increments the asset's version from 1 to 2, got "
            f"{asset_z['version']}"
        )

        governing = _governing_assessment(asset_z["id"], scenario["assessment_z"]["id"])
        assert_condition_assessment(governing)
        assert governing["superseded"] is False, (
            "the only assessment on the asset governs, so superseded must be false, got "
            f"{governing['superseded']}"
        )

def _setup_hammer_price_of_301500_on_a_de_minimis_lot() -> dict:
    """A de-minimis furniture lot at a venue charging a 0.105 buyer premium and a
    0.0635 sales tax, hammered down at 301500 and closed.

    The asset is valued at 12540, so its computed reserve of 7524 demands no
    deposit and a single bid of 301500 clears it outright.
    """
    scenario = setup_open_lot()
    lot = scenario["lot"]

    bidder = register_bidder(
        status="REGISTERED",
        legal_name="Hill Country Resale",
        email="buy@hillcountry.example",
        bidder_type="BUSINESS",
    )
    bid = place_bid(lot["id"], bidder["id"], 301500)

    set_clock("2026-09-05T00:00:00Z")
    closed = get_success_data(api_client.close_auction_lot(lot["id"], _OFFICER))

    invoice = find_invoice_for_lot(lot["id"])
    assert invoice is not None, "the close cascade must issue a SaleInvoice"

    scenario["bidder"] = bidder
    scenario["bid"] = bid
    scenario["lot"] = closed
    scenario["invoice"] = read_invoice(invoice["id"])
    return scenario


class TestInvoiceMoneyLinesRoundedPerLineThenSummed:
    """The premium and the tax are each rounded before they are added, and the sum
    itself is never rounded again."""

    def test_each_money_line_is_rounded_on_its_own(self):
        """PRD §3.7: "Three money lines are computed from the winning bid and the hosting
        venue's rates as read at close time, and the rounding order is pinned."
        PRD §3.7: "The `buyer_premium_cents` is the `hammer_price_cents` multiplied by the
        venue's `buyer_premium_pct`, rounded half up to whole cents on its own."
        PRD §3.7: "The `sales_tax_cents` is the sum of `hammer_price_cents` and
        `buyer_premium_cents` multiplied by the venue's `sales_tax_pct`, again rounded half
        up on its own — the tax is charged on the premium-inclusive amount, not on the hammer
        price alone."

        Design: Difficulty/combinatorial_formula/cf_invoice_per_line_rounding_then_sum
        """
        scenario = _setup_hammer_price_of_301500_on_a_de_minimis_lot()
        invoice = scenario["invoice"]

        assert_sale_invoice(invoice)
        assert invoice["hammer_price_cents"] == 301500, (
            "the invoice must carry the winning bid's amount_cents of 301500, got "
            f"{invoice['hammer_price_cents']}"
        )
        assert invoice["buyer_premium_cents"] == 31658, (
            "301500 at a 0.105 premium is exactly 31657.5, which rounds half up on its "
            f"own to 31658, got {invoice['buyer_premium_cents']}"
        )
        assert invoice["sales_tax_cents"] == 21156, (
            "the tax runs on the premium-inclusive 333158 at 0.0635, so it must round to "
            f"21156, got {invoice['sales_tax_cents']}"
        )

    def test_the_total_is_the_exact_sum_and_not_a_compound_product(self):
        """PRD §3.7: "The `total_due_cents` is then the exact sum of the three integers with
        no further rounding at all."
        PRD §3.7: "Producing the total by rounding a single compound product of the hammer
        price against both rates together is forbidden: the two orders disagree by a full
        cent on many inputs, so a hammer price of 301,500 cents yields 354,314 cents under
        the pinned per-line order and 354,313 cents under the forbidden compound one."
        PRD §2.6: "Sums of already-rounded integers are exact and are never rounded again."

        Design: Difficulty/combinatorial_formula/cf_invoice_per_line_rounding_then_sum
        """
        scenario = _setup_hammer_price_of_301500_on_a_de_minimis_lot()
        invoice = scenario["invoice"]

        assert invoice["total_due_cents"] == 354314, (
            "the pinned per-line order totals 354314 on a hammer price of 301500, got "
            f"{invoice['total_due_cents']}"
        )
        assert invoice["total_due_cents"] != 354313, (
            "354313 is the forbidden compound-product order, which rounds once over both "
            "rates together instead of once per line"
        )
        assert (
            invoice["total_due_cents"]
            == invoice["hammer_price_cents"]
            + invoice["buyer_premium_cents"]
            + invoice["sales_tax_cents"]
        ), (
            "total_due_cents must be the exact sum of the three stored integers; got "
            f"{invoice['total_due_cents']} against "
            f"{invoice['hammer_price_cents']} + {invoice['buyer_premium_cents']} + "
            f"{invoice['sales_tax_cents']}"
        )

    def test_the_freshly_issued_invoice_owes_its_whole_total_seven_days_out(self):
        """PRD §3.7: "Finally, `balance_due_cents` is `total_due_cents` less
        `amount_paid_cents`, so a freshly issued invoice has a balance equal to its total."
        PRD §3.7: "Hop three, caused by hop two, follows from a bid having become `WINNING`:
        a `SaleInvoice` is created for that bidder in `status` `ISSUED`, carrying
        `auction_lot_id` and `bidder_id`, with `hammer_price_cents` equal to the winning
        bid's `amount_cents`, its money lines computed as described below,
        `amount_paid_cents` and `deposit_applied_cents` at 0, `default_reason` and
        `void_reason` null, and `due_at` set to `closed_at` plus a payment term of seven
        whole days."
        PRD §3.7: "**When the candidate set is non-empty**, the lot closes at `CLOSED_MET`
        and four hops run."
        PRD §3.7: "The selected bid moves `ACTIVE` → `WINNING`, every other `ACTIVE` bid on
        the lot moves `ACTIVE` → `OUTBID` processed in `created_at` ascending order, and the
        winning `Bidder`'s `winning_lot_count` is incremented by 1."

        Design: Difficulty/combinatorial_formula/cf_invoice_per_line_rounding_then_sum
        """
        scenario = _setup_hammer_price_of_301500_on_a_de_minimis_lot()
        invoice, lot = scenario["invoice"], scenario["lot"]

        assert invoice["status"] == "ISSUED", (
            f"the close cascade must issue the invoice at ISSUED, got {invoice['status']}"
        )
        assert invoice["amount_paid_cents"] == 0, (
            f"a freshly issued invoice has nothing paid, got {invoice['amount_paid_cents']}"
        )
        assert invoice["balance_due_cents"] == 354314, (
            "the balance of a freshly issued invoice equals its total of 354314, got "
            f"{invoice['balance_due_cents']}"
        )
        assert _as_instant(invoice["due_at"]) == _as_instant("2026-09-12T00:00:00Z"), (
            "a close at 2026-09-05T00:00:00Z plus seven whole days is due at "
            f"2026-09-12T00:00:00Z, got {invoice['due_at']}"
        )

        assert_auction_lot(lot)
        assert lot["status"] == "CLOSED_MET", (
            f"a bid at or above reserve closes the lot at CLOSED_MET, got {lot['status']}"
        )
        assert lot["high_bid_cents"] == 301500, (
            f"the lot must record a high_bid_cents of 301500, got {lot['high_bid_cents']}"
        )

        bids = list_lot_bids(lot["id"])
        winning = [row for row in bids if row["id"] == scenario["bid"]["id"]]
        assert winning, "the placed bid must remain discoverable on the lot"
        assert winning[0]["status"] == "WINNING", (
            "the sole candidate bid must be selected as WINNING, got "
            f"{winning[0]['status']}"
        )

class TestHandlingFeeBandKeyedOnThePreWaiverBase:
    """The band lookup reads `base_transfer_cents` and nothing else."""

    def test_a_federal_donation_waives_the_base_but_keeps_its_fee_band(self):
        """PRD §3.3: "Its `federal_use_period_end_on` is computed at creation by adding a
        category-dependent number of calendar months to `federal_use_period_start_on`:
        eighteen months for a `VEHICLE`, a `HEAVY_EQUIPMENT` item or a
        `RESTRICTED_MILITARY` article, and twelve months for `IT_EQUIPMENT` or `FURNITURE`."
        PRD §3.5: "Second, multiply the asset's stored `fair_market_value_cents` by that
        factor and round the product half up to whole cents; the result is stored as
        `base_transfer_cents`."
        PRD §3.5: "Third, select the `handling_fee_cents` from a three-band schedule keyed
        **only** on `base_transfer_cents`: a base below one thousand dollars draws a
        fifty-dollar fee; a base of one thousand dollars or more but below ten thousand
        dollars draws a one hundred twenty-five dollar fee; a base of ten thousand dollars
        or more draws a three hundred dollar fee."
        PRD §3.5: "The band is chosen from the pre-waiver, pre-fee base figure and the fee
        is never fed back into the band selection."
        PRD §3.5: "Fourth, assemble `transfer_price_cents`: it is the `handling_fee_cents`
        alone when the asset's `federal_source` is true — federally donated property is
        passed on as a donation and its acquisition value is waived, but the agency's own
        handling cost is still owed — and it is `base_transfer_cents` plus
        `handling_fee_cents` when `federal_source` is false."
        PRD §3.5: "A federally sourced asset therefore still lands in the fee band its
        (waived) base would have occupied."

        Design: Difficulty/combinatorial_formula/cf_transfer_handling_fee_tier_keyed_on_prewaiver_base
        """
        scenario = _setup_three_awarded_transfer_candidates()
        asset_f = scenario["asset_f"]

        assert asset_f["federal_use_period_end_on"] == "2026-06-15", (
            "twelve calendar months from 2025-06-15 for IT_EQUIPMENT ends 2026-06-15, got "
            f"{asset_f['federal_use_period_end_on']}"
        )
        assert asset_f["fair_market_value_cents"] == 985946, (
            "the switch stack must be valued at 985946, got "
            f"{asset_f['fair_market_value_cents']}"
        )

        order = _issue_transfer_order(
            asset_f["id"], scenario["recipient"]["id"], scenario["requests"]["f"]["id"]
        )
        assert_transfer_order(order)

        assert order["base_transfer_cents"] == 492973, (
            "fifty hundredths of 985946 rounds to 492973, got "
            f"{order['base_transfer_cents']}"
        )
        assert order["handling_fee_cents"] == 12500, (
            "the band is read from the pre-waiver base of 492973, so the fee must be "
            f"12500, got {order['handling_fee_cents']}"
        )
        assert order["transfer_price_cents"] == 12500, (
            "the federal donation waives the base only, leaving the fee alone at 12500, "
            f"got {order['transfer_price_cents']}"
        )
        assert order["transfer_price_cents"] != 5000, (
            "5000 would mean the band was keyed on the post-waiver total instead of on "
            "base_transfer_cents"
        )

    def test_the_non_federal_twin_carries_the_identical_fee_on_a_full_price(self):
        """PRD §3.5: "Second, multiply the asset's stored `fair_market_value_cents` by that
        factor and round the product half up to whole cents; the result is stored as
        `base_transfer_cents`."
        PRD §3.5: "Fourth, assemble `transfer_price_cents`: it is the `handling_fee_cents`
        alone when the asset's `federal_source` is true — federally donated property is
        passed on as a donation and its acquisition value is waived, but the agency's own
        handling cost is still owed — and it is `base_transfer_cents` plus
        `handling_fee_cents` when `federal_source` is false."
        PRD §3.5: "The band is chosen from the pre-waiver, pre-fee base figure and the fee
        is never fed back into the band selection."

        Design: Difficulty/combinatorial_formula/cf_transfer_handling_fee_tier_keyed_on_prewaiver_base
        """
        scenario = _setup_three_awarded_transfer_candidates()
        asset_n = scenario["asset_n"]

        assert asset_n["fair_market_value_cents"] == 985946, (
            "the non-federal twin must carry the identical valuation of 985946, got "
            f"{asset_n['fair_market_value_cents']}"
        )

        federal_order = _issue_transfer_order(
            scenario["asset_f"]["id"],
            scenario["recipient"]["id"],
            scenario["requests"]["f"]["id"],
        )
        order = _issue_transfer_order(
            asset_n["id"], scenario["recipient"]["id"], scenario["requests"]["n"]["id"]
        )
        assert_transfer_order(order)

        assert order["base_transfer_cents"] == 492973, (
            "fifty hundredths of 985946 rounds to 492973, got "
            f"{order['base_transfer_cents']}"
        )
        assert order["handling_fee_cents"] == 12500, (
            f"the fee must be identical to the federal order at 12500, got "
            f"{order['handling_fee_cents']}"
        )
        assert order["transfer_price_cents"] == 505473, (
            "a non-federal asset owes base plus fee, 492973 + 12500 = 505473, got "
            f"{order['transfer_price_cents']}"
        )
        assert order["handling_fee_cents"] == federal_order["handling_fee_cents"], (
            "the waiver changes the price but never the fee band; got "
            f"{order['handling_fee_cents']} against "
            f"{federal_order['handling_fee_cents']}"
        )

    def test_a_base_landing_exactly_on_the_band_boundary_takes_the_upper_fee(self):
        """PRD §3.5: "Third, select the `handling_fee_cents` from a three-band schedule keyed
        **only** on `base_transfer_cents`: a base below one thousand dollars draws a
        fifty-dollar fee; a base of one thousand dollars or more but below ten thousand
        dollars draws a one hundred twenty-five dollar fee; a base of ten thousand dollars
        or more draws a three hundred dollar fee."
        PRD §3.5: "Fourth, assemble `transfer_price_cents`: it is the `handling_fee_cents`
        alone when the asset's `federal_source` is true — federally donated property is
        passed on as a donation and its acquisition value is waived, but the agency's own
        handling cost is still owed — and it is `base_transfer_cents` plus
        `handling_fee_cents` when `federal_source` is false."

        Design: Difficulty/combinatorial_formula/cf_transfer_handling_fee_tier_keyed_on_prewaiver_base
        """
        scenario = _setup_three_awarded_transfer_candidates()
        asset_b = scenario["asset_b"]

        assert asset_b["fair_market_value_cents"] == 200000, (
            "the workstation cluster must be valued at 200000, got "
            f"{asset_b['fair_market_value_cents']}"
        )

        order = _issue_transfer_order(
            asset_b["id"], scenario["recipient"]["id"], scenario["requests"]["b"]["id"]
        )
        assert_transfer_order(order)

        assert order["base_transfer_cents"] == 100000, (
            "fifty hundredths of 200000 lands exactly on the band boundary at 100000, "
            f"got {order['base_transfer_cents']}"
        )
        assert order["handling_fee_cents"] == 12500, (
            "a base of one thousand dollars or more takes the middle fee, so exactly "
            f"100000 must draw 12500 rather than 5000, got {order['handling_fee_cents']}"
        )
        assert order["transfer_price_cents"] == 112500, (
            "a non-federal asset owes base plus fee, 100000 + 12500 = 112500, got "
            f"{order['transfer_price_cents']}"
        )

    def test_only_release_stamps_the_recipients_own_use_period(self):
        """PRD §3.5: "A newly issued order sits in `status` `ISSUED` with
        `issued_by_user_id` stamped from the officer's `X-User-ID`, and with
        `acknowledged_at`, `use_period_end_on` and `void_reason` all null."
        PRD §3.5: "Acknowledgement is what starts the recipient's own federal use period,
        though the resulting `use_period_end_on` is not written until the asset actually
        leaves custody, as described in §3.8."
        PRD §3.8: "From `AWARDED_TRANSFER`, a second hop caused by the asset leaving custody
        moves the asset's `ACKNOWLEDGED` `TransferOrder` to `COMPLETED` and, where the
        asset's `federal_source` is true, computes that order's `use_period_end_on` by adding
        the asset category's use-period months to the calendar date of the order's
        `acknowledged_at`, with the same day-of-month clamping described in §2.4 — the
        recipient inherits an obligation of its own, counted from when it accepted the
        paperwork rather than from when the property moved."
        PRD §3.8: "A successful release stores `released_at` from the logical clock along
        with the supplied `odometer_disclosure_reading`, `lien_release_reference` and
        `title_recipient_name`, and moves the asset to `RELEASED`."

        Design: Difficulty/combinatorial_formula/cf_transfer_handling_fee_tier_keyed_on_prewaiver_base
        """
        scenario = _setup_three_awarded_transfer_candidates()
        recipient_id = scenario["recipient"]["id"]
        asset_f = scenario["asset_f"]

        order_f = _issue_transfer_order(
            asset_f["id"], recipient_id, scenario["requests"]["f"]["id"]
        )
        order_n = _issue_transfer_order(
            scenario["asset_n"]["id"], recipient_id, scenario["requests"]["n"]["id"]
        )

        assert order_f["use_period_end_on"] is None, (
            "a newly issued order carries a null use_period_end_on, got "
            f"{order_f['use_period_end_on']}"
        )

        get_success_data(
            api_client.acknowledge_transfer_order(
                order_f["id"], make_agency_officer_headers(recipient_id)
            )
        )
        released = validate_success(
            api_client.release_asset(
                asset_f["id"], {"title_recipient_name": "City of Cedar Park"}, _OFFICER
            ),
            200,
        )

        assert_surplus_asset(released)
        assert released["disposition_status"] == "RELEASED", (
            "an acknowledged transfer order admits release, so the asset must reach "
            f"RELEASED, got {released['disposition_status']}"
        )
        assert released["title_recipient_name"] == "City of Cedar Park", (
            "the supplied title_recipient_name must be stored, got "
            f"{released['title_recipient_name']}"
        )

        completed = read_transfer_order(order_f["id"])
        assert completed["status"] == "COMPLETED", (
            "release moves the acknowledged order to COMPLETED, got "
            f"{completed['status']}"
        )
        assert completed["use_period_end_on"] == "2027-08-01", (
            "twelve months from the 2026-08-01 acknowledgement date for IT_EQUIPMENT ends "
            f"2027-08-01, got {completed['use_period_end_on']}"
        )

        untouched = read_transfer_order(order_n["id"])
        assert untouched["status"] == "ISSUED", (
            "the twin's order was never acknowledged or released, so it must stand at "
            f"ISSUED, got {untouched['status']}"
        )
        assert untouched["use_period_end_on"] is None, (
            "use_period_end_on is only stamped by release, so an ISSUED order must keep "
            f"it null, got {untouched['use_period_end_on']}"
        )
