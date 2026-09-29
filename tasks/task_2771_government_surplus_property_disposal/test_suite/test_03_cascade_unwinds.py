"""Multi-hop cascades that unwind a completed decision across several entities.

Three chains are exercised: voiding an acknowledged transfer order back into
screening, debarring a bidder who had already part-paid for a lot, and a
demilitarisation certificate whose method destroys the property under a live
auction.
"""

from datetime import datetime

from test_helpers import (
    ADMIN_USER_ID,
    CLOCK_EPOCH,
    OFFICER_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_asset_with_payload,
    advance_tier,
    assert_bid,
    assert_deposit_custody_invariant,
    assert_lot_rollups,
    assert_sale_invoice,
    assert_screening_cycle,
    assert_screening_request,
    assert_surplus_asset,
    assert_transfer_order,
    assert_turn_in,
    assess_asset,
    create_bid_payload,
    create_clearance_certificate_payload,
    create_draft_turn_in,
    create_lot,
    create_transfer_order_payload,
    create_vehicle_asset_payload,
    file_screening_request,
    find_invoice_for_lot,
    list_lot_bids,
    make_agency_officer_headers,
    make_bidder_headers,
    make_clearance_technician_headers,
    make_disposal_officer_headers,
    make_program_admin_headers,
    open_screening_cycle,
    pay_invoice,
    place_bid,
    read_asset,
    read_bidder,
    read_cycle,
    read_invoice,
    read_lot,
    read_request,
    read_transfer_order,
    read_turn_in,
    read_venue,
    register_bidder,
    register_nonprofit,
    register_state_agency,
    register_venue,
    review_turn_in,
    set_clock,
    submit_turn_in,
    validate_error,
    validate_paginated,
    validate_success,
)

FINANCE = TEST_USERS["finance_controller_headers"]
OFFICER = TEST_USERS["disposal_officer_headers"]


def _instant(value) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of the same moment compare
    equal regardless of how many fractional digits are rendered."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


# ─── Chain 1: an acknowledged transfer order voided back into screening ────

ROLLER_PAYLOAD_DESCRIPTION = "2020 Wacker roller, seized drum"
VOID_REASON = "NPO-12 lost its commercial driver and cannot take custody"


def _setup_acknowledged_nonprofit_transfer(api) -> dict:
    """One turn-in with two assets. Asset P walks the ladder to the nonprofit tier,
    is awarded to NPO-12 against a losing sibling request from NPO-13, and the
    resulting transfer order is acknowledged. Asset Q's cycle is the control row."""
    set_clock(CLOCK_EPOCH)
    ag_st = register_state_agency()
    ag_np = register_nonprofit(
        name="Capital Area Food Relief",
        agency_code="NPO-12",
        donee_certification_expires_on="2027-03-31",
    )
    ag_np2 = register_nonprofit(
        name="Colorado River Conservancy",
        agency_code="NPO-13",
        donee_certification_expires_on="2027-03-31",
    )
    turn_in = create_draft_turn_in(ag_st["id"])
    asset_p = add_asset_with_payload(
        ag_st["id"], create_vehicle_asset_payload(turn_in["id"])
    )
    asset_q = add_asset_with_payload(
        ag_st["id"],
        {
            "turn_in_id": turn_in["id"],
            "category": "HEAVY_EQUIPMENT",
            "description": ROLLER_PAYLOAD_DESCRIPTION,
            "acquisition_cost_cents": 870401,
            "acquisition_date": "2020-06-30",
        },
    )
    submit_turn_in(ag_st["id"], turn_in["id"])
    assess_asset(
        asset_p["id"], asset_p["version"],
        condition_code="C4", functional=True,
        repair_cost_estimate_cents=185000, assessed_on="2026-07-28",
    )
    assess_asset(
        asset_q["id"], asset_q["version"],
        condition_code="C5", functional=False,
        repair_cost_estimate_cents=0, assessed_on="2026-07-28",
    )
    review_turn_in(turn_in["id"], "ACCEPT")

    cyc_p = open_screening_cycle(
        asset_p["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
    )
    advance_tier(cyc_p["id"], times=2)
    r_a = file_screening_request(
        cyc_p["id"], ag_np["id"],
        intended_use="Food bank delivery route support",
        justification=(
            "The pantry fleet cannot haul pallets to the three rural distribution "
            "points."
        ),
        needed_by_date="2026-09-20",
    )
    r_b = file_screening_request(
        cyc_p["id"], ag_np2["id"],
        intended_use="Riparian restoration crew transport",
        justification=(
            "Volunteer crews currently tow equipment with privately owned vehicles."
        ),
        needed_by_date="2026-09-25",
    )
    validate_success(
        api.award_screening_cycle(
            cyc_p["id"], r_a["id"], make_disposal_officer_headers(OFFICER_USER_ID)
        ),
        200,
    )
    order = validate_success(
        api.create_transfer_order(
            create_transfer_order_payload(asset_p["id"], ag_np["id"], r_a["id"]),
            make_disposal_officer_headers(OFFICER_USER_ID),
        ),
        201,
    )
    validate_success(
        api.acknowledge_transfer_order(
            order["id"], make_agency_officer_headers(ag_np["id"])
        ),
        200,
    )

    cyc_q = open_screening_cycle(
        asset_q["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
    )
    advance_tier(cyc_q["id"], times=1)

    set_clock("2026-08-03T00:00:00Z")
    return {
        "ag_st": ag_st, "ag_np": ag_np, "ag_np2": ag_np2, "turn_in": turn_in,
        "asset_p": asset_p, "asset_q": asset_q, "cyc_p": cyc_p, "cyc_q": cyc_q,
        "r_a": r_a, "r_b": r_b, "order": order,
    }


def _void(api, order_id: str):
    return api.void_transfer_order(
        order_id, VOID_REASON, make_disposal_officer_headers(OFFICER_USER_ID)
    )


class TestTransferVoidFourHopReturnToScreening:
    """One void call walks order -> request -> cycle -> asset."""

    def test_void_of_an_acknowledged_order_walks_all_four_hops(self, api):
        """Acknowledged is a legal void source, and each hop is caused by the one
        before it rather than by the request.

        PRD: "An order in either `ISSUED` or `ACKNOWLEDGED` may be voided by a
        `DisposalOfficer` with a `void_reason`, and the void unwinds the entire award
        in four hops."
        PRD: "Hop one stores the `void_reason` and moves the order to `VOIDED`; when
        the order had been acknowledged, `acknowledged_at` is retained for audit rather
        than cleared."
        PRD: "Hop two, caused by hop one, moves the documented `ScreeningRequest` from
        `APPROVED` to `DENIED` with `denial_reason` set to `TRANSFER_VOIDED`."
        PRD: "Hop three, caused by hop two, follows from that request no longer being
        approved: the parent `ScreeningCycle` moves from `AWARDED` back to `OPEN`, with
        `current_tier` left exactly where it was, `tier_opened_at` reset to the logical
        clock, `tier_deadline_at` recomputed from that reset opening, and
        `awarded_by_user_id` and `awarded_at` cleared back to null — the tier gets a
        fresh full window to find another taker."
        PRD: "Hop four, caused by hop three, follows from the cycle being open again:
        the cycle's asset moves `disposition_status` from `AWARDED_TRANSFER` back to
        `SCREENING`."

        Design: Difficulty/transitive_cascade/tc_transfer_void_four_hop_return_to_screening
        """
        scenario = _setup_acknowledged_nonprofit_transfer(api)
        order_id = scenario["order"]["id"]

        before = read_transfer_order(order_id)
        assert before["status"] == "ACKNOWLEDGED", (
            f"precondition: the order must be ACKNOWLEDGED, got {before['status']}"
        )
        acknowledged_at = before["acknowledged_at"]
        assert acknowledged_at is not None, (
            "precondition: acknowledgement stamps acknowledged_at"
        )

        validate_success(_void(api, order_id), 200)

        # Hop one — the order itself.
        voided = read_transfer_order(order_id)
        assert_transfer_order(voided)
        assert voided["status"] == "VOIDED", (
            f"hop one moves the order to VOIDED, got {voided['status']}"
        )
        assert voided["void_reason"] == VOID_REASON, (
            f"hop one stores the void_reason, got {voided['void_reason']!r}"
        )
        _assert_instant(
            voided["acknowledged_at"], acknowledged_at, "acknowledged_at"
        )

        # Hop two — the request the order documented.
        request = read_request(scenario["r_a"]["id"])
        assert_screening_request(request)
        assert request["status"] == "DENIED", (
            f"hop two moves the documented request to DENIED, got {request['status']}"
        )
        assert request["denial_reason"] == "TRANSFER_VOIDED", (
            "the documented request's denial_reason must be TRANSFER_VOIDED, got "
            f"{request['denial_reason']}"
        )

        # Hop three — the parent cycle.
        cycle = read_cycle(scenario["cyc_p"]["id"])
        assert_screening_cycle(cycle)
        assert cycle["status"] == "OPEN", (
            f"hop three moves the cycle from AWARDED back to OPEN, got "
            f"{cycle['status']}"
        )
        assert cycle["awarded_at"] is None, (
            f"awarded_at is cleared back to null, got {cycle['awarded_at']}"
        )
        assert cycle["awarded_by_user_id"] is None, (
            f"awarded_by_user_id is cleared back to null, got "
            f"{cycle['awarded_by_user_id']}"
        )
        assert cycle["current_tier"] == "ELIGIBLE_NONPROFIT", (
            "current_tier is left exactly where it was rather than rewinding to "
            f"STATE_AGENCY, got {cycle['current_tier']}"
        )
        assert cycle["tier_advance_count"] == 2, (
            "the two advances that reached the nonprofit tier are preserved, got "
            f"{cycle['tier_advance_count']}"
        )
        _assert_instant(
            cycle["tier_opened_at"], "2026-08-03T00:00:00Z", "tier_opened_at"
        )
        _assert_instant(
            cycle["tier_deadline_at"], "2026-08-08T00:00:00Z", "tier_deadline_at"
        )

        # Hop four — the cycle's asset.
        asset = read_asset(scenario["asset_p"]["id"])
        assert_surplus_asset(asset)
        assert asset["disposition_status"] == "SCREENING", (
            "hop four walks the asset from AWARDED_TRANSFER back to SCREENING, got "
            f"{asset['disposition_status']}"
        )

    def test_one_void_call_bumps_the_version_of_every_row_it_touched(self, api):
        """The cascade is a write to four rows, so four version counters move on a
        single request.

        PRD: "Each of the four rows touched — order, request, cycle and asset — has its
        `version` incremented by 1."
        PRD: "Each hop that mutates a row refreshes that row's `updated_at` and
        increments its `version` by 1, so a cascade that touches an invoice, a lot, an
        asset and a bidder bumps four version counters."
        PRD: "Most resources additionally carry an `updated_at` — an ISO 8601 UTC
        timestamp refreshed on every mutation of the row — and a `version`, an integer
        that starts at 1 on insert and increments by exactly 1 on every mutation of
        that row, including mutations the server performs on its own initiative as part
        of a cascade and including recomputation of derived fields."

        Design: Difficulty/transitive_cascade/tc_transfer_void_four_hop_return_to_screening
        """
        scenario = _setup_acknowledged_nonprofit_transfer(api)
        order_id = scenario["order"]["id"]

        before = {
            "order": read_transfer_order(order_id),
            "request": read_request(scenario["r_a"]["id"]),
            "cycle": read_cycle(scenario["cyc_p"]["id"]),
            "asset": read_asset(scenario["asset_p"]["id"]),
        }

        validate_success(_void(api, order_id), 200)

        after = {
            "order": read_transfer_order(order_id),
            "request": read_request(scenario["r_a"]["id"]),
            "cycle": read_cycle(scenario["cyc_p"]["id"]),
            "asset": read_asset(scenario["asset_p"]["id"]),
        }
        for label in ("order", "request", "cycle", "asset"):
            assert after[label]["version"] == before[label]["version"] + 1, (
                f"the void must increment the {label} version by exactly 1, from "
                f"{before[label]['version']} to {after[label]['version']}"
            )

        assert after["order"]["version"] == 3, (
            "three mutations of the order row — issuance, acknowledgement and the "
            f"void — give version 3, got {after['order']['version']}"
        )
        assert after["request"]["version"] == 3, (
            "three mutations of the request row — filing, the award's approval and "
            f"the void's denial — give version 3, got {after['request']['version']}"
        )
        assert after["asset"]["version"] == 5, (
            "five mutations of the asset row — creation, the assessment, the cycle "
            "entry, the award and the void's return to screening — give version 5, "
            f"got {after['asset']['version']}"
        )

    def test_cascade_is_scoped_to_the_voided_award(self, api):
        """The already-denied sibling request, the control cycle on the same turn-in
        and the parent turn-in are all left as they were.

        PRD: "It also resolves every competitor: the named request moves `SUBMITTED` →
        `APPROVED`, and every *other* request on the cycle whose `status` is
        `SUBMITTED` or `INFO_REQUESTED` moves to `DENIED` with `denial_reason` set to
        `LOST_AWARD`, processed in `created_at` ascending order."
        PRD: "Hop two, caused by hop one, moves the documented `ScreeningRequest` from
        `APPROVED` to `DENIED` with `denial_reason` set to `TRANSFER_VOIDED`."
        PRD: "Whenever an operation leaves every one of an `ACCEPTED` turn-in's assets
        in a terminal `disposition_status` — that is, every asset is `RELEASED`,
        `RETAINED` or `DESTROYED` — the turn-in moves from `ACCEPTED` to `CLOSED` on
        the server's own initiative, its `appraised_total_cents` freezes at its
        then-current value, and its `version` increments by 1."

        Design: Difficulty/transitive_cascade/tc_transfer_void_four_hop_return_to_screening
        """
        scenario = _setup_acknowledged_nonprofit_transfer(api)

        sibling_before = read_request(scenario["r_b"]["id"])
        control_cycle_before = read_cycle(scenario["cyc_q"]["id"])
        control_asset_before = read_asset(scenario["asset_q"]["id"])
        turn_in_before = read_turn_in(scenario["turn_in"]["id"])

        validate_success(_void(api, scenario["order"]["id"]), 200)

        sibling = read_request(scenario["r_b"]["id"])
        assert sibling["status"] == "DENIED", (
            f"the losing sibling stays DENIED, got {sibling['status']}"
        )
        assert sibling["denial_reason"] == "LOST_AWARD", (
            "the sibling's denial_reason is not rewritten to TRANSFER_VOIDED, got "
            f"{sibling['denial_reason']}"
        )
        assert sibling["version"] == 2, (
            "two mutations of the sibling row — filing and the award's denial — give "
            f"version 2, got {sibling['version']}"
        )
        assert sibling["version"] == sibling_before["version"], (
            "the void writes only the request the order documented"
        )

        control_cycle = read_cycle(scenario["cyc_q"]["id"])
        assert control_cycle["status"] == "OPEN", (
            f"the control cycle stays OPEN, got {control_cycle['status']}"
        )
        assert control_cycle["current_tier"] == "LOCAL_GOVERNMENT", (
            "the control cycle keeps its own tier, got "
            f"{control_cycle['current_tier']}"
        )
        assert control_cycle["tier_advance_count"] == 1, (
            "the control cycle keeps its single advance, got "
            f"{control_cycle['tier_advance_count']}"
        )
        assert control_cycle["version"] == 2, (
            "two mutations of the control cycle — opening and one advance — give "
            f"version 2, got {control_cycle['version']}"
        )
        assert control_cycle["version"] == control_cycle_before["version"], (
            "the void writes only the cycle whose award it unwound"
        )

        control_asset = read_asset(scenario["asset_q"]["id"])
        assert control_asset["disposition_status"] == "SCREENING", (
            "the second asset on the same turn-in stays in SCREENING, got "
            f"{control_asset['disposition_status']}"
        )
        assert control_asset["version"] == 3, (
            "three mutations of the second asset — creation, its assessment and its "
            f"own cycle entry — give version 3, got {control_asset['version']}"
        )
        assert control_asset["version"] == control_asset_before["version"], (
            "the void writes only the asset of the cycle it reopened"
        )

        turn_in = read_turn_in(scenario["turn_in"]["id"])
        assert_turn_in(turn_in)
        assert turn_in["status"] == "ACCEPTED", (
            "no asset reached a terminal disposition, so the upward closure does not "
            f"fire and the turn-in stays ACCEPTED, got {turn_in['status']}"
        )
        assert turn_in["version"] == turn_in_before["version"], (
            "the turn-in row is not written by the void, so its version is unchanged "
            f"at {turn_in_before['version']}, got {turn_in['version']}"
        )


# ─── Chain 2: debarring the winner of a part-paid lot ──────────────────────

SERVER_FMV_CENTS = 985_946
SERVER_RESERVE_CENTS = 591_568
SERVER_REQUIRED_DEPOSIT_CENTS = 59_157
HAMMER_CENTS = 640_000
PREMIUM_CENTS = 67_200
TAX_CENTS = 44_907
TOTAL_DUE_CENTS = 752_107
DEPOSIT_CENTS = 60_000
CASH_CENTS = 40_000
AMOUNT_PAID_CENTS = 100_000
BALANCE_DUE_CENTS = 652_107


def _setup_part_paid_sold_lot(api) -> dict:
    """A rack server auctioned to a registered bidder who part-paid the invoice with
    cash plus its whole deposit, leaving the lot CLOSED_MET and the asset SOLD."""
    set_clock(CLOCK_EPOCH)
    agency = register_state_agency()
    turn_in = create_draft_turn_in(
        agency["id"], custody_location="Austin Data Center Dock 2"
    )
    asset = add_asset_with_payload(
        agency["id"],
        {
            "turn_in_id": turn_in["id"],
            "category": "IT_EQUIPMENT",
            "description": "Dell PowerEdge R740 rack server, drives removed",
            "acquisition_cost_cents": 1449920,
            "acquisition_date": "2023-11-02",
        },
    )
    submit_turn_in(agency["id"], turn_in["id"])
    assess_asset(
        asset["id"], asset["version"],
        condition_code="C2", functional=True,
        repair_cost_estimate_cents=0, assessed_on="2026-07-30",
    )
    review_turn_in(turn_in["id"], "ACCEPT")

    cycle = open_screening_cycle(
        asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=3
    )
    advance_tier(cycle["id"], times=4)

    venue = register_venue()
    lot = create_lot(asset["id"], venue["id"])

    set_clock("2026-09-01T00:00:00Z")
    validate_success(
        api.open_auction_lot(
            lot["id"], make_disposal_officer_headers(OFFICER_USER_ID)
        ),
        200,
    )
    bidder = register_bidder(
        status="REGISTERED", deposit_cents=DEPOSIT_CENTS,
        legal_name="Lone Star Equipment LLC", email="bids@lonestar.example",
    )
    bid = place_bid(lot["id"], bidder["id"], HAMMER_CENTS)

    set_clock("2026-09-05T00:00:00Z")
    validate_success(
        api.close_auction_lot(
            lot["id"], make_disposal_officer_headers(OFFICER_USER_ID)
        ),
        200,
    )
    invoice = find_invoice_for_lot(lot["id"])
    assert invoice is not None, (
        "the close cascade must have issued an invoice discoverable by its lot"
    )
    pay_invoice(invoice["id"], bidder["id"], CASH_CENTS, use_deposit=True)

    return {
        "agency": agency, "turn_in": turn_in, "asset": asset, "cycle": cycle,
        "venue": venue, "lot": lot, "bidder": bidder, "bid": bid,
        "invoice": invoice,
    }


def _debar(api, bidder_id: str):
    return api.set_bidder_status(
        bidder_id, "DEBARRED", make_program_admin_headers(ADMIN_USER_ID)
    )


class TestBidderDebarmentFiveHopUnwind:
    """Debarment runs backwards along the auction pipeline in five hops."""

    def test_part_paid_invoice_is_the_starting_point(self, api):
        """The deposit moves before the cash, so the invoice records the full deposit
        alongside the cash instalment and sits at PARTIALLY_PAID.

        PRD: "Where `use_deposit` is true, the deposit moves first, before the cash is
        applied: the smaller of the bidder's `deposit_held_cents` and the invoice's
        `balance_due_cents` moves out of `deposit_held_cents` and into
        `deposit_applied_cents` on both the `Bidder` and the `SaleInvoice`, and the
        moved amount counts as payment in its own right."
        PRD: "The invoice's `amount_paid_cents` therefore always equals the sum of every
        cash `amount_cents` received plus the invoice's own `deposit_applied_cents`, and
        `balance_due_cents` is re-derived as `total_due_cents` less
        `amount_paid_cents`."
        PRD: "A payment that leaves a balance moves the invoice `ISSUED` →
        `PARTIALLY_PAID`, or holds it at `PARTIALLY_PAID` on later instalments; a
        payment that brings `amount_paid_cents` exactly up to `total_due_cents` moves it
        to `PAID`, and that settlement in turn moves the lot `CLOSED_MET` → `SETTLED`."
        PRD: "For every `Bidder`, `deposit_paid_cents` — the cumulative cash the bidder
        has ever deposited — always equals the sum of `deposit_held_cents`,
        `deposit_applied_cents` and `deposit_forfeited_cents`."

        Design: Difficulty/transitive_cascade/tc_bidder_debarment_five_hop_unwind
        """
        scenario = _setup_part_paid_sold_lot(api)

        lot = read_lot(scenario["lot"]["id"])
        assert lot["reserve_price_cents"] == SERVER_RESERVE_CENTS, (
            f"the computed reserve must be {SERVER_RESERVE_CENTS}, got "
            f"{lot['reserve_price_cents']}"
        )
        assert lot["required_deposit_cents"] == SERVER_REQUIRED_DEPOSIT_CENTS, (
            f"required_deposit_cents must be {SERVER_REQUIRED_DEPOSIT_CENTS}, got "
            f"{lot['required_deposit_cents']}"
        )
        assert lot["status"] == "CLOSED_MET", (
            f"a met reserve closes the lot at CLOSED_MET, got {lot['status']}"
        )

        invoice = read_invoice(scenario["invoice"]["id"])
        assert_sale_invoice(invoice)
        assert invoice["hammer_price_cents"] == HAMMER_CENTS
        assert invoice["buyer_premium_cents"] == PREMIUM_CENTS, (
            f"buyer_premium_cents must be {PREMIUM_CENTS}, got "
            f"{invoice['buyer_premium_cents']}"
        )
        assert invoice["sales_tax_cents"] == TAX_CENTS, (
            f"sales_tax_cents must be {TAX_CENTS}, got {invoice['sales_tax_cents']}"
        )
        assert invoice["total_due_cents"] == TOTAL_DUE_CENTS, (
            f"total_due_cents must be {TOTAL_DUE_CENTS}, got "
            f"{invoice['total_due_cents']}"
        )
        assert invoice["amount_paid_cents"] == AMOUNT_PAID_CENTS, (
            f"amount_paid_cents must be {AMOUNT_PAID_CENTS} — {CASH_CENTS} cash plus "
            f"a {DEPOSIT_CENTS} deposit — got {invoice['amount_paid_cents']}"
        )
        assert invoice["balance_due_cents"] == BALANCE_DUE_CENTS, (
            f"balance_due_cents must be {BALANCE_DUE_CENTS}, got "
            f"{invoice['balance_due_cents']}"
        )
        assert invoice["status"] == "PARTIALLY_PAID", (
            f"a payment that leaves a balance gives PARTIALLY_PAID, got "
            f"{invoice['status']}"
        )

        bidder = read_bidder(scenario["bidder"]["id"])
        assert bidder["deposit_paid_cents"] == DEPOSIT_CENTS, (
            f"deposit_paid_cents must be {DEPOSIT_CENTS}, got "
            f"{bidder['deposit_paid_cents']}"
        )
        assert bidder["deposit_held_cents"] == 0, (
            "the whole deposit moved out of deposit_held_cents, got "
            f"{bidder['deposit_held_cents']}"
        )
        assert bidder["deposit_applied_cents"] == DEPOSIT_CENTS, (
            f"deposit_applied_cents must be {DEPOSIT_CENTS}, got "
            f"{bidder['deposit_applied_cents']}"
        )
        assert_deposit_custody_invariant(bidder)
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "SOLD", (
            "precondition: the close cascade must have moved the asset to SOLD"
        )

    def test_debarment_walks_all_five_hops(self, api):
        """One status call retracts the winning bid, unwinds the lot, voids the invoice,
        returns the asset to the auction pool and gives the deposit back to held.

        PRD: "A `ProgramAdmin` or a `DisposalOfficer` moves a bidder from `REGISTERED`
        or from `SUSPENDED` to `DEBARRED`, and five hops follow."
        PRD: "Hop one moves the bidder to `DEBARRED`."
        PRD: "Hop two, caused by hop one, moves every bid belonging to that bidder whose
        `status` is `ACTIVE` or `WINNING` to `RETRACTED`, processed in `created_at`
        ascending order, decrementing that bidder's `winning_lot_count` by 1 for each
        retracted winner."
        PRD: "Hop three, caused by hop two, handles each lot that just lost its winning
        bid: the lot moves `CLOSED_MET` → `CLOSED_NO_SALE`, its `high_bid_cents` and
        `bid_count` are re-derived over the bids that remain in `ACTIVE` or `WINNING`,
        and its `SaleInvoice` in `ISSUED` or `PARTIALLY_PAID` moves to `VOIDED` with
        `void_reason` recorded as `WINNER_DEBARRED`."
        PRD: "Hop four, caused by hop three, follows from those lots having become
        `CLOSED_NO_SALE`: each affected asset moves `disposition_status` `SOLD` →
        `AUCTION_ELIGIBLE`, ready to be auctioned again."
        PRD: "Hop five, caused by the invoices voided in hop three, returns each voided
        invoice's `deposit_applied_cents` to that bidder's `deposit_held_cents`, so the
        debarred bidder's deposit custody identity still balances even as its money is
        frozen."

        Design: Difficulty/transitive_cascade/tc_bidder_debarment_five_hop_unwind
        """
        scenario = _setup_part_paid_sold_lot(api)

        validate_success(_debar(api, scenario["bidder"]["id"]), 200)

        # Hop one — the bidder.
        bidder = read_bidder(scenario["bidder"]["id"])
        assert bidder["status"] == "DEBARRED", (
            f"hop one moves the bidder to DEBARRED, got {bidder['status']}"
        )

        # Hop two — the bidder's live bids.
        bid = None
        for row in list_lot_bids(scenario["lot"]["id"]):
            if row["id"] == scenario["bid"]["id"]:
                bid = row
        assert bid is not None, "the retracted bid is still listed on its lot"
        assert_bid(bid)
        assert bid["status"] == "RETRACTED", (
            "hop two retracts the winning bid, a transition no forward path allows; "
            f"got {bid['status']}"
        )

        # Hop three — the lot and its invoice.
        lot = read_lot(scenario["lot"]["id"])
        assert lot["status"] == "CLOSED_NO_SALE", (
            f"hop three moves the lot from CLOSED_MET to CLOSED_NO_SALE, got "
            f"{lot['status']}"
        )
        invoice = read_invoice(scenario["invoice"]["id"])
        assert invoice["status"] == "VOIDED", (
            f"hop three voids the invoice, got {invoice['status']}"
        )
        assert invoice["void_reason"] == "WINNER_DEBARRED", (
            f"the invoice's void_reason must be WINNER_DEBARRED, got "
            f"{invoice['void_reason']!r}"
        )

        # Hop four — the asset under the lot.
        asset = read_asset(scenario["asset"]["id"])
        assert asset["disposition_status"] == "AUCTION_ELIGIBLE", (
            "hop four returns the asset from SOLD to the non-terminal "
            f"AUCTION_ELIGIBLE, got {asset['disposition_status']}"
        )

        # Hop five — the money.
        assert bidder["deposit_applied_cents"] == 0, (
            "hop five empties deposit_applied_cents, got "
            f"{bidder['deposit_applied_cents']}"
        )
        assert bidder["deposit_held_cents"] == DEPOSIT_CENTS, (
            f"hop five returns the whole {DEPOSIT_CENTS} deposit to "
            f"deposit_held_cents, got {bidder['deposit_held_cents']}"
        )
        assert bidder["deposit_forfeited_cents"] == 0, (
            "custody is restored rather than forfeited, so "
            f"deposit_forfeited_cents stays 0, got {bidder['deposit_forfeited_cents']}"
        )
        assert bidder["deposit_paid_cents"] == DEPOSIT_CENTS, (
            f"deposit_paid_cents is never reduced and stays {DEPOSIT_CENTS}, got "
            f"{bidder['deposit_paid_cents']}"
        )

    def test_debarment_restores_every_roll_up_it_had_driven_up(self, api):
        """The compensating cascade recomputes the lot, venue and bidder roll-ups back
        to their pre-sale values, and the parent turn-in does not close.

        PRD: "Derived roll-up counters are always **fully recomputed** from their source
        rows rather than incrementally adjusted, so that a compensating operation
        restores the previous value exactly rather than leaving an accumulated drift."
        PRD: "An accepted bid is created in `status` `ACTIVE` with `placed_at` stamped
        from the logical clock, and it recomputes two roll-ups on the lot:
        `high_bid_cents` becomes the largest `amount_cents` among the lot's bids whose
        `status` is `ACTIVE` or `WINNING`, and 0 when that set is empty; `bid_count`
        becomes the number of the lot's bids whose `status` is `ACTIVE`, `WINNING` or
        `OUTBID`, which deliberately excludes retracted ones."
        PRD: "Creation also recomputes the hosting venue's `active_lot_count`, which
        counts that venue's lots in `DRAFT` or `OPEN`, and increments the asset's
        `version` by 1."
        PRD: "Hop two, caused by hop one, moves every bid belonging to that bidder whose
        `status` is `ACTIVE` or `WINNING` to `RETRACTED`, processed in `created_at`
        ascending order, decrementing that bidder's `winning_lot_count` by 1 for each
        retracted winner."
        PRD: "For every `Bidder`, `deposit_paid_cents` — the cumulative cash the bidder
        has ever deposited — always equals the sum of `deposit_held_cents`,
        `deposit_applied_cents` and `deposit_forfeited_cents`."
        PRD: "`deposit_paid_cents` is monotonically non-decreasing: it grows when a
        deposit is recorded and is never reduced by anything, not by an application to
        an invoice, not by a forfeiture and not by a void."
        PRD: "Whenever an operation leaves every one of an `ACCEPTED` turn-in's assets
        in a terminal `disposition_status` — that is, every asset is `RELEASED`,
        `RETAINED` or `DESTROYED` — the turn-in moves from `ACCEPTED` to `CLOSED` on the
        server's own initiative, its `appraised_total_cents` freezes at its then-current
        value, and its `version` increments by 1."

        Design: Difficulty/transitive_cascade/tc_bidder_debarment_five_hop_unwind
        """
        scenario = _setup_part_paid_sold_lot(api)
        assert read_bidder(scenario["bidder"]["id"])["winning_lot_count"] == 1, (
            "precondition: closing the lot gave the winner a winning_lot_count of 1"
        )

        validate_success(_debar(api, scenario["bidder"]["id"]), 200)

        lot = read_lot(scenario["lot"]["id"])
        assert lot["high_bid_cents"] == 0, (
            "with the only bid retracted the live-bid set is empty, so high_bid_cents "
            f"recomputes to 0, got {lot['high_bid_cents']}"
        )
        assert lot["bid_count"] == 0, (
            "bid_count excludes retracted bids, so it recomputes to 0, got "
            f"{lot['bid_count']}"
        )
        assert_lot_rollups(lot, list_lot_bids(scenario["lot"]["id"]))

        venue = read_venue(scenario["venue"]["id"])
        assert venue["active_lot_count"] == 0, (
            "CLOSED_NO_SALE is neither DRAFT nor OPEN, so the venue's "
            f"active_lot_count is 0, got {venue['active_lot_count']}"
        )

        bidder = read_bidder(scenario["bidder"]["id"])
        assert bidder["winning_lot_count"] == 0, (
            "retracting the winning bid decrements winning_lot_count back to 0, got "
            f"{bidder['winning_lot_count']}"
        )
        assert bidder["deposit_paid_cents"] == DEPOSIT_CENTS, (
            "deposit_paid_cents is never reduced by a void, got "
            f"{bidder['deposit_paid_cents']}"
        )
        assert_deposit_custody_invariant(bidder)

        turn_in = read_turn_in(scenario["turn_in"]["id"])
        assert turn_in["status"] == "ACCEPTED", (
            "AUCTION_ELIGIBLE is not a terminal disposition, so the upward closure "
            f"does not fire and the turn-in stays ACCEPTED, got {turn_in['status']}"
        )
        assert turn_in["appraised_total_cents"] == SERVER_FMV_CENTS, (
            f"appraised_total_cents stays {SERVER_FMV_CENTS}, got "
            f"{turn_in['appraised_total_cents']}"
        )

    def test_debarred_bidder_bidding_again_is_told_about_the_lot(self, api):
        """After the unwind the lot is no longer open, and the lot gate outranks the
        bidder's own standing.

        PRD: "The lot must be `OPEN` with the logical clock at or after `opens_at` and
        strictly before `closes_at`, otherwise `ERR_LOT_NOT_OPEN` — this outranks the
        bidder's own standing, so a bid on a closed lot by an unregistered bidder
        reports the lot."
        PRD: "The bidder's `status` must be `REGISTERED`; `PENDING`, `SUSPENDED` and
        `DEBARRED` are all refused with `ERR_BIDDER_NOT_REGISTERED` (HTTP 403)."
        PRD: "Hop three, caused by hop two, handles each lot that just lost its winning
        bid: the lot moves `CLOSED_MET` → `CLOSED_NO_SALE`, its `high_bid_cents` and
        `bid_count` are re-derived over the bids that remain in `ACTIVE` or `WINNING`,
        and its `SaleInvoice` in `ISSUED` or `PARTIALLY_PAID` moves to `VOIDED` with
        `void_reason` recorded as `WINNER_DEBARRED`."

        Design: Difficulty/transitive_cascade/tc_bidder_debarment_five_hop_unwind
        """
        scenario = _setup_part_paid_sold_lot(api)
        validate_success(_debar(api, scenario["bidder"]["id"]), 200)

        bidder_id = scenario["bidder"]["id"]
        assert read_lot(scenario["lot"]["id"])["status"] == "CLOSED_NO_SALE", (
            "precondition: the cascade left the lot at CLOSED_NO_SALE"
        )
        assert read_bidder(bidder_id)["status"] == "DEBARRED", (
            "precondition: the bidder is DEBARRED"
        )

        validate_error(
            api.place_bid(
                scenario["lot"]["id"],
                create_bid_payload(bidder_id, HAMMER_CENTS + 25_000),
                make_bidder_headers(bidder_id),
            ),
            ApiErrorId.ERR_LOT_NOT_OPEN,
        )

        lot = read_lot(scenario["lot"]["id"])
        assert lot["bid_count"] == 0, (
            f"the refused bid creates nothing, so bid_count stays 0, got "
            f"{lot['bid_count']}"
        )
        assert lot["high_bid_cents"] == 0, (
            f"the refused bid leaves high_bid_cents at 0, got {lot['high_bid_cents']}"
        )


# ─── Chain 3: destruction under a live auction ─────────────────────────────

TURRET_FMV_CENTS = 62_669
TURRET_RESERVE_CENTS = 37_601
DESTROY_NOTES = "Turret ring and trunnions cut per demil code Q"


def _setup_listed_restricted_asset_with_bid(api) -> dict:
    """A demil-code-Q turret that walked the ladder to exhaustion, is listed at an
    OPEN lot and carries one ACTIVE bid at the reserve."""
    set_clock(CLOCK_EPOCH)
    agency = register_state_agency(
        name="State Military Department", agency_code="ARM-04"
    )
    turn_in = create_draft_turn_in(
        agency["id"], custody_location="Camp Swift Bunker 3"
    )
    asset = add_asset_with_payload(
        agency["id"],
        {
            "turn_in_id": turn_in["id"],
            "category": "RESTRICTED_MILITARY",
            "description": "Armored turret assembly, weapon removed",
            "acquisition_cost_cents": 870400,
            "acquisition_date": "2020-06-30",
            "is_restricted": True,
            "demil_code": "Q",
        },
    )
    submit_turn_in(agency["id"], turn_in["id"])
    assess_asset(
        asset["id"], asset["version"],
        condition_code="C5", functional=False,
        repair_cost_estimate_cents=0, assessed_on="2026-07-29",
    )
    review_turn_in(turn_in["id"], "ACCEPT")

    cycle = open_screening_cycle(
        asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=3
    )
    advance_tier(cycle["id"], times=4)

    venue = register_venue()
    lot = create_lot(asset["id"], venue["id"])

    set_clock("2026-09-01T00:00:00Z")
    validate_success(
        api.open_auction_lot(
            lot["id"], make_disposal_officer_headers(OFFICER_USER_ID)
        ),
        200,
    )
    bidder = register_bidder(
        status="REGISTERED", end_use_certificate_expires_on="2027-01-31",
        legal_name="Republic Salvage Inc", email="desk@republicsalvage.example",
    )
    bid = place_bid(lot["id"], bidder["id"], TURRET_RESERVE_CENTS)

    return {
        "agency": agency, "turn_in": turn_in, "asset": asset, "cycle": cycle,
        "venue": venue, "lot": lot, "bidder": bidder, "bid": bid,
    }


def _destroy(api, asset_id: str):
    return api.create_clearance_certificate(
        asset_id,
        create_clearance_certificate_payload(
            cert_type="DEMILITARIZATION", method="DESTROY",
            serials_verified=True, certified_on="2026-09-01", notes=DESTROY_NOTES,
        ),
        make_clearance_technician_headers(TECHNICIAN_USER_ID),
    )


class TestDemilDestroyFourHopCancellation:
    """A destroy certificate ends the property and cancels the auction under it."""

    def test_destroy_certificate_moves_both_axes_and_cancels_the_live_lot(self, api):
        """One certificate insert drives both lifecycle axes, cancels the OPEN lot,
        retracts its bid and recomputes the venue's active-lot roll-up.

        PRD: "A `ClearanceTechnician` files a clearance certificate against an asset,
        supplying the `cert_type` — either `DATA_SANITIZATION` or `DEMILITARIZATION` —
        the `method` performed, a `serials_verified` boolean recording whether the
        physical serial numbers matched the record, a `certified_on` calendar date on
        which the work was done, and optional `notes`."
        PRD: "The certificate stores the `asset_id` it addresses and stamps
        `technician_user_id` from the technician's `X-User-ID`."
        PRD: "**Destruction.** A `DEMILITARIZATION` certificate whose `method` is
        `DESTROY` — admissible only where `is_restricted` is true and `demil_code` is
        `Q` — does not merely certify the asset, it ends it."
        PRD: "Filed against an asset whose `disposition_status` is `ASSESSED`,
        `SCREENING`, `AUCTION_ELIGIBLE` or `LISTED`, hop one sets `disposition_status`
        to `DESTROYED` and `clearance_status` to `CLEARED` simultaneously — the only
        place in the system where one request moves both axes."
        PRD: "From `AUCTION_ELIGIBLE`, every lot for the asset whose `status` is `DRAFT`
        moves to `CANCELLED`; from `LISTED`, every lot whose `status` is `DRAFT` or
        `OPEN` does, in each case processed in `created_at` ascending order, with every
        bid on those cancelled lots whose `status` is `ACTIVE` or `WINNING` moving to
        `RETRACTED` and each affected venue's `active_lot_count` recomputed."

        Design: Difficulty/transitive_cascade/tc_demil_destroy_four_hop_cancellation
        """
        scenario = _setup_listed_restricted_asset_with_bid(api)
        asset_id = scenario["asset"]["id"]

        before_asset = read_asset(asset_id)
        assert before_asset["disposition_status"] == "LISTED", (
            f"precondition: the asset must be LISTED, got "
            f"{before_asset['disposition_status']}"
        )
        assert before_asset["clearance_status"] == "REQUIRED_PENDING", (
            "precondition: a restricted asset carries a pending release gate, got "
            f"{before_asset['clearance_status']}"
        )
        assert before_asset["fair_market_value_cents"] == TURRET_FMV_CENTS, (
            f"precondition: fair_market_value_cents must be {TURRET_FMV_CENTS}, got "
            f"{before_asset['fair_market_value_cents']}"
        )
        before_lot = read_lot(scenario["lot"]["id"])
        assert before_lot["status"] == "OPEN", (
            f"precondition: the lot must be OPEN, got {before_lot['status']}"
        )
        assert before_lot["reserve_price_cents"] == TURRET_RESERVE_CENTS, (
            f"precondition: the computed reserve must be {TURRET_RESERVE_CENTS}, got "
            f"{before_lot['reserve_price_cents']}"
        )
        assert before_lot["required_deposit_cents"] == 0, (
            "precondition: a reserve below five thousand dollars needs no deposit, got "
            f"{before_lot['required_deposit_cents']}"
        )
        assert read_venue(scenario["venue"]["id"])["active_lot_count"] == 1, (
            "precondition: the OPEN lot counts towards the venue's active_lot_count"
        )

        certificate = validate_success(_destroy(api, asset_id), 201)
        assert certificate["cert_type"] == "DEMILITARIZATION", (
            f"the certificate stores its cert_type, got {certificate['cert_type']}"
        )
        assert certificate["method"] == "DESTROY", (
            f"the certificate stores its method, got {certificate['method']}"
        )
        assert certificate["serials_verified"] is True, (
            "the certificate stores serials_verified, got "
            f"{certificate['serials_verified']}"
        )
        assert certificate["technician_user_id"] == TECHNICIAN_USER_ID, (
            "technician_user_id is stamped from the filing technician, got "
            f"{certificate['technician_user_id']}"
        )
        assert certificate["asset_id"] == asset_id, (
            "the certificate stores the asset it addresses"
        )
        assert certificate["notes"] == DESTROY_NOTES, (
            f"the optional notes are stored, got {certificate['notes']!r}"
        )

        # Hop one — both axes at once.
        asset = read_asset(asset_id)
        assert asset["disposition_status"] == "DESTROYED", (
            f"hop one sets disposition_status to DESTROYED, got "
            f"{asset['disposition_status']}"
        )
        assert asset["clearance_status"] == "CLEARED", (
            f"hop one sets clearance_status to CLEARED in the same call, got "
            f"{asset['clearance_status']}"
        )

        # Hop two — the lot under the destroyed asset.
        lot = read_lot(scenario["lot"]["id"])
        assert lot["status"] == "CANCELLED", (
            f"hop two cancels the OPEN lot under a live auction, got {lot['status']}"
        )

        # Hop three — the bid and the venue roll-up.
        bids = list_lot_bids(scenario["lot"]["id"])
        retracted = [b for b in bids if b["id"] == scenario["bid"]["id"]]
        assert retracted, "the retracted bid is still listed on its lot"
        assert retracted[0]["status"] == "RETRACTED", (
            f"hop three retracts the ACTIVE bid, got {retracted[0]['status']}"
        )
        assert read_venue(scenario["venue"]["id"])["active_lot_count"] == 0, (
            "a CANCELLED lot is neither DRAFT nor OPEN, so the venue's "
            "active_lot_count recomputes to 0"
        )

    def test_destruction_closes_the_parent_turn_in_and_creates_no_invoice(self, api):
        """The fourth hop bubbles upward: the destroyed asset is the turn-in's only
        child, so the parent closes. A cancellation is not a close, so no invoice
        exists.

        PRD: "In every variant a final hop bubbles upward: when every asset of the
        parent turn-in has reached a terminal disposition, the turn-in moves `ACCEPTED`
        → `CLOSED`."
        PRD: "Whenever an operation leaves every one of an `ACCEPTED` turn-in's assets
        in a terminal `disposition_status` — that is, every asset is `RELEASED`,
        `RETAINED` or `DESTROYED` — the turn-in moves from `ACCEPTED` to `CLOSED` on the
        server's own initiative, its `appraised_total_cents` freezes at its then-current
        value, and its `version` increments by 1."
        PRD: "Invoices are never created directly through a request."
        PRD: "An accepted bid is created in `status` `ACTIVE` with `placed_at` stamped
        from the logical clock, and it recomputes two roll-ups on the lot:
        `high_bid_cents` becomes the largest `amount_cents` among the lot's bids whose
        `status` is `ACTIVE` or `WINNING`, and 0 when that set is empty; `bid_count`
        becomes the number of the lot's bids whose `status` is `ACTIVE`, `WINNING` or
        `OUTBID`, which deliberately excludes retracted ones."
        PRD: "The asset's `version` increments by 1."

        Design: Difficulty/transitive_cascade/tc_demil_destroy_four_hop_cancellation
        """
        scenario = _setup_listed_restricted_asset_with_bid(api)
        asset_id = scenario["asset"]["id"]
        assert read_turn_in(scenario["turn_in"]["id"])["status"] == "ACCEPTED", (
            "precondition: the parent turn-in is ACCEPTED before the destruction"
        )

        validate_success(_destroy(api, asset_id), 201)

        turn_in = read_turn_in(scenario["turn_in"]["id"])
        assert_turn_in(turn_in)
        assert turn_in["status"] == "CLOSED", (
            "the bubble-up fires because the destroyed asset is the turn-in's only "
            f"child and DESTROYED is terminal, got {turn_in['status']}"
        )
        assert turn_in["asset_count"] == 1, (
            f"asset_count counts every asset regardless of state, got "
            f"{turn_in['asset_count']}"
        )
        assert turn_in["appraised_total_cents"] == TURRET_FMV_CENTS, (
            f"appraised_total_cents freezes at {TURRET_FMV_CENTS}, got "
            f"{turn_in['appraised_total_cents']}"
        )

        invoices, meta = validate_paginated(
            api.list_sale_invoices(
                FINANCE, params={"auction_lot_id": scenario["lot"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "a cancellation is not a close, so no invoice was ever issued for the "
            f"lot; got {meta['total_count']}"
        )
        assert invoices == [], (
            f"the invoice listing for the cancelled lot must be empty, got {invoices}"
        )

        lot = read_lot(scenario["lot"]["id"])
        assert lot["high_bid_cents"] == 0, (
            "the retracted bid leaves the live-bid set empty, so high_bid_cents "
            f"recomputes to 0, got {lot['high_bid_cents']}"
        )
        assert lot["bid_count"] == 0, (
            f"bid_count excludes retracted bids, so it recomputes to 0, got "
            f"{lot['bid_count']}"
        )
        assert_lot_rollups(lot, list_lot_bids(scenario["lot"]["id"]))

        asset = read_asset(asset_id)
        assert asset["version"] == 6, (
            "six mutations of the asset row — creation, the assessment, the "
            "screening-cycle entry, the tier exhaustion, the listing and the destroy "
            f"certificate — give version 6, got {asset['version']}"
        )

    def test_terminal_states_refuse_the_operations_they_used_to_accept(self, api):
        """`CANCELLED` and `DESTROYED` are ends of the line: reopening the lot and
        releasing the asset are both refused.

        PRD: "Generic state preconditions, including every attempt from a terminal state
        and every repeat of an already-applied trigger: `ERR_INVALID_STATE` (409),
        followed by the specialised state codes `ERR_TURN_IN_NOT_DRAFT`,
        `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`, `ERR_BIDDER_NOT_REGISTERED`,
        `ERR_AGENCY_SUSPENDED`, `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED`
        and `ERR_VENUE_CLOSED`, in that order."
        PRD: "Opening a draft lot for bidding moves it `DRAFT` → `OPEN`; it requires the
        venue to still be `ACTIVE`, refusing with `ERR_VENUE_CLOSED` otherwise, and it
        requires the logical clock to lie inside the sale window, at or after `opens_at`
        and strictly before `closes_at`, refusing with `ERR_INVALID_STATE` otherwise."
        PRD: "Any other disposition state, an unpaid invoice or an unacknowledged order
        is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/tc_demil_destroy_four_hop_cancellation
        """
        scenario = _setup_listed_restricted_asset_with_bid(api)
        asset_id = scenario["asset"]["id"]
        lot_id = scenario["lot"]["id"]

        validate_success(_destroy(api, asset_id), 201)

        validate_error(
            api.open_auction_lot(
                lot_id, make_disposal_officer_headers(OFFICER_USER_ID)
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        assert read_lot(lot_id)["status"] == "CANCELLED", (
            "the refused reopening leaves the lot CANCELLED"
        )

        validate_error(
            api.release_asset(
                asset_id, {}, make_disposal_officer_headers(OFFICER_USER_ID)
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        asset = read_asset(asset_id)
        assert asset["disposition_status"] == "DESTROYED", (
            "the refused release leaves the asset DESTROYED"
        )
        assert asset["released_at"] is None, (
            f"released_at stays null on a destroyed asset, got {asset['released_at']}"
        )
        assert asset["version"] == 6, (
            "the two refused calls write nothing, so the asset version stays 6, got "
            f"{asset['version']}"
        )
