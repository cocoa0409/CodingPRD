"""Merger control: the two valuation variants, the determination ladder they
feed, the filing gate and the waiting period that ends the file.
"""
from test_helpers import (
    COUNSEL, UNKNOWN_UUID, ApiErrorId, assert_hsr_analysis, assert_instant_equals,
    assert_transaction, clear_transaction, create_hsr_analysis_payload,
    file_transaction, read_hsr_analysis, read_transaction, register_business_unit,
    register_transaction, run_hsr_analysis, set_clock, transaction_version,
    validate_error, validate_error_is_one_of, validate_paginated, validate_success,
)


def test_signed_deal_variant_lands_below_the_notification_threshold(api):
    """PRD §3.7: "Under `SIGNED_DEAL` it is `deal_value_cents` plus
    `assumed_liabilities_cents`; under `MARKET_VALUE` it is
    `market_valuation_cents` plus `assumed_liabilities_cents`. Either way the
    result is stored in `size_of_transaction_cents` as integer cents with no
    rounding of any kind."
    PRD §3.7: "Otherwise, if the size of the transaction is **strictly below**
    120 million dollars — that is, strictly below 12,000,000,000 cents — the
    determination is `BELOW_THRESHOLD` and `filing_required` is false."
    PRD §3.7: "The transaction's status is then re-derived from the outcome: a
    `filing_required` of true drives it to `ANALYZED`, and false drives it to
    `EXEMPT`, in each case incrementing the transaction's `version` by 1."

    Design: Difficulty/dual_variant_calc/hsr_valuation_variant_divergence_on_transaction
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Kelmar Coatings BV",
        deal_value_cents=11_000_000_000, assumed_liabilities_cents=100_000_000,
        market_valuation_cents=13_000_000_000)

    data = validate_success(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"], transaction["version"],
                                    "SIGNED_DEAL"),
        COUNSEL), 201)

    assert_hsr_analysis(data)
    assert data["size_of_transaction_cents"] == 11_100_000_000
    assert data["determination"] == "BELOW_THRESHOLD"
    assert data["filing_required"] is False
    assert read_transaction(transaction["id"])["status"] == "EXEMPT"


def test_market_value_variant_supersedes_and_requires_a_filing(api):
    """PRD §3.7: "The analysis records the acting counsel in
    `analyzed_by_user_id` and opens in `ACTIVE`; any prior `ACTIVE` analysis for
    the same transaction moves to the terminal `SUPERSEDED`, so exactly one
    analysis is ever operative."
    PRD §3.7: "Because the two variants differ only in the consideration term,
    the very same transaction row can land on opposite sides of the reporting
    threshold depending on which valuation counsel runs."
    PRD §3.7: "That re-derivation is legal from `DRAFT`, from `ANALYZED` and
    from `EXEMPT`, so re-analysis under a different variant may cycle a
    transaction `EXEMPT → ANALYZED → EXEMPT` as often as counsel needs; the
    `ACTIVE` analysis is always the transaction's operative determination."

    Design: Difficulty/dual_variant_calc/hsr_valuation_variant_divergence_on_transaction
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Kelmar Coatings BV",
        deal_value_cents=11_000_000_000, assumed_liabilities_cents=100_000_000,
        market_valuation_cents=13_000_000_000)
    signed = run_hsr_analysis(transaction["id"], "SIGNED_DEAL",
                              expected_version=transaction["version"])

    market = validate_success(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"],
                                    transaction_version(transaction["id"]),
                                    "MARKET_VALUE"),
        COUNSEL), 201)

    assert market["size_of_transaction_cents"] == 13_100_000_000
    assert market["determination"] == "FILING_REQUIRED"
    assert market["filing_required"] is True
    assert market["status"] == "ACTIVE"
    assert read_hsr_analysis(signed["id"])["status"] == "SUPERSEDED"
    assert read_transaction(transaction["id"])["status"] == "ANALYZED"


def test_size_exactly_at_the_threshold_is_not_below_threshold(api):
    """PRD §3.7: "Otherwise, if the size of the transaction is **strictly
    below** 120 million dollars — that is, strictly below 12,000,000,000 cents —
    the determination is `BELOW_THRESHOLD` and `filing_required` is false. A
    size exactly equal to that figure is *not* below threshold and falls through
    to the clauses beneath."
    PRD §3.7: "If the larger is at least 480 million dollars (48,000,000,000
    cents) **and** the smaller is at least 48 million dollars (4,800,000,000
    cents), the determination is `FILING_REQUIRED` and `filing_required` is
    true."

    Design: Difficulty/boundary_precision_check/hsr_size_exactly_at_threshold_is_not_below_threshold
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Exactly At Threshold BV",
        deal_value_cents=11_900_000_000, assumed_liabilities_cents=100_000_000,
        market_valuation_cents=11_900_000_000,
        acquirer_total_assets_cents=50_000_000_000,
        target_total_assets_cents=5_000_000_000)

    data = validate_success(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"], transaction["version"],
                                    "SIGNED_DEAL"),
        COUNSEL), 201)

    assert data["size_of_transaction_cents"] == 12_000_000_000
    assert data["determination"] == "FILING_REQUIRED"
    assert data["filing_required"] is True
    assert read_transaction(transaction["id"])["status"] == "ANALYZED"


def test_one_cent_under_the_threshold_is_below_threshold(api):
    """PRD §3.7: "Otherwise, if the size of the transaction is **strictly
    below** 120 million dollars — that is, strictly below 12,000,000,000 cents —
    the determination is `BELOW_THRESHOLD` and `filing_required` is false."
    PRD §3.7: "The transaction's status is then re-derived from the outcome: a
    `filing_required` of true drives it to `ANALYZED`, and false drives it to
    `EXEMPT`, in each case incrementing the transaction's `version` by 1."

    Design: Difficulty/boundary_precision_check/hsr_size_exactly_at_threshold_is_not_below_threshold
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="One Cent Below BV",
        deal_value_cents=11_899_999_999, assumed_liabilities_cents=100_000_000,
        market_valuation_cents=11_899_999_999,
        acquirer_total_assets_cents=50_000_000_000,
        target_total_assets_cents=5_000_000_000)

    data = validate_success(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"], transaction["version"],
                                    "SIGNED_DEAL"),
        COUNSEL), 201)

    assert data["size_of_transaction_cents"] == 11_999_999_999
    assert data["determination"] == "BELOW_THRESHOLD"
    assert data["filing_required"] is False
    assert read_transaction(transaction["id"])["status"] == "EXEMPT"


def test_exemption_code_short_circuits_the_determination_ladder(api):
    """PRD §3.7: "If the `exemption_code` is anything other than `NONE`, the
    determination is `EXEMPT` and `filing_required` is false. An exempt
    transaction is never sized against any threshold."
    PRD §3.7: "The `determination` then follows a ladder evaluated strictly top
    to bottom, with the first match winning:"

    Design: Corner/calculations/hsr_exemption_code_short_circuits_the_determination_ladder
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Ordinary Course Assets",
        deal_value_cents=60_000_000_000, assumed_liabilities_cents=0,
        market_valuation_cents=60_000_000_000,
        exemption_code="ORDINARY_COURSE")

    data = validate_success(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"], transaction["version"],
                                    "SIGNED_DEAL"),
        COUNSEL), 201)

    assert data["size_of_transaction_cents"] == 60_000_000_000
    assert data["determination"] == "EXEMPT"
    assert data["filing_required"] is False
    assert read_transaction(transaction["id"])["status"] == "EXEMPT"


def test_size_of_person_test_fails_one_cent_under_the_smaller_floor(api):
    """PRD §3.7: "Otherwise the size sits in the band from the lower threshold
    up to but not including the upper figure, and the size-of-person test
    decides. Take the larger of `acquirer_total_assets_cents` and
    `target_total_assets_cents`, and the smaller of the two. If the larger is at
    least 480 million dollars (48,000,000,000 cents) **and** the smaller is at
    least 48 million dollars (4,800,000,000 cents), the determination is
    `FILING_REQUIRED` and `filing_required` is true. Otherwise the determination
    is `SIZE_OF_PERSON_NOT_MET` and `filing_required` is false."

    Design: Corner/calculations/hsr_size_of_person_test_not_met_between_the_two_thresholds
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="One Cent Short BV",
        deal_value_cents=12_000_000_000, assumed_liabilities_cents=0,
        market_valuation_cents=12_000_000_000,
        acquirer_total_assets_cents=50_000_000_000,
        target_total_assets_cents=4_799_999_999)

    data = validate_success(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"], transaction["version"],
                                    "SIGNED_DEAL"),
        COUNSEL), 201)

    assert data["size_of_transaction_cents"] == 12_000_000_000
    assert data["determination"] == "SIZE_OF_PERSON_NOT_MET"
    assert data["filing_required"] is False
    assert read_transaction(transaction["id"])["status"] == "EXEMPT"


def test_filing_a_transaction_that_has_never_been_analysed_is_refused(api):
    """PRD §3.7: "Filing is counsel's next act and is legal only from
    `ANALYZED`, and only when the transaction's `ACTIVE` analysis carries
    `filing_required` of true; anything else is refused with
    `ERR_TRANSACTION_NOT_ANALYZED`."
    PRD §3.7: "The transaction opens in `DRAFT` at `version` 1 and may be listed
    filtered by acquiring unit and `status`."

    Design: Corner/state_machines/transaction_filing_from_draft_is_rejected_before_any_analysis
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Unanalysed BV",
        deal_value_cents=20_000_000_000, assumed_liabilities_cents=0,
        market_valuation_cents=20_000_000_000)
    assert_transaction(transaction)
    assert transaction["status"] == "DRAFT"
    assert transaction["version"] == 1

    resp = api.file_transaction(transaction["id"], COUNSEL)

    # PRD names ERR_TRANSACTION_NOT_ANALYZED for this refusal in §3.7 and at
    # ladder rung 13, while rung 10 ("the target resource is in a state from
    # which the requested transition is declared") sits at a higher priority and
    # would report ERR_INVALID_STATE for a DRAFT transaction. The PRD admits
    # both readings, so either code is accepted.
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_TRANSACTION_NOT_ANALYZED.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])
    assert resp.status_code == 409
    assert read_transaction(transaction["id"])["status"] == "DRAFT"


def test_waiting_period_clearance_is_inclusive_at_its_boundary_instant(api):
    """PRD §3.7: "Filing moves the transaction to `FILED`, stamps `filed_at`
    with the current logical clock, sets `waiting_period_end` to `filed_at`
    advanced by 30 days, and increments `version` by 1. Recording clearance
    moves `FILED → CLEARED`, which is terminal, and increments `version` by 1 —
    but only once the logical clock has reached `waiting_period_end`. An early
    attempt is refused with `ERR_WAITING_PERIOD_ACTIVE`; the comparison is
    inclusive, so the clock standing exactly at `waiting_period_end` is enough."

    Design: Corner/calculations/hsr_waiting_period_clearance_allowed_at_the_exact_boundary_instant
    """
    set_clock("2026-08-01T00:00:00Z")
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Waiting Period BV",
        deal_value_cents=60_000_000_000, assumed_liabilities_cents=0,
        market_valuation_cents=60_000_000_000)
    run_hsr_analysis(transaction["id"], "SIGNED_DEAL",
                     expected_version=transaction["version"])
    filed = file_transaction(transaction["id"])
    assert_instant_equals(filed["waiting_period_end"], "2026-08-31T00:00:00.000Z",
                          "Transaction.waiting_period_end")

    set_clock("2026-08-30T23:59:00Z")
    early = api.clear_transaction(transaction["id"], COUNSEL)
    validate_error(early, ApiErrorId.ERR_WAITING_PERIOD_ACTIVE.value)
    assert early.status_code == 409

    set_clock("2026-08-31T00:00:00Z")
    cleared = validate_success(api.clear_transaction(transaction["id"], COUNSEL))
    assert cleared["status"] == "CLEARED"


def test_cleared_transaction_is_terminal_and_refuses_a_second_filing(api):
    """PRD §3.7: "Recording clearance moves `FILED → CLEARED`, which is
    terminal, and increments `version` by 1 — but only once the logical clock
    has reached `waiting_period_end`."
    PRD §3.7: "Filing is counsel's next act and is legal only from `ANALYZED`,
    and only when the transaction's `ACTIVE` analysis carries `filing_required`
    of true; anything else is refused with `ERR_TRANSACTION_NOT_ANALYZED`."
    PRD §3.7: "Filing moves the transaction to `FILED`, stamps `filed_at` with
    the current logical clock, sets `waiting_period_end` to `filed_at` advanced
    by 30 days, and increments `version` by 1."

    Design: Corner/state_machines/transaction_cleared_state_is_terminal_and_refuses_refiling
    """
    set_clock("2026-08-01T00:00:00Z")
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Big Target BV",
        deal_value_cents=60_000_000_000, assumed_liabilities_cents=0,
        market_valuation_cents=60_000_000_000)
    analysis = run_hsr_analysis(transaction["id"], "SIGNED_DEAL",
                                expected_version=transaction["version"])
    assert analysis["size_of_transaction_cents"] == 60_000_000_000
    assert analysis["determination"] == "FILING_REQUIRED"

    filed = file_transaction(transaction["id"])
    assert_instant_equals(filed["filed_at"], "2026-08-01T00:00:00.000Z",
                          "Transaction.filed_at")
    assert_instant_equals(filed["waiting_period_end"], "2026-08-31T00:00:00.000Z",
                          "Transaction.waiting_period_end")
    set_clock("2026-08-31T00:00:00Z")
    clear_transaction(transaction["id"])

    resp = api.file_transaction(transaction["id"], COUNSEL)
    # CLEARED is terminal: PRD rung 10 says ERR_INVALID_STATE "covers every
    # attempt from a terminal state", while §3.7 says "anything else is refused
    # with ERR_TRANSACTION_NOT_ANALYZED". Either code is accepted.
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_TRANSACTION_NOT_ANALYZED.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])
    assert resp.status_code == 409
    assert read_transaction(transaction["id"])["status"] == "CLEARED"


def test_second_analysis_carrying_the_stale_transaction_version_is_refused(api):
    """PRD §2.6: "A `POST /compliance/hsr-analyses` request must carry
    `expected_transaction_version` as a required, non-optional field whose value
    is the `version` the client last observed on the target transaction."
    PRD §2.6: "A mismatch with the transaction's current `version` is rejected
    with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_transaction_version_on_hsr_analysis_returns_412
    """
    set_clock()
    unit = register_business_unit()
    transaction = register_transaction(
        unit["id"], target_name="Kelmar Coatings BV",
        deal_value_cents=11_000_000_000, assumed_liabilities_cents=100_000_000,
        market_valuation_cents=13_000_000_000)
    stale_version = transaction["version"]

    first = validate_success(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"], stale_version,
                                    "SIGNED_DEAL"),
        COUNSEL), 201)
    assert first["determination"] == "BELOW_THRESHOLD"

    second = api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction["id"], stale_version,
                                    "MARKET_VALUE"),
        COUNSEL)
    validate_error(second, ApiErrorId.ERR_STALE_VERSION.value)
    assert second.status_code == 412

    assert read_hsr_analysis(first["id"])["status"] == "ACTIVE"
    assert read_transaction(transaction["id"])["status"] == "EXEMPT"
    _rows, meta = validate_paginated(api.list_hsr_analyses(
        COUNSEL, params={"transaction_id": transaction["id"]}))
    assert meta["total_count"] == 1


def test_unknown_hsr_analysis_id_returns_its_own_not_found_code(api):
    """PRD §2.7: "The not-found codes referenced at rungs 5 and 6 are
    entity-specific: `ERR_BUSINESS_UNIT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_CURRICULUM_NOT_FOUND`, `ERR_TRAINING_ASSIGNMENT_NOT_FOUND`,
    `ERR_ASSOCIATION_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`,
    `ERR_MEETING_NOT_FOUND`, `ERR_ATTENDANCE_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`,
    `ERR_TRANSACTION_NOT_FOUND`, `ERR_HSR_ANALYSIS_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_DRILL_NOT_FOUND`,
    `ERR_DOCUMENT_AUDIT_NOT_FOUND`, `ERR_LENIENCY_APPLICATION_NOT_FOUND`, and
    `ERR_RISK_ASSESSMENT_NOT_FOUND`."

    Design: Corner/errors/hsr_analysis_get_with_unknown_uuid_returns_not_found
    """
    set_clock()

    resp = api.get_hsr_analysis(UNKNOWN_UUID, COUNSEL)

    validate_error(resp, ApiErrorId.ERR_HSR_ANALYSIS_NOT_FOUND.value)
    assert resp.status_code == 404
