"""Input-validation corners on the screening ladder and the disposal channels.

Each test pins one validation rule the PRD states for screening requests, tier
advances, awards, transfer orders, bids, payments, sale windows, proceeds
distributions and clearance certificates. Every rejection is checked both for
the exact error identifier the PRD names and for the absence of any persisted
side effect, and each accepted boundary value is checked for the stored figures
the PRD derives from it.
"""

from datetime import datetime, timezone

from test_helpers import (
    ADMIN,
    CLOCK_EPOCH,
    FINANCE,
    FINANCE_USER_ID,
    OFFICER,
    TECHNICIAN,
    TECHNICIAN_USER_ID,
    ApiErrorId,
    add_asset,
    add_asset_with_payload,
    api_client,
    create_auction_lot_payload,
    create_bid_payload,
    create_clearance_certificate_payload,
    create_draft_turn_in,
    create_it_asset_payload,
    create_payment_payload,
    create_proceeds_distribution_payload,
    create_restricted_asset_payload,
    create_screening_cycle_payload,
    create_screening_request_payload,
    create_transfer_order_payload,
    file_screening_request,
    get_success_data,
    lodge_deposit,
    make_bidder_headers,
    open_screening_cycle,
    post_distribution,
    read_agency,
    read_asset,
    read_bidder,
    read_cycle,
    read_invoice,
    read_lot,
    read_request,
    read_venue,
    register_bidder,
    register_nonprofit,
    register_state_agency,
    register_venue,
    set_clock,
    setup_assessed_asset,
    setup_assessed_assets,
    setup_closed_met_lot,
    setup_open_lot,
    setup_open_lot_with_bidder,
    submit_turn_in,
    suspend_agency,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# A high-value FURNITURE item: acquired inside the current year and appraised at
# C1 while functional with no repair estimate, so its fair market value equals
# the whole acquisition cost and the item sits above the screening threshold.
_HIGH_VALUE_ASSET = {
    "acquisition_cost_cents": 1000000,
    "acquisition_date": "2026-01-10",
    "description": "Executive conference room suite, twenty-four seats",
}
_HIGH_VALUE_ASSESSMENT = {
    "condition_code": "C1",
    "functional": True,
    "repair_cost_estimate_cents": 0,
    "assessed_on": "2026-07-31",
}


def _parse_instant(value):
    """Read an ISO 8601 UTC instant whatever fractional precision it carries, so
    that two spellings of one instant compare equal."""
    assert isinstance(value, str) and value, f"expected an instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_instant(actual, expected, label):
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label} must be the instant {expected}, got {actual!r}"
    )


def _high_value_screened_asset():
    """One accepted, above-threshold asset ready to be pushed into screening."""
    return setup_assessed_asset(
        asset_overrides=_HIGH_VALUE_ASSET,
        assessment_overrides=_HIGH_VALUE_ASSESSMENT,
    )


def _request_count_for_cycle(cycle_id):
    _, meta = validate_paginated(
        api_client.list_screening_requests(OFFICER, {"screening_cycle_id": cycle_id})
    )
    return meta["total_count"]


class TestSuspensionOutranksTierPriority:
    """The screening-request filing checks run in the order the PRD fixes."""

    def test_suspended_requester_reports_suspension_not_its_wrong_tier(self):
        """A suspended organisation whose type also fails the tier gate reports
        the suspension, because the suspension check runs first.

        PRD: "Three checks follow existence resolution, in this order: the
        requesting organisation must not be `SUSPENDED`, or the filing is
        refused with `ERR_AGENCY_SUSPENDED`; the organisation's `agency_type`
        must equal the cycle's `current_tier`, or the filing is refused with
        `ERR_TIER_PRIORITY_VIOLATION` — this is what makes the ladder a ladder,
        and it also means a cycle sitting at `PUBLIC_SALE` admits no screening
        request at all, since no organisation's type is `PUBLIC_SALE`; and the
        logical clock must fall inside the closed interval running from
        `tier_opened_at` through `tier_deadline_at`, both endpoints included, or
        the filing is refused with `ERR_TIER_WINDOW_EXPIRED`."

        PRD: "A filed request lands in `status` `SUBMITTED` with
        `information_request_note`, `denial_reason` all null and
        `resubmission_count` at 0, and it freezes `tier_at_submission` as a copy
        of the cycle's `current_tier` at that instant — one of `STATE_AGENCY`,
        `LOCAL_GOVERNMENT` or `ELIGIBLE_NONPROFIT`."

        Design: Corner/validations/val_agency_suspension_outranks_tier_priority
        """
        scenario = _high_value_screened_asset()
        state_agency = scenario["agency"]
        nonprofit = register_nonprofit(
            name="Hill Country Youth Services", agency_code="NPO-04"
        )
        cycle = open_screening_cycle(
            scenario["asset"]["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
        )
        assert cycle["current_tier"] == "STATE_AGENCY", (
            "a new cycle opens at the first rung of the ladder"
        )

        suspend_agency(nonprofit["id"])
        nonprofit_filing = create_screening_request_payload(cycle["id"], nonprofit["id"])
        validate_error(
            api_client.create_screening_request(nonprofit_filing, ADMIN),
            ApiErrorId.ERR_AGENCY_SUSPENDED,
        )
        assert _request_count_for_cycle(cycle["id"]) == 0, (
            "a filing refused for suspension must not persist a request"
        )

        # Reinstated, the same organisation now fails only the tier gate.
        get_success_data(api_client.set_agency_status(nonprofit["id"], "ACTIVE", ADMIN))
        validate_error(
            api_client.create_screening_request(nonprofit_filing, ADMIN),
            ApiErrorId.ERR_TIER_PRIORITY_VIOLATION,
        )
        assert _request_count_for_cycle(cycle["id"]) == 0, (
            "a filing refused on tier priority must not persist a request"
        )

        accepted = validate_success(
            api_client.create_screening_request(
                create_screening_request_payload(cycle["id"], state_agency["id"]),
                ADMIN,
            ),
            201,
        )
        assert accepted["status"] == "SUBMITTED", "an accepted filing lands SUBMITTED"
        assert accepted["tier_at_submission"] == "STATE_AGENCY", (
            "tier_at_submission freezes the cycle's current_tier at filing time"
        )
        assert read_cycle(cycle["id"])["open_request_count"] == 1, (
            "open_request_count counts the one SUBMITTED request"
        )
        assert _request_count_for_cycle(cycle["id"]) == 1, (
            "only the accepted filing is on file"
        )


class TestTierWindowBounds:
    """The tier filing window is a closed interval on both of its endpoints."""

    def test_filing_is_admitted_on_both_endpoints_and_refused_outside_them(self):
        """One second before the window opens and one second after it closes are
        both refused; the opening instant and the deadline instant are both
        admitted.

        PRD: "Three checks follow existence resolution, in this order: the
        requesting organisation must not be `SUSPENDED`, or the filing is
        refused with `ERR_AGENCY_SUSPENDED`; the organisation's `agency_type`
        must equal the cycle's `current_tier`, or the filing is refused with
        `ERR_TIER_PRIORITY_VIOLATION` — this is what makes the ladder a ladder,
        and it also means a cycle sitting at `PUBLIC_SALE` admits no screening
        request at all, since no organisation's type is `PUBLIC_SALE`; and the
        logical clock must fall inside the closed interval running from
        `tier_opened_at` through `tier_deadline_at`, both endpoints included, or
        the filing is refused with `ERR_TIER_WINDOW_EXPIRED`."

        PRD: "Its `tier_deadline_at` is derived as the `tier_opened_at` plus
        `tier_window_days` whole days, where a day is an exact multiple of
        twenty-four hours."

        Design: Corner/validations/val_tier_window_is_closed_on_both_bounds
        """
        scenario = _high_value_screened_asset()
        first_agency = scenario["agency"]
        second_agency = register_state_agency(
            name="Texas Facilities Commission", agency_code="TFC-02"
        )
        cycle = open_screening_cycle(
            scenario["asset"]["id"],
            opens_at="2026-08-02T00:00:00Z",
            tier_window_days=3,
        )
        _assert_instant(
            cycle["tier_opened_at"], "2026-08-02T00:00:00.000Z", "tier_opened_at"
        )
        _assert_instant(
            cycle["tier_deadline_at"], "2026-08-05T00:00:00.000Z", "tier_deadline_at"
        )

        set_clock("2026-08-01T23:59:59Z")
        validate_error(
            api_client.create_screening_request(
                create_screening_request_payload(cycle["id"], first_agency["id"]), ADMIN
            ),
            ApiErrorId.ERR_TIER_WINDOW_EXPIRED,
        )
        assert _request_count_for_cycle(cycle["id"]) == 0, (
            "a filing one second before the window opens persists nothing"
        )

        set_clock("2026-08-02T00:00:00Z")
        opening_filing = validate_success(
            api_client.create_screening_request(
                create_screening_request_payload(cycle["id"], first_agency["id"]), ADMIN
            ),
            201,
        )
        assert opening_filing["status"] == "SUBMITTED", (
            "the opening instant itself is inside the closed interval"
        )

        set_clock("2026-08-05T00:00:00Z")
        deadline_filing = validate_success(
            api_client.create_screening_request(
                create_screening_request_payload(cycle["id"], second_agency["id"]), ADMIN
            ),
            201,
        )
        assert deadline_filing["status"] == "SUBMITTED", (
            "the deadline instant itself is inside the closed interval"
        )
        assert deadline_filing["tier_at_submission"] == "STATE_AGENCY", (
            "tier_at_submission is copied from the cycle's current_tier"
        )

        set_clock("2026-08-05T00:00:01Z")
        validate_error(
            api_client.create_screening_request(
                create_screening_request_payload(cycle["id"], second_agency["id"]), ADMIN
            ),
            ApiErrorId.ERR_TIER_WINDOW_EXPIRED,
        )

        final_cycle = read_cycle(cycle["id"])
        assert final_cycle["status"] == "OPEN", "the cycle is untouched by the refusals"
        assert final_cycle["open_request_count"] == 2, (
            "only the two in-window filings count towards open_request_count"
        )
        assert _request_count_for_cycle(cycle["id"]) == 2, (
            "exactly the two admitted filings are on file"
        )


class TestTierAdvanceGate:
    """An open request holds its tier until the deadline is reached."""

    def test_advance_is_refused_inside_the_window_and_admitted_on_the_deadline(self):
        """With one SUBMITTED request outstanding, an advance one second before
        the deadline is refused and an advance on the deadline instant succeeds.

        PRD: "An advance is permitted only when the cycle's
        `open_request_count` is zero — nobody in this tier wants the property —
        or when the logical clock has reached or passed `tier_deadline_at`,
        meaning the window has closed regardless of interest."

        PRD: "An advance attempted while the tier still holds open requests
        inside its window is refused with `ERR_TIER_WINDOW_OPEN`."

        PRD: "From `STATE_AGENCY`, `LOCAL_GOVERNMENT` or `ELIGIBLE_NONPROFIT`,
        the advance keeps the cycle in `OPEN` and moves `current_tier` exactly
        one step along the fixed order `STATE_AGENCY` → `LOCAL_GOVERNMENT` →
        `ELIGIBLE_NONPROFIT` → `PUBLIC_SALE`; `tier_opened_at` is reset to the
        logical clock, `tier_deadline_at` is recomputed from that new opening
        instant plus the same `tier_window_days`, `tier_advance_count` increases
        by 1, and the cycle's `version` increments by 1."

        PRD: "That frozen tier exists for audit and is **never** rewritten
        afterwards, not even when the request is revised."

        Design: Corner/validations/val_open_request_blocks_tier_advance_until_deadline
        """
        scenario = _high_value_screened_asset()
        cycle = open_screening_cycle(
            scenario["asset"]["id"], opens_at=CLOCK_EPOCH, tier_window_days=3
        )
        _assert_instant(
            cycle["tier_deadline_at"], "2026-08-04T00:00:00.000Z", "tier_deadline_at"
        )
        request = file_screening_request(cycle["id"], scenario["agency"]["id"])
        assert request["status"] == "SUBMITTED", "the filing is outstanding"

        set_clock("2026-08-03T23:59:59Z")
        validate_error(
            api_client.advance_screening_tier(cycle["id"], OFFICER),
            ApiErrorId.ERR_TIER_WINDOW_OPEN,
        )
        blocked = read_cycle(cycle["id"])
        assert blocked["current_tier"] == "STATE_AGENCY", (
            "a refused advance leaves the ladder exactly where it was"
        )
        assert blocked["tier_advance_count"] == 0, (
            "a refused advance does not count as an advance"
        )

        set_clock("2026-08-04T00:00:00Z")
        advanced = validate_success(
            api_client.advance_screening_tier(cycle["id"], OFFICER), 200
        )
        assert advanced["current_tier"] == "LOCAL_GOVERNMENT", (
            "reaching the deadline releases the tier regardless of open interest"
        )
        assert advanced["tier_advance_count"] == 1, "the advance is counted"
        assert advanced["status"] == "OPEN", "the cycle stays open on the next rung"
        _assert_instant(
            advanced["tier_opened_at"], "2026-08-04T00:00:00.000Z", "tier_opened_at"
        )
        _assert_instant(
            advanced["tier_deadline_at"], "2026-08-07T00:00:00.000Z", "tier_deadline_at"
        )
        assert advanced["open_request_count"] == 1, (
            "the advance does not resolve the outstanding request"
        )

        carried = read_request(request["id"])
        assert carried["status"] == "SUBMITTED", (
            "the request survives the advance untouched"
        )
        assert carried["tier_at_submission"] == "STATE_AGENCY", (
            "tier_at_submission is never rewritten"
        )
        assert carried["denial_reason"] is None, (
            "an advance denies nobody, so denial_reason stays null"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "SCREENING", (
            "the asset stays in SCREENING while the ladder walks"
        )


class TestAwardAndTransferCrossChecks:
    """An award and a transfer order both reject a request from elsewhere."""

    def test_foreign_request_and_foreign_asset_are_both_refused(self):
        """A request belonging to another cycle cannot win this cycle, and a
        transfer order cannot name an asset other than the one its request
        competed for.

        PRD: "The cycle must be `OPEN`; the named request must belong to this
        very cycle and must be in `status` `SUBMITTED`, and a request from
        another cycle or in any other status is refused with
        `ERR_REQUEST_CYCLE_MISMATCH`; and the requesting organisation must still
        be `ACTIVE`, an award naming a request from a suspended organisation
        being refused with `ERR_AGENCY_SUSPENDED`."

        PRD: "All three are supplied explicitly and all three are
        cross-checked: the `screening_request_id` must name a request whose
        `status` is `APPROVED`, and the supplied `asset_id` and
        `recipient_agency_id` must match, respectively, the asset of that
        request's cycle and the organisation that filed the request."

        PRD: "Any divergence is refused with `ERR_REQUEST_CYCLE_MISMATCH`."

        PRD: "First, read the recipient's discount factor from its
        `agency_type`: a `STATE_AGENCY` pays twenty-five hundredths of value, a
        `LOCAL_GOVERNMENT` pays fifty hundredths, and an `ELIGIBLE_NONPROFIT`
        pays ten hundredths."

        Design: Corner/validations/val_award_and_transfer_reject_foreign_request
        """
        scenario = setup_assessed_assets([
            {
                "kind": "furniture",
                "overrides": _HIGH_VALUE_ASSET,
                "assessment": _HIGH_VALUE_ASSESSMENT,
            },
            {
                "kind": "furniture",
                "overrides": dict(
                    _HIGH_VALUE_ASSET,
                    description="Executive breakout room suite, twelve seats",
                ),
                "assessment": _HIGH_VALUE_ASSESSMENT,
            },
        ])
        agency = scenario["agency"]
        first_asset, second_asset = scenario["assets"]
        first_cycle = open_screening_cycle(
            first_asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
        )
        second_cycle = open_screening_cycle(
            second_asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
        )
        request = file_screening_request(first_cycle["id"], agency["id"])

        validate_error(
            api_client.award_screening_cycle(
                second_cycle["id"], request["id"], OFFICER
            ),
            ApiErrorId.ERR_REQUEST_CYCLE_MISMATCH,
        )
        untouched = read_cycle(second_cycle["id"])
        assert untouched["status"] == "OPEN", "a refused award leaves the cycle open"
        assert untouched["awarded_by_user_id"] is None, (
            "a refused award stamps nobody as the awarding officer"
        )

        awarded = validate_success(
            api_client.award_screening_cycle(first_cycle["id"], request["id"], OFFICER),
            200,
        )
        assert awarded["status"] == "AWARDED", "the request's own cycle admits the award"
        assert read_request(request["id"])["status"] == "APPROVED", (
            "the named request wins the cycle"
        )

        validate_error(
            api_client.create_transfer_order(
                create_transfer_order_payload(
                    second_asset["id"], agency["id"], request["id"]
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_REQUEST_CYCLE_MISMATCH,
        )
        _, meta = validate_paginated(
            api_client.list_transfer_orders(OFFICER, {"asset_id": second_asset["id"]})
        )
        assert meta["total_count"] == 0, (
            "a refused transfer order persists nothing against the foreign asset"
        )

        order = validate_success(
            api_client.create_transfer_order(
                create_transfer_order_payload(
                    first_asset["id"], agency["id"], request["id"]
                ),
                OFFICER,
            ),
            201,
        )
        assert order["status"] == "ISSUED", "a newly issued order sits in ISSUED"
        assert order["base_transfer_cents"] == 250000, (
            "a STATE_AGENCY recipient pays twenty-five hundredths of the valuation"
        )
        assert order["handling_fee_cents"] == 12500, (
            "the handling fee band is keyed only on base_transfer_cents"
        )
        assert order["transfer_price_cents"] == 262500, (
            "a non-federal asset is priced as base plus handling fee"
        )
        assert read_asset(first_asset["id"])["disposition_status"] == "AWARDED_TRANSFER", (
            "the awarded asset moved to AWARDED_TRANSFER"
        )
        assert read_asset(second_asset["id"])["disposition_status"] == "SCREENING", (
            "the untouched asset is still in its own screening cycle"
        )


class TestBidFiscalBounds:
    """The reserve floor and the minimum increment are both inclusive bounds."""

    def test_reserve_and_increment_are_refused_one_cent_short_and_admitted_at_par(self):
        """A bid one cent under the reserve is refused, the reserve itself is
        admitted, a second bid one cent under the increment is refused and the
        increment itself is admitted.

        PRD: "By default the reserve is derived from the asset's stored
        valuation: take sixty hundredths of `fair_market_value_cents`, round that
        product half up to whole cents, and use the larger of that figure and
        twenty-five dollars."

        PRD: "The `amount_cents` must be at or above the lot's
        `reserve_price_cents`, otherwise `ERR_BID_BELOW_RESERVE` (HTTP 422)."

        PRD: "Where the lot already carries at least one `ACTIVE` bid, the
        `amount_cents` must also be at or above the lot's current
        `high_bid_cents` plus a minimum increment of twenty-five dollars,
        otherwise `ERR_BID_INCREMENT_NOT_MET` (HTTP 422)."

        Design: Corner/validations/val_reserve_floor_then_minimum_increment_on_bids
        """
        scenario = setup_open_lot(
            kind="furniture",
            route="de_minimis",
            opens_at="2026-08-02T00:00:00Z",
            closes_at="2026-08-03T00:00:00Z",
        )
        lot = scenario["lot"]
        assert lot["reserve_price_cents"] == 7524, (
            "the computed reserve is sixty hundredths of the stored valuation"
        )
        assert lot["required_deposit_cents"] == 0, (
            "a reserve below five thousand dollars requires no deposit"
        )
        first = register_bidder(email="first@lonestarsalvage.example")
        second = register_bidder(
            email="second@hillcountryauctions.example",
            legal_name="Hill Country Auctions LLC",
        )

        validate_error(
            api_client.place_bid(
                lot["id"],
                create_bid_payload(first["id"], 7523),
                make_bidder_headers(first["id"]),
            ),
            ApiErrorId.ERR_BID_BELOW_RESERVE,
        )
        assert read_lot(lot["id"])["bid_count"] == 0, (
            "a bid one cent below the reserve is not recorded"
        )

        at_reserve = validate_success(
            api_client.place_bid(
                lot["id"],
                create_bid_payload(first["id"], 7524),
                make_bidder_headers(first["id"]),
            ),
            201,
        )
        assert at_reserve["status"] == "ACTIVE", "an accepted bid is created ACTIVE"
        after_first = read_lot(lot["id"])
        assert after_first["high_bid_cents"] == 7524, "the reserve itself is admitted"
        assert after_first["bid_count"] == 1, "exactly one bid stands on the lot"

        validate_error(
            api_client.place_bid(
                lot["id"],
                create_bid_payload(second["id"], 10023),
                make_bidder_headers(second["id"]),
            ),
            ApiErrorId.ERR_BID_INCREMENT_NOT_MET,
        )
        assert read_lot(lot["id"])["high_bid_cents"] == 7524, (
            "a bid one cent short of the increment leaves the high bid alone"
        )

        validate_success(
            api_client.place_bid(
                lot["id"],
                create_bid_payload(second["id"], 10024),
                make_bidder_headers(second["id"]),
            ),
            201,
        )
        final_lot = read_lot(lot["id"])
        assert final_lot["high_bid_cents"] == 10024, (
            "the high bid plus the minimum increment is admitted at par"
        )
        assert final_lot["bid_count"] == 2, "both admitted bids are counted"
        for bidder in (first, second):
            assert read_bidder(bidder["id"])["winning_lot_count"] == 0, (
                "no lot has closed, so nobody has won anything yet"
            )


class TestBidDepositRequirement:
    """The deposit gate is satisfied out of held funds and is inclusive."""

    def test_bid_is_refused_until_held_deposit_reaches_the_requirement(self):
        """With no deposit and then with one cent too little the bid is refused
        for the deposit; topped up to the requirement exactly, it is admitted.

        PRD: "A reserve of five thousand dollars **or more** requires a deposit
        of ten hundredths of the reserve, rounded half up to whole cents, but
        never less than five hundred dollars."

        PRD: "Last, the bidder's `deposit_held_cents` must be at or above the
        lot's `required_deposit_cents`, otherwise `ERR_BID_DEPOSIT_INSUFFICIENT`
        (HTTP 402) — the deposit requirement is re-read from the lot on every
        bid, and it is satisfied out of held funds without consuming them."

        PRD: "A deposit carries an `amount_cents` and adds that amount to both
        `deposit_paid_cents` and `deposit_held_cents`, leaving
        `deposit_applied_cents` and `deposit_forfeited_cents` untouched, which
        keeps the deposit-custody identity of §2.13 intact."

        Design: Corner/validations/val_bid_requires_deposit_at_or_above_requirement
        """
        scenario = setup_open_lot_with_bidder(
            kind="furniture",
            route="screening",
            asset_overrides=_HIGH_VALUE_ASSET,
            assessment_overrides=_HIGH_VALUE_ASSESSMENT,
            opens_at="2026-08-02T00:00:00Z",
            closes_at="2026-08-03T00:00:00Z",
        )
        lot, bidder = scenario["lot"], scenario["bidder"]
        assert lot["reserve_price_cents"] == 600000, (
            "the computed reserve is sixty hundredths of the stored valuation"
        )
        assert lot["reserve_source"] == "COMPUTED", (
            "no override was supplied, so the reserve is the computed figure"
        )
        assert lot["required_deposit_cents"] == 60000, (
            "a reserve at or above five thousand dollars demands ten hundredths of it"
        )
        headers = make_bidder_headers(bidder["id"])

        validate_error(
            api_client.place_bid(
                lot["id"], create_bid_payload(bidder["id"], 600000), headers
            ),
            ApiErrorId.ERR_BID_DEPOSIT_INSUFFICIENT,
        )
        lodge_deposit(bidder["id"], 59999)
        validate_error(
            api_client.place_bid(
                lot["id"], create_bid_payload(bidder["id"], 600000), headers
            ),
            ApiErrorId.ERR_BID_DEPOSIT_INSUFFICIENT,
        )
        assert read_lot(lot["id"])["bid_count"] == 0, (
            "neither refused bid was recorded against the lot"
        )

        lodge_deposit(bidder["id"], 1)
        admitted = validate_success(
            api_client.place_bid(
                lot["id"], create_bid_payload(bidder["id"], 600000), headers
            ),
            201,
        )
        assert admitted["status"] == "ACTIVE", "an accepted bid is created ACTIVE"
        final_lot = read_lot(lot["id"])
        assert final_lot["high_bid_cents"] == 600000, "the admitted bid sets the high bid"
        assert final_lot["bid_count"] == 1, "exactly the admitted bid is counted"

        final_bidder = read_bidder(bidder["id"])
        assert final_bidder["deposit_paid_cents"] == 60000, (
            "both lodgements accumulate into deposit_paid_cents"
        )
        assert final_bidder["deposit_held_cents"] == 60000, (
            "the deposit gate is satisfied out of held funds without consuming them"
        )
        assert final_bidder["deposit_applied_cents"] == 0, (
            "bidding applies nothing to an invoice"
        )
        assert final_bidder["deposit_forfeited_cents"] == 0, (
            "nothing has been forfeited"
        )
        exhausted = read_cycle(scenario["cycle"]["id"])
        assert exhausted["status"] == "EXHAUSTED", (
            "the asset reached the auction channel through ladder exhaustion"
        )
        assert exhausted["current_tier"] == "PUBLIC_SALE", (
            "exhaustion leaves the cycle on the last rung of the ladder"
        )


class TestPaymentFitsRemainingBalance:
    """A payment may never exceed the balance standing before the call."""

    def test_overpayment_is_refused_at_every_stage_and_the_exact_balance_settles(self):
        """One cent over the outstanding balance is refused both on the first
        instalment and on the last, and the exact balance settles the invoice.

        PRD: "The `buyer_premium_cents` is the `hammer_price_cents` multiplied by
        the venue's `buyer_premium_pct`, rounded half up to whole cents on its
        own."

        PRD: "The `sales_tax_cents` is the sum of `hammer_price_cents` and
        `buyer_premium_cents` multiplied by the venue's `sales_tax_pct`, again
        rounded half up on its own — the tax is charged on the premium-inclusive
        amount, not on the hammer price alone."

        PRD: "The `amount_cents` must be strictly greater than zero and must not
        exceed the invoice's `balance_due_cents` as it stands before the call,
        and the combined cash plus deposit that this one call would apply must
        likewise not exceed that balance; either overshoot is refused with
        `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422)."

        PRD: "A payment that leaves a balance moves the invoice `ISSUED` →
        `PARTIALLY_PAID`, or holds it at `PARTIALLY_PAID` on later instalments; a
        payment that brings `amount_paid_cents` exactly up to `total_due_cents`
        moves it to `PAID`, and that settlement in turn moves the lot
        `CLOSED_MET` → `SETTLED`."

        Design: Corner/validations/val_payment_amount_must_fit_remaining_balance
        """
        scenario = setup_closed_met_lot(
            bid_amount_cents=10000,
            kind="furniture",
            route="de_minimis",
            opens_at="2026-08-02T00:00:00Z",
            closes_at="2026-08-03T00:00:00Z",
        )
        invoice = scenario["invoice"]
        assert invoice["buyer_premium_cents"] == 1050, "the premium rounds on its own"
        assert invoice["sales_tax_cents"] == 702, (
            "the tax is charged on the premium-inclusive amount and rounds on its own"
        )
        assert invoice["total_due_cents"] == 11752, (
            "the total is the exact sum of the three money lines"
        )
        _assert_instant(invoice["due_at"], "2026-08-10T00:00:00.000Z", "due_at")

        validate_error(
            api_client.pay_sale_invoice(
                invoice["id"], create_payment_payload(11753), FINANCE
            ),
            ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE,
        )
        # A zero amount breaks the strictly-positive rule and the balance rule at
        # once, and the PRD states both in the same breath, so either identifier
        # is a faithful reading.
        validate_error_is_one_of(
            api_client.pay_sale_invoice(
                invoice["id"], create_payment_payload(0), FINANCE
            ),
            [ApiErrorId.ERR_INVALID_REQUEST, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE],
        )
        refused = read_invoice(invoice["id"])
        assert refused["status"] == "ISSUED", "a refused payment leaves the invoice alone"
        assert refused["amount_paid_cents"] == 0, "no money was taken"

        part = validate_success(
            api_client.pay_sale_invoice(
                invoice["id"], create_payment_payload(5000), FINANCE
            ),
            200,
        )
        assert part["status"] == "PARTIALLY_PAID", "a payment leaving a balance part-pays"
        assert part["balance_due_cents"] == 6752, (
            "the balance is the total less what has been paid"
        )

        validate_error(
            api_client.pay_sale_invoice(
                invoice["id"], create_payment_payload(6753), FINANCE
            ),
            ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE,
        )
        assert read_invoice(invoice["id"])["amount_paid_cents"] == 5000, (
            "the refused instalment took nothing further"
        )

        settled = validate_success(
            api_client.pay_sale_invoice(
                invoice["id"], create_payment_payload(6752), FINANCE
            ),
            200,
        )
        assert settled["status"] == "PAID", "the exact remaining balance is admitted"
        assert settled["amount_paid_cents"] == 11752, "the invoice is paid in full"
        assert settled["balance_due_cents"] == 0, "nothing is left outstanding"
        assert read_lot(scenario["lot"]["id"])["status"] == "SETTLED", (
            "settlement carries the lot from CLOSED_MET to SETTLED"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "SOLD", (
            "the sold asset stays SOLD through settlement"
        )


class TestWindowSanityBounds:
    """Both sale windows and screening windows must open no earlier than now."""

    def test_malformed_windows_are_refused_and_the_clock_instant_is_admitted(self):
        """A window opening before the clock, a zero-length window and an
        inverted window are all refused; an `opens_at` equal to the clock is
        admitted for a lot and for a screening cycle alike.

        PRD: "Finally the window is checked for basic sanity: `opens_at` must be
        at or after the logical clock and `closes_at` must be strictly later than
        `opens_at`, otherwise `ERR_INVALID_WINDOW` (HTTP 422)."

        PRD: "Next comes the federal use-period gate of §3.3, refused with
        `ERR_FEDERAL_USE_PERIOD_ACTIVE`; last comes the window check, in which
        `opens_at` must be at or after the logical clock, a violation of which is
        refused with `ERR_INVALID_WINDOW` (HTTP 422)."

        PRD: "A new lot sits in `status` `DRAFT` with `high_bid_cents` and
        `bid_count` at 0 and `closed_by_user_id` and `closed_at` null."

        PRD: "Creation also recomputes the hosting venue's `active_lot_count`,
        which counts that venue's lots in `DRAFT` or `OPEN`, and increments the
        asset's `version` by 1."

        PRD: "Its `tier_deadline_at` is derived as the `tier_opened_at` plus
        `tier_window_days` whole days, where a day is an exact multiple of
        twenty-four hours."

        Design: Corner/validations/val_lot_and_cycle_window_bounds_rejected
        """
        scenario = setup_assessed_assets([
            {"kind": "furniture"},
            {
                "kind": "furniture",
                "overrides": _HIGH_VALUE_ASSET,
                "assessment": _HIGH_VALUE_ASSESSMENT,
            },
        ])
        cheap_asset, dear_asset = scenario["assets"]
        venue = register_venue()

        for opens_at, closes_at, why in [
            ("2026-07-31T23:59:59Z", "2026-08-03T00:00:00Z",
             "a window opening one second before the clock is malformed"),
            ("2026-08-02T00:00:00Z", "2026-08-02T00:00:00Z",
             "a zero-length window is malformed because closes_at is not strictly later"),
            ("2026-08-03T00:00:00Z", "2026-08-02T00:00:00Z",
             "an inverted window is malformed"),
        ]:
            validate_error(
                api_client.create_auction_lot(
                    create_auction_lot_payload(
                        cheap_asset["id"], venue["id"],
                        opens_at=opens_at, closes_at=closes_at,
                    ),
                    OFFICER,
                ),
                ApiErrorId.ERR_INVALID_WINDOW,
            )
            assert read_asset(cheap_asset["id"])["disposition_status"] == "ASSESSED", why

        validate_error(
            api_client.create_screening_cycle(
                create_screening_cycle_payload(
                    dear_asset["id"], opens_at="2026-07-31T23:59:59Z",
                    tier_window_days=3,
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_INVALID_WINDOW,
        )
        assert read_asset(dear_asset["id"])["disposition_status"] == "ASSESSED", (
            "a refused cycle leaves the asset out of screening"
        )

        lot = validate_success(
            api_client.create_auction_lot(
                create_auction_lot_payload(
                    cheap_asset["id"], venue["id"],
                    opens_at=CLOCK_EPOCH, closes_at="2026-08-03T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        assert lot["status"] == "DRAFT", "a new lot sits in DRAFT"
        assert lot["reserve_price_cents"] == 7524, (
            "the computed reserve is sixty hundredths of the stored valuation"
        )
        assert read_asset(cheap_asset["id"])["disposition_status"] == "LISTED", (
            "the de-minimis asset is listable straight out of ASSESSED"
        )

        cycle = validate_success(
            api_client.create_screening_cycle(
                create_screening_cycle_payload(
                    dear_asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=3
                ),
                OFFICER,
            ),
            201,
        )
        _assert_instant(cycle["tier_opened_at"], CLOCK_EPOCH, "tier_opened_at")
        _assert_instant(
            cycle["tier_deadline_at"], "2026-08-04T00:00:00.000Z", "tier_deadline_at"
        )
        assert read_venue(venue["id"])["active_lot_count"] == 1, (
            "only the admitted lot counts towards the venue's active lots"
        )


class TestDistributionBasisAndSinglePostedRow:
    """A basis is only available when its money has arrived, and one lot posts once."""

    def test_cash_basis_is_unavailable_unpaid_and_a_second_posting_is_refused(self):
        """On a closed lot whose invoice is merely issued, the cash basis is
        unavailable while the accrual basis is not; once the accrual row is
        posted, a further distribution for the same lot is refused.

        PRD: "Then the requested basis must be available: `ACCRUAL` requires the
        lot's `status` to be `CLOSED_MET` or `SETTLED`, while `CASH` requires that
        and additionally requires the lot's non-`VOIDED` `SaleInvoice` to be
        `PAID` or `DEFAULTED`; an unavailable basis is refused with
        `ERR_DISTRIBUTION_BASIS_UNAVAILABLE`."

        PRD: "Last, a lot may carry at most one posted distribution, so creating
        another one while a distribution for the same `auction_lot_id` is already
        `POSTED` is refused with `ERR_DISTRIBUTION_ALREADY_POSTED`."

        PRD: "The first slice is the smaller of the base and five thousand
        dollars, charged at twelve and a half hundredths."

        PRD: "The `net_to_agency_cents` is the larger of zero and the base less
        the service fee less the cost recovery."

        PRD: "The post stamps `posted_by_user_id` and `posted_at`, moves the row
        to `POSTED`, and in a second hop caused by that stamping recomputes the
        beneficiary agency's `proceeds_account_balance_cents` and
        `posted_distribution_count`."

        Design: Corner/validations/val_distribution_basis_availability_and_single_posted_row
        """
        scenario = setup_closed_met_lot(
            bid_amount_cents=10000,
            kind="furniture",
            route="de_minimis",
            opens_at="2026-08-02T00:00:00Z",
            closes_at="2026-08-03T00:00:00Z",
        )
        lot, agency = scenario["lot"], scenario["agency"]
        assert scenario["invoice"]["status"] == "ISSUED", (
            "the buyer has not paid, so no cash has arrived"
        )

        validate_error(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(lot["id"], lot["version"], "CASH"),
                FINANCE,
            ),
            ApiErrorId.ERR_DISTRIBUTION_BASIS_UNAVAILABLE,
        )
        _, meta = validate_paginated(
            api_client.list_proceeds_distributions(
                FINANCE, {"auction_lot_id": lot["id"]}
            )
        )
        assert meta["total_count"] == 0, "a refused basis persists no distribution"

        distribution = validate_success(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot["id"], lot["version"], "ACCRUAL"
                ),
                FINANCE,
            ),
            201,
        )
        assert distribution["distributable_base_cents"] == 10000, (
            "the accrual base is the price the lot achieved"
        )
        assert distribution["service_fee_cents"] == 1250, (
            "the whole base falls inside the first fee slice"
        )
        assert distribution["cost_recovery_cents"] == 0, (
            "the asset carries no verified clearance certificate to recover against"
        )
        assert distribution["net_to_agency_cents"] == 8750, (
            "the net is the base less the fee less the recovery"
        )

        posted = post_distribution(distribution["id"])
        assert posted["status"] == "POSTED", "the calculated row posts to the ledger"
        assert posted["posted_by_user_id"] == FINANCE_USER_ID, (
            "posted_by_user_id is stamped from the posting controller"
        )
        beneficiary = read_agency(agency["id"])
        assert beneficiary["proceeds_account_balance_cents"] == 8750, (
            "the beneficiary's ledger is recomputed from the posted net"
        )
        assert beneficiary["posted_distribution_count"] == 1, (
            "the beneficiary carries exactly one posted distribution"
        )

        validate_error(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot["id"], read_lot(lot["id"])["version"], "ACCRUAL"
                ),
                FINANCE,
            ),
            ApiErrorId.ERR_DISTRIBUTION_ALREADY_POSTED,
        )
        _, meta = validate_paginated(
            api_client.list_proceeds_distributions(
                FINANCE, {"auction_lot_id": lot["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "the refused second calculation persists nothing"
        )


class TestCertificateFamilyBeforeApplicability:
    """The method-family check runs ahead of the applicability check."""

    def test_method_family_is_reported_before_inapplicability(self):
        """A badly paired type and method on an asset with no release gate reports
        the family mismatch; the same asset with a well-paired certificate reports
        the inapplicability; and `DESTROY` is admitted only at demilitarisation
        code `Q`.

        PRD: "Four checks run, in this order. The `certified_on` date may not be
        in the future relative to the logical clock, refused with
        `ERR_FUTURE_DATE`."

        PRD: "Then the `method` must belong to its `cert_type`'s family: a
        `DATA_SANITIZATION` certificate admits only `NIST_CLEAR`, `NIST_PURGE` or
        `DEGAUSS`, a `DEMILITARIZATION` certificate admits only `MUTILATE` or
        `DESTROY`, and `DESTROY` in particular is admitted only when the asset's
        `demil_code` is `Q`; a mismatch is refused with
        `ERR_CLEARANCE_METHOD_MISMATCH` (HTTP 422)."

        PRD: "Only then is applicability considered: a certificate may be filed
        only against an asset whose `clearance_status` is `REQUIRED_PENDING`,
        `BLOCKED` or `CLEARED`, because an asset at `NOT_REQUIRED` has no release
        gate to certify, and the attempt is refused with
        `ERR_CLEARANCE_NOT_APPLICABLE`."

        PRD: "Because the family check sits ahead of the applicability check, a
        badly paired `cert_type` and `method` filed against an unrestricted,
        non-data-bearing asset reports the method mismatch rather than the
        inapplicability."

        Design: Corner/validations/val_certificate_method_family_outranks_applicability
        """
        set_clock()
        agency = register_state_agency()
        turn_in = create_draft_turn_in(agency["id"])
        data_asset = add_asset_with_payload(
            agency["id"],
            create_it_asset_payload(
                turn_in["id"],
                acquisition_cost_cents=300000,
                acquisition_date="2024-05-20",
                is_data_bearing=True,
            ),
        )
        restricted_asset = add_asset_with_payload(
            agency["id"],
            create_restricted_asset_payload(
                turn_in["id"],
                acquisition_cost_cents=900000,
                acquisition_date="2019-06-01",
                demil_code="B",
            ),
        )
        plain_asset = add_asset(agency["id"], turn_in["id"])
        submit_turn_in(agency["id"], turn_in["id"])
        assert plain_asset["clearance_status"] == "NOT_REQUIRED", (
            "an item that is neither data-bearing nor restricted has no release gate"
        )

        for asset_id, cert_type, method, expected, why in [
            (plain_asset["id"], "DATA_SANITIZATION", "MUTILATE",
             ApiErrorId.ERR_CLEARANCE_METHOD_MISMATCH,
             "a mutilation is outside the sanitisation family, and the family check "
             "outranks the missing release gate"),
            (plain_asset["id"], "DATA_SANITIZATION", "NIST_PURGE",
             ApiErrorId.ERR_CLEARANCE_NOT_APPLICABLE,
             "a well-paired certificate on a gateless asset reports inapplicability"),
            (data_asset["id"], "DEMILITARIZATION", "NIST_PURGE",
             ApiErrorId.ERR_CLEARANCE_METHOD_MISMATCH,
             "a purge is outside the demilitarisation family"),
            (restricted_asset["id"], "DEMILITARIZATION", "DESTROY",
             ApiErrorId.ERR_CLEARANCE_METHOD_MISMATCH,
             "destruction is admitted only at demilitarisation code Q"),
        ]:
            validate_error(
                api_client.create_clearance_certificate(
                    asset_id,
                    create_clearance_certificate_payload(
                        cert_type=cert_type, method=method
                    ),
                    TECHNICIAN,
                ),
                expected,
            )
            _, meta = validate_paginated(
                api_client.list_clearance_certificates(asset_id, TECHNICIAN)
            )
            assert meta["total_count"] == 0, why

        certificate = validate_success(
            api_client.create_clearance_certificate(
                restricted_asset["id"],
                create_clearance_certificate_payload(
                    cert_type="DEMILITARIZATION", method="MUTILATE"
                ),
                TECHNICIAN,
            ),
            201,
        )
        assert certificate["technician_user_id"] == TECHNICIAN_USER_ID, (
            "the filing technician is recorded on the certificate"
        )
        assert read_asset(restricted_asset["id"])["clearance_status"] == "CLEARED", (
            "a verified certificate completing every required type clears the asset"
        )
        assert read_asset(data_asset["id"])["clearance_status"] == "REQUIRED_PENDING", (
            "the data-bearing asset still awaits its sanitisation certificate"
        )
        assert read_asset(plain_asset["id"])["clearance_status"] == "NOT_REQUIRED", (
            "the gateless asset is untouched by every refusal"
        )
