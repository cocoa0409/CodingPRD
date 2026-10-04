"""Judgment collection: payment/reversal conservation, suspension gates,
asset-trace reinstatement, and fiscal bounds."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_judgment_balance_invariants,
    create_judgment_payload,
    create_payment_payload,
    get_fund,
    get_judgment,
    get_success_data,
    make_company_representative_headers,
    record_asset_trace,
    record_payment,
    reinstate_judgment,
    setup_judgment_with_fund,
    setup_suspended_judgment,
    suspend_judgment,
    validate_error,
)

_COMMISSIONER = TEST_USERS["commissioner_headers"]


def test_judgment_payment_and_reversal_conserve_principal_balance():
    """PRD section 3.5: "Each accepted payment adds to (or, for a reversal,
    subtracts from) `collected_cents` — which always equals the sum of
    collection payments minus the sum of reversals — and `outstanding_cents`
    is recomputed as `amount_cents` minus `collected_cents`."
    PRD section 3.5: "The linked fund's `total_collected_cents` is synced to
    the judgment's `collected_cents` on every payment and reversal, and the
    judgment's `version` increments each time."

    Design: Difficulty/compensating_invariant/judgment_payment_and_reversal_conserve_principal_balance
    """
    bundle = setup_judgment_with_fund(judgment_amount_cents=3_000_000)
    judgment_id = bundle["judgment"]["id"]
    fund_id = bundle["fund"]["id"]
    company_id = bundle["company"]["id"]

    collected = record_payment(judgment_id, company_id, 2_000_000, kind="COLLECTION")
    assert collected["collected_cents"] == 2_000_000
    assert collected["outstanding_cents"] == 1_000_000
    assert collected["collection_status"] == "PARTIALLY_COLLECTED"

    reversed_ = record_payment(judgment_id, company_id, 500_000, kind="REVERSAL")
    assert reversed_["collected_cents"] == 1_500_000, (
        "the compensating reversal must conserve principal coverage"
    )
    assert reversed_["outstanding_cents"] == 1_500_000
    assert reversed_["collection_status"] == "PARTIALLY_COLLECTED"

    judgment = get_judgment(judgment_id)
    assert_judgment_balance_invariants(judgment)

    fund = get_fund(fund_id)
    assert fund["total_collected_cents"] == 1_500_000, "ledger must sync through the reversal"
    assert fund["status"] == "OPEN_FOR_CLAIMS", (
        "the fund opened when the collection first crossed the minimum and never re-closes"
    )


def test_suspended_overpayment_state_error_beats_fiscal_error():
    """PRD section 3.5: "while `suspension_status` is `SUSPENDED`, no payment
    or reversal is accepted at all, and the attempt is rejected with
    `ERR_JUDGMENT_SUSPENDED`."
    PRD section 2.8: "When several checks could fail, the one at the lowest
    priority number fires first and determines the error the client sees;
    later checks are not evaluated."

    Design: Difficulty/priority_pair_validation_conflict/suspended_overpayment_state_error_beats_fiscal_error
    """
    bundle = setup_suspended_judgment(
        sworn_total_assets_cents=100_000, judgment_amount_cents=3_000_000
    )
    judgment_id = bundle["judgment"]["id"]
    company_id = bundle["company"]["id"]

    # 4,000,000 also exceeds the 3,000,000 outstanding — but the tier-5 state
    # rule must beat the tier-14 fiscal rule.
    resp = api_client.create_payment(
        judgment_id,
        create_payment_payload(amount_cents=4_000_000, kind="COLLECTION"),
        make_company_representative_headers(company_id),
    )
    validate_error(resp, ApiErrorId.ERR_JUDGMENT_SUSPENDED)

    judgment = get_judgment(judgment_id)
    assert judgment["collected_cents"] == 0
    assert judgment["collection_status"] == "OUTSTANDING"
    assert judgment["suspension_status"] == "SUSPENDED"


def test_judgment_second_entry_on_same_order_rejected():
    """PRD section 3.5: "An order carries at most one judgment; a second entry
    attempt fails with `ERR_JUDGMENT_ALREADY_EXISTS`."

    Design: Corner/validations/judgment_second_entry_on_same_order_rejected
    """
    bundle = setup_judgment_with_fund(judgment_amount_cents=3_000_000)
    order_id = bundle["order"]["id"]

    resp = api_client.create_judgment(
        order_id, create_judgment_payload(amount_cents=1_000_000), _COMMISSIONER
    )
    validate_error(resp, ApiErrorId.ERR_JUDGMENT_ALREADY_EXISTS)

    judgments = get_success_data(api_client.get_order_judgment(order_id, _COMMISSIONER))
    assert len(judgments) == 1
    assert judgments[0]["amount_cents"] == 3_000_000


def test_payment_above_outstanding_rejected():
    """PRD section 3.5: "a `COLLECTION` may not exceed the judgment's
    `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`)".

    Design: Corner/validations/payment_above_outstanding_rejected
    """
    bundle = setup_judgment_with_fund(judgment_amount_cents=3_000_000)
    judgment_id = bundle["judgment"]["id"]

    resp = api_client.create_payment(
        judgment_id,
        create_payment_payload(amount_cents=3_000_001, kind="COLLECTION"),
        make_company_representative_headers(bundle["company"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)

    judgment = get_judgment(judgment_id)
    assert judgment["collected_cents"] == 0
    assert judgment["collection_status"] == "OUTSTANDING"


def test_reversal_above_collected_rejected():
    """PRD section 3.5: "a `REVERSAL` may not exceed the `collected_cents`
    already booked (`ERR_REVERSAL_EXCEEDS_COLLECTED`)".

    Design: Corner/validations/reversal_above_collected_rejected
    """
    bundle = setup_judgment_with_fund(judgment_amount_cents=3_000_000)
    judgment_id = bundle["judgment"]["id"]
    company_id = bundle["company"]["id"]

    record_payment(judgment_id, company_id, 1_000_000, kind="COLLECTION")
    resp = api_client.create_payment(
        judgment_id,
        create_payment_payload(amount_cents=1_000_001, kind="REVERSAL"),
        make_company_representative_headers(company_id),
    )
    validate_error(resp, ApiErrorId.ERR_REVERSAL_EXCEEDS_COLLECTED)

    judgment = get_judgment(judgment_id)
    assert judgment["collected_cents"] == 1_000_000
    assert judgment["outstanding_cents"] == 2_000_000


def test_suspension_at_exactly_ten_percent_assets_rejected():
    """PRD section 3.5: "the sworn total must be strictly less than one-tenth
    of the judgment's current `outstanding_cents`; at or above that threshold
    the request fails with `ERR_SUSPENSION_THRESHOLD_NOT_MET`."

    Design: Corner/validations/suspension_at_exactly_ten_percent_assets_rejected
    """
    bundle = setup_judgment_with_fund(judgment_amount_cents=3_000_000)
    judgment_id = bundle["judgment"]["id"]

    at_threshold = api_client.transition_judgment(
        judgment_id,
        {"target_state": "SUSPENDED", "sworn_total_assets_cents": 300_000},
        _COMMISSIONER,
    )
    validate_error(at_threshold, ApiErrorId.ERR_SUSPENSION_THRESHOLD_NOT_MET)

    suspended = suspend_judgment(judgment_id, 299_999)
    assert suspended["suspension_status"] == "SUSPENDED"
    judgment = get_judgment(judgment_id)
    assert judgment["sworn_total_assets_cents"] == 299_999


def test_reinstate_requires_qualifying_asset_trace():
    """PRD section 3.5: "the judgment's `asset_trace_log` must be non-empty
    (otherwise `ERR_NO_COMPLETED_ASSET_TRACE`), and the most recent trace by
    `traced_at` must report `found_assets_cents` of at least one-tenth of the
    current `outstanding_cents` (otherwise `ERR_SUSPENSION_THRESHOLD_NOT_MET`)."

    Design: Corner/validations/reinstate_requires_qualifying_asset_trace
    """
    bundle = setup_suspended_judgment(
        sworn_total_assets_cents=100_000, judgment_amount_cents=3_000_000
    )
    judgment_id = bundle["judgment"]["id"]

    no_trace = api_client.transition_judgment(
        judgment_id, {"target_state": "REINSTATED"}, _COMMISSIONER
    )
    validate_error(no_trace, ApiErrorId.ERR_NO_COMPLETED_ASSET_TRACE)

    record_asset_trace(judgment_id, 200_000, trace_ref="trace-1")
    low_trace = api_client.transition_judgment(
        judgment_id, {"target_state": "REINSTATED"}, _COMMISSIONER
    )
    validate_error(low_trace, ApiErrorId.ERR_SUSPENSION_THRESHOLD_NOT_MET)

    # Advance the clock so the qualifying trace is unambiguously the most
    # recent by traced_at (PRD compares timestamps at second precision).
    advance_clock("2026-10-02T00:00:00Z")
    record_asset_trace(judgment_id, 300_000, trace_ref="trace-2")
    reinstated = reinstate_judgment(judgment_id)
    assert reinstated["suspension_status"] == "REINSTATED"

    judgment = get_judgment(judgment_id)
    assert len(judgment["asset_trace_log"]) == 2
    assert [e["trace_ref"] for e in judgment["asset_trace_log"]] == ["trace-1", "trace-2"]
