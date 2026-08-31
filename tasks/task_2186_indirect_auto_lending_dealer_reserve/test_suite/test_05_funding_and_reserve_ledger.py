"""Funding, dealer participation, the volume incentive, and the reserve ledger."""
from test_helpers import (
    ADMIN, ANALYST, ANALYST_USER_ID, FUNDER, FUNDER_USER_ID, ApiErrorId,
    BASE_REQUIRED_DOC_TYPES, CLOCK_START, api_client, assert_contract,
    assert_ledger_balance_matches_entries, assert_reserve_entry, dealer_version,
    make_funding_specialist_headers, post_reserve_adjustment, read_contract,
    read_dealer, set_clock, setup_booked_contract, setup_docs_verified_contract,
    setup_funded_contract, setup_program, validate_error, validate_paginated,
    validate_success, verify_document,
)


def test_rate_participation_accrues_the_scheduled_yield_over_the_full_term(api):
    """PRD 3.5: "Under a pinned `participation_method` of `RATE_PARTICIPATION`, the
    gross participation is `amount_financed_cents`, multiplied by the eligible markup
    expressed as a fraction of ten thousand, multiplied by a number of basis months
    divided by twelve, multiplied by the participation factor of 0.55 — and the
    result is rounded half up to whole cents **exactly once, at the very end**, with
    every intermediate product carried at full precision."
    PRD 3.5: "The **scheduled-yield** variant, which runs at funding, uses the
    contract's full `term_months`; it values the participation over the whole
    scheduled term and it is the figure actually posted to the ledger."
    PRD 3.5: "`dealer_proceeds_cents` is computed once here as
    `amount_financed_cents`, less `acquisition_fee_cents`, plus
    `reserve_accrued_cents`, plus `incentive_accrued_cents` — what the dealership is
    actually paid."

    Design: Difficulty/dual_variant_calc/reserve_scheduled_yield_vs_earned_to_date_on_contract
    """
    program = setup_program()
    ready = setup_docs_verified_contract(program, doc_prefix="IMG-k1")

    response = api.fund_contract(
        ready["contract"]["id"], {"funding_date": CLOCK_START}, FUNDER
    )
    contract = validate_success(response, 200)
    assert_contract(contract)

    assert contract["reserve_accrued_cents"] == 154055
    assert contract["incentive_accrued_cents"] == 7003
    assert contract["dealer_proceeds_cents"] == 2801000 - 15000 + 154055 + 7003
    assert contract["unpaid_principal_cents"] == 2801000
    assert contract["funding_status"] == "FUNDED"
    assert contract["reserve_status"] == "ACCRUED"
    assert contract["funded_by_user_id"] == FUNDER_USER_ID

    dealer = read_dealer(program["dealer_id"])
    assert dealer["reserve_balance_cents"] == 161058
    assert dealer["outstanding_principal_cents"] == 2801000
    assert dealer["funded_contract_count"] == 1
    assert dealer["total_funded_ever_count"] == 1


def test_flat_fee_participation_takes_the_agreement_cap(api):
    """PRD 3.5: "Under a pinned `participation_method` of `FLAT_FEE`, the gross
    participation is instead the smaller of the agreement's `flat_fee_cap_cents` and
    `amount_financed_cents` multiplied by 150 basis points expressed as a fraction of
    ten thousand, that product rounded half up to whole cents."
    PRD 3.5: "Separately, a volume incentive accrues on every funded contract
    regardless of participation method."

    Design: Corner/calculations/flat_fee_participation_variant_caps_reserve_at_agreement_cap
    """
    program = setup_program(
        agreement_overrides={
            "participation_method": "FLAT_FEE", "flat_fee_cap_cents": 30000,
        }
    )
    ready = setup_docs_verified_contract(program, doc_prefix="IMG-ff")

    contract = validate_success(
        api.fund_contract(ready["contract"]["id"], {"funding_date": CLOCK_START}, FUNDER),
        200,
    )
    assert contract["reserve_accrued_cents"] == 30000
    assert contract["incentive_accrued_cents"] == 7003
    assert contract["dealer_proceeds_cents"] == 2823003
    assert contract["reserve_status"] == "ACCRUED"
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 37003


def test_participation_is_clamped_by_the_program_reserve_cap(api):
    """PRD 3.5: "Whichever branch applies, `reserve_accrued_cents` is the smaller of
    that gross figure and the program reserve cap of 250,000 cents — no single
    contract may accrue more than two thousand five hundred dollars of participation."
    PRD 3.5: "`incentive_accrued_cents` is the smaller of 15,000 cents and
    `amount_financed_cents` multiplied by 25 basis points expressed as a fraction of
    ten thousand, that product rounded half up to whole cents"

    Design: Corner/calculations/reserve_program_cap_clamps_large_participation
    """
    program = setup_program()
    ready = setup_docs_verified_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-cap", "monthly_income_cents": 900000,
            "monthly_debt_cents": 200000, "amount_financed_cents": 5000000,
            "collateral_value_cents": 5000000, "term_months": 72,
        },
        doc_prefix="IMG-cap",
    )
    assert ready["application"]["assigned_tier_code"] == "T1"
    assert ready["application"]["demotion_count"] == 0

    contract = validate_success(
        api.fund_contract(ready["contract"]["id"], {"funding_date": CLOCK_START}, FUNDER),
        200,
    )
    assert contract["reserve_accrued_cents"] == 250000
    assert contract["incentive_accrued_cents"] == 12500
    assert contract["dealer_proceeds_cents"] == 5247500

    dealer = read_dealer(program["dealer_id"])
    assert dealer["reserve_balance_cents"] == 262500
    assert dealer["outstanding_principal_cents"] == 5000000


def test_funding_posts_two_accrual_entries_in_order(api):
    """PRD 3.5: "Two ledger entries are posted, **in this order**: first a
    `PARTICIPATION_ACCRUAL` entry crediting `reserve_accrued_cents`, then an
    `INCENTIVE_ACCRUAL` entry crediting `incentive_accrued_cents`."
    PRD 3.5: "Each names the dealership's `dealer_id` and this `contract_id`,
    carries a signed `amount_cents`, and stamps `balance_after_cents` with the
    dealership's `reserve_balance_cents` as it stood immediately after that entry was
    applied — so reading the two entries back shows the balance stepping twice, not
    once."
    PRD 3.5: "The ledger as a whole can be read and narrowed by `dealer_id`, by
    `contract_id`, and by `entry_type`, in `created_at` ascending order — the order in
    which the entries were actually posted."

    Design: Corner/entities/reserve_entry_readable_by_id_and_by_contract_filter
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-re")
    contract_id = funded["contract"]["id"]

    entries, meta = validate_paginated(
        api.list_reserve_entries(ADMIN, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == 2
    for entry in entries:
        assert_reserve_entry(entry)

    assert entries[0]["entry_type"] == "PARTICIPATION_ACCRUAL"
    assert entries[0]["amount_cents"] == 154055
    assert entries[0]["balance_after_cents"] == 154055
    assert entries[1]["entry_type"] == "INCENTIVE_ACCRUAL"
    assert entries[1]["amount_cents"] == 7003
    assert entries[1]["balance_after_cents"] == 161058

    single = validate_success(api.get_reserve_entry(entries[0]["id"], ADMIN), 200)
    assert single["id"] == entries[0]["id"]
    assert single["contract_id"] == contract_id
    assert single["dealer_id"] == program["dealer_id"]


def test_the_decisioning_operator_may_not_release_the_funds(api):
    """PRD 2.10: "The `X-User-ID` of the `FundingSpecialist` releasing funds must
    differ from the `decisioned_by_user_id` recorded on the application the contract
    was booked from. When they are equal, the funding is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD 3.5: "On a successful funding the contract records `funded_at` as the
    supplied `funding_date` and `funded_by_user_id` as the acting `X-User-ID`"

    Design: Corner/validations/segregation_of_duties_blocks_decisioner_from_funding
    """
    program = setup_program()
    ready = setup_docs_verified_contract(program, doc_prefix="IMG-so")
    contract_id = ready["contract"]["id"]
    assert ready["application"]["decisioned_by_user_id"] == ANALYST_USER_ID

    conflicted = make_funding_specialist_headers(ANALYST_USER_ID)
    validate_error(
        api.fund_contract(contract_id, {"funding_date": CLOCK_START}, conflicted),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409,
    )

    contract = validate_success(
        api.fund_contract(contract_id, {"funding_date": CLOCK_START}, FUNDER), 200
    )
    assert contract["funding_status"] == "FUNDED"
    assert contract["funded_by_user_id"] == FUNDER_USER_ID
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 161058


def test_funding_more_than_thirty_days_after_the_decision_is_refused(api):
    """PRD 3.5: "The supplied `funding_date` must fall no more than 30 days after
    the application's `decisioned_at`, and must also be at or after the contract's
    `contract_date`; either failure is `ERR_FUNDING_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/validations/funding_after_thirty_day_window_returns_funding_window_expired
    """
    program = setup_program()
    ready = setup_docs_verified_contract(program, doc_prefix="IMG-fw")
    set_clock("2026-09-15T00:00:00Z")

    response = api.fund_contract(
        ready["contract"]["id"], {"funding_date": "2026-09-15T00:00:00Z"}, FUNDER
    )
    validate_error(response, ApiErrorId.ERR_FUNDING_WINDOW_EXPIRED.value, 422)

    contract = read_contract(ready["contract"]["id"])
    assert contract["funding_status"] == "DOCS_VERIFIED"
    assert contract["funded_at"] is None
    dealer = read_dealer(program["dealer_id"])
    assert dealer["total_funded_ever_count"] == 0
    assert dealer["reserve_balance_cents"] == 0


def test_incomplete_documents_are_reported_before_the_funding_line(api):
    """PRD 3.5: "A `FundingSpecialist` supplies a single input — the `funding_date`
    — and the platform runs six checks before any of it happens, in this order. The
    contract's `funding_status` must be `DOCS_VERIFIED`, meaning every type in
    `required_doc_types` has a document in `VERIFIED`; otherwise
    `ERR_DOCS_NOT_VERIFIED` (HTTP 409)."
    PRD 3.5: "And the dealership's current `outstanding_principal_cents` plus this
    contract's `amount_financed_cents` must be at or below its `funding_line_cents`;
    exceeding the line is `ERR_DEALER_FUNDING_LINE_EXCEEDED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/fund_docs_state_beats_funding_line_fiscal
    """
    program = setup_program(dealer_overrides={"funding_line_cents": 1000000})
    booked = setup_booked_contract(program, doc_prefix="IMG-cf")
    contract_id = booked["contract"]["id"]
    assert booked["contract"]["amount_financed_cents"] == 2801000

    verify_document(booked["documents"]["RETAIL_INSTALLMENT_CONTRACT"]["id"])
    assert read_contract(contract_id)["funding_status"] == "PENDING_DOCS"

    response = api.fund_contract(contract_id, {"funding_date": CLOCK_START}, FUNDER)
    error = validate_error(response, ApiErrorId.ERR_DOCS_NOT_VERIFIED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_DEALER_FUNDING_LINE_EXCEEDED.value


def test_the_funding_line_breach_surfaces_once_the_package_is_complete(api):
    """PRD 3.5: "And the dealership's current `outstanding_principal_cents` plus
    this contract's `amount_financed_cents` must be at or below its
    `funding_line_cents`; exceeding the line is `ERR_DEALER_FUNDING_LINE_EXCEEDED`
    (HTTP 409)."
    PRD 3.4: "when that verification brings every type in `required_doc_types` to
    `VERIFIED`, the contract advances `PENDING_DOCS → DOCS_VERIFIED`"

    Design: Difficulty/priority_pair_validation_conflict/fund_docs_state_beats_funding_line_fiscal
    """
    program = setup_program(dealer_overrides={"funding_line_cents": 1000000})
    booked = setup_booked_contract(program, doc_prefix="IMG-cf2")
    contract_id = booked["contract"]["id"]
    for document in booked["documents"].values():
        verify_document(document["id"])
    assert read_contract(contract_id)["funding_status"] == "DOCS_VERIFIED"

    response = api.fund_contract(contract_id, {"funding_date": CLOCK_START}, FUNDER)
    validate_error(response, ApiErrorId.ERR_DEALER_FUNDING_LINE_EXCEEDED.value, 409)

    contract = read_contract(contract_id)
    assert contract["funding_status"] == "DOCS_VERIFIED"
    assert contract["funded_at"] is None
    dealer = read_dealer(program["dealer_id"])
    assert dealer["reserve_balance_cents"] == 0
    assert dealer["total_funded_ever_count"] == 0


def test_manual_adjustment_may_not_drive_the_reserve_below_zero(api):
    """PRD 3.5: "An adjustment that would drive `reserve_balance_cents` below zero
    is refused with `ERR_RESERVE_BALANCE_NEGATIVE` (HTTP 409)."
    PRD 2.11: "A manual reserve adjustment must not drive `reserve_balance_cents`
    below zero, and neither may a fair-lending remediation posting; either attempt is
    refused with `ERR_RESERVE_BALANCE_NEGATIVE` (HTTP 409)."

    Design: Corner/validations/reserve_adjustment_below_zero_returns_reserve_balance_negative
    """
    program = setup_program()
    version = dealer_version(program["dealer_id"])

    response = api.create_reserve_adjustment(
        program["dealer_id"],
        {"amount_cents": -1000, "reason": "CORRECTION", "expected_dealer_version": version},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_RESERVE_BALANCE_NEGATIVE.value, 409)

    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 0
    _, meta = validate_paginated(
        api.list_reserve_entries(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 0


def test_repeating_an_adjustment_from_one_reading_of_the_version_is_rejected(api):
    """PRD 2.6: "Posting a manual reserve adjustment
    (`POST /lending/dealers/{id}/reserve-adjustments`) is guarded identically: the
    request body must carry a non-optional `expected_dealer_version` matching the
    dealership's current `version`, and a mismatch is rejected with
    `ERR_STALE_DEALER_VERSION` (HTTP 412)."
    PRD 3.5: "The resulting entry has `entry_type` `MANUAL_ADJUSTMENT` and a null
    `contract_id`, because it belongs to the dealership rather than to any single
    deal; `balance_after_cents` is stamped, `reserve_balance_cents` is recomputed, and
    `Dealer.version` advances by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_dealer_version_rejects_repeat_reserve_adjustment
    """
    program = setup_program()
    observed_version = dealer_version(program["dealer_id"])
    payload = {
        "amount_cents": 50000,
        "reason": "OPENING_RESERVE_BALANCE",
        "expected_dealer_version": observed_version,
    }

    first = validate_success(
        api.create_reserve_adjustment(program["dealer_id"], dict(payload), ADMIN), 201
    )
    assert_reserve_entry(first)
    assert first["entry_type"] == "MANUAL_ADJUSTMENT"
    assert first["contract_id"] is None
    assert first["balance_after_cents"] == 50000

    validate_error(
        api.create_reserve_adjustment(program["dealer_id"], dict(payload), ADMIN),
        ApiErrorId.ERR_STALE_DEALER_VERSION.value, 412,
    )

    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 50000
    _, meta = validate_paginated(
        api.list_reserve_entries(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 1


def test_reserve_balance_reconciles_with_the_whole_ledger(api):
    """PRD 2.8: "`reserve_balance_cents` is the signed sum of `amount_cents` across
    every ledger entry whose `dealer_id` is this dealership's, taken over all entry
    types, and it is recomputed on every ledger posting."
    PRD 2.8: "`outstanding_principal_cents` is the sum of `unpaid_principal_cents`
    across this dealership's contracts whose `funding_status` is `FUNDED`, using each
    contract's currently persisted value"

    Design: Corner/cross_cutting_complexity_layers/derived_reserve_balance_matches_ledger_sum_after_mixed_postings
    """
    program = setup_program()
    post_reserve_adjustment(program["dealer_id"], 50000)
    setup_funded_contract(program, doc_prefix="IMG-dr")

    entries, meta = validate_paginated(
        api.list_reserve_entries(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 3
    assert entries[0]["entry_type"] == "MANUAL_ADJUSTMENT"
    assert entries[0]["amount_cents"] == 50000
    assert entries[0]["balance_after_cents"] == 50000
    assert entries[1]["entry_type"] == "PARTICIPATION_ACCRUAL"
    assert entries[1]["amount_cents"] == 154055
    assert entries[1]["balance_after_cents"] == 204055
    assert entries[2]["entry_type"] == "INCENTIVE_ACCRUAL"
    assert entries[2]["amount_cents"] == 7003
    assert entries[2]["balance_after_cents"] == 211058

    dealer = read_dealer(program["dealer_id"])
    assert dealer["reserve_balance_cents"] == 211058
    assert_ledger_balance_matches_entries(dealer, entries)
    assert dealer["outstanding_principal_cents"] == 2801000
    assert dealer["funded_contract_count"] == 1
