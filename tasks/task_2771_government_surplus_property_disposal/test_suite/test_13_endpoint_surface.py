"""Request and response surface corners of the disposal endpoints.

These tests exercise what the endpoints themselves promise: which roles may
drive the logical clock, which fields a conditional action demands before it
will stamp anything, which columns a list endpoint filters on, and how a
collection read partitions rows that have already been ranked. Pagination is
always requested explicitly so that no unstated server-side default is being
asserted.
"""

from datetime import datetime

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    add_asset,
    add_asset_with_payload,
    create_auction_lot_payload,
    create_bid_payload,
    create_draft_turn_in,
    create_screening_cycle_payload,
    create_screening_request_payload,
    create_transfer_order_payload,
    create_vehicle_asset_payload,
    make_agency_officer_headers,
    make_bidder_headers,
    make_disposal_officer_headers,
    make_finance_controller_headers,
    make_program_admin_headers,
    make_surplus_assessor_headers,
    register_bidder,
    register_state_agency,
    register_venue,
    review_turn_in,
    set_clock,
    submit_turn_in,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers()
ASSESSOR = make_surplus_assessor_headers()
OFFICER = make_disposal_officer_headers()
FINANCE = make_finance_controller_headers()


# ─── module-local helpers ──────────────────────────────────────────────────


def _instant(value):
    """Parse one of the PRD's ISO 8601 UTC instants so two spellings of the
    same moment compare equal regardless of fractional-digit width."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _assert_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def _assessment_payload(expected_asset_version, **overrides):
    payload = {
        "condition_code": "C1",
        "functional": True,
        "repair_cost_estimate_cents": 0,
        "assessed_on": "2026-07-31",
        "expected_asset_version": expected_asset_version,
    }
    payload.update(overrides)
    return payload


def _three_draft_turn_ins(api):
    """One ACTIVE agency, one REGISTERED bidder and three DRAFT turn-ins, each
    holding one FURNITURE asset, with the clock at 2026-08-01T06:00:00Z."""
    set_clock("2026-08-01T06:00:00Z")
    agency = register_state_agency()
    bidder = register_bidder(
        legal_name="Cedar Ridge Salvage LLC", email="bids@cedarridge.example"
    )
    turn_ins = []
    for index in range(3):
        turn_in = create_draft_turn_in(
            agency["id"], custody_location=f"Austin Yard {index + 1}"
        )
        add_asset(
            agency["id"],
            turn_in["id"],
            description=f"Guest chair set {index + 1}",
            acquisition_cost_cents=104_500,
            acquisition_date="2024-05-20",
        )
        turn_ins.append(turn_in)
    return agency, bidder, turn_ins


def _award_asset_to(api, asset_id, recipient_agency_id):
    """Walk one ASSESSED asset to an approved STATE_AGENCY-tier request."""
    cycle = validate_success(
        api.create_screening_cycle(
            create_screening_cycle_payload(
                asset_id, opens_at=CLOCK_EPOCH, tier_window_days=5
            ),
            OFFICER,
        ),
        201,
    )
    request = validate_success(
        api.create_screening_request(
            create_screening_request_payload(cycle["id"], recipient_agency_id),
            ADMIN,
        ),
        201,
    )
    validate_success(api.award_screening_cycle(cycle["id"], request["id"], OFFICER))
    return cycle, request


class TestClockAction:
    """The clock endpoint has no output of its own, only downstream stamps."""

    def test_clock_moved_by_three_different_roles_drives_each_submission_stamp(
        self, api
    ):
        """Three moves, three roles, three submitted_at values.

        "Nothing in this system reads the host's wall clock."

        "An administrative test-driving capability, `POST
        /_clock/set_current_utc`, accepts a `current_utc` instant and moves the
        logical clock to it; the capability is open to all seven roles, performs
        no state transition and stamps no entity."

        "Submission moves `status` from `DRAFT` to `SUBMITTED`, stamps
        `submitted_at` from the logical clock and increments the turn-in's
        `version` by 1."

        "Where a rule speaks of an instant — `opens_at`, `closes_at`,
        `tier_opened_at`, `tier_deadline_at`, `due_at`, `submitted_at`,
        `reviewed_at`, `released_at`, `closed_at`, `placed_at`,
        `acknowledged_at`, `awarded_at`, `posted_at` — the value is a full ISO
        8601 UTC timestamp with three fractional digits and the comparison is
        made against the logical clock instant."

        Design: Corner/endpoints/ep_clock_action_is_open_to_every_role_and_drives_stamps
        """
        agency, bidder, (first, second, third) = _three_draft_turn_ins(api)
        officer_headers = make_agency_officer_headers(agency["id"])
        bidder_headers = make_bidder_headers(bidder["id"])

        validate_success(api.submit_turn_in(first["id"], officer_headers))

        # The relinquishing organisation's own officer moves the clock.
        validate_success(
            api.set_current_utc("2026-08-02T09:30:00Z", officer_headers)
        )
        validate_success(api.submit_turn_in(second["id"], officer_headers))

        # So may a bidder, which has no other stake in a turn-in at all.
        validate_success(api.set_current_utc("2026-08-03T11:45:15Z", bidder_headers))
        validate_success(api.submit_turn_in(third["id"], officer_headers))

        expected = {
            first["id"]: "2026-08-01T06:00:00Z",
            second["id"]: "2026-08-02T09:30:00Z",
            third["id"]: "2026-08-03T11:45:15Z",
        }
        for turn_in_id, moment in expected.items():
            stamped = validate_success(api.get_turn_in(turn_in_id, officer_headers))
            _assert_instant(stamped["submitted_at"], moment, "submitted_at")
            assert stamped["status"] == "SUBMITTED", (
                f"turn-in {turn_in_id} must be SUBMITTED, got {stamped['status']!r}"
            )
            assert stamped["reviewed_at"] is None, (
                "submission does not review the turn-in, so reviewed_at stays null"
            )

    def test_clock_action_stamps_no_entity_and_returns_an_empty_data_object(self, api):
        """The action itself creates nothing and reports nothing.

        "An administrative test-driving capability, `POST
        /_clock/set_current_utc`, accepts a `current_utc` instant and moves the
        logical clock to it; the capability is open to all seven roles, performs
        no state transition and stamps no entity. It returns HTTP 200 with an
        empty `data` object."

        "`total_count` is the number of rows matching the filters before the
        window is applied, and `has_more` is true when rows remain beyond the
        returned window."

        Design: Corner/endpoints/ep_clock_action_is_open_to_every_role_and_drives_stamps
        """
        agency, bidder, turn_ins = _three_draft_turn_ins(api)
        officer_headers = make_agency_officer_headers(agency["id"])
        bidder_headers = make_bidder_headers(bidder["id"])

        for headers, moment in (
            (ADMIN, "2026-08-01T06:00:00Z"),
            (officer_headers, "2026-08-02T09:30:00Z"),
            (bidder_headers, "2026-08-03T11:45:15Z"),
        ):
            data = validate_success(api.set_current_utc(moment, headers), 200)
            assert data == {}, (
                f"the clock action returns an empty data object, got {data!r}"
            )

        rows, meta = validate_paginated(
            api.list_turn_ins(ADMIN, {"limit": 50, "offset": 0})
        )
        assert meta["total_count"] == 3, (
            "three clock moves created no row of their own; got total_count "
            f"{meta['total_count']}"
        )
        assert meta["limit"] == 50 and meta["offset"] == 0, (
            f"the requested window is echoed, got {meta['limit']}/{meta['offset']}"
        )
        assert meta["has_more"] is False, (
            "every matching row fits inside a window of 50"
        )
        assert {row["id"] for row in rows} == {t["id"] for t in turn_ins}, (
            "the listing holds exactly the three turn-ins that were created"
        )
        for row in rows:
            assert row["status"] == "DRAFT", (
                "no turn-in was submitted, so the clock moved nothing; got "
                f"{row['status']!r}"
            )
            assert row["submitted_at"] is None, (
                "a DRAFT turn-in carries no submission stamp"
            )


def _acknowledged_vehicle_transfer(api):
    """A lien-encumbered VEHICLE whose transfer order the recipient's own
    officer has already acknowledged."""
    set_clock(CLOCK_EPOCH)
    owner = register_state_agency()
    recipient = register_state_agency(
        name="Texas Facilities Commission", agency_code="TFC-02"
    )
    turn_in = create_draft_turn_in(owner["id"], custody_location="Austin Fleet Pool")
    asset = add_asset_with_payload(
        owner["id"],
        create_vehicle_asset_payload(
            turn_in["id"],
            description="2016 half-ton pickup",
            acquisition_cost_cents=2_800_000,
            acquisition_date="2016-04-11",
            vin="1FTEW1E45JKE12345",
            odometer_reading=148_320,
            title_number="TX-77410992",
            lien_holder_name="First State Bank of Bastrop",
        ),
    )
    submit_turn_in(owner["id"], turn_in["id"])
    validate_success(
        api.create_condition_assessment(
            asset["id"],
            _assessment_payload(asset["version"], condition_code="C3"),
            ASSESSOR,
        ),
        201,
    )
    review_turn_in(turn_in["id"], "ACCEPT")
    _cycle, request = _award_asset_to(api, asset["id"], recipient["id"])
    order = validate_success(
        api.create_transfer_order(
            create_transfer_order_payload(
                asset["id"], recipient["id"], request["id"]
            ),
            OFFICER,
        ),
        201,
    )
    validate_success(
        api.acknowledge_transfer_order(
            order["id"], make_agency_officer_headers(recipient["id"])
        )
    )
    return owner, recipient, turn_in, asset, order


class TestVehicleRelease:
    """Release demands the vehicle paperwork before it stamps anything."""

    def test_release_documentation_gates_refuse_and_stamp_nothing(self, api):
        """Three incomplete releases, three refusals, no partial writes.

        "A `VEHICLE` requires an `odometer_disclosure_reading` that is present
        and at or above the asset's recorded `odometer_reading`, together with a
        non-empty `title_recipient_name`, and is otherwise refused with
        `ERR_ODOMETER_DISCLOSURE_REQUIRED` (HTTP 422)."

        "An asset carrying a non-null `lien_holder_name` requires a non-empty
        `lien_release_reference`, and is otherwise refused with
        `ERR_LIEN_NOT_RELEASED`."

        "Those secondary effects are part of the operation's contract, not
        best-effort housekeeping: an operation either applies all of its hops
        or, if a validation fails, applies none of them."

        Design: Corner/endpoints/ep_vehicle_release_stamps_title_transfer_fields
        """
        owner, recipient, turn_in, asset, order = _acknowledged_vehicle_transfer(api)

        assert order["base_transfer_cents"] == 98_000, (
            "round_half_up(392000 * 0.25) for a STATE_AGENCY recipient; got "
            f"{order['base_transfer_cents']}"
        )
        assert order["handling_fee_cents"] == 5_000, (
            "a base of 98000 sits just under the middle fee band; got "
            f"{order['handling_fee_cents']}"
        )
        assert order["transfer_price_cents"] == 103_000, (
            f"98000 plus 5000; got {order['transfer_price_cents']}"
        )

        before = validate_success(api.get_asset(asset["id"], OFFICER))

        validate_error(
            api.release_asset(asset["id"], {}, OFFICER),
            ApiErrorId.ERR_ODOMETER_DISCLOSURE_REQUIRED,
        )
        # A disclosed reading below the recorded one is a rollback, not a
        # disclosure, so the same gate speaks even though the field is present.
        validate_error(
            api.release_asset(
                asset["id"],
                {
                    "odometer_disclosure_reading": 148_000,
                    "title_recipient_name": "Texas Facilities Commission",
                    "lien_release_reference": "LR-2026-33417",
                },
                OFFICER,
            ),
            ApiErrorId.ERR_ODOMETER_DISCLOSURE_REQUIRED,
        )
        # With the odometer gate satisfied, the next gate in order speaks.
        validate_error(
            api.release_asset(
                asset["id"],
                {
                    "odometer_disclosure_reading": 148_500,
                    "title_recipient_name": "Texas Facilities Commission",
                },
                OFFICER,
            ),
            ApiErrorId.ERR_LIEN_NOT_RELEASED,
        )

        after = validate_success(api.get_asset(asset["id"], OFFICER))
        assert after["disposition_status"] == "AWARDED_TRANSFER", (
            "a refused release leaves the asset where it stood; got "
            f"{after['disposition_status']!r}"
        )
        assert after["version"] == before["version"], (
            "none of the three refused calls applied any hop, so no version "
            f"moved; got {after['version']} against {before['version']}"
        )
        for field in (
            "released_at",
            "odometer_disclosure_reading",
            "lien_release_reference",
            "title_recipient_name",
        ):
            assert after[field] is None, (
                f"{field} must still be null after a refused release, got "
                f"{after[field]!r}"
            )

        untouched_order = validate_success(
            api.get_transfer_order(order["id"], FINANCE)
        )
        assert untouched_order["status"] == "ACKNOWLEDGED", (
            "the second hop never ran; got {0!r}".format(untouched_order["status"])
        )
        untouched_turn_in = validate_success(
            api.get_turn_in(turn_in["id"], make_agency_officer_headers(owner["id"]))
        )
        assert untouched_turn_in["status"] == "ACCEPTED", (
            "the upward closure never ran; got "
            f"{untouched_turn_in['status']!r}"
        )

    def test_complete_release_stamps_the_paperwork_and_runs_both_hops(self, api):
        """The successful call stores every disclosure and cascades twice.

        "A successful release stores `released_at` from the logical clock along
        with the supplied `odometer_disclosure_reading`, `lien_release_reference`
        and `title_recipient_name`, and moves the asset to `RELEASED`."

        "From `AWARDED_TRANSFER`, a second hop caused by the asset leaving
        custody moves the asset's `ACKNOWLEDGED` `TransferOrder` to `COMPLETED`
        and, where the asset's `federal_source` is true, computes that order's
        `use_period_end_on` by adding the asset category's use-period months to
        the calendar date of the order's `acknowledged_at`, with the same
        day-of-month clamping described in §2.4 — the recipient inherits an
        obligation of its own, counted from when it accepted the paperwork rather
        than from when the property moved."

        "A final hop bubbles upward exactly as destruction does: when every asset
        of the parent turn-in has reached a terminal disposition, the turn-in
        moves `ACCEPTED` → `CLOSED`. The asset's `version` increments by 1."

        Design: Corner/endpoints/ep_vehicle_release_stamps_title_transfer_fields
        """
        owner, recipient, turn_in, asset, order = _acknowledged_vehicle_transfer(api)
        before = validate_success(api.get_asset(asset["id"], OFFICER))

        released = validate_success(
            api.release_asset(
                asset["id"],
                {
                    "odometer_disclosure_reading": 148_500,
                    "title_recipient_name": "Texas Facilities Commission",
                    "lien_release_reference": "LR-2026-33417",
                },
                OFFICER,
            ),
            200,
        )

        assert released["disposition_status"] == "RELEASED", (
            f"got {released['disposition_status']!r}"
        )
        _assert_instant(released["released_at"], CLOCK_EPOCH, "released_at")
        assert released["odometer_disclosure_reading"] == 148_500, (
            f"got {released['odometer_disclosure_reading']}"
        )
        assert released["title_recipient_name"] == "Texas Facilities Commission", (
            f"got {released['title_recipient_name']!r}"
        )
        assert released["lien_release_reference"] == "LR-2026-33417", (
            f"got {released['lien_release_reference']!r}"
        )
        assert released["version"] == before["version"] + 1, (
            "the release increments the asset's version by exactly 1; got "
            f"{released['version']} against {before['version']}"
        )

        completed = validate_success(api.get_transfer_order(order["id"], FINANCE))
        assert completed["status"] == "COMPLETED", (
            f"the second hop completes the order; got {completed['status']!r}"
        )
        assert completed["use_period_end_on"] is None, (
            "the vehicle is not federally sourced, so the recipient inherits no "
            f"use period; got {completed['use_period_end_on']!r}"
        )

        closed = validate_success(
            api.get_turn_in(turn_in["id"], make_agency_officer_headers(owner["id"]))
        )
        assert closed["status"] == "CLOSED", (
            "the vehicle was the turn-in's only asset and it is now terminal; "
            f"got {closed['status']!r}"
        )


def _two_issued_transfer_orders(api):
    """Two ISSUED transfer orders whose three foreign keys are all distinct."""
    set_clock(CLOCK_EPOCH)
    owner = register_state_agency()
    facilities = register_state_agency(
        name="Texas Facilities Commission", agency_code="TFC-02"
    )
    workforce = register_state_agency(
        name="Texas Workforce Commission", agency_code="TWC-03"
    )
    turn_in = create_draft_turn_in(owner["id"])
    assets = [
        add_asset(
            owner["id"],
            turn_in["id"],
            description=f"Workstation cluster {label}",
            acquisition_cost_cents=1_000_000,
            acquisition_date="2026-01-10",
        )
        for label in ("A", "B")
    ]
    submit_turn_in(owner["id"], turn_in["id"])
    for asset in assets:
        validate_success(
            api.create_condition_assessment(
                asset["id"], _assessment_payload(asset["version"]), ASSESSOR
            ),
            201,
        )
    review_turn_in(turn_in["id"], "ACCEPT")

    _cycle_a, request_a = _award_asset_to(api, assets[0]["id"], facilities["id"])
    _cycle_b, request_b = _award_asset_to(api, assets[1]["id"], workforce["id"])
    order_a = validate_success(
        api.create_transfer_order(
            create_transfer_order_payload(
                assets[0]["id"], facilities["id"], request_a["id"]
            ),
            OFFICER,
        ),
        201,
    )
    order_b = validate_success(
        api.create_transfer_order(
            create_transfer_order_payload(
                assets[1]["id"], workforce["id"], request_b["id"]
            ),
            OFFICER,
        ),
        201,
    )
    return {
        "assets": assets,
        "facilities": facilities,
        "workforce": workforce,
        "request_a": request_a,
        "request_b": request_b,
        "order_a": order_a,
        "order_b": order_b,
    }


class TestTransferOrderListSurface:
    """Each of the order's three links is an independent list filter."""

    def test_each_foreign_key_filter_selects_exactly_its_own_order(self, api):
        """Three filters over two orders, one row each.

        "Orders may be listed narrowed by `asset_id`, by `recipient_agency_id`,
        by `screening_request_id` or by `status`."

        "All three are supplied explicitly and all three are cross-checked: the
        `screening_request_id` must name a request whose `status` is `APPROVED`,
        and the supplied `asset_id` and `recipient_agency_id` must match,
        respectively, the asset of that request's cycle and the organisation that
        filed the request."

        "`total_count` is the number of rows matching the filters before the
        window is applied, and `has_more` is true when rows remain beyond the
        returned window."

        Design: Corner/endpoints/ep_transfer_order_filters_expose_all_three_links
        """
        scenario = _two_issued_transfer_orders(api)
        order_a, order_b = scenario["order_a"], scenario["order_b"]

        detail = validate_success(api.get_transfer_order(order_a["id"], FINANCE))
        assert detail["asset_id"] == scenario["assets"][0]["id"], (
            f"the asset link must round-trip, got {detail['asset_id']!r}"
        )
        assert detail["recipient_agency_id"] == scenario["facilities"]["id"], (
            f"the recipient link must round-trip, got "
            f"{detail['recipient_agency_id']!r}"
        )
        assert detail["screening_request_id"] == scenario["request_a"]["id"], (
            f"the request link must round-trip, got "
            f"{detail['screening_request_id']!r}"
        )
        assert detail["status"] == "ISSUED", f"got {detail['status']!r}"

        for label, params, expected in (
            (
                "asset_id",
                {"asset_id": scenario["assets"][1]["id"], "limit": 50},
                order_b,
            ),
            (
                "recipient_agency_id",
                {"recipient_agency_id": scenario["facilities"]["id"], "limit": 50},
                order_a,
            ),
            (
                "screening_request_id",
                {"screening_request_id": scenario["request_b"]["id"], "limit": 50},
                order_b,
            ),
        ):
            rows, meta = validate_paginated(api.list_transfer_orders(OFFICER, params))
            assert meta["total_count"] == 1, (
                f"the {label} filter must select exactly one order, got "
                f"total_count {meta['total_count']}"
            )
            assert [row["id"] for row in rows] == [expected["id"]], (
                f"the {label} filter must return only order {expected['id']}, got "
                f"{[row['id'] for row in rows]}"
            )

    def test_status_filter_returns_both_orders_with_the_requested_window(self, api):
        """The status filter is the one that selects both rows.

        "Orders may be listed narrowed by `asset_id`, by `recipient_agency_id`,
        by `screening_request_id` or by `status`."

        "Second, multiply the asset's stored `fair_market_value_cents` by that
        factor and round the product half up to whole cents; the result is
        stored as `base_transfer_cents`."

        "the named request moves `SUBMITTED` → `APPROVED`, and every *other*
        request on the cycle whose `status` is `SUBMITTED` or `INFO_REQUESTED`
        moves to `DENIED` with `denial_reason` set to `LOST_AWARD`, processed in
        `created_at` ascending order."

        "List responses populate four pagination fields inside the envelope's
        `meta` object: `limit`, `offset`, `total_count` and `has_more`."

        Design: Corner/endpoints/ep_transfer_order_filters_expose_all_three_links
        """
        scenario = _two_issued_transfer_orders(api)

        rows, meta = validate_paginated(
            api.list_transfer_orders(
                OFFICER, {"status": "ISSUED", "limit": 50, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, (
            f"both orders are ISSUED, got total_count {meta['total_count']}"
        )
        assert meta["limit"] == 50, f"limit must be echoed, got {meta['limit']}"
        assert meta["offset"] == 0, f"offset must be echoed, got {meta['offset']}"
        assert meta["has_more"] is False, "two rows fit inside a window of 50"
        assert {row["id"] for row in rows} == {
            scenario["order_a"]["id"],
            scenario["order_b"]["id"],
        }, "the status filter must hold both orders"

        for row in rows:
            assert row["base_transfer_cents"] == 250_000, (
                "round_half_up(1000000 * 0.25) for a STATE_AGENCY recipient; got "
                f"{row['base_transfer_cents']}"
            )
            assert row["handling_fee_cents"] == 12_500, (
                f"a base of 250000 draws the middle fee band; got "
                f"{row['handling_fee_cents']}"
            )
            assert row["transfer_price_cents"] == 262_500, (
                f"250000 plus 12500; got {row['transfer_price_cents']}"
            )

        for request in (scenario["request_a"], scenario["request_b"]):
            approved = validate_success(
                api.get_screening_request(request["id"], OFFICER)
            )
            assert approved["status"] == "APPROVED", (
                "each documented request won its own cycle; got "
                f"{approved['status']!r}"
            )


def _closed_lot_with_two_bids(api):
    """A de-minimis lot closed after a displaced bid and a winning bid."""
    set_clock(CLOCK_EPOCH)
    agency = register_state_agency()
    turn_in = create_draft_turn_in(agency["id"])
    asset = add_asset(
        agency["id"],
        turn_in["id"],
        description="Lateral file cabinets, single pallet",
        acquisition_cost_cents=104_500,
        acquisition_date="2024-05-20",
    )
    submit_turn_in(agency["id"], turn_in["id"])
    validate_success(
        api.create_condition_assessment(
            asset["id"],
            _assessment_payload(asset["version"], condition_code="C6"),
            ASSESSOR,
        ),
        201,
    )
    review_turn_in(turn_in["id"], "ACCEPT")

    venue = register_venue(name="Austin Auction Yard", venue_code="AUS-01")
    lot = validate_success(
        api.create_auction_lot(
            create_auction_lot_payload(
                asset["id"],
                venue["id"],
                opens_at="2026-08-02T00:00:00Z",
                closes_at="2026-08-03T00:00:00Z",
            ),
            OFFICER,
        ),
        201,
    )
    displaced_bidder = register_bidder(
        legal_name="Cedar Ridge Salvage LLC", email="bids@cedarridge.example"
    )
    winning_bidder = register_bidder(
        legal_name="Balcones Reclaim Co", email="desk@balconesreclaim.example"
    )

    set_clock("2026-08-02T00:00:00Z")
    validate_success(api.open_auction_lot(lot["id"], OFFICER))
    first_bid = validate_success(
        api.place_bid(
            lot["id"],
            create_bid_payload(displaced_bidder["id"], 7_524),
            make_bidder_headers(displaced_bidder["id"]),
        ),
        201,
    )
    second_bid = validate_success(
        api.place_bid(
            lot["id"],
            create_bid_payload(winning_bidder["id"], 10_024),
            make_bidder_headers(winning_bidder["id"]),
        ),
        201,
    )

    set_clock("2026-08-03T00:00:00Z")
    closed = validate_success(api.close_auction_lot(lot["id"], OFFICER))
    return {
        "lot": lot,
        "closed": closed,
        "displaced_bidder": displaced_bidder,
        "winning_bidder": winning_bidder,
        "first_bid": first_bid,
        "second_bid": second_bid,
    }


class TestBidCollectionReads:
    """After the close the same rows carry three different statuses."""

    def test_bid_collections_partition_the_retained_rows_after_the_close(self, api):
        """Every bid survives the close and each read ranks them the same way.

        "Bids may be listed per lot or per bidder, narrowed by `status`, and the
        per-lot listing returns the highest `amount_cents` first."

        "The selected bid moves `ACTIVE` → `WINNING`, every other `ACTIVE` bid on
        the lot moves `ACTIVE` → `OUTBID` processed in `created_at` ascending
        order, and the winning `Bidder`'s `winning_lot_count` is incremented by
        1."

        "A bid's `status` moves among `ACTIVE`, `OUTBID`, `WINNING` and
        `RETRACTED`, of which `OUTBID` and `RETRACTED` are terminal."

        Design: Corner/endpoints/ep_bid_collection_read_reflects_post_close_ranking
        """
        scenario = _closed_lot_with_two_bids(api)
        lot_id = scenario["lot"]["id"]
        first_bid, second_bid = scenario["first_bid"], scenario["second_bid"]

        assert scenario["lot"]["reserve_price_cents"] == 7_524, (
            "round_half_up(12540 * 0.60) for the de-minimis appraisal; got "
            f"{scenario['lot']['reserve_price_cents']}"
        )
        assert scenario["lot"]["required_deposit_cents"] == 0, (
            "a reserve below five thousand dollars requires no deposit; got "
            f"{scenario['lot']['required_deposit_cents']}"
        )

        rows, meta = validate_paginated(
            api.list_lot_bids(lot_id, OFFICER, {"limit": 50, "offset": 0})
        )
        assert meta["total_count"] == 2, (
            "the displaced bid is retained after the close; got total_count "
            f"{meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [second_bid["id"], first_bid["id"]], (
            "the per-lot listing returns the highest amount first; got "
            f"{[row['id'] for row in rows]}"
        )

        winning, winning_meta = validate_paginated(
            api.list_lot_bids(lot_id, FINANCE, {"status": "WINNING", "limit": 50})
        )
        assert winning_meta["total_count"] == 1, (
            f"exactly one bid wins; got total_count {winning_meta['total_count']}"
        )
        assert winning[0]["id"] == second_bid["id"], (
            f"the higher bid is the winner; got {winning[0]['id']}"
        )
        assert winning[0]["amount_cents"] == 10_024, (
            f"got {winning[0]['amount_cents']}"
        )

        outbid, outbid_meta = validate_paginated(
            api.list_lot_bids(lot_id, FINANCE, {"status": "OUTBID", "limit": 50})
        )
        assert outbid_meta["total_count"] == 1, (
            "a bid displaced before the close is neither deleted nor retracted; "
            f"got total_count {outbid_meta['total_count']}"
        )
        assert outbid[0]["id"] == first_bid["id"], (
            f"got {outbid[0]['id']}"
        )
        assert outbid[0]["amount_cents"] == 7_524, (
            f"the displaced amount is retained; got {outbid[0]['amount_cents']}"
        )

        own_rows, own_meta = validate_paginated(
            api.list_bidder_bids(
                scenario["displaced_bidder"]["id"],
                make_bidder_headers(scenario["displaced_bidder"]["id"]),
                {"limit": 50},
            )
        )
        assert own_meta["total_count"] == 1, (
            "the per-bidder collection holds only that bidder's own bid; got "
            f"total_count {own_meta['total_count']}"
        )
        assert [row["id"] for row in own_rows] == [first_bid["id"]], (
            f"got {[row['id'] for row in own_rows]}"
        )

    def test_close_rollups_invoice_lines_and_winning_counts(self, api):
        """The close cascade is visible through the lot, invoice and bidders.

        "Hop one stamps `closed_by_user_id` from the officer's `X-User-ID` and
        `closed_at` from the logical clock."

        "The close also re-derives `high_bid_cents` and `bid_count` on the lot
        and recomputes the venue's `active_lot_count`, and increments both the
        lot's and the asset's `version` by 1."

        "The `buyer_premium_cents` is the `hammer_price_cents` multiplied by the
        venue's `buyer_premium_pct`, rounded half up to whole cents on its own."

        "The `sales_tax_cents` is the sum of `hammer_price_cents` and
        `buyer_premium_cents` multiplied by the venue's `sales_tax_pct`, again
        rounded half up on its own — the tax is charged on the premium-inclusive
        amount, not on the hammer price alone."

        "The `total_due_cents` is then the exact sum of the three integers with
        no further rounding at all."

        Design: Corner/endpoints/ep_bid_collection_read_reflects_post_close_ranking
        """
        scenario = _closed_lot_with_two_bids(api)
        closed = validate_success(
            api.get_auction_lot(scenario["lot"]["id"], OFFICER)
        )

        assert closed["status"] == "CLOSED_MET", (
            f"the candidate set was non-empty; got {closed['status']!r}"
        )
        assert closed["high_bid_cents"] == 10_024, (
            "the largest amount over the bids still ACTIVE or WINNING; got "
            f"{closed['high_bid_cents']}"
        )
        assert closed["bid_count"] == 2, (
            "the count spans ACTIVE, WINNING and OUTBID; got "
            f"{closed['bid_count']}"
        )
        assert closed["closed_by_user_id"] == "officer-01", (
            f"stamped from the closing officer's X-User-ID; got "
            f"{closed['closed_by_user_id']!r}"
        )

        invoices, invoice_meta = validate_paginated(
            api.list_sale_invoices(
                FINANCE, {"auction_lot_id": scenario["lot"]["id"], "limit": 50}
            )
        )
        assert invoice_meta["total_count"] == 1, (
            "the close cascade created exactly one invoice; got total_count "
            f"{invoice_meta['total_count']}"
        )
        invoice = invoices[0]
        assert invoice["bidder_id"] == scenario["winning_bidder"]["id"], (
            f"the invoice is raised against the winner; got "
            f"{invoice['bidder_id']!r}"
        )
        assert invoice["hammer_price_cents"] == 10_024, (
            f"got {invoice['hammer_price_cents']}"
        )
        assert invoice["buyer_premium_cents"] == 1_053, (
            f"round_half_up(10024 * 0.105); got {invoice['buyer_premium_cents']}"
        )
        assert invoice["sales_tax_cents"] == 703, (
            "round_half_up((10024 + 1053) * 0.0635) on the premium-inclusive "
            f"amount; got {invoice['sales_tax_cents']}"
        )
        assert invoice["total_due_cents"] == 11_780, (
            f"10024 plus 1053 plus 703; got {invoice['total_due_cents']}"
        )
        _assert_instant(invoice["due_at"], "2026-08-10T00:00:00Z", "due_at")

        winner = validate_success(
            api.get_bidder(scenario["winning_bidder"]["id"], ADMIN)
        )
        assert winner["winning_lot_count"] == 1, (
            f"the winner's counter is incremented by 1; got "
            f"{winner['winning_lot_count']}"
        )
        loser = validate_success(
            api.get_bidder(scenario["displaced_bidder"]["id"], ADMIN)
        )
        assert loser["winning_lot_count"] == 0, (
            f"the displaced bidder won nothing; got {loser['winning_lot_count']}"
        )
