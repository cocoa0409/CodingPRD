"""Arithmetic corners of the surplus-property money rules.

Every figure here is compared as an exact whole-cent integer. The PRD evaluates
its products in exact decimal arithmetic and pins where each rounding happens,
so an approximate comparison would hide the very defects these tests exist to
catch.
"""

from datetime import datetime

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    add_asset,
    add_asset_with_payload,
    create_asset_payload,
    create_auction_lot_payload,
    create_bid_payload,
    create_clearance_certificate_payload,
    create_draft_turn_in,
    create_proceeds_distribution_payload,
    create_screening_cycle_payload,
    create_screening_request_payload,
    create_transfer_order_payload,
    make_agency_officer_headers,
    make_bidder_headers,
    make_clearance_technician_headers,
    make_disposal_officer_headers,
    make_finance_controller_headers,
    make_program_admin_headers,
    make_surplus_assessor_headers,
    register_bidder,
    register_local_government,
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
TECHNICIAN = make_clearance_technician_headers()
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


def _submitted_furniture_turn_in(costs, acquisition_date="2026-01-10"):
    """A SUBMITTED turn-in of an ACTIVE state agency holding one FURNITURE
    asset per entry in ``costs``, in order."""
    set_clock(CLOCK_EPOCH)
    agency = register_state_agency()
    turn_in = create_draft_turn_in(agency["id"])
    assets = [
        add_asset(
            agency["id"],
            turn_in["id"],
            description=f"Office furniture lot {index + 1}",
            acquisition_cost_cents=cost,
            acquisition_date=acquisition_date,
        )
        for index, cost in enumerate(costs)
    ]
    submit_turn_in(agency["id"], turn_in["id"])
    return agency, turn_in, assets


def _accepted_furniture_turn_in(api, costs, acquisition_date="2026-01-10", **overrides):
    """As above, then appraise every asset with the same assessment and accept."""
    agency, turn_in, assets = _submitted_furniture_turn_in(
        costs, acquisition_date=acquisition_date
    )
    for asset in assets:
        validate_success(
            api.create_condition_assessment(
                asset["id"],
                _assessment_payload(asset["version"], **overrides),
                ASSESSOR,
            ),
            201,
        )
    review_turn_in(turn_in["id"], "ACCEPT")
    return agency, turn_in, assets


def _award_asset_to(api, asset_id, recipient_agency_id, advance_once):
    """Walk one ASSESSED asset through a screening cycle to an approved request
    for ``recipient_agency_id``, advancing the ladder one step when asked."""
    cycle = validate_success(
        api.create_screening_cycle(
            create_screening_cycle_payload(
                asset_id, opens_at=CLOCK_EPOCH, tier_window_days=5
            ),
            OFFICER,
        ),
        201,
    )
    if advance_once:
        validate_success(api.advance_screening_tier(cycle["id"], OFFICER))
    request = validate_success(
        api.create_screening_request(
            create_screening_request_payload(cycle["id"], recipient_agency_id),
            ADMIN,
        ),
        201,
    )
    validate_success(api.award_screening_cycle(cycle["id"], request["id"], OFFICER))
    return cycle, request


class TestFairMarketValueCorners:
    """The valuation product, its single rounding and its zero floor."""

    def test_non_functional_factor_and_repair_deduction_floor(self, api):
        """Two valuation corners on one write pass.

        "The **functional factor** is one when the governing assessment's
        `functional` flag is true, and sixty hundredths when it is false."

        "Multiply `acquisition_cost_cents` by the condition factor, the age
        factor and the functional factor, and round that single product half up
        to whole cents."

        "From the resulting whole-cent figure subtract the governing
        assessment's `repair_cost_estimate_cents`. If the subtraction would go
        below zero the value is zero instead — repairs can drive an item's
        market value to nothing but never below it."

        Design: Corner/calculations/calc_fmv_non_functional_factor_and_repair_floor
        """
        agency, turn_in, (asset_nf, asset_rf) = _submitted_furniture_turn_in(
            [1_000_000, 25_000]
        )

        # C1 keeps the full condition factor and the acquisition date is inside
        # the same year as the clock, so only the functional factor bites.
        validate_success(
            api.create_condition_assessment(
                asset_nf["id"],
                _assessment_payload(asset_nf["version"], functional=False),
                ASSESSOR,
            ),
            201,
        )
        # A repair estimate larger than the whole rounded base.
        validate_success(
            api.create_condition_assessment(
                asset_rf["id"],
                _assessment_payload(
                    asset_rf["version"], repair_cost_estimate_cents=30_000
                ),
                ASSESSOR,
            ),
            201,
        )

        seized = validate_success(api.get_asset(asset_nf["id"], OFFICER))
        assert seized["fair_market_value_cents"] == 600_000, (
            "a mint-condition item that does not run is worth sixty hundredths "
            "of its condition value: round_half_up(1000000 * 1.00 * 1.00 * 0.60)"
        )

        floored = validate_success(api.get_asset(asset_rf["id"], OFFICER))
        assert floored["fair_market_value_cents"] == 0, (
            "a 25000-cent base less a 30000-cent repair estimate is floored at "
            f"0, never negative; got {floored['fair_market_value_cents']}"
        )
        assert floored["condition_code"] == "C1", (
            "the zero floor does not blank the condition copied from the "
            f"governing assessment; got {floored['condition_code']!r}"
        )

        for asset in (seized, floored):
            assert asset["disposition_status"] == "ASSESSED", (
                "the first assessment drives the asset from INTAKE to ASSESSED"
            )
            assert asset["version"] == 2, (
                "the asset's version increments by exactly 1 on the assessment; "
                f"got {asset['version']}"
            )

    def test_zero_valued_asset_contributes_nothing_to_the_appraised_total(self, api):
        """The parent roll-up sums the valuations, and a floored one adds zero.

        "`appraised_total_cents` is the sum of `fair_market_value_cents` over
        only those child assets whose valuation is non-null, accumulated in
        `created_at` ascending order, and 0 when none of them is valued yet."

        "Either way the parent turn-in's `appraised_total_cents` is recomputed
        and the asset's `version` increments by 1."

        Design: Corner/calculations/calc_fmv_non_functional_factor_and_repair_floor
        """
        agency, turn_in, (asset_nf, asset_rf) = _submitted_furniture_turn_in(
            [1_000_000, 25_000]
        )
        validate_success(
            api.create_condition_assessment(
                asset_nf["id"],
                _assessment_payload(asset_nf["version"], functional=False),
                ASSESSOR,
            ),
            201,
        )
        validate_success(
            api.create_condition_assessment(
                asset_rf["id"],
                _assessment_payload(
                    asset_rf["version"], repair_cost_estimate_cents=30_000
                ),
                ASSESSOR,
            ),
            201,
        )

        parent = validate_success(
            api.get_turn_in(turn_in["id"], make_agency_officer_headers(agency["id"]))
        )
        assert parent["appraised_total_cents"] == 600_000, (
            "600000 plus the zero-valued asset's 0; the floored asset "
            f"contributes nothing, got {parent['appraised_total_cents']}"
        )
        assert parent["asset_count"] == 2, (
            "asset_count counts every child asset regardless of its valuation"
        )

    def test_governing_assessment_is_ranked_by_assessed_on_not_by_insert_order(
        self, api
    ):
        """A back-dated correction cannot dislodge a later inspection date.

        "Candidates are ranked by `assessed_on` descending — the most recent
        inspection date wins — and where two share the same inspection date, by
        `created_at` descending, so the later-recorded of two same-day
        assessments wins."

        "Every other candidate carries `superseded` equal to true, and the
        governing one carries `superseded` equal to false."

        "Note carefully that `superseded` is an *output* of the ranking and not
        a filter on it: an already-superseded assessment stays in the candidate
        pool for every subsequent run, so a correction recorded with an earlier
        `assessed_on` cannot dislodge a later one, and deleting nothing ever
        changes the pool."

        Design: Corner/calculations/calc_fmv_governing_assessment_ranked_by_assessed_on
        """
        agency, turn_in, (asset,) = _submitted_furniture_turn_in([1_000_000])

        newer = validate_success(
            api.create_condition_assessment(
                asset["id"],
                _assessment_payload(
                    asset["version"], condition_code="C2", assessed_on="2026-07-28"
                ),
                ASSESSOR,
            ),
            201,
        )
        after_first = validate_success(api.get_asset(asset["id"], ASSESSOR))
        assert after_first["fair_market_value_cents"] == 850_000, (
            "round_half_up(1000000 * 0.85 * 1.00 * 1.00) for the C2 appraisal"
        )

        older = validate_success(
            api.create_condition_assessment(
                asset["id"],
                _assessment_payload(
                    after_first["version"],
                    condition_code="C5",
                    assessed_on="2026-07-20",
                    notes="Back-dated inspection sheet located in the yard office",
                ),
                ASSESSOR,
            ),
            201,
        )

        revalued = validate_success(api.get_asset(asset["id"], OFFICER))
        assert revalued["fair_market_value_cents"] == 850_000, (
            "the 2026-07-28 row still governs, so the value stays at 850000 "
            f"rather than dropping to the C5 figure; got "
            f"{revalued['fair_market_value_cents']}"
        )
        assert revalued["condition_code"] == "C2", (
            "the governing assessment's condition code is the one copied onto "
            f"the asset; got {revalued['condition_code']!r}"
        )
        assert revalued["version"] == 3, (
            "the asset is still rewritten by the insert even though the value "
            f"did not move; got version {revalued['version']}"
        )

        rows, meta = validate_paginated(
            api.list_condition_assessments(asset["id"], ASSESSOR, {"limit": 50})
        )
        assert meta["total_count"] == 2, (
            f"both assessments are retained, got total_count {meta['total_count']}"
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[newer["id"]]["superseded"] is False, (
            "the 2026-07-28 row is the top-ranked candidate and governs"
        )
        assert by_id[older["id"]]["superseded"] is True, (
            "the just-inserted 2026-07-20 row is the superseded one"
        )

        parent = validate_success(
            api.get_turn_in(turn_in["id"], make_agency_officer_headers(agency["id"]))
        )
        assert parent["appraised_total_cents"] == 850_000, (
            "the recomputed roll-up follows the governing valuation"
        )


class TestTransferHandlingFeeTierBoundary:
    """The handling-fee band is keyed on the discounted base, inclusively."""

    def test_handling_fee_band_boundary_at_exactly_one_thousand_dollars_of_base(
        self, api
    ):
        """Two cents of appraised value cross the fee band.

        "First, read the recipient's discount factor from its `agency_type`: a
        `STATE_AGENCY` pays twenty-five hundredths of value, a
        `LOCAL_GOVERNMENT` pays fifty hundredths, and an `ELIGIBLE_NONPROFIT`
        pays ten hundredths."

        "Second, multiply the asset's stored `fair_market_value_cents` by that
        factor and round the product half up to whole cents; the result is
        stored as `base_transfer_cents`."

        "Third, select the `handling_fee_cents` from a three-band schedule keyed
        **only** on `base_transfer_cents`: a base below one thousand dollars
        draws a fifty-dollar fee; a base of one thousand dollars or more but
        below ten thousand dollars draws a one hundred twenty-five dollar fee; a
        base of ten thousand dollars or more draws a three hundred dollar fee."

        "The age factor is one minus ten hundredths for each of those full
        years, but never less than twenty hundredths — an item held twelve years
        and an item held twenty years are both floored at the same twenty
        hundredths of original value."

        "A newly issued order sits in `status` `ISSUED` with
        `issued_by_user_id` stamped from the officer's `X-User-ID`, and with
        `acknowledged_at`, `use_period_end_on` and `void_reason` all null."

        Design: Corner/calculations/calc_transfer_handling_fee_tier_boundary_at_100000_base
        """
        agency, turn_in, (asset_hi, asset_lo) = _accepted_furniture_turn_in(
            api, [1_000_000, 999_990], acquisition_date="2005-01-01"
        )
        city = register_local_government()

        valued_hi = validate_success(api.get_asset(asset_hi["id"], OFFICER))
        valued_lo = validate_success(api.get_asset(asset_lo["id"], OFFICER))
        assert valued_hi["fair_market_value_cents"] == 200_000, (
            "the age factor clamps to twenty hundredths after twenty-one full "
            f"years; got {valued_hi['fair_market_value_cents']}"
        )
        assert valued_lo["fair_market_value_cents"] == 199_998, (
            f"round_half_up(999990 * 1.00 * 0.20 * 1.00); got "
            f"{valued_lo['fair_market_value_cents']}"
        )

        _, request_hi = _award_asset_to(api, asset_hi["id"], city["id"], True)
        _, request_lo = _award_asset_to(api, asset_lo["id"], city["id"], True)

        order_hi = validate_success(
            api.create_transfer_order(
                create_transfer_order_payload(
                    asset_hi["id"], city["id"], request_hi["id"]
                ),
                OFFICER,
            ),
            201,
        )
        order_lo = validate_success(
            api.create_transfer_order(
                create_transfer_order_payload(
                    asset_lo["id"], city["id"], request_lo["id"]
                ),
                OFFICER,
            ),
            201,
        )

        assert order_hi["base_transfer_cents"] == 100_000, (
            "round_half_up(200000 * 0.50) for a LOCAL_GOVERNMENT recipient; got "
            f"{order_hi['base_transfer_cents']}"
        )
        assert order_hi["handling_fee_cents"] == 12_500, (
            "a base of exactly one thousand dollars is already in the middle "
            f"band; got {order_hi['handling_fee_cents']}"
        )
        assert order_hi["transfer_price_cents"] == 112_500, (
            "base plus fee for a non-federal asset; got "
            f"{order_hi['transfer_price_cents']}"
        )

        assert order_lo["base_transfer_cents"] == 99_999, (
            f"round_half_up(199998 * 0.50); got {order_lo['base_transfer_cents']}"
        )
        assert order_lo["handling_fee_cents"] == 5_000, (
            "one cent below the band boundary still draws the fifty-dollar fee; "
            f"got {order_lo['handling_fee_cents']}"
        )
        assert order_lo["transfer_price_cents"] == 104_999, (
            f"base plus fee; got {order_lo['transfer_price_cents']}"
        )

        for order in (order_hi, order_lo):
            assert order["status"] == "ISSUED", "a new order sits in ISSUED"
            assert order["issued_by_user_id"] == "officer-01", (
                "issued_by_user_id is stamped from the officer's X-User-ID; got "
                f"{order['issued_by_user_id']!r}"
            )
            assert order["use_period_end_on"] is None, (
                "neither asset is federally sourced"
            )
            assert order["acknowledged_at"] is None, (
                "a newly issued order has not been acknowledged"
            )

        awarded = validate_success(api.get_asset(asset_hi["id"], OFFICER))
        assert awarded["disposition_status"] == "AWARDED_TRANSFER", (
            f"the award moved the asset; got {awarded['disposition_status']!r}"
        )
        assert awarded["fair_market_value_cents"] == 200_000, (
            "transfer pricing never overwrites the stored appraisal; got "
            f"{awarded['fair_market_value_cents']}"
        )


def _sell_de_minimis_asset(api, asset_id, hammer_cents, end_use_expires_on=None):
    """List one de-minimis asset, take a single bid at ``hammer_cents`` and
    close the lot. Returns the closed lot and the winning bidder."""
    venue = register_venue(name="Austin Auction Yard", venue_code="AUS-01")
    lot = validate_success(
        api.create_auction_lot(
            create_auction_lot_payload(
                asset_id,
                venue["id"],
                opens_at="2026-08-02T00:00:00Z",
                closes_at="2026-08-03T00:00:00Z",
            ),
            OFFICER,
        ),
        201,
    )
    bidder = register_bidder(
        legal_name="Cedar Ridge Salvage LLC",
        email="bids@cedarridge.example",
        end_use_certificate_expires_on=end_use_expires_on,
    )
    set_clock("2026-08-02T00:00:00Z")
    validate_success(api.open_auction_lot(lot["id"], OFFICER))
    validate_success(
        api.place_bid(
            lot["id"],
            create_bid_payload(bidder["id"], hammer_cents),
            make_bidder_headers(bidder["id"]),
        ),
        201,
    )
    set_clock("2026-08-03T00:00:00Z")
    closed = validate_success(api.close_auction_lot(lot["id"], OFFICER))
    return closed, bidder


class TestProceedsWaterfallCorners:
    """The marginal service-fee slices and the verified-certificate input set."""

    def test_service_fee_is_the_sum_of_marginal_slices_not_an_average_rate(self, api):
        """A base of 600000 straddles the first fee slice.

        "Under the `ACCRUAL` basis it is the price the lot achieved, the lot's
        `high_bid_cents`, whether or not the buyer ever paid a cent."

        "The first slice is the smaller of the base and five thousand dollars,
        charged at twelve and a half hundredths."

        "The second slice is the portion of the base above five thousand dollars
        up to fifty thousand dollars, and is zero when the base does not reach
        five thousand dollars, charged at eight hundred seventy-five
        ten-thousandths."

        "Each of the three products is rounded half up to whole cents
        independently, and `service_fee_cents` is the exact sum of those three
        integers. Applying a single blended rate to the whole base, or rounding
        only once at the end, is not the same computation."

        "The `net_to_agency_cents` is the larger of zero and the base less the
        service fee less the cost recovery."

        "It is resolved at create time by walking from the lot to its asset,
        from the asset's `turn_in_id` to that turn-in, and from there to the
        turn-in's `turning_in_agency_id` — the organisation that relinquished
        the property, which may be quite different from anyone involved in the
        sale."

        Design: Corner/calculations/calc_proceeds_waterfall_marginal_slices_not_average_rate
        """
        agency, turn_in, (asset,) = _accepted_furniture_turn_in(
            api,
            [104_500],
            acquisition_date="2024-05-20",
            condition_code="C6",
        )
        closed_lot, _bidder = _sell_de_minimis_asset(api, asset["id"], 600_000)

        distribution = validate_success(
            api.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    closed_lot["id"], closed_lot["version"], basis="ACCRUAL"
                ),
                FINANCE,
            ),
            201,
        )

        assert distribution["status"] == "CALCULATED", (
            f"a new distribution lands in CALCULATED; got {distribution['status']!r}"
        )
        assert distribution["distributable_base_cents"] == 600_000, (
            "the ACCRUAL base is the lot's high_bid_cents; got "
            f"{distribution['distributable_base_cents']}"
        )
        assert distribution["service_fee_cents"] == 71_250, (
            "round_half_up(500000 * 0.125) is 62500 and "
            "round_half_up(100000 * 0.0875) is 8750, summing to 71250; a flat "
            "12.5 percent would give 75000 and a flat 8.75 percent 52500, got "
            f"{distribution['service_fee_cents']}"
        )
        assert distribution["cost_recovery_cents"] == 0, (
            "the asset carries no clearance certificates at all; got "
            f"{distribution['cost_recovery_cents']}"
        )
        assert distribution["net_to_agency_cents"] == 528_750, (
            f"600000 less 71250 less 0; got {distribution['net_to_agency_cents']}"
        )
        assert distribution["beneficiary_agency_id"] == agency["id"], (
            "the beneficiary is resolved through the lot's asset to its "
            "turn-in's relinquishing organisation"
        )

        beneficiary = validate_success(api.get_agency(agency["id"], ADMIN))
        assert beneficiary["proceeds_account_balance_cents"] == 0, (
            "only POSTED distributions reach the ledger; got "
            f"{beneficiary['proceeds_account_balance_cents']}"
        )
        assert beneficiary["posted_distribution_count"] == 0, (
            "a merely calculated distribution is not counted; got "
            f"{beneficiary['posted_distribution_count']}"
        )

    def test_cost_recovery_counts_verified_certificates_only(self, api):
        """One failed re-check contributes nothing to the recovery.

        "The `cost_recovery_cents` is seventy-five dollars for each
        `DATA_SANITIZATION` certificate plus two hundred twenty-five dollars for
        each `DEMILITARIZATION` certificate, counted over the asset's clearance
        certificates whose `serials_verified` is true as they exist at the
        moment the distribution is created."

        "There is no time window and no de-duplication by `method`: three
        separate verified sanitisation certificates on one asset recover three
        times the sanitisation fee, and a certificate filed after the
        distribution was created does not retroactively change it."

        "A certificate with `serials_verified` false is persisted for audit and
        moves the asset to `BLOCKED`, whether it arrives at `REQUIRED_PENDING`
        or at `CLEARED` — a clearance that has already been granted can be
        revoked by a later failed verification, though only while the asset has
        not yet reached `RELEASED`."

        "The `net_to_agency_cents` is the larger of zero and the base less the
        service fee less the cost recovery."

        Design: Corner/calculations/calc_proceeds_cost_recovery_counts_verified_certificates_only
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        turn_in = create_draft_turn_in(
            agency["id"], custody_location="Camp Swift Storage"
        )
        asset = add_asset_with_payload(
            agency["id"],
            create_asset_payload(
                turn_in["id"],
                category="RESTRICTED_MILITARY",
                description="Field communications shelter with onboard storage",
                acquisition_cost_cents=104_500,
                acquisition_date="2024-05-20",
                is_data_bearing=True,
                is_restricted=True,
                demil_code="B",
            ),
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

        sanitization = validate_success(
            api.create_clearance_certificate(
                asset["id"],
                create_clearance_certificate_payload(
                    cert_type="DATA_SANITIZATION",
                    method="NIST_PURGE",
                    serials_verified=True,
                    certified_on="2026-08-01",
                ),
                TECHNICIAN,
            ),
            201,
        )
        demilitarization = validate_success(
            api.create_clearance_certificate(
                asset["id"],
                create_clearance_certificate_payload(
                    cert_type="DEMILITARIZATION",
                    method="MUTILATE",
                    serials_verified=True,
                    certified_on="2026-08-01",
                ),
                TECHNICIAN,
            ),
            201,
        )
        failed = validate_success(
            api.create_clearance_certificate(
                asset["id"],
                create_clearance_certificate_payload(
                    cert_type="DATA_SANITIZATION",
                    method="DEGAUSS",
                    serials_verified=False,
                    certified_on="2026-08-01",
                    notes="Re-check of two drive serials failed",
                ),
                TECHNICIAN,
            ),
            201,
        )
        review_turn_in(turn_in["id"], "ACCEPT")

        closed_lot, _bidder = _sell_de_minimis_asset(
            api, asset["id"], 600_000, end_use_expires_on="2027-06-30"
        )

        distribution = validate_success(
            api.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    closed_lot["id"], closed_lot["version"], basis="ACCRUAL"
                ),
                FINANCE,
            ),
            201,
        )

        assert distribution["distributable_base_cents"] == 600_000, (
            f"the ACCRUAL base is the hammer price; got "
            f"{distribution['distributable_base_cents']}"
        )
        assert distribution["service_fee_cents"] == 71_250, (
            f"62500 plus 8750; got {distribution['service_fee_cents']}"
        )
        assert distribution["cost_recovery_cents"] == 30_000, (
            "7500 for the one verified sanitisation certificate plus 22500 for "
            "the one verified demilitarisation certificate; counting all three "
            f"rows would give 37500, got {distribution['cost_recovery_cents']}"
        )
        assert distribution["net_to_agency_cents"] == 498_750, (
            f"600000 less 71250 less 30000; got "
            f"{distribution['net_to_agency_cents']}"
        )

        blocked = validate_success(api.get_asset(asset["id"], OFFICER))
        assert blocked["clearance_status"] == "BLOCKED", (
            "the failed re-check revoked the clearance, yet the two verified "
            "certificates still count because the recovery reads certificate "
            f"rows; got {blocked['clearance_status']!r}"
        )

        rows, meta = validate_paginated(
            api.list_clearance_certificates(asset["id"], TECHNICIAN, {"limit": 50})
        )
        assert meta["total_count"] == 3, (
            f"every certificate is persisted; got total_count {meta['total_count']}"
        )
        ids = {row["id"] for row in rows}
        for certificate in (sanitization, demilitarization, failed):
            assert certificate["id"] in ids, (
                f"certificate {certificate['id']} must survive in the listing"
            )


class TestScreeningTierDeadline:
    """Each tier window is measured from the tier's own opening instant."""

    def test_first_tier_deadline_derives_from_the_supplied_opening_instant(self, api):
        """The first window is measured from `opens_at`, not from the clock.

        "A new cycle is `OPEN`, its `current_tier` is `STATE_AGENCY`, its
        `tier_opened_at` equals the supplied `opens_at`, its
        `tier_advance_count` is 0, its `open_request_count` is 0, and
        `awarded_by_user_id` and `awarded_at` are null."

        "Its `tier_deadline_at` is derived as the `tier_opened_at` plus
        `tier_window_days` whole days, where a day is an exact multiple of
        twenty-four hours."

        "Opening the cycle also moves the asset from `ASSESSED` to `SCREENING`
        and increments the asset's `version` by 1."

        Design: Corner/calculations/calc_screening_tier_deadline_recomputed_on_each_advance
        """
        agency, turn_in, (asset,) = _accepted_furniture_turn_in(api, [1_000_000])

        cycle = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    asset["id"],
                    opens_at="2026-08-04T00:00:00Z",
                    tier_window_days=3,
                ),
                OFFICER,
            ),
            201,
        )

        assert cycle["current_tier"] == "STATE_AGENCY", (
            f"a new cycle starts at the top of the ladder; got "
            f"{cycle['current_tier']!r}"
        )
        assert cycle["status"] == "OPEN", f"got {cycle['status']!r}"
        assert cycle["tier_advance_count"] == 0, (
            f"nothing has advanced yet; got {cycle['tier_advance_count']}"
        )
        _assert_instant(
            cycle["tier_opened_at"], "2026-08-04T00:00:00Z", "tier_opened_at"
        )
        _assert_instant(
            cycle["tier_deadline_at"], "2026-08-07T00:00:00Z", "tier_deadline_at"
        )

        screening = validate_success(api.get_asset(asset["id"], OFFICER))
        assert screening["disposition_status"] == "SCREENING", (
            f"cycle creation moves the asset; got "
            f"{screening['disposition_status']!r}"
        )

    def test_advance_restamps_the_tier_opening_and_recomputes_the_deadline(self, api):
        """Advancing late does not shorten the next window.

        "An advance is permitted only when the cycle's `open_request_count` is
        zero — nobody in this tier wants the property — or when the logical
        clock has reached or passed `tier_deadline_at`, meaning the window has
        closed regardless of interest."

        "From `STATE_AGENCY`, `LOCAL_GOVERNMENT` or `ELIGIBLE_NONPROFIT`, the
        advance keeps the cycle in `OPEN` and moves `current_tier` exactly one
        step along the fixed order `STATE_AGENCY` → `LOCAL_GOVERNMENT` →
        `ELIGIBLE_NONPROFIT` → `PUBLIC_SALE`; `tier_opened_at` is reset to the
        logical clock, `tier_deadline_at` is recomputed from that new opening
        instant plus the same `tier_window_days`, `tier_advance_count` increases
        by 1, and the cycle's `version` increments by 1."

        "Calendar-day arithmetic on instants is exact: adding a whole number of
        days means adding that many multiples of 24 hours."

        Design: Corner/calculations/calc_screening_tier_deadline_recomputed_on_each_advance
        """
        agency, turn_in, (asset,) = _accepted_furniture_turn_in(api, [1_000_000])
        cycle = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    asset["id"],
                    opens_at="2026-08-04T00:00:00Z",
                    tier_window_days=3,
                ),
                OFFICER,
            ),
            201,
        )

        # Two days and nine hours into a three-day window, with nobody asking.
        set_clock("2026-08-06T09:15:30Z")
        validate_success(api.advance_screening_tier(cycle["id"], OFFICER))

        advanced = validate_success(api.get_screening_cycle(cycle["id"], OFFICER))
        assert advanced["current_tier"] == "LOCAL_GOVERNMENT", (
            f"exactly one step along the fixed order; got "
            f"{advanced['current_tier']!r}"
        )
        assert advanced["status"] == "OPEN", (
            f"the ladder is not exhausted yet; got {advanced['status']!r}"
        )
        assert advanced["tier_advance_count"] == 1, (
            f"got {advanced['tier_advance_count']}"
        )
        _assert_instant(
            advanced["tier_opened_at"], "2026-08-06T09:15:30Z", "tier_opened_at"
        )
        _assert_instant(
            advanced["tier_deadline_at"], "2026-08-09T09:15:30Z", "tier_deadline_at"
        )
        assert advanced["open_request_count"] == 0, (
            "the advance was legal through the empty-request branch of the gate; "
            f"got {advanced['open_request_count']}"
        )


class TestDeMinimisThreshold:
    """One cent of appraised value picks the disposal channel."""

    @staticmethod
    def _threshold_pair(api):
        agency, turn_in, assets = _accepted_furniture_turn_in(api, [25_000, 24_999])
        venue = register_venue(name="Austin Auction Yard", venue_code="AUS-01")
        return agency, assets[0], assets[1], venue

    def test_asset_at_exactly_the_threshold_must_be_screened_not_listed(self, api):
        """25000 is not strictly below 25000, so the exemption does not apply.

        "An asset still in `ASSESSED` is listable only under the de-minimis
        exemption: its `fair_market_value_cents` must be strictly below two
        hundred fifty dollars, and its turn-in must have been `ACCEPTED`, in
        which case it moves `ASSESSED` → `LISTED` without ever entering a
        screening cycle."

        "The comparison is strict, so an asset valued at exactly twenty-five
        thousand cents is not exempt and cannot take this path."

        "The threshold is inclusive on the screening side: an asset valued at
        exactly twenty-five thousand cents is **not** exempt and must complete
        screening."

        Design: Corner/calculations/calc_de_minimis_threshold_is_strict_less_than
        """
        agency, at_threshold, _below, venue = self._threshold_pair(api)
        assert (
            validate_success(api.get_asset(at_threshold["id"], OFFICER))[
                "fair_market_value_cents"
            ]
            == 25_000
        ), "the at-threshold asset must be appraised at exactly 25000"

        validate_error(
            api.create_auction_lot(
                create_auction_lot_payload(
                    at_threshold["id"],
                    venue["id"],
                    opens_at="2026-08-02T00:00:00Z",
                    closes_at="2026-08-03T00:00:00Z",
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_ASSET_NOT_DISPOSABLE,
        )

        cycle = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    at_threshold["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
                ),
                OFFICER,
            ),
            201,
        )
        assert cycle["current_tier"] == "STATE_AGENCY", (
            f"the screening channel accepts it; got {cycle['current_tier']!r}"
        )

        screening = validate_success(api.get_asset(at_threshold["id"], OFFICER))
        assert screening["disposition_status"] == "SCREENING", (
            f"got {screening['disposition_status']!r}"
        )

        _rows, meta = validate_paginated(
            api.list_auction_lots(
                OFFICER, {"asset_id": at_threshold["id"], "limit": 50}
            )
        )
        assert meta["total_count"] == 0, (
            "the refused listing persisted nothing; got total_count "
            f"{meta['total_count']}"
        )

    def test_asset_one_cent_below_the_threshold_is_listable_and_never_screened(
        self, api
    ):
        """24999 is strictly below the threshold, so the channels swap over.

        "An asset still in `ASSESSED` is listable only under the de-minimis
        exemption: its `fair_market_value_cents` must be strictly below two
        hundred fifty dollars, and its turn-in must have been `ACCEPTED`, in
        which case it moves `ASSESSED` → `LISTED` without ever entering a
        screening cycle."

        "By default the reserve is derived from the asset's stored valuation:
        take sixty hundredths of `fair_market_value_cents`, round that product
        half up to whole cents, and use the larger of that figure and twenty-five
        dollars."

        "The asset must be in `disposition_status` `ASSESSED`, its turn-in must
        have been `ACCEPTED`, and its `fair_market_value_cents` must be at least
        two hundred fifty dollars — low-value property is statutorily exempt from
        tier screening and pushing a below-threshold item into a cycle is refused
        with `ERR_ASSET_NOT_DISPOSABLE`."

        Design: Corner/calculations/calc_de_minimis_threshold_is_strict_less_than
        """
        agency, _at_threshold, below, venue = self._threshold_pair(api)
        assert (
            validate_success(api.get_asset(below["id"], OFFICER))[
                "fair_market_value_cents"
            ]
            == 24_999
        ), "the below-threshold asset must be appraised at exactly 24999"

        lot = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    below["id"],
                    venue["id"],
                    opens_at="2026-08-02T00:00:00Z",
                    closes_at="2026-08-03T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        assert lot["reserve_price_cents"] == 14_999, (
            f"round_half_up(24999 * 0.60); got {lot['reserve_price_cents']}"
        )
        assert lot["reserve_source"] == "COMPUTED", (
            "the officer supplied no override, so the computed figure is stored; "
            f"got {lot['reserve_source']!r}"
        )

        listed = validate_success(api.get_asset(below["id"], OFFICER))
        assert listed["disposition_status"] == "LISTED", (
            "the exempt asset moves straight from ASSESSED to LISTED; got "
            f"{listed['disposition_status']!r}"
        )

        validate_error(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    below["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_ASSET_NOT_DISPOSABLE,
        )
