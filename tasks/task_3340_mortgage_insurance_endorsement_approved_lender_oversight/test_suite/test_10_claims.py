"""Insurance claims: filing gates, payment computation, pay/deny outcomes."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_escrow,
    create_lm_action,
    declare_default,
    endorse_case,
    evaluate_lm_action,
    exhaust_waterfall,
    file_claim,
    get_case,
    list_escrows,
    set_clock,
    setup_endorsed_case,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_admin_headers,
    make_examiner_headers,
    make_servicer_officer_headers,
)


def _setup_defaulted_case(api, legal_name="Claim Co", **case_overrides):
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": legal_name}, case_overrides=case_overrides
    )
    declare_default(case["id"], lender["id"])
    return lender, get_case(case["id"])


def _setup_waterfall_exhausted(api, legal_name="Claim Co", **case_overrides):
    lender, case = _setup_defaulted_case(api, legal_name=legal_name, **case_overrides)
    exhaust_waterfall(case["id"], lender["id"])
    return lender, case


# ---------------------------------------------------------------------------
# Waterfall gate
# ---------------------------------------------------------------------------
def test_error_waterfall_not_exhausted_on_claim(api):
    """PRD §3.8: "With the waterfall exhausted — every tier 1 through 6 holding an
    action in `INFEASIBLE` or `FAILED` status — the servicer files a claim, and filing
    before exhaustion is rejected with `ERR_WATERFALL_NOT_EXHAUSTED`."

    Design: Corner/errors/error_waterfall_not_exhausted_on_claim
    """
    lender, case = _setup_defaulted_case(api, legal_name="Partial Waterfall Co",
                                         borrower_reference="PW-1")
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "REPAYMENT_PLAN")["id"],
        lender["id"], "INFEASIBLE",
    )
    response = api_client.create_claim(
        case["id"],
        {"claim_type": "CONVEYANCE", "unpaid_principal_balance_cents": 30_000_000,
         "expense_items": []},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_WATERFALL_NOT_EXHAUSTED)
    assert get_case(case["id"])["status"] == "IN_DEFAULT"


# ---------------------------------------------------------------------------
# Filing deadline
# ---------------------------------------------------------------------------
def test_error_claim_deadline_passed(api):
    """PRD §3.8: "The claim must be filed on or before the 180th day after
    `default_date`, inclusive; afterwards the filing is rejected with
    `ERR_CLAIM_DEADLINE_PASSED`."

    Design: Corner/errors/error_claim_deadline_passed
    """
    lender, case = _setup_waterfall_exhausted(
        api, legal_name="Deadline Co", borrower_reference="DL-1"
    )
    # Default was stamped at the 2026-09-01 logical clock; 2027-03-01 is day 181.
    set_clock("2027-03-01T00:00:00Z")
    response = api_client.create_claim(
        case["id"],
        {"claim_type": "CONVEYANCE", "unpaid_principal_balance_cents": 30_000_000,
         "expense_items": []},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_DEADLINE_PASSED)


def test_error_claim_deadline_inclusive_at_day_180(api):
    """PRD §3.8: "The claim must be filed on or before the 180th day after
    `default_date`, inclusive; afterwards the filing is rejected with
    `ERR_CLAIM_DEADLINE_PASSED`."

    Design: Corner/errors/error_claim_deadline_inclusive_at_day_180
    """
    lender, case = _setup_waterfall_exhausted(
        api, legal_name="Inclusive Co", borrower_reference="INC-1"
    )
    # 2027-02-28 is exactly 180 days after the 2026-09-01 default: still allowed.
    set_clock("2027-02-28T00:00:00Z")
    response = api_client.create_claim(
        case["id"],
        {"claim_type": "CONVEYANCE", "unpaid_principal_balance_cents": 30_000_000,
         "expense_items": []},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response, expected_status=201)
    assert data["status"] == "UNDER_REVIEW"
    assert get_case(case["id"])["status"] == "CLAIM_FILED"


# ---------------------------------------------------------------------------
# Claim payment computation
# ---------------------------------------------------------------------------
def test_claim_expense_component_rounds_per_line_then_sums(api):
    """PRD §3.8: "The claim payment is computed at filing with a pinned rounding order:
    each expense line is rounded to whole cents first, and only then are the lines
    summed. The `principal_component_cents` for a `CONVEYANCE` claim is the unpaid
    principal balance multiplied by 8,500 basis points — that is, by 8,500 and divided
    by ten thousand, rounded half-up — an 85 percent coverage of principal."
    PRD §3.8: "The `total_claim_cents` is the principal component plus the expense
    component minus the forfeited escrow offset."

    Design: Corner/calculations/claim_expense_component_rounds_per_line_then_sums
    """
    lender, case = _setup_waterfall_exhausted(
        api, legal_name="Round Co", borrower_reference="RND-1"
    )
    response = api_client.create_claim(
        case["id"],
        {"claim_type": "CONVEYANCE", "unpaid_principal_balance_cents": 30_000_000,
         "expense_items": [
             {"amount_cents": 101, "allowable_pct_bps": 5000},
             {"amount_cents": 101, "allowable_pct_bps": 5000},
         ]},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response, expected_status=201)
    assert data["principal_component_cents"] == 25_500_000
    # Per-line: round_half_up(101 * 5,000 / 10,000) = round_half_up(50.5) = 51, twice.
    assert data["expense_component_cents"] == 102
    assert data["total_claim_cents"] == 25_500_102
    assert get_case(case["id"])["status"] == "CLAIM_FILED"


# ---------------------------------------------------------------------------
# WITHOUT_CONVEYANCE escrow forfeiture
# ---------------------------------------------------------------------------
def test_without_conveyance_filing_forfeits_escrows_into_case_total(api):
    """PRD §3.4: "filing a claim without conveyance forfeits the case's escrows: every
    escrow of the case in `OPEN` or `EXPIRED` status moves to `FORFEITED`, and the sum
    of their `remaining_amount_cents` is recorded on the case as
    `forfeited_escrow_total_cents`, which later offsets the claim payment."
    PRD §3.8: "For a `WITHOUT_CONVEYANCE` claim, that same 85 percent figure is itself
    multiplied by 9,000 basis points and divided by ten thousand, rounded half-up — a
    90 percent damage factor applied after coverage."

    Design: Corner/errors/without_conveyance_filing_forfeits_escrows_into_case_total
    """
    # Run the whole flow at an early clock so one escrow expires via the sweep before
    # filing while the other is still open.
    set_clock("2026-01-15T00:00:00Z")
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "CWOC Co"},
        case_overrides={"borrower_reference": "CW-1"},
        appraisal_overrides={"effective_date": "2026-01-01"},
    )
    lid, cid = lender["id"], case["id"]
    escrow_1 = create_escrow(
        cid, lid, amount_cents=500_000, start_date="2026-01-01", end_date="2026-03-31"
    )
    escrow_2 = create_escrow(
        cid, lid, amount_cents=300_000, start_date="2026-04-02", end_date="2026-05-31"
    )
    declare_default(cid, lid)
    exhaust_waterfall(cid, lid)
    # Advance to 2026-05-01: escrow 1 (end 2026-03-31) sweeps EXPIRED; escrow 2 stays
    # OPEN. The filing is 106 days after the 2026-01-15 default: inside the window.
    set_clock("2026-05-01T00:00:00Z")
    response = api_client.create_claim(
        cid,
        {"claim_type": "WITHOUT_CONVEYANCE",
         "unpaid_principal_balance_cents": 30_000_000, "expense_items": []},
        make_servicer_officer_headers(lid),
    )
    data = validate_success(response, expected_status=201)
    # principal = round_half_up(round_half_up(30,000,000 * 8,500/10,000) * 9,000/10,000)
    #           = round_half_up(25,500,000 * 0.9) = 22,950,000.
    assert data["principal_component_cents"] == 22_950_000
    assert data["forfeited_escrow_offset_cents"] == 800_000
    assert data["total_claim_cents"] == 22_150_000
    escrows = {e["id"]: e for e in list_escrows(cid)}
    assert escrows[escrow_1["id"]]["status"] == "FORFEITED"
    assert escrows[escrow_2["id"]]["status"] == "FORFEITED"
    assert get_case(cid)["forfeited_escrow_total_cents"] == 800_000


# ---------------------------------------------------------------------------
# Claim decisions
# ---------------------------------------------------------------------------
def test_claim_pay_moves_case_to_claim_paid(api):
    """PRD §3.8: "A `ClaimsExaminer` decides it with a `decision` of `PAY` or `DENY`:
    paying moves the claim to `PAID` and the case from `CLAIM_FILED` to `CLAIM_PAID`"

    Design: Corner/errors/claim_pay_moves_case_to_claim_paid
    """
    lender, case = _setup_waterfall_exhausted(
        api, legal_name="Pay Co", borrower_reference="PAY-1"
    )
    claim = file_claim(case["id"], lender["id"])
    response = api_client.decide_claim(
        claim["id"], {"decision": "PAY"}, make_examiner_headers("cx-1")
    )
    data = validate_success(response)
    assert data["status"] == "PAID"
    assert get_case(case["id"])["status"] == "CLAIM_PAID"


def test_claim_deny_returns_case_to_in_default(api):
    """PRD §3.8: "while denying records `denial_reason` as `EXAMINER_DENIAL`, moves the
    claim to `DENIED`, and returns the case from `CLAIM_FILED` to `IN_DEFAULT` — the
    denial loop may repeat, and the servicer may refile while the 180-day deadline from
    `default_date` still holds."

    Design: Corner/errors/claim_deny_returns_case_to_in_default
    """
    lender, case = _setup_waterfall_exhausted(
        api, legal_name="Deny Co", borrower_reference="DNY-1"
    )
    claim = file_claim(case["id"], lender["id"])
    response = api_client.decide_claim(
        claim["id"], {"decision": "DENY"}, make_examiner_headers("cx-1")
    )
    data = validate_success(response)
    assert data["status"] == "DENIED"
    assert data["denial_reason"] == "EXAMINER_DENIAL"
    assert get_case(case["id"])["status"] == "IN_DEFAULT"


# ---------------------------------------------------------------------------
# Difficulty: pinned per-line expense rounding (mode: nested rounding)
# ---------------------------------------------------------------------------
def _setup_claim_ready_case(api):
    """Case (base 20,000,000) endorsed 2026-09-01, defaulted 2026-10-01, waterfall
    exhausted, clock at 2026-10-02 — one day into the 180-day filing window."""
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "Pinned Rounding Co"},
        case_overrides={
            "borrower_reference": "BOR-C",
            "base_loan_amount_cents": 20_000_000,
            "appraised_value_cents": 24_000_000,
        },
        appraisal_overrides={"appraised_value_cents": 24_000_000},
    )
    set_clock("2026-10-01T00:00:00Z")
    declare_default(case["id"], lender["id"])
    exhaust_waterfall(case["id"], lender["id"])
    set_clock("2026-10-02T00:00:00Z")
    return lender, case


def test_claim_pinned_rounding_components(api):
    """PRD §3.8: "The claim payment is computed at filing with a pinned rounding order:
    each expense line is rounded to whole cents first, and only then are the lines
    summed."
    PRD §3.8: "The `total_claim_cents` is the principal component plus the expense
    component minus the forfeited escrow offset."

    Design: Difficulty/combinatorial_formula/claim_expense_rounding_per_line_then_sum
    """
    lender, case = _setup_claim_ready_case(api)
    response = api_client.create_claim(
        case["id"],
        {"claim_type": "CONVEYANCE", "unpaid_principal_balance_cents": 20_000_000,
         "expense_items": [
             {"amount_cents": 21, "allowable_pct_bps": 5000},
             {"amount_cents": 21, "allowable_pct_bps": 5000},
         ]},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response, expected_status=201)
    assert data["principal_component_cents"] == 17_000_000
    # Each 21-cent line at 5,000 bps yields 10.5 -> 11; summed 22. The rejected
    # sum-then-round order would give 21.
    assert data["expense_component_cents"] == 22
    assert data["total_claim_cents"] == 17_000_022


def test_claim_pinned_rounding_components_persist(api):
    """PRD §3.8: "Filing moves the case from `IN_DEFAULT` to `CLAIM_FILED`"
    PRD §3.8: "A new claim lands in `UNDER_REVIEW`."
    PRD §4: "| GET | /mi/loan-cases/{loanCaseId}/claims | List claims of the case |
    PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover,
    ClaimsExaminer |"

    Design: Difficulty/combinatorial_formula/claim_expense_rounding_per_line_then_sum
    """
    lender, case = _setup_claim_ready_case(api)
    claim = file_claim(
        case["id"], lender["id"],
        unpaid_principal_balance_cents=20_000_000,
        expense_items=[
            {"amount_cents": 21, "allowable_pct_bps": 5000},
            {"amount_cents": 21, "allowable_pct_bps": 5000},
        ],
    )
    assert claim["status"] == "UNDER_REVIEW"
    assert get_case(case["id"])["status"] == "CLAIM_FILED"
    data, meta = validate_paginated(
        api_client.list_claims(case["id"], make_admin_headers())
    )
    assert meta["total_count"] == 1
    assert data[0]["total_claim_cents"] == 17_000_022


# ---------------------------------------------------------------------------
# Difficulty: claim gated by waterfall exhaustion
# ---------------------------------------------------------------------------
def _setup_five_tiers_infeasible(api):
    """Defaulted case with waterfall tiers 1-5 INFEASIBLE and tier 6 untouched."""
    lender, case = _setup_defaulted_case(
        api, legal_name="Waterfall Gate Co", borrower_reference="WG-1"
    )
    lid, cid = lender["id"], case["id"]
    for action_type in (
        "REPAYMENT_PLAN", "SPECIAL_FORBEARANCE", "LOAN_MODIFICATION",
        "PARTIAL_CLAIM", "PRE_FORECLOSURE_SALE",
    ):
        evaluate_lm_action(
            create_lm_action(cid, lid, action_type)["id"], lid, "INFEASIBLE"
        )
    return lender, case


def test_claim_rejected_until_waterfall_exhausted(api):
    """PRD §3.8: "With the waterfall exhausted — every tier 1 through 6 holding an
    action in `INFEASIBLE` or `FAILED` status — the servicer files a claim, and filing
    before exhaustion is rejected with `ERR_WATERFALL_NOT_EXHAUSTED`."

    Design: Difficulty/cross_entity_state_dependency/claim_gated_by_loss_mitigation_waterfall_exhaustion
    """
    lender, case = _setup_five_tiers_infeasible(api)
    response = api_client.create_claim(
        case["id"],
        {"claim_type": "CONVEYANCE", "unpaid_principal_balance_cents": 19_000_000,
         "expense_items": []},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_WATERFALL_NOT_EXHAUSTED)
    assert get_case(case["id"])["status"] == "IN_DEFAULT"


def test_claim_succeeds_after_waterfall_exhausted(api):
    """PRD §3.8: "With the waterfall exhausted — every tier 1 through 6 holding an
    action in `INFEASIBLE` or `FAILED` status — the servicer files a claim"
    PRD §3.8: "The `principal_component_cents` for a `CONVEYANCE` claim is the unpaid
    principal balance multiplied by 8,500 basis points — that is, by 8,500 and divided
    by ten thousand, rounded half-up — an 85 percent coverage of principal."
    PRD §3.8: "Filing moves the case from `IN_DEFAULT` to `CLAIM_FILED`"

    Design: Difficulty/cross_entity_state_dependency/claim_gated_by_loss_mitigation_waterfall_exhaustion
    """
    lender, case = _setup_five_tiers_infeasible(api)
    # Opening tier 6 is legal only after tier 5 resolves; failing it exhausts the
    # waterfall.
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "DEED_IN_LIEU")["id"],
        lender["id"], "FAIL",
    )
    response = api_client.create_claim(
        case["id"],
        {"claim_type": "CONVEYANCE", "unpaid_principal_balance_cents": 19_000_000,
         "expense_items": []},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response, expected_status=201)
    assert data["status"] == "UNDER_REVIEW"
    # round_half_up(19,000,000 * 8,500 / 10,000) == 16,150,000.
    assert data["total_claim_cents"] == 16_150_000
    assert get_case(case["id"])["status"] == "CLAIM_FILED"

