"""Operations gated on the current state of a different row.

Each scenario here keeps the addressed resource perfectly valid and moves the
blocking condition onto a third row: a sale venue that has been closed, a
recipient organisation whose federal donee certification has lapsed, or a parent
turn-in that has left `DRAFT`. Where the blocking row can be repaired the repair
is driven through the PRD's own capability and the retried request is asserted
down to its pinned money lines.
"""

from test_helpers import (
    ASSESSOR_USER_ID,
    OFFICER_USER_ID,
    ApiErrorId,
    assert_auction_lot,
    assert_sale_venue,
    assert_surplus_asset,
    assert_transfer_order,
    assert_turn_in,
    create_auction_lot_payload,
    create_condition_assessment_payload,
    create_it_asset_payload,
    create_transfer_order_payload,
    make_agency_officer_headers,
    make_disposal_officer_headers,
    make_program_admin_headers,
    make_surplus_assessor_headers,
    read_asset,
    read_request,
    read_turn_in,
    read_venue,
    register_venue,
    setup_assessed_asset,
    setup_assessed_assets,
    setup_awarded_transfer_candidate,
    validate_error,
    validate_paginated,
    validate_success,
)

# A 2024 furniture pallet costing 104500 cents, appraised C6 / functional with no
# repair estimate, is worth 12540 cents on the logical clock's 2026-08-01 date.
FURNITURE_FMV_CENTS = 12540
FURNITURE_RESERVE_CENTS = 7524
# A 2019 pickup costing 3217467 cents, appraised C4 / functional less a 185000
# repair estimate, is worth 297620 cents on the same date.
PICKUP_FMV_CENTS = 297620

OFFICER_HEADERS = make_disposal_officer_headers(OFFICER_USER_ID)
ADMIN_HEADERS = make_program_admin_headers()


class TestLotCreationRequiresActiveVenue:
    """An auction lot is refused when the venue it names has been closed, even
    though the asset and the sale window are both admissible."""

    def test_lot_creation_at_closed_venue_rejected_with_venue_closed(self, api):
        """PRD §3.1: "Closing a venue moves its `status` from `ACTIVE` to `CLOSED`; lots
        already in `DRAFT` or `OPEN` there keep their own status and continue to run, but
        no new lot may be created at a closed venue and no draft lot at a closed venue may
        be opened for bidding — both attempts are refused with `ERR_VENUE_CLOSED`."
        PRD §3.6: "The venue's `status` must be `ACTIVE`, or the request is refused with
        `ERR_VENUE_CLOSED`."
        PRD §2.9: "Those secondary effects are part of the operation's contract, not
        best-effort housekeeping: an operation either applies all of its hops or, if a
        validation fails, applies none of them."

        Design: Difficulty/cross_entity_state_dependency/cesd_lot_creation_requires_active_venue
        """
        scenario = setup_assessed_asset(kind="furniture")
        asset = scenario["asset"]
        assert asset["fair_market_value_cents"] == FURNITURE_FMV_CENTS, (
            "the pallet must appraise at 12540 cents, below the de-minimis screening "
            f"threshold; got {asset['fair_market_value_cents']}"
        )
        assert asset["disposition_status"] == "ASSESSED"
        asset_version_before = asset["version"]

        venue = register_venue(
            name="Austin Surplus Yard", venue_code="AUS-01", concurrent_lot_capacity=4
        )

        closed = validate_success(
            api.set_venue_status(venue["id"], "CLOSED", ADMIN_HEADERS), 200
        )
        assert_sale_venue(closed)
        assert closed["status"] == "CLOSED", (
            f"closing the venue must move status to CLOSED, got {closed['status']}"
        )
        assert closed["version"] == 2, (
            f"the close is one mutation of the venue row, so version is 2, got {closed['version']}"
        )

        resp = api.create_auction_lot(
            create_auction_lot_payload(asset["id"], venue["id"]), OFFICER_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_CLOSED)

        venue_after = read_venue(venue["id"])
        assert venue_after["active_lot_count"] == 0, (
            "the refused create writes nothing, so the closed venue still counts no "
            f"DRAFT or OPEN lot; got {venue_after['active_lot_count']}"
        )
        asset_after = read_asset(asset["id"])
        assert asset_after["disposition_status"] == "ASSESSED", (
            "the asset must stay ASSESSED after the refusal, got "
            f"{asset_after['disposition_status']}"
        )
        assert asset_after["version"] == asset_version_before, (
            "no hop of the refused create may touch the asset, so its version stays at "
            f"{asset_version_before}; got {asset_after['version']}"
        )
        _, meta = validate_paginated(
            api.list_auction_lots(OFFICER_HEADERS, params={"venue_id": venue["id"]})
        )
        assert meta["total_count"] == 0, (
            f"no partial lot row may survive the refusal; got {meta['total_count']}"
        )

    def test_lot_re_addressed_to_an_active_venue_is_created(self, api):
        """PRD §3.6: "An asset still in `ASSESSED` is listable only under the de-minimis
        exemption: its `fair_market_value_cents` must be strictly below two hundred fifty
        dollars, and its turn-in must have been `ACCEPTED`, in which case it moves
        `ASSESSED` → `LISTED` without ever entering a screening cycle."
        PRD §3.6: "Every lot gets a human-readable `lot_number` assembled as the venue's
        `venue_code`, a hyphen, and the lot's one-based position among all lots at that
        venue ordered by `created_at` ascending, with the position zero-padded to four
        digits — the third lot ever created at a venue coded `NORTHYARD` is therefore
        `NORTHYARD-0003`."
        PRD §3.6: "By default the reserve is derived from the asset's stored valuation:
        take sixty hundredths of `fair_market_value_cents`, round that product half up to
        whole cents, and use the larger of that figure and twenty-five dollars."
        PRD §3.6: "A reserve below five thousand dollars requires no deposit at all and
        `required_deposit_cents` is 0."
        PRD §3.6: "Creation also recomputes the hosting venue's `active_lot_count`, which
        counts that venue's lots in `DRAFT` or `OPEN`, and increments the asset's
        `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/cesd_lot_creation_requires_active_venue
        """
        scenario = setup_assessed_asset(kind="furniture")
        asset = scenario["asset"]

        closed_venue = register_venue(
            name="Austin Surplus Yard", venue_code="AUS-01", concurrent_lot_capacity=4
        )
        open_venue = register_venue(
            name="Round Rock Surplus Annex",
            venue_code="AUS-02",
            concurrent_lot_capacity=4,
        )
        validate_success(
            api.set_venue_status(closed_venue["id"], "CLOSED", ADMIN_HEADERS), 200
        )

        validate_error(
            api.create_auction_lot(
                create_auction_lot_payload(asset["id"], closed_venue["id"]),
                OFFICER_HEADERS,
            ),
            ApiErrorId.ERR_VENUE_CLOSED,
        )

        lot = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(asset["id"], open_venue["id"]),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert_auction_lot(lot)
        assert lot["status"] == "DRAFT", f"a new lot opens in DRAFT, got {lot['status']}"
        assert lot["venue_id"] == open_venue["id"]
        assert lot["lot_number"] == "AUS-02-0001", (
            "the lot number counts positions per venue, so the rejected attempt at the "
            f"closed venue consumed no number; got {lot['lot_number']}"
        )
        assert lot["reserve_price_cents"] == FURNITURE_RESERVE_CENTS, (
            "the computed reserve is sixty hundredths of 12540 rounded half up, i.e. "
            f"7524; got {lot['reserve_price_cents']}"
        )
        assert lot["reserve_source"] == "COMPUTED", (
            f"no override was supplied, so reserve_source is COMPUTED; got {lot['reserve_source']}"
        )
        assert lot["required_deposit_cents"] == 0, (
            "a reserve of 7524 cents is below the five-thousand-dollar deposit threshold, "
            f"so no deposit is required; got {lot['required_deposit_cents']}"
        )

        assert read_venue(closed_venue["id"])["active_lot_count"] == 0, (
            "the closed venue never hosted a lot"
        )
        hosting = read_venue(open_venue["id"])
        assert hosting["active_lot_count"] == 1, (
            f"the hosting venue now counts one DRAFT lot; got {hosting['active_lot_count']}"
        )
        listed = read_asset(asset["id"])
        assert listed["disposition_status"] == "LISTED", (
            "the de-minimis exemption moves the asset ASSESSED to LISTED; got "
            f"{listed['disposition_status']}"
        )
        assert listed["version"] == scenario["asset"]["version"] + 1, (
            "lot creation increments the asset's version by exactly 1"
        )


class TestTransferOrderRequiresUnlapsedDoneeCertification:
    """Issuance is gated on a date field of the recipient organisation, not on
    that organisation's own status field."""

    def _awarded_nonprofit_scenario(self, **recipient_overrides):
        overrides = {"agency_code": "NPO-13"}
        overrides.update(recipient_overrides)
        return setup_awarded_transfer_candidate(
            recipient_kind="nonprofit", kind="vehicle", recipient_overrides=overrides
        )

    def test_lapsed_donee_certification_blocks_transfer_order(self, api):
        """PRD §3.5: "Then the federal donee rule applies: a transfer to an
        `ELIGIBLE_NONPROFIT` recipient, and **any** transfer of a `federal_source` asset
        regardless of recipient type, requires the recipient to hold
        `federal_donee_status` equal to `CERTIFIED` with a
        `donee_certification_expires_on` that is on or after the logical clock's current
        date. A recipient without certification, with a `NONE` or `SUSPENDED` donee
        status, or with a lapsed expiry date is refused with
        `ERR_DONEE_CERTIFICATION_INVALID`."
        PRD §2.9: "Those secondary effects are part of the operation's contract, not
        best-effort housekeeping: an operation either applies all of its hops or, if a
        validation fails, applies none of them."

        Design: Difficulty/cross_entity_state_dependency/cesd_transfer_order_requires_unlapsed_donee_certification
        """
        scenario = self._awarded_nonprofit_scenario(
            donee_certification_expires_on="2026-07-31"
        )
        recipient = scenario["recipient"]
        asset = scenario["asset"]
        request = scenario["request"]

        assert recipient["status"] == "ACTIVE", (
            "the recipient organisation itself is in good standing"
        )
        assert recipient["federal_donee_status"] == "CERTIFIED"
        assert recipient["donee_certification_expires_on"] == "2026-07-31", (
            "the certification lapsed one day before the logical clock date 2026-08-01"
        )
        assert request["status"] == "APPROVED"
        assert asset["disposition_status"] == "AWARDED_TRANSFER"
        asset_version_before = asset["version"]

        resp = api.create_transfer_order(
            create_transfer_order_payload(
                asset["id"], recipient["id"], request["id"]
            ),
            OFFICER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DONEE_CERTIFICATION_INVALID)

        _, meta = validate_paginated(
            api.list_transfer_orders(OFFICER_HEADERS, params={"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 0, (
            f"no transfer order may survive the refusal; got {meta['total_count']}"
        )
        assert read_asset(asset["id"])["version"] == asset_version_before, (
            "the refused issuance touches no row, so the asset's version is unchanged"
        )
        assert read_request(request["id"])["status"] == "APPROVED", (
            "the approved screening request is untouched by the refusal"
        )

    def test_suspended_donee_status_blocks_transfer_order(self, api):
        """PRD §3.5: "Then the federal donee rule applies: a transfer to an
        `ELIGIBLE_NONPROFIT` recipient, and **any** transfer of a `federal_source` asset
        regardless of recipient type, requires the recipient to hold
        `federal_donee_status` equal to `CERTIFIED` with a
        `donee_certification_expires_on` that is on or after the logical clock's current
        date. A recipient without certification, with a `NONE` or `SUSPENDED` donee
        status, or with a lapsed expiry date is refused with
        `ERR_DONEE_CERTIFICATION_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/cesd_transfer_order_requires_unlapsed_donee_certification
        """
        scenario = self._awarded_nonprofit_scenario(
            agency_code="NPO-14",
            federal_donee_status="SUSPENDED",
            donee_certification_expires_on="2027-06-30",
        )
        recipient = scenario["recipient"]
        assert recipient["federal_donee_status"] == "SUSPENDED", (
            "the certification date is comfortably in the future; only the donee status "
            "disqualifies the recipient"
        )

        resp = api.create_transfer_order(
            create_transfer_order_payload(
                scenario["asset"]["id"], recipient["id"], scenario["request"]["id"]
            ),
            OFFICER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DONEE_CERTIFICATION_INVALID)

    def test_recertified_recipient_prices_the_transfer_at_the_nonprofit_tier(self, api):
        """PRD §3.1: "Separately, a donee-certification capability records or withdraws
        federal surplus donee eligibility, writing `federal_donee_status` and, where
        applicable, `donee_certification_expires_on`; it is the mechanism by which an
        organisation becomes eligible to receive federally donated property under §3.3."
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
        PRD §3.5: "A newly issued order sits in `status` `ISSUED` with
        `issued_by_user_id` stamped from the officer's `X-User-ID`, and with
        `acknowledged_at`, `use_period_end_on` and `void_reason` all null."

        Design: Difficulty/cross_entity_state_dependency/cesd_transfer_order_requires_unlapsed_donee_certification
        """
        scenario = self._awarded_nonprofit_scenario(
            donee_certification_expires_on="2026-07-31"
        )
        recipient = scenario["recipient"]
        asset = scenario["asset"]
        request = scenario["request"]
        assert asset["fair_market_value_cents"] == PICKUP_FMV_CENTS, (
            "the pickup must appraise at 297620 cents; got "
            f"{asset['fair_market_value_cents']}"
        )

        payload = create_transfer_order_payload(
            asset["id"], recipient["id"], request["id"]
        )
        validate_error(
            api.create_transfer_order(payload, OFFICER_HEADERS),
            ApiErrorId.ERR_DONEE_CERTIFICATION_INVALID,
        )

        repaired = validate_success(
            api.set_agency_donee_certification(
                recipient["id"],
                {
                    "federal_donee_status": "CERTIFIED",
                    "donee_certification_expires_on": "2027-06-30",
                },
                ADMIN_HEADERS,
            ),
            200,
        )
        assert repaired["donee_certification_expires_on"] == "2027-06-30", (
            "the capability rewrites the expiry date in place; got "
            f"{repaired['donee_certification_expires_on']}"
        )
        assert repaired["federal_donee_status"] == "CERTIFIED"
        assert repaired["version"] == recipient["version"] + 1, (
            "recording the certification is one mutation of the organisation row"
        )

        order = validate_success(api.create_transfer_order(payload, OFFICER_HEADERS), 201)
        assert_transfer_order(order)
        assert order["status"] == "ISSUED", (
            f"a newly issued order sits in ISSUED, got {order['status']}"
        )
        assert order["issued_by_user_id"] == OFFICER_USER_ID, (
            "issued_by_user_id is stamped from the issuing officer's X-User-ID; got "
            f"{order['issued_by_user_id']}"
        )
        assert order["base_transfer_cents"] == 29762, (
            "the nonprofit tier pays ten hundredths of 297620, rounded half up to 29762; "
            f"got {order['base_transfer_cents']}"
        )
        assert order["handling_fee_cents"] == 5000, (
            "a base of 29762 cents falls in the lowest band and draws a fifty-dollar "
            f"fee; got {order['handling_fee_cents']}"
        )
        assert order["transfer_price_cents"] == 34762, (
            "the asset is not federally sourced, so the price is 29762 + 5000; got "
            f"{order['transfer_price_cents']}"
        )
        assert order["acknowledged_at"] is None, (
            "pricing the transfer starts no use period, so acknowledged_at is null"
        )
        assert order["use_period_end_on"] is None, (
            "use_period_end_on stays null until the property actually leaves custody"
        )
        assert order["void_reason"] is None


class TestAssetCreationRequiresDraftTurnIn:
    """Adding property is gated on the parent turn-in still being `DRAFT`, while
    the parent's own acceptance is gated on the state of all of its children."""

    def _submitted_turn_in_with_one_unvalued_asset(self):
        """A submitted turn-in holding an appraised pickup and an unappraised
        furniture pallet."""
        return setup_assessed_assets(
            [
                {"kind": "vehicle"},
                {"kind": "furniture", "assessment": None},
            ],
            accept=False,
        )

    def test_asset_creation_on_submitted_turn_in_rejected(self, api):
        """PRD §3.2: "Each item becomes a `SurplusAsset` naming its `turn_in_id`, and the
        turn-in must be in `DRAFT` at that moment; adding property to a turn-in in any
        other state is refused with `ERR_TURN_IN_NOT_DRAFT`."
        PRD §3.2: "It also freezes the asset set — from this point forward adding property
        to the turn-in is refused with `ERR_TURN_IN_NOT_DRAFT`."
        PRD §3.2: "`asset_count` is the number of assets whose `turn_in_id` is this
        turn-in, counted across every `disposition_status` value without exception."

        Design: Difficulty/cross_entity_state_dependency/cesd_asset_creation_requires_draft_turn_in
        """
        scenario = self._submitted_turn_in_with_one_unvalued_asset()
        agency = scenario["agency"]
        turn_in = scenario["turn_in"]
        assert turn_in["status"] == "SUBMITTED", (
            f"the parent turn-in must be SUBMITTED, got {turn_in['status']}"
        )
        assert turn_in["asset_count"] == 2, (
            f"the turn-in holds two assets before the refusal, got {turn_in['asset_count']}"
        )
        version_before = turn_in["version"]

        resp = api.create_asset(
            create_it_asset_payload(
                turn_in["id"], description="Late-arriving rack-mounted server"
            ),
            make_agency_officer_headers(agency["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TURN_IN_NOT_DRAFT)

        after = read_turn_in(turn_in["id"], agency["id"])
        assert_turn_in(after)
        assert after["asset_count"] == 2, (
            "the frozen asset set must still hold exactly two assets; got "
            f"{after['asset_count']}"
        )
        assert after["version"] == version_before, (
            "the refused create applies none of its hops, so the parent's version stays "
            f"at {version_before}; got {after['version']}"
        )
        _, meta = validate_paginated(
            api.list_assets(
                ADMIN_HEADERS,
                params={"turn_in_id": turn_in["id"]},
            )
        )
        assert meta["total_count"] == 2, (
            f"no third asset row may survive the refusal; got {meta['total_count']}"
        )

    def test_acceptance_blocked_while_a_child_asset_is_unvalued(self, api):
        """PRD §3.2: "Acceptance requires that the turn-in be in `SUBMITTED` and that
        **every** child asset has left `INTAKE` — equivalently, that every child asset has
        at least one condition assessment on file and therefore a non-null
        `fair_market_value_cents`."
        PRD §3.2: "A turn-in with even one unvalued asset cannot be accepted and is
        refused with `ERR_TURN_IN_NOT_ASSESSED`; this is a compound guard, in which the
        parent's transition is conditioned on the state of all of its children."
        PRD §3.2: "`appraised_total_cents` is the sum of `fair_market_value_cents` over
        only those child assets whose valuation is non-null, accumulated in `created_at`
        ascending order, and 0 when none of them is valued yet."

        Design: Difficulty/cross_entity_state_dependency/cesd_asset_creation_requires_draft_turn_in
        """
        scenario = self._submitted_turn_in_with_one_unvalued_asset()
        agency = scenario["agency"]
        turn_in = scenario["turn_in"]
        pickup, pallet = scenario["assets"]

        assert pickup["disposition_status"] == "ASSESSED", (
            f"the pickup has an assessment on file, got {pickup['disposition_status']}"
        )
        assert pickup["fair_market_value_cents"] == PICKUP_FMV_CENTS, (
            f"the pickup must appraise at 297620 cents, got {pickup['fair_market_value_cents']}"
        )
        assert pallet["disposition_status"] == "INTAKE", (
            "the pallet has never been inspected, so it is still INTAKE; got "
            f"{pallet['disposition_status']}"
        )
        assert pallet["fair_market_value_cents"] is None, (
            "an uninspected asset carries no valuation; got "
            f"{pallet['fair_market_value_cents']}"
        )
        assert turn_in["appraised_total_cents"] == PICKUP_FMV_CENTS, (
            "only the valued child contributes to the running total; got "
            f"{turn_in['appraised_total_cents']}"
        )

        resp = api.review_turn_in(
            turn_in["id"], {"decision": "ACCEPT"}, OFFICER_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_TURN_IN_NOT_ASSESSED)

        after = read_turn_in(turn_in["id"], agency["id"])
        assert after["status"] == "SUBMITTED", (
            f"the refused acceptance leaves the turn-in SUBMITTED, got {after['status']}"
        )
        assert after["reviewed_at"] is None, (
            "no review stamp may be written by a refused acceptance; got "
            f"{after['reviewed_at']}"
        )
        assert after["version"] == turn_in["version"], (
            "the refused acceptance applies none of its hops"
        )

    def test_valuing_the_last_child_unblocks_acceptance(self, api):
        """PRD §3.3: "The first assessment on an asset drives `disposition_status` from
        `INTAKE` to `ASSESSED`."
        PRD §3.3: "Either way the parent turn-in's `appraised_total_cents` is recomputed
        and the asset's `version` increments by 1."
        PRD §3.2: "Acceptance moves `status` from `SUBMITTED` to `ACCEPTED`, stamps
        `reviewed_at` from the logical clock, recomputes `appraised_total_cents`, and
        increments the turn-in's `version` by 1."
        PRD §3.2: "A turn-in with even one unvalued asset cannot be accepted and is
        refused with `ERR_TURN_IN_NOT_ASSESSED`; this is a compound guard, in which the
        parent's transition is conditioned on the state of all of its children."

        Design: Difficulty/cross_entity_state_dependency/cesd_asset_creation_requires_draft_turn_in
        """
        scenario = self._submitted_turn_in_with_one_unvalued_asset()
        agency = scenario["agency"]
        turn_in = scenario["turn_in"]
        pallet = scenario["assets"][1]

        validate_error(
            api.review_turn_in(turn_in["id"], {"decision": "ACCEPT"}, OFFICER_HEADERS),
            ApiErrorId.ERR_TURN_IN_NOT_ASSESSED,
        )

        assessment = validate_success(
            api.create_condition_assessment(
                pallet["id"],
                create_condition_assessment_payload(
                    pallet["version"],
                    condition_code="C6",
                    functional=True,
                    repair_cost_estimate_cents=0,
                    assessed_on="2026-07-30",
                ),
                make_surplus_assessor_headers(ASSESSOR_USER_ID),
            ),
            201,
        )
        assert assessment["asset_id"] == pallet["id"]
        assert assessment["superseded"] is False, (
            "the first assessment on the pallet governs its valuation"
        )

        valued = read_asset(pallet["id"])
        assert_surplus_asset(valued)
        assert valued["disposition_status"] == "ASSESSED", (
            "the first assessment drives the pallet INTAKE to ASSESSED; got "
            f"{valued['disposition_status']}"
        )
        assert valued["fair_market_value_cents"] == FURNITURE_FMV_CENTS, (
            f"the pallet must appraise at 12540 cents, got {valued['fair_market_value_cents']}"
        )
        assert valued["version"] == pallet["version"] + 1, (
            "the assessment increments the asset's version by exactly 1"
        )

        before_accept = read_turn_in(turn_in["id"], agency["id"])
        assert before_accept["appraised_total_cents"] == 310160, (
            "the recomputed total is 297620 + 12540 = 310160; got "
            f"{before_accept['appraised_total_cents']}"
        )

        accepted = validate_success(
            api.review_turn_in(turn_in["id"], {"decision": "ACCEPT"}, OFFICER_HEADERS),
            200,
        )
        assert_turn_in(accepted)
        assert accepted["status"] == "ACCEPTED", (
            f"acceptance moves SUBMITTED to ACCEPTED, got {accepted['status']}"
        )
        assert accepted["reviewed_at"] is not None, (
            "acceptance stamps reviewed_at from the logical clock"
        )
        assert accepted["reviewed_at"].startswith("2026-08-01T00:00:00"), (
            "reviewed_at is stamped from the logical clock, which stands at "
            f"2026-08-01T00:00:00Z; got {accepted['reviewed_at']}"
        )
        assert accepted["asset_count"] == 2, (
            f"acceptance changes no asset membership, got {accepted['asset_count']}"
        )
        assert accepted["appraised_total_cents"] == 310160, (
            f"the accepted total is 310160; got {accepted['appraised_total_cents']}"
        )
        assert accepted["version"] == before_accept["version"] + 1, (
            "acceptance increments the turn-in's version by exactly 1"
        )
