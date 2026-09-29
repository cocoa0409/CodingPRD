"""Optimistic concurrency, close-time selection and list-window semantics.

The PRD protects exactly two write paths with an optimistic-concurrency token —
condition-assessment recording against a `SurplusAsset` and proceeds-distribution
creation against an `AuctionLot` — and pins where those refusals sit in the
validation precedence order. This module also covers the close-time winning-bid
selector's blindness to retracted bids and the pagination window contract on the
asset listing.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_auction_lot,
    assert_condition_assessment,
    assert_lot_rollups,
    assert_proceeds_distribution,
    assert_proceeds_net,
    assert_race_outcome,
    assert_sale_invoice,
    assert_surplus_asset,
    assert_version_incremented,
    create_asset_payload,
    create_condition_assessment_payload,
    create_draft_turn_in,
    create_it_asset_payload,
    create_proceeds_distribution_payload,
    create_vehicle_asset_payload,
    find_invoice_for_lot,
    get_success_data,
    list_lot_bids,
    make_disposal_officer_headers,
    make_finance_controller_headers,
    make_program_admin_headers,
    make_surplus_assessor_headers,
    place_bid,
    read_asset,
    read_bidder,
    read_lot,
    register_bidder,
    register_state_agency,
    run_race,
    set_clock,
    setup_assessed_assets,
    setup_lot_with_active_bid,
    validate_error,
    validate_paginated,
    validate_success,
    add_asset_with_payload,
)

ASSESSOR = make_surplus_assessor_headers()
OFFICER = make_disposal_officer_headers()
FINANCE = make_finance_controller_headers()
ADMIN = make_program_admin_headers()


# ─── Local scenario builders ──────────────────────────────────────────────

def _submitted_turn_in_with_unappraised_furniture() -> dict:
    """One SUBMITTED turn-in holding a single FURNITURE asset that has never been
    appraised, so the asset's `version` still stands where creation left it.

    Cost 1000000 cents acquired 2026-01-10 against a logical clock of
    2026-08-01 gives no full elapsed year, so the age factor is 1 and the
    condition factor alone drives fair market value.
    """
    scenario = setup_assessed_assets(
        [{
            "kind": "furniture",
            "overrides": {
                "description": "Modular workstation cluster",
                "acquisition_cost_cents": 1_000_000,
                "acquisition_date": "2026-01-10",
            },
            "assessment": None,
        }],
        clock=CLOCK_EPOCH,
        accept=False,
    )
    scenario["asset"] = scenario["assets"][0]
    return scenario


def _assessment_payload(expected_asset_version, **overrides) -> dict:
    payload = {
        "condition_code": "C1",
        "functional": True,
        "repair_cost_estimate_cents": 0,
        "assessed_on": "2026-07-15",
    }
    payload.update(overrides)
    return create_condition_assessment_payload(expected_asset_version, **payload)


def _closed_met_furniture_lot() -> dict:
    """A de-minimis FURNITURE asset sold on one lot for a hammer price of 20000,
    the lot closed with the reserve met and its `SaleInvoice` still `ISSUED`.

    ``lot_version_while_open`` is read back while the lot is still OPEN and after
    the bid, so the close is the only mutation of the lot between that read and
    the refusals the tests drive.
    """
    scenario = setup_lot_with_active_bid(
        bid_amount_cents=20_000, kind="furniture", route="de_minimis",
    )
    scenario["lot_version_while_open"] = scenario["lot"]["version"]
    set_clock(scenario["lot"]["closes_at"])
    scenario["lot"] = get_success_data(
        api_client.close_auction_lot(scenario["lot"]["id"], OFFICER)
    )
    return scenario


class TestConditionAssessmentOptimisticConcurrency:
    """`POST /assets/{id}/condition-assessments` guarded by `expected_asset_version`."""

    def test_first_assessment_consumes_the_expected_asset_version_token(self):
        """A matching `expected_asset_version` is accepted and spends the token.

        "Recording a condition assessment against an asset — `POST
        /assets/{id}/condition-assessments` — requires a non-optional
        `expected_asset_version` field in the request body, carrying the client's
        last observed `version` of the addressed `SurplusAsset`."

        "Either way the parent turn-in's `appraised_total_cents` is recomputed and
        the asset's `version` increments by 1."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_asset_version_refused_and_future_date_outranks_it
        """
        scenario = _submitted_turn_in_with_unappraised_furniture()
        asset = scenario["asset"]
        assert asset["version"] == 1, (
            "a freshly created asset that has never been assessed sits at version 1"
        )

        created = validate_success(
            api_client.create_condition_assessment(
                asset["id"], _assessment_payload(1), ASSESSOR
            ),
            201,
        )
        assert_condition_assessment(created)
        assert created["condition_code"] == "C1"
        assert created["superseded"] is False, (
            "the only assessment on file is the governing one"
        )

        after = read_asset(asset["id"])
        assert_surplus_asset(after)
        assert after["fair_market_value_cents"] == 1_000_000, (
            "1000000 cents at condition factor 1, age factor 1 and functional "
            f"factor 1 with no repair deduction, got {after['fair_market_value_cents']}"
        )
        assert after["condition_code"] == "C1"
        assert after["disposition_status"] == "ASSESSED"
        assert_version_incremented(after["version"], asset["version"])
        assert after["version"] == 2, (
            f"the asset's version must increment by 1, got {after['version']}"
        )

    def test_replaying_the_spent_asset_version_token_writes_nothing(self):
        """A stale `expected_asset_version` is refused and leaves no assessment row.

        "If that value does not equal the asset's current `version`, the request is
        rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412) and nothing is written."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_asset_version_refused_and_future_date_outranks_it
        """
        scenario = _submitted_turn_in_with_unappraised_furniture()
        asset_id = scenario["asset"]["id"]
        validate_success(
            api_client.create_condition_assessment(
                asset_id, _assessment_payload(1), ASSESSOR
            ),
            201,
        )

        replay = api_client.create_condition_assessment(
            asset_id, _assessment_payload(1, condition_code="C3"), ASSESSOR
        )
        validate_error(replay, ApiErrorId.ERR_STALE_ASSET_VERSION)

        rows, meta = validate_paginated(
            api_client.list_condition_assessments(asset_id, ASSESSOR)
        )
        assert meta["total_count"] == 1, (
            f"the refused replay must write nothing, got {meta['total_count']} rows"
        )
        assert rows[0]["condition_code"] == "C1"

        after = read_asset(asset_id)
        assert after["version"] == 2, (
            f"a refused write may not move the asset's version, got {after['version']}"
        )
        assert after["condition_code"] == "C1", (
            "the refused replay may not overturn the governing valuation"
        )
        assert after["fair_market_value_cents"] == 1_000_000

    def test_future_assessed_on_outranks_the_stale_version_refusal(self):
        """A request that is both future-dated and stale reports the future date.

        "When several rules could reject the same request, the **first** rule
        violated in the order below determines the response, and no later rule is
        evaluated."

        "10. Dates not in the future relative to the logical clock date —
        otherwise `ERR_FUTURE_DATE` (422). This rule guards exactly three
        operations: asset creation, condition-assessment recording and
        clearance-certificate filing."

        "14. Optimistic concurrency: `ERR_STALE_ASSET_VERSION` and
        `ERR_STALE_LOT_VERSION` (both 412)."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_asset_version_refused_and_future_date_outranks_it
        """
        scenario = _submitted_turn_in_with_unappraised_furniture()
        asset_id = scenario["asset"]["id"]
        validate_success(
            api_client.create_condition_assessment(
                asset_id, _assessment_payload(1), ASSESSOR
            ),
            201,
        )

        both_wrong = api_client.create_condition_assessment(
            asset_id,
            _assessment_payload(1, condition_code="C3", assessed_on="2026-09-01"),
            ASSESSOR,
        )
        validate_error(both_wrong, ApiErrorId.ERR_FUTURE_DATE)

        _, meta = validate_paginated(
            api_client.list_condition_assessments(asset_id, ASSESSOR)
        )
        assert meta["total_count"] == 1, "the refused request must write nothing"
        assert read_asset(asset_id)["version"] == 2

    def test_re_reading_the_asset_yields_a_token_that_supersedes(self):
        """A re-read version is accepted after the refusals and rewrites the valuation.

        "The protection is not decorative: a second assessment legitimately
        supersedes the first, so a writer holding a stale view of the asset would
        silently overturn a re-appraisal it never saw."

        "Every later assessment is a self-transition, `ASSESSED` to `ASSESSED`, and
        it is a genuine rewrite of the valuation rather than an append: the
        assessment that had been governing acquires `superseded` equal to true, and
        the asset's `condition_code` and `fair_market_value_cents` are recomputed
        from the new governing assessment."

        "Assessments for an asset are listed with the governing assessment first,
        ordered by `assessed_on` descending and then by `created_at` descending."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_asset_version_refused_and_future_date_outranks_it
        """
        scenario = _submitted_turn_in_with_unappraised_furniture()
        asset_id = scenario["asset"]["id"]
        first = validate_success(
            api_client.create_condition_assessment(
                asset_id, _assessment_payload(1), ASSESSOR
            ),
            201,
        )
        validate_error(
            api_client.create_condition_assessment(
                asset_id, _assessment_payload(1, condition_code="C3"), ASSESSOR
            ),
            ApiErrorId.ERR_STALE_ASSET_VERSION,
        )

        fresh_version = read_asset(asset_id)["version"]
        second = validate_success(
            api_client.create_condition_assessment(
                asset_id,
                _assessment_payload(
                    fresh_version, condition_code="C3", assessed_on="2026-07-20"
                ),
                ASSESSOR,
            ),
            201,
        )
        assert second["superseded"] is False

        after = read_asset(asset_id)
        assert after["condition_code"] == "C3", (
            "the later inspection date governs the valuation"
        )
        assert after["fair_market_value_cents"] == 700_000, (
            "1000000 cents at the C3 condition factor of seventy hundredths, got "
            f"{after['fair_market_value_cents']}"
        )
        assert after["version"] == 3, (
            f"a second accepted assessment lifts the asset to version 3, got {after['version']}"
        )

        rows, meta = validate_paginated(
            api_client.list_condition_assessments(asset_id, ASSESSOR)
        )
        assert meta["total_count"] == 2, "both assessments stay on file"
        assert rows[0]["id"] == second["id"], (
            "the governing assessment is listed first, by assessed_on descending"
        )
        assert rows[0]["superseded"] is False
        assert rows[1]["id"] == first["id"]
        assert rows[1]["superseded"] is True, (
            "the assessment that had been governing acquires superseded true"
        )

    def test_concurrent_assessments_on_one_token_leave_a_single_row(self):
        """Two racing writers holding the same token produce exactly one assessment.

        "If that value does not equal the asset's current `version`, the request is
        rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412) and nothing is written."

        "Either way the parent turn-in's `appraised_total_cents` is recomputed and
        the asset's `version` increments by 1."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_asset_version_refused_and_future_date_outranks_it
        """
        scenario = _submitted_turn_in_with_unappraised_furniture()
        asset_id = scenario["asset"]["id"]

        results = run_race(
            lambda: api_client.create_condition_assessment(
                asset_id,
                _assessment_payload(1, condition_code="C2", assessed_on="2026-07-16"),
                ASSESSOR,
            ),
            lambda: api_client.create_condition_assessment(
                asset_id,
                _assessment_payload(1, condition_code="C3", assessed_on="2026-07-16"),
                ASSESSOR,
            ),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        validate_error(outcome["failures"][0], ApiErrorId.ERR_STALE_ASSET_VERSION)

        _, meta = validate_paginated(
            api_client.list_condition_assessments(asset_id, ASSESSOR)
        )
        assert meta["total_count"] == 1, (
            f"only the winning writer may leave a row, got {meta['total_count']}"
        )

        after = read_asset(asset_id)
        assert after["version"] == 2, (
            "exactly one accepted write means exactly one version increment, got "
            f"{after['version']}"
        )
        assert after["condition_code"] in ("C2", "C3")
        expected = {"C2": 850_000, "C3": 700_000}[after["condition_code"]]
        assert after["fair_market_value_cents"] == expected, (
            "the valuation must match whichever assessment won, expected "
            f"{expected} for {after['condition_code']}"
        )


class TestProceedsDistributionOptimisticConcurrency:
    """`POST /proceeds-distributions` guarded by `expected_auction_lot_version`."""

    def test_stale_lot_version_outranks_the_unavailable_basis(self):
        """A stale token on a CASH request reports the stale version, not the basis.

        "Creating a proceeds distribution — `POST /proceeds-distributions` —
        requires a non-optional `expected_auction_lot_version` field carrying the
        client's last observed `version` of the referenced `AuctionLot`. A mismatch
        with the lot's current `version` is rejected with `ERR_STALE_LOT_VERSION`
        (HTTP 412)."

        "The checks run in a fixed order after the lot has been resolved. The
        stale-version check comes first, refusing with `ERR_STALE_LOT_VERSION`.
        Then the requested basis must be available: `ACCRUAL` requires the lot's
        `status` to be `CLOSED_MET` or `SETTLED`, while `CASH` requires that and
        additionally requires the lot's non-`VOIDED` `SaleInvoice` to be `PAID` or
        `DEFAULTED`; an unavailable basis is refused with
        `ERR_DISTRIBUTION_BASIS_UNAVAILABLE`."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_lot_version_refused_and_outranks_basis_availability
        """
        scenario = _closed_met_furniture_lot()
        lot = scenario["lot"]
        stale = scenario["lot_version_while_open"]
        assert lot["status"] == "CLOSED_MET"
        assert lot["version"] == stale + 1, (
            "closing the lot increments its version by 1, making the pre-close "
            f"token stale; got {lot['version']} against {stale}"
        )

        refused = api_client.create_proceeds_distribution(
            create_proceeds_distribution_payload(lot["id"], stale, basis="CASH"),
            FINANCE,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_LOT_VERSION)

        _, meta = validate_paginated(
            api_client.list_proceeds_distributions(
                FINANCE, params={"auction_lot_id": lot["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"a refused create must write nothing, got {meta['total_count']} rows"
        )
        assert read_lot(lot["id"])["version"] == lot["version"], (
            "a refused create may not move the lot's version"
        )

    def test_unresolvable_lot_reference_outranks_the_stale_lot_version(self):
        """A body foreign key that does not resolve is answered before the token check.

        "12. Every foreign key in the request body resolves, in entity
        field-declaration order — otherwise the matching 404 code."

        "The checks run in a fixed order after the lot has been resolved."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_lot_version_refused_and_outranks_basis_availability
        """
        scenario = _closed_met_furniture_lot()
        stale = scenario["lot_version_while_open"]

        refused = api_client.create_proceeds_distribution(
            create_proceeds_distribution_payload(
                NON_EXISTENT_UUID, stale, basis="CASH"
            ),
            FINANCE,
        )
        validate_error(refused, ApiErrorId.ERR_AUCTION_LOT_NOT_FOUND)

    def test_cash_basis_is_unavailable_while_the_invoice_is_still_issued(self):
        """A current token on a CASH request reaches the basis check and fails there.

        "Then the requested basis must be available: `ACCRUAL` requires the lot's
        `status` to be `CLOSED_MET` or `SETTLED`, while `CASH` requires that and
        additionally requires the lot's non-`VOIDED` `SaleInvoice` to be `PAID` or
        `DEFAULTED`; an unavailable basis is refused with
        `ERR_DISTRIBUTION_BASIS_UNAVAILABLE`."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_lot_version_refused_and_outranks_basis_availability
        """
        scenario = _closed_met_furniture_lot()
        lot = scenario["lot"]

        invoice = find_invoice_for_lot(lot["id"])
        assert invoice is not None, "closing with the reserve met issues an invoice"
        assert invoice["status"] == "ISSUED", (
            "an unpaid invoice leaves the cash basis unavailable"
        )

        refused = api_client.create_proceeds_distribution(
            create_proceeds_distribution_payload(
                lot["id"], lot["version"], basis="CASH"
            ),
            FINANCE,
        )
        validate_error(refused, ApiErrorId.ERR_DISTRIBUTION_BASIS_UNAVAILABLE)

    def test_current_lot_version_is_accepted_and_then_itself_goes_stale(self):
        """An accrual create with the current token succeeds and spends that token.

        "Under the `ACCRUAL` basis it is the price the lot achieved, the lot's
        `high_bid_cents`, whether or not the buyer ever paid a cent."

        "Creating it moves any earlier distribution for the same lot that is still
        `CALCULATED` to `SUPERSEDED`, so a lot never carries two live drafts, and —
        because the calculation reads the lot — the create also increments the
        `AuctionLot`'s `version` by 1, which means a second create against the same
        `expected_auction_lot_version` will be rejected as stale."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_lot_version_refused_and_outranks_basis_availability
        """
        scenario = _closed_met_furniture_lot()
        lot = scenario["lot"]
        token = lot["version"]

        created = validate_success(
            api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot["id"], token, basis="ACCRUAL"
                ),
                FINANCE,
            ),
            201,
        )
        assert_proceeds_distribution(created)
        assert created["status"] == "CALCULATED"
        assert created["basis"] == "ACCRUAL"
        assert created["distributable_base_cents"] == 20000, (
            "the accrual base is the lot's high_bid_cents of 20000, got "
            f"{created['distributable_base_cents']}"
        )
        assert created["service_fee_cents"] == 2500, (
            "20000 cents falls wholly in the first slice at twelve and a half "
            f"hundredths, got {created['service_fee_cents']}"
        )
        assert created["cost_recovery_cents"] == 0, (
            "furniture carries no verified clearance certificates"
        )
        assert created["net_to_agency_cents"] == 17500, (
            f"20000 less the 2500 fee, got {created['net_to_agency_cents']}"
        )
        assert_proceeds_net(created)
        assert created["beneficiary_agency_id"] == scenario["agency"]["id"], (
            "the beneficiary walks from the lot to the turning-in organisation"
        )

        after = read_lot(lot["id"])
        assert_version_incremented(after["version"], token)
        assert after["version"] == token + 1, (
            f"the create increments the lot's version by 1, got {after['version']}"
        )

        replay = api_client.create_proceeds_distribution(
            create_proceeds_distribution_payload(lot["id"], token, basis="ACCRUAL"),
            FINANCE,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_LOT_VERSION)

        rows, meta = validate_paginated(
            api_client.list_proceeds_distributions(
                FINANCE, params={"auction_lot_id": lot["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused replay must not add a draft, got {meta['total_count']}"
        )
        assert rows[0]["id"] == created["id"]

    def test_concurrent_distribution_creates_on_one_token_leave_one_draft(self):
        """Two racing creates on the same lot token yield exactly one distribution.

        "A mismatch with the lot's current `version` is rejected with
        `ERR_STALE_LOT_VERSION` (HTTP 412)."

        "Creating it moves any earlier distribution for the same lot that is still
        `CALCULATED` to `SUPERSEDED`, so a lot never carries two live drafts, and —
        because the calculation reads the lot — the create also increments the
        `AuctionLot`'s `version` by 1, which means a second create against the same
        `expected_auction_lot_version` will be rejected as stale."

        Design: Corner/cross_cutting_complexity_layers/ccl_stale_lot_version_refused_and_outranks_basis_availability
        """
        scenario = _closed_met_furniture_lot()
        lot = scenario["lot"]
        token = lot["version"]

        def create():
            return api_client.create_proceeds_distribution(
                create_proceeds_distribution_payload(
                    lot["id"], token, basis="ACCRUAL"
                ),
                FINANCE,
            )

        results = run_race(create, create)
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        validate_error(outcome["failures"][0], ApiErrorId.ERR_STALE_LOT_VERSION)

        rows, meta = validate_paginated(
            api_client.list_proceeds_distributions(
                FINANCE, params={"auction_lot_id": lot["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"exactly one draft may exist for the lot, got {meta['total_count']}"
        )
        assert rows[0]["status"] == "CALCULATED"
        assert rows[0]["net_to_agency_cents"] == 17500, (
            "the surviving draft nets 20000 less the 2500 service fee"
        )

        after = read_lot(lot["id"])
        assert after["version"] == token + 1, (
            "only the winning create may increment the lot's version, got "
            f"{after['version']}"
        )


class TestWinningBidSelectorSkipsRetractedBids:
    """A retracted top bid is invisible to the close-time candidate set."""

    @staticmethod
    def _lot_with_a_retracted_top_bid() -> dict:
        """One OPEN de-minimis lot carrying a 10000 bid from a standing bidder and a
        20000 bid from a bidder that is then debarred, which retracts its bid."""
        scenario = setup_lot_with_active_bid(
            bid_amount_cents=10_000, kind="furniture", route="de_minimis",
        )
        scenario["low_bidder"] = scenario["bidder"]
        scenario["low_bid"] = scenario["bid"]
        scenario["high_bidder"] = register_bidder(
            legal_name="Balcones Reclaim Co",
            email="desk@balconesreclaim.example",
        )
        scenario["high_bid"] = place_bid(
            scenario["lot"]["id"], scenario["high_bidder"]["id"], 20_000
        )
        scenario["high_bidder"] = get_success_data(
            api_client.set_bidder_status(
                scenario["high_bidder"]["id"], "DEBARRED", ADMIN
            )
        )
        scenario["lot"] = read_lot(scenario["lot"]["id"])
        return scenario

    def test_debarment_retracts_the_top_bid_without_closing_the_lot(self):
        """Debarring the leading bidder retracts its bid and leaves the lot OPEN.

        "Hop two, caused by hop one, moves every bid belonging to that bidder whose
        `status` is `ACTIVE` or `WINNING` to `RETRACTED`, processed in `created_at`
        ascending order, decrementing that bidder's `winning_lot_count` by 1 for
        each retracted winner."

        "The transitions from `PENDING` to `REGISTERED`, between `REGISTERED` and
        `SUSPENDED`, and a mere suspension all leave existing bids exactly as they
        stand; only debarment retracts them."

        Design: Corner/cross_cutting_complexity_layers/ccl_winning_bid_selector_skips_retracted_bids
        """
        scenario = self._lot_with_a_retracted_top_bid()

        assert scenario["high_bidder"]["status"] == "DEBARRED"
        assert scenario["high_bidder"]["winning_lot_count"] == 0, (
            "the retracted bid was never WINNING, so no decrement applies"
        )

        bids = {b["id"]: b for b in list_lot_bids(scenario["lot"]["id"])}
        assert bids[scenario["high_bid"]["id"]]["status"] == "RETRACTED", (
            "the debarred bidder's ACTIVE bid must move to RETRACTED"
        )
        assert bids[scenario["low_bid"]["id"]]["status"] == "ACTIVE", (
            "the other bidder's bid is untouched by someone else's debarment"
        )

        assert scenario["lot"]["status"] == "OPEN", (
            "no lot lost a WINNING bid, so no lot may be walked to CLOSED_NO_SALE"
        )
        assert find_invoice_for_lot(scenario["lot"]["id"]) is None, (
            "an invoice exists only once a bid has become WINNING"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "LISTED"

    def test_close_selects_the_surviving_bid_and_ignores_the_retracted_one(self):
        """The 20000 retracted bid is not a candidate, so the 10000 bid wins.

        "The close then evaluates the **winning-bid candidate set**: the lot's bids
        whose `status` is `ACTIVE` and whose `amount_cents` is at or above the lot's
        `reserve_price_cents`. Bids already `OUTBID` or `RETRACTED` are never
        candidates."

        "Hop two, caused by hop one, runs the winning-bid selector over the
        candidate set: the highest `amount_cents` wins; where two candidates tie on
        amount, the earlier `placed_at` wins; where they still tie, the earlier
        `created_at` wins."

        Design: Corner/cross_cutting_complexity_layers/ccl_winning_bid_selector_skips_retracted_bids
        """
        scenario = self._lot_with_a_retracted_top_bid()
        lot_id = scenario["lot"]["id"]
        assert scenario["lot"]["reserve_price_cents"] == 7524, (
            "sixty hundredths of the 12540-cent valuation, got "
            f"{scenario['lot']['reserve_price_cents']}"
        )

        set_clock(scenario["lot"]["closes_at"])
        closed = validate_success(api_client.close_auction_lot(lot_id, OFFICER))
        assert_auction_lot(closed)
        assert closed["status"] == "CLOSED_MET", (
            "the surviving 10000 bid clears the 7524 reserve"
        )

        bids = {b["id"]: b for b in list_lot_bids(lot_id)}
        assert bids[scenario["low_bid"]["id"]]["status"] == "WINNING", (
            "the only candidate must be selected even though a larger retracted "
            "bid exists on the lot"
        )
        assert bids[scenario["high_bid"]["id"]]["status"] == "RETRACTED", (
            "RETRACTED is terminal, so the outbid sweep may not touch it"
        )

        assert read_bidder(scenario["low_bidder"]["id"])["winning_lot_count"] == 1
        assert read_bidder(scenario["high_bidder"]["id"])["winning_lot_count"] == 0

    def test_close_re_derives_the_rollups_over_the_surviving_bid_only(self):
        """The re-derived roll-ups exclude the retracted bid from both figures.

        "The close also re-derives `high_bid_cents` and `bid_count` on the lot and
        recomputes the venue's `active_lot_count`, and increments both the lot's and
        the asset's `version` by 1."

        "An accepted bid is created in `status` `ACTIVE` with `placed_at` stamped
        from the logical clock, and it recomputes two roll-ups on the lot:
        `high_bid_cents` becomes the largest `amount_cents` among the lot's bids
        whose `status` is `ACTIVE` or `WINNING`, and 0 when that set is empty;
        `bid_count` becomes the number of the lot's bids whose `status` is `ACTIVE`,
        `WINNING` or `OUTBID`, which deliberately excludes retracted ones."

        Design: Corner/cross_cutting_complexity_layers/ccl_winning_bid_selector_skips_retracted_bids
        """
        scenario = self._lot_with_a_retracted_top_bid()
        lot_id = scenario["lot"]["id"]

        set_clock(scenario["lot"]["closes_at"])
        closed = validate_success(api_client.close_auction_lot(lot_id, OFFICER))

        bids = list_lot_bids(lot_id)
        assert_lot_rollups(closed, bids)
        assert closed["high_bid_cents"] == 10_000, (
            "the retracted 20000 bid is outside the ACTIVE-or-WINNING set, got "
            f"{closed['high_bid_cents']}"
        )
        assert closed["bid_count"] == 1, (
            f"retracted bids are not counted, got {closed['bid_count']}"
        )
        assert read_lot(lot_id)["high_bid_cents"] == 10_000, (
            "the re-derived roll-up must be readable on the next request"
        )

    def test_invoice_is_priced_from_the_surviving_bid(self):
        """The invoice is raised against the surviving bidder at 10000, not 20000.

        "Hop three, caused by hop two, follows from a bid having become `WINNING`: a
        `SaleInvoice` is created for that bidder in `status` `ISSUED`, carrying
        `auction_lot_id` and `bidder_id`, with `hammer_price_cents` equal to the
        winning bid's `amount_cents`, its money lines computed as described below,
        `amount_paid_cents` and `deposit_applied_cents` at 0, `default_reason` and
        `void_reason` null, and `due_at` set to `closed_at` plus a payment term of
        seven whole days."

        "The `buyer_premium_cents` is the `hammer_price_cents` multiplied by the
        venue's `buyer_premium_pct`, rounded half up to whole cents on its own."

        "The `sales_tax_cents` is the sum of `hammer_price_cents` and
        `buyer_premium_cents` multiplied by the venue's `sales_tax_pct`, again
        rounded half up on its own — the tax is charged on the premium-inclusive
        amount, not on the hammer price alone."

        Design: Corner/cross_cutting_complexity_layers/ccl_winning_bid_selector_skips_retracted_bids
        """
        scenario = self._lot_with_a_retracted_top_bid()
        lot_id = scenario["lot"]["id"]

        set_clock(scenario["lot"]["closes_at"])
        validate_success(api_client.close_auction_lot(lot_id, OFFICER))

        invoice = find_invoice_for_lot(lot_id)
        assert invoice is not None, "a CLOSED_MET lot carries an issued invoice"
        assert_sale_invoice(invoice)
        assert invoice["bidder_id"] == scenario["low_bidder"]["id"], (
            "the invoice belongs to the surviving bidder, not the debarred one"
        )
        assert invoice["status"] == "ISSUED"
        assert invoice["hammer_price_cents"] == 10_000, (
            f"the winning bid's amount, got {invoice['hammer_price_cents']}"
        )
        assert invoice["buyer_premium_cents"] == 1050, (
            "10000 at the venue's buyer premium, got "
            f"{invoice['buyer_premium_cents']}"
        )
        assert invoice["sales_tax_cents"] == 702, (
            "the premium-inclusive 11050 taxed and rounded half up on its own, got "
            f"{invoice['sales_tax_cents']}"
        )
        assert invoice["total_due_cents"] == 11752, (
            f"the exact sum of the three money lines, got {invoice['total_due_cents']}"
        )
        assert invoice["balance_due_cents"] == 11752
        assert invoice["due_at"][:19] == "2026-09-12T00:00:00", (
            "closed_at of 2026-09-05 plus a seven-day payment term, got "
            f"{invoice['due_at']}"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "SOLD"


class TestAssetListingPaginationAndFilters:
    """`GET /assets` window defaults, filter intersection and rejected bounds."""

    @staticmethod
    def _four_assets_across_two_turn_ins() -> dict:
        """Two DRAFT turn-ins for one organisation holding four assets created in a
        known order, so `created_at` ascending is a known sequence."""
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        first = create_draft_turn_in(agency["id"], custody_location="Austin Yard 4")
        second = create_draft_turn_in(agency["id"], custody_location="Bastrop Depot 2")

        a1 = add_asset_with_payload(
            agency["id"], create_asset_payload(first["id"])
        )
        a2 = add_asset_with_payload(
            agency["id"],
            create_asset_payload(
                first["id"],
                description="Conference table and chair set",
                acquisition_cost_cents=250_000,
                acquisition_date="2023-11-02",
            ),
        )
        a3 = add_asset_with_payload(
            agency["id"],
            create_vehicle_asset_payload(
                first["id"],
                description="2016 Chevrolet Tahoe patrol unit",
                acquisition_cost_cents=2_800_000,
                acquisition_date="2016-04-11",
                vin="1FTEW1EF0GFA12345",
                odometer_reading=168420,
                title_number="TX-9911-4472",
            ),
        )
        a4 = add_asset_with_payload(
            agency["id"],
            create_it_asset_payload(
                second["id"],
                description="Rack-mounted storage array",
                acquisition_cost_cents=900_000,
                acquisition_date="2021-09-15",
                is_data_bearing=True,
            ),
        )
        return {
            "agency": agency,
            "turn_in_one": first,
            "turn_in_two": second,
            "order": [a1["id"], a2["id"], a3["id"], a4["id"]],
        }

    def test_omitted_pagination_uses_the_documented_defaults(self):
        """An unparameterised listing returns limit 10, offset 0 and every row.

        "`limit` caps the number of rows returned; it defaults to 10 when omitted,
        its minimum accepted value is 1 and its maximum is 100."

        "`offset` is the number of rows to skip and defaults to 0; its minimum
        accepted value is 0."

        "List responses populate four pagination fields inside the envelope's `meta`
        object: `limit`, `offset`, `total_count` and `has_more`."

        "Unless a specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/cross_cutting_complexity_layers/ccl_asset_list_pagination_defaults_filters_and_invalid_bounds
        """
        setup = self._four_assets_across_two_turn_ins()

        rows, meta = validate_paginated(api_client.list_assets(OFFICER))
        assert meta["limit"] == 10, f"limit defaults to 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"
        assert meta["total_count"] == 4, f"four assets exist, got {meta['total_count']}"
        assert meta["has_more"] is False, (
            "all four rows fit inside the default window"
        )
        assert len(rows) == 4
        assert [r["id"] for r in rows] == setup["order"], (
            "assets must be ordered by created_at ascending"
        )
        for row in rows:
            assert_surplus_asset(row)

    def test_total_count_ignores_the_window_and_has_more_reports_the_remainder(self):
        """A narrowed window reports the unwindowed total and a truthful has_more.

        "`total_count` is the number of rows matching the filters before the window
        is applied, and `has_more` is true when rows remain beyond the returned
        window."

        Design: Corner/cross_cutting_complexity_layers/ccl_asset_list_pagination_defaults_filters_and_invalid_bounds
        """
        setup = self._four_assets_across_two_turn_ins()

        rows, meta = validate_paginated(
            api_client.list_assets(OFFICER, params={"limit": 2})
        )
        assert len(rows) == 2, f"the window caps the rows at 2, got {len(rows)}"
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 4, (
            f"the total is counted before the window, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, "two rows remain beyond this window"
        assert [r["id"] for r in rows] == setup["order"][:2]

        rows, meta = validate_paginated(
            api_client.list_assets(OFFICER, params={"limit": 2, "offset": 3})
        )
        assert len(rows) == 1, (
            f"only one row survives an offset of 3 over four rows, got {len(rows)}"
        )
        assert rows[0]["id"] == setup["order"][3]
        assert meta["total_count"] == 4
        assert meta["has_more"] is False, "nothing remains beyond the last row"

    def test_offset_past_the_end_returns_an_empty_window_not_an_error(self):
        """An offset equal to the row count is a legal empty window.

        "`offset` is the number of rows to skip and defaults to 0; its minimum
        accepted value is 0."

        "`total_count` is the number of rows matching the filters before the window
        is applied, and `has_more` is true when rows remain beyond the returned
        window."

        Design: Corner/cross_cutting_complexity_layers/ccl_asset_list_pagination_defaults_filters_and_invalid_bounds
        """
        self._four_assets_across_two_turn_ins()

        rows, meta = validate_paginated(
            api_client.list_assets(OFFICER, params={"limit": 2, "offset": 4})
        )
        assert rows == [], f"the window starts past the last row, got {rows}"
        assert meta["offset"] == 4
        assert meta["total_count"] == 4, (
            f"the unwindowed total is unaffected, got {meta['total_count']}"
        )
        assert meta["has_more"] is False

    def test_filters_intersect_and_are_counted_before_the_window(self):
        """`turn_in_id`, `category` and `disposition_status` narrow the same listing.

        "Asset listings may be narrowed by `turn_in_id`, by `component_of_asset_id`,
        by `category`, by `disposition_status` or by `clearance_status`."

        "`total_count` is the number of rows matching the filters before the window
        is applied, and `has_more` is true when rows remain beyond the returned
        window."

        Design: Corner/cross_cutting_complexity_layers/ccl_asset_list_pagination_defaults_filters_and_invalid_bounds
        """
        setup = self._four_assets_across_two_turn_ins()

        rows, meta = validate_paginated(
            api_client.list_assets(
                OFFICER, params={"turn_in_id": setup["turn_in_two"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"only one asset sits on the second turn-in, got {meta['total_count']}"
        )
        assert [r["id"] for r in rows] == [setup["order"][3]]

        rows, meta = validate_paginated(
            api_client.list_assets(
                OFFICER,
                params={
                    "turn_in_id": setup["turn_in_one"]["id"],
                    "category": "VEHICLE",
                },
            )
        )
        assert meta["total_count"] == 1, (
            "the two filters intersect rather than union, got "
            f"{meta['total_count']}"
        )
        assert [r["id"] for r in rows] == [setup["order"][2]]

        rows, meta = validate_paginated(
            api_client.list_assets(
                OFFICER, params={"category": "VEHICLE", "disposition_status": "SOLD"}
            )
        )
        assert rows == [], (
            "no asset has left INTAKE, so the intersection is empty"
        )
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        rows, meta = validate_paginated(
            api_client.list_assets(
                OFFICER, params={"disposition_status": "INTAKE"}
            )
        )
        assert meta["total_count"] == 4, (
            "every asset created without an assessment stays at INTAKE"
        )

    @pytest.mark.parametrize(
        "params, label",
        [
            ({"limit": 0}, "a limit below the minimum of 1"),
            ({"limit": 101}, "a limit above the maximum of 100"),
            ({"offset": -1}, "a negative offset"),
        ],
    )
    def test_out_of_range_pagination_is_refused(self, params, label):
        """Bounds outside the permitted ranges are rejected, not clamped.

        "A `limit` outside the range 1 through 100 inclusive, or a negative
        `offset`, or a non-integer value for either, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        "8. `limit` and `offset` within their permitted ranges on list endpoints —
        otherwise `ERR_INVALID_PAGINATION` (400)."

        Design: Corner/cross_cutting_complexity_layers/ccl_asset_list_pagination_defaults_filters_and_invalid_bounds
        """
        self._four_assets_across_two_turn_ins()

        refused = api_client.list_assets(OFFICER, params=params)
        error = validate_error(refused, ApiErrorId.ERR_INVALID_PAGINATION)
        assert error["error_id"] == "ERR_INVALID_PAGINATION", (
            f"{label} must be rejected outright rather than clamped"
        )

    def test_boundary_pagination_values_are_accepted(self):
        """The inclusive edges of the permitted ranges are legal.

        "`limit` caps the number of rows returned; it defaults to 10 when omitted,
        its minimum accepted value is 1 and its maximum is 100."

        "`offset` is the number of rows to skip and defaults to 0; its minimum
        accepted value is 0."

        Design: Corner/cross_cutting_complexity_layers/ccl_asset_list_pagination_defaults_filters_and_invalid_bounds
        """
        setup = self._four_assets_across_two_turn_ins()

        rows, meta = validate_paginated(
            api_client.list_assets(OFFICER, params={"limit": 1, "offset": 0})
        )
        assert meta["limit"] == 1 and meta["offset"] == 0
        assert [r["id"] for r in rows] == [setup["order"][0]]
        assert meta["has_more"] is True

        rows, meta = validate_paginated(
            api_client.list_assets(OFFICER, params={"limit": 100})
        )
        assert meta["limit"] == 100, "100 is the inclusive maximum"
        assert len(rows) == 4
        assert meta["has_more"] is False
