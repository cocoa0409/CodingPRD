"""The daily NAV strike, its finalization, and the pricing-error correction workflow."""

from test_helpers import (
    ApiErrorId,
    assert_nav_record,
    assert_pricing_error_case,
    assert_pricing_fields_cleared,
    assess_case,
    approve_case,
    create_nav_record_payload,
    create_pricing_error_case_payload,
    create_share_class,
    ledger_entries_for_trade,
    make_accountant_headers,
    money,
    open_case,
    position_for,
    price,
    read_case,
    read_nav_record,
    read_registration,
    read_share_class,
    read_trade,
    setup_assessed_boundary_cases,
    setup_finalized_nav_for_case,
    setup_five_link_cascade,
    setup_reference_data,
    setup_trade_awaiting_nav_under_review,
    setup_two_dated_settled_purchases,
    shares,
    strike_nav,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    NO_LOAD_BREAKPOINT_TIERS,
    SINGLE_TIER_BREAKPOINT_TIERS,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestNavStrike:
    def test_a_class_with_no_shares_strikes_at_its_seed_price(self, api):
        """PRD §3.3: "The strike itself is mechanical. At the moment of the call the
        class's live `total_shares_outstanding` is captured into
        `shares_outstanding_snapshot`. If that snapshot is exactly `0.000` — the class has
        no shares on the transfer agent's books — then `nav_per_share` is set to the class's
        configured `seed_nav_per_share`."
        PRD §3.3: "The record also carries `original_nav_per_share`, which stays null for
        the record's whole ordinary life."

        Design: Corner/calculations/nav_strike_falls_back_to_the_seed_when_no_shares_are_outstanding
        """
        base = setup_reference_data(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            with_registration=False,
            class_overrides={"class_code": "B", "seed_nav_per_share": 12.5000},
        )
        response = api.create_nav_record(
            create_nav_record_payload(
                base["share_class"]["id"],
                valuation_date=MONDAY,
                total_net_assets=250000.00,
            ),
            ACCOUNTANT,
        )
        record = validate_success(response, 201)
        assert_nav_record(record)
        assert record["shares_outstanding_snapshot"] == shares(0.000)
        assert record["nav_per_share"] == price(12.5000)
        assert record["status"] == "PRELIMINARY"
        assert record.get("original_nav_per_share") is None

    def test_a_second_strike_on_the_same_class_and_date_is_refused(self, api):
        """PRD §3.3: "At most one record may exist per share class and valuation date; a
        second attempt at the same pair is refused with `ERR_NAV_DATE_DUPLICATE`."

        Design: Corner/validations/duplicate_nav_valuation_date_returns_nav_date_duplicate
        """
        base = setup_reference_data(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
        )
        other_class = create_share_class(
            base["fund"]["id"], class_code="I", seed_nav_per_share=15.0000,
            breakpoint_tiers=list(NO_LOAD_BREAKPOINT_TIERS),
        )
        strike_nav(base["share_class"]["id"], MONDAY, 0.00, finalize=False)

        duplicate = api.create_nav_record(
            create_nav_record_payload(
                base["share_class"]["id"], valuation_date=MONDAY, total_net_assets=100.00
            ),
            ACCOUNTANT,
        )
        assert duplicate.status_code == 409
        validate_error(duplicate, ApiErrorId.ERR_NAV_DATE_DUPLICATE.value)

        other = validate_success(
            api.create_nav_record(
                create_nav_record_payload(
                    other_class["id"], valuation_date=MONDAY, total_net_assets=0.00
                ),
                ACCOUNTANT,
            ),
            201,
        )
        assert other["nav_per_share"] == price(15.0000)

        _, meta = validate_paginated(
            api.list_share_class_nav_records(base["share_class"]["id"], ACCOUNTANT)
        )
        assert meta["total_count"] == 1

    def test_finalizing_an_already_final_record_is_refused(self, api):
        """PRD §3.3: "Finalizing a preliminary strike is a `FundAccountant` action that
        moves it `PRELIMINARY → FINAL`, stamps `finalized_at` with the current logical clock
        instant, and increments the record's `version`."
        PRD §3.3: "Only a record that is currently `PRELIMINARY` may be finalized; anything
        else answers `ERR_INVALID_NAV_STATE`."

        Design: Corner/state_machines/finalize_an_already_final_nav_record_returns_invalid_nav_state
        """
        base = setup_reference_data(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
        )
        record = strike_nav(base["share_class"]["id"], MONDAY, 0.00, finalize=True)

        response = api.finalize_nav_record(record["id"], ACCOUNTANT)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_NAV_STATE.value)

        after = read_nav_record(record["id"])
        assert after["status"] == "FINAL"
        assert after["version"] == record["version"]


class TestMaterialityBoundary:
    def test_exactly_fifty_basis_points_is_material(self, api):
        """PRD §3.9: "`error_bps` is the absolute difference between the corrected NAV and
        the original NAV, divided by the original NAV, multiplied by ten thousand to express
        it in basis points, and rounded half-up to two decimal places."
        PRD §3.9: "`materiality` is then `MATERIAL` when `error_bps` is greater than or
        equal to fifty basis points — half of one percent — and `IMMATERIAL` when it is
        strictly below fifty. The comparison is inclusive at the boundary: an error of
        exactly `50.00` basis points is `MATERIAL`."

        Design: Difficulty/boundary_precision_check/materiality_threshold_is_inclusive_at_exactly_fifty_basis_points
        """
        setup = setup_assessed_boundary_cases()
        assert setup["material_nav"]["nav_per_share"] == price(11.0000)

        assessed = validate_success(
            api.assess_pricing_error_case(
                setup["material_case"]["id"], make_accountant_headers("fa-1")
            ),
            200,
        )
        assert_pricing_error_case(assessed)
        assert assessed["error_bps"] == money(50.00)
        assert assessed["materiality"] == "MATERIAL"
        assert assessed["status"] == "ASSESSED"

    def test_one_ten_thousandth_below_the_threshold_is_immaterial(self, api):
        """PRD §3.9: "`error_bps` is the absolute difference between the corrected NAV and
        the original NAV, divided by the original NAV, multiplied by ten thousand to express
        it in basis points, and rounded half-up to two decimal places."
        PRD §3.9: "`materiality` is then `MATERIAL` when `error_bps` is greater than or
        equal to fifty basis points — half of one percent — and `IMMATERIAL` when it is
        strictly below fifty. The comparison is inclusive at the boundary: an error of
        exactly `50.00` basis points is `MATERIAL`."

        Design: Difficulty/boundary_precision_check/materiality_threshold_is_inclusive_at_exactly_fifty_basis_points
        """
        setup = setup_assessed_boundary_cases()
        assert setup["immaterial_nav"]["nav_per_share"] == price(11.0000)

        assessed = validate_success(
            api.assess_pricing_error_case(
                setup["immaterial_case"]["id"], make_accountant_headers("fa-1")
            ),
            200,
        )
        assert assessed["error_bps"] == money(49.09)
        assert assessed["materiality"] == "IMMATERIAL"

    def test_closing_a_material_case_as_immaterial_is_refused(self, api):
        """PRD §3.9: "The immaterial branch closes the case out. It requires `materiality`
        to be `IMMATERIAL`, moves the case `ASSESSED → IMMATERIAL_CLOSED`, and stamps
        `approved_by_user_id` from the officer's `X-User-ID`."
        PRD §3.9: "Neither branch may be taken from a case that is not `ASSESSED`, and
        neither may be taken against the wrong determination; both mistakes answer
        `ERR_INVALID_CASE_STATE`."

        Design: Difficulty/boundary_precision_check/materiality_threshold_is_inclusive_at_exactly_fifty_basis_points
        """
        setup = setup_assessed_boundary_cases()
        assess_case(setup["material_case"]["id"])

        response = api.close_immaterial_pricing_error_case(
            setup["material_case"]["id"], COMPLIANCE
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)

        after = read_case(setup["material_case"]["id"])
        assert after["status"] == "ASSESSED"

    def test_approving_a_correction_on_an_immaterial_case_is_refused(self, api):
        """PRD §3.9: "The material branch merely authorizes the sweep. It requires
        `materiality` to be `MATERIAL`, moves the case `ASSESSED → MATERIAL_APPROVED`, and
        stamps `approved_by_user_id` from the officer's `X-User-ID`."
        PRD §3.9: "Neither branch may be taken from a case that is not `ASSESSED`, and
        neither may be taken against the wrong determination; both mistakes answer
        `ERR_INVALID_CASE_STATE`."

        Design: Corner/state_machines/approve_correction_on_an_immaterial_case_returns_invalid_case_state
        """
        ref = setup_finalized_nav_for_case()
        case = open_case(
            ref["nav"], 11.0100, error_reason="Rounding difference on an accrual"
        )
        assessed = assess_case(case["id"])
        assert assessed["error_bps"] == money(9.09)
        assert assessed["materiality"] == "IMMATERIAL"

        response = api.approve_correction_pricing_error_case(case["id"], COMPLIANCE)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)

        assert read_case(case["id"])["status"] == "ASSESSED"
        assert read_nav_record(ref["nav"]["id"])["status"] == "UNDER_ERROR_REVIEW"


class TestCorrectionBranches:
    def test_the_immaterial_branch_corrects_the_price_without_restating_anything(self, api):
        """PRD §3.9: "On the pricing side it returns the NAV record
        `UNDER_ERROR_REVIEW → FINAL`: the record's `original_nav_per_share` is set to the
        `nav_per_share` that was in force, `nav_per_share` is replaced by the case's
        `corrected_nav_per_share` so that the price applies from here forward, and the
        record's `version` increments."
        PRD §3.9: "Crucially, nothing is restated — no already-settled trade is touched, no
        position moves, no share balance changes."

        Design: Difficulty/non_linear_state_machine/pricing_error_case_forks_into_disjoint_immaterial_and_material_effects
        """
        setup = setup_two_dated_settled_purchases()

        case = open_case(
            setup["nav_monday"], 10.0450, error_reason="Stale bond pricing on 08-03"
        )
        assessed = assess_case(case["id"])
        assert assessed["error_bps"] == money(45.00)
        assert assessed["materiality"] == "IMMATERIAL"

        closed = validate_success(
            api.close_immaterial_pricing_error_case(case["id"], COMPLIANCE), 200
        )
        assert closed["status"] == "IMMATERIAL_CLOSED"
        assert closed["restated_trade_count"] == 0

        record = read_nav_record(setup["nav_monday"]["id"])
        assert record["status"] == "FINAL"
        assert record["nav_per_share"] == price(10.0450)
        assert record["original_nav_per_share"] == price(10.0000)

        untouched = read_trade(setup["monday_trade"]["id"])
        assert untouched["execution_status"] == "PRICED_FINAL"
        assert untouched["shares_transacted"] == shares(5730.000)
        assert untouched.get("restated_share_delta") is None

    def test_the_material_branch_corrects_the_price_and_restates_the_settled_trade(self, api):
        """PRD §3.9: "The NAV record moves `UNDER_ERROR_REVIEW → CORRECTED`. Its
        `original_nav_per_share` preserves the price that was in force and its
        `nav_per_share` is replaced by the case's `corrected_nav_per_share`; its `version`
        increments."
        PRD §3.9: "Each such order has its `nav_per_share_applied` replaced by the corrected
        NAV, its `shares_transacted` recomputed at that corrected NAV under the same pricing
        rules that produced it originally, and its `restated_share_delta` written as the new
        `shares_transacted` minus the previous one. The case's `restated_trade_count` records
        how many orders were restated."
        PRD §3.9: "Because those share quantities changed, one ledger entry with an
        `entry_reason` of `NAV_CORRECTION_RESTATEMENT` is appended per restated order, each
        position's `shares` moves by that order's `restated_share_delta`, and the class's
        `total_shares_outstanding` moves by the total of those deltas."

        Design: Difficulty/non_linear_state_machine/pricing_error_case_forks_into_disjoint_immaterial_and_material_effects
        """
        setup = setup_two_dated_settled_purchases()

        case = open_case(
            setup["nav_tuesday"], 11.0600,
            error_reason="Missed corporate action on 08-04",
        )
        assessed = assess_case(case["id"])
        assert assessed["error_bps"] == money(54.55)
        assert assessed["materiality"] == "MATERIAL"

        approve_case(case["id"])
        reprocessed = validate_success(
            api.reprocess_pricing_error_case(
                case["id"], make_accountant_headers("fa-2")
            ),
            200,
        )
        assert reprocessed["status"] == "REPROCESSED"
        assert reprocessed["restated_trade_count"] == 1

        record = read_nav_record(setup["nav_tuesday"]["id"])
        assert record["status"] == "CORRECTED"
        assert record["nav_per_share"] == price(11.0600)

        restated = read_trade(setup["tuesday_trade"]["id"])
        assert restated["execution_status"] == "RESTATED"
        assert restated["shares_transacted"] == shares(1874.774)
        assert restated["restated_share_delta"] == shares(-10.226)

        assert read_share_class(setup["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(7604.774)


class TestReprocessingCascade:
    def test_the_correction_restates_the_settled_trade_and_moves_the_share_balance(self, api):
        """PRD §3.9: "Because that price changed, every order with a `settlement_status` of
        `SETTLED` that was priced on that record — that is, whose `trade_date` equals the
        corrected record's `valuation_date` and whose `share_class_id` equals that record's
        `share_class_id` — moves `PRICED_FINAL → RESTATED`."
        PRD §3.9: "Because those share quantities changed, one ledger entry with an
        `entry_reason` of `NAV_CORRECTION_RESTATEMENT` is appended per restated order, each
        position's `shares` moves by that order's `restated_share_delta`, and the class's
        `total_shares_outstanding` moves by the total of those deltas."

        Design: Difficulty/transitive_cascade/material_reprocess_drives_five_link_chain_to_provisional_trade_rollback
        """
        setup = setup_five_link_cascade()

        reprocessed = validate_success(
            api.reprocess_pricing_error_case(
                setup["case"]["id"], make_accountant_headers("fa-2")
            ),
            200,
        )
        assert reprocessed["status"] == "REPROCESSED"
        assert reprocessed["error_bps"] == money(50.00)
        assert reprocessed["materiality"] == "MATERIAL"
        assert reprocessed["restated_trade_count"] == 1

        record = read_nav_record(setup["nav_tuesday"]["id"])
        assert record["status"] == "CORRECTED"
        assert record["nav_per_share"] == price(11.0550)
        assert record["original_nav_per_share"] == price(11.0000)

        restated = read_trade(setup["tuesday_trade"]["id"])
        assert restated["execution_status"] == "RESTATED"
        assert restated["shares_transacted"] == shares(1875.622)
        assert restated["restated_share_delta"] == shares(-9.378)

        entries = [
            entry
            for entry in ledger_entries_for_trade(setup["tuesday_trade"]["id"])
            if entry["entry_reason"] == "NAV_CORRECTION_RESTATEMENT"
        ]
        assert len(entries) == 1
        assert entries[0]["share_delta"] == shares(-9.378)
        assert entries[0]["resulting_share_balance"] == shares(1875.622)

        position = position_for(
            setup["tuesday_account"]["id"], setup["share_class"]["id"]
        )
        assert position["shares"] == shares(1875.622)
        assert read_share_class(setup["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(7605.622)

    def test_the_moved_balance_invalidates_later_strikes_and_rolls_back_provisional_orders(self, api):
        """PRD §3.9: "Because the class's share balance changed underneath every later
        strike, every NAV record of that same class whose `valuation_date` is strictly later
        than the corrected record's `valuation_date` and whose `status` is `PRELIMINARY`
        moves `PRELIMINARY → STALE_REPRICE_REQUIRED`, with its `version` incremented. The
        case's `invalidated_nav_record_count` records how many records were invalidated."
        PRD §3.9: "Because those NAV records were invalidated, every order priced against
        one of them whose `execution_status` is `PRICED_PROVISIONAL` falls back
        `PRICED_PROVISIONAL → RECEIVED`, and its pricing fields — `pricing_variant`,
        `nav_per_share_applied`, `sales_load_pct`, `sales_load_amount`,
        `net_invested_amount`, `shares_transacted`, `roa_qualifying_amount` and
        `roa_basis_variant` — are all cleared back to null, so the order must be priced again
        once its NAV record has been re-struck and finalized."

        Design: Difficulty/transitive_cascade/material_reprocess_drives_five_link_chain_to_provisional_trade_rollback
        """
        setup = setup_five_link_cascade()
        assert setup["provisional_trade"]["execution_status"] == "PRICED_PROVISIONAL"
        assert setup["provisional_trade"]["shares_transacted"] == shares(856.818)

        reprocessed = validate_success(
            api.reprocess_pricing_error_case(
                setup["case"]["id"], make_accountant_headers("fa-2")
            ),
            200,
        )
        assert reprocessed["invalidated_nav_record_count"] == 1

        stale = read_nav_record(setup["nav_wednesday"]["id"])
        assert stale["status"] == "STALE_REPRICE_REQUIRED"

        rolled_back = read_trade(setup["provisional_trade"]["id"])
        assert rolled_back["execution_status"] == "RECEIVED"
        assert_pricing_fields_cleared(rolled_back)

        untouched = read_trade(setup["monday_trade"]["id"])
        assert untouched["execution_status"] == "PRICED_FINAL"
        assert untouched["shares_transacted"] == shares(5730.000)


class TestPricingAgainstAnImpairedNavRecord:
    def test_pricing_against_a_record_under_error_review_is_refused(self, api):
        """PRD §3.5: "If a required record exists but is `UNDER_ERROR_REVIEW` or
        `STALE_REPRICE_REQUIRED`, pricing is refused with `ERR_NAV_NOT_FINAL` — an order may
        not be priced against a NAV whose correctness is in question or whose share base has
        been invalidated."
        PRD §3.9: "Opening captures the record's current `nav_per_share` into the case's
        `original_nav_per_share`, stamps `detected_by_user_id` from the caller's
        `X-User-ID`, creates the case in `DETECTED` with `error_bps` and `materiality` both
        null, `restated_trade_count` and `invalidated_nav_record_count` both 0, and
        `approved_by_user_id` and `reprocessed_by_user_id` null, and drives the NAV record
        `FINAL → UNDER_ERROR_REVIEW`, incrementing that record's `version`."

        Design: Difficulty/cross_entity_state_dependency/trade_pricing_depends_on_nav_record_not_being_under_error_review
        """
        setup = setup_trade_awaiting_nav_under_review()
        assert setup["nav"]["status"] == "UNDER_ERROR_REVIEW"

        response = api.price_trade(setup["trade"]["id"], OPERATOR)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_NAV_NOT_FINAL.value)

    def test_the_refused_pricing_call_leaves_the_order_and_its_reservation_untouched(self, api):
        """PRD §3.5: "If a required record exists but is `UNDER_ERROR_REVIEW` or
        `STALE_REPRICE_REQUIRED`, pricing is refused with `ERR_NAV_NOT_FINAL` — an order may
        not be priced against a NAV whose correctness is in question or whose share base has
        been invalidated."
        PRD §3.4: "For a `PURCHASE`, the order's `gross_amount` must be less than or equal
        to that registration's `remaining_amount` — equality is accepted and drives the
        registration straight to `EXHAUSTED` — and an amount above it is refused with
        `ERR_BLUE_SKY_CAPACITY_EXCEEDED`; on success `reserved_amount` increases by
        `gross_amount`."

        Design: Difficulty/cross_entity_state_dependency/trade_pricing_depends_on_nav_record_not_being_under_error_review
        """
        setup = setup_trade_awaiting_nav_under_review()
        api.price_trade(setup["trade"]["id"], OPERATOR)

        after = read_trade(setup["trade"]["id"])
        assert after["execution_status"] == "RECEIVED"
        assert after.get("pricing_variant") is None
        assert after.get("shares_transacted") is None

        registration = read_registration(setup["registration"]["id"])
        assert registration["reserved_amount"] == money(30000.00), (
            "a failed pricing call must not disturb the capture-time reservation"
        )


class TestPricingErrorCaseVersionGate:
    def test_a_stale_nav_version_blocks_a_second_case_on_the_same_record(self, api):
        """PRD §2.8: "Opening a pricing error case — `POST /pricing-error-cases` — requires
        `expected_nav_record_version` in the request body, likewise a required field,
        carrying the `version` of the target `NavRecord` as the client last observed it. If
        that value does not equal the record's current `version`, the request is rejected
        with `ERR_STALE_NAV_RECORD_VERSION` and HTTP 412."
        PRD §2.7: "And because version gating (rule 8) sits ahead of every business rule, a
        caller holding a stale view of an account or a NAV record learns that first, before
        any domain-specific complaint."

        Design: Corner/cross_cutting_complexity_layers/stale_nav_record_version_blocks_a_second_pricing_error_case
        """
        ref = setup_finalized_nav_for_case()
        stale_version = ref["nav"]["version"]
        first = open_case(
            ref["nav"], 11.0600, error_reason="First look at the mispricing"
        )

        response = api.create_pricing_error_case(
            create_pricing_error_case_payload(
                ref["nav"]["id"], 11.0900, stale_version,
                error_reason="Second look with a stale view",
            ),
            make_accountant_headers("fa-2"),
        )
        assert response.status_code == 412
        validate_error(response, ApiErrorId.ERR_STALE_NAV_RECORD_VERSION.value)

        assert read_case(first["id"])["status"] == "DETECTED"
        _, meta = validate_paginated(
            api.list_pricing_error_cases(
                ACCOUNTANT, params={"nav_record_id": ref["nav"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert read_nav_record(ref["nav"]["id"])["status"] == "UNDER_ERROR_REVIEW"
