"""Fund accounts and fiscal controls: settled-vs-committed availability and
which variant gates, the frozen-state priority over sufficiency, the void
compensating action, and the federal/trust activity separation (PRD §2.7,
§3.7, §2.8)."""

from test_helpers import (
    FUND_WORKED_APPROPRIATION,
    FUND_WORKED_APPROVED_ACQUISITION,
    FUND_WORKED_COMMITTED,
    FUND_WORKED_POSTED,
    FUND_WORKED_REJECTED_SPEND,
    FUND_WORKED_SETTLED,
    ApiErrorId,
    create_approved_acquisition_review,
    create_federal_fund,
    create_trust_fund,
    freeze_fund,
    get_fund,
    make_finance_officer_headers,
    post_expenditure,
    reset_clock,
    validate_error,
    validate_paginated,
    void_expenditure,
)


def test_fund_settled_vs_committed_gating(api):
    """PRD §2.7: "All spending gates — expenditure creation, acquisition approval, and acquisition execution — are validated against the conservative committed figure, never the settled one. For example, given an appropriation of 1,000,000,000 cents, posted expenditures of 120,000,000 cents, and one approved-but-unexecuted acquisition estimated at 300,000,000 cents, the settled figure reads 880,000,000 cents while the committed figure reads 580,000,000 cents; an expenditure of 700,000,000 cents would pass the settled reading but is rejected with `ERR_INSUFFICIENT_FUND_AVAILABLE` (HTTP 409) because the committed reading governs."

    Design: Difficulty/dual_variant_calc/fund_settled_vs_committed_gating
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=FUND_WORKED_APPROPRIATION)
    post_expenditure(
        fund["id"], amount_cents=FUND_WORKED_POSTED, activity_type="OPERATIONS", memo="HVAC retrofit"
    )
    create_approved_acquisition_review(
        fund["id"],
        estimated_cost_cents=FUND_WORKED_APPROVED_ACQUISITION,
        curator_user_id="cur-7",
        chair_user_id="chair-1",
    )
    # 700,000,000 passes the settled reading (880,000,000) but not the
    # committed reading (580,000,000), and the committed reading governs.
    resp = api.create_expenditure(
        fund["id"],
        {
            "amount_cents": FUND_WORKED_REJECTED_SPEND,
            "activity_type": "OPERATIONS",
            "memo": "Roof replacement",
        },
        headers=make_finance_officer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUND_AVAILABLE)
    fund_after = get_fund(fund["id"])
    assert fund_after["settled_available_cents"] == FUND_WORKED_SETTLED == 880000000
    assert fund_after["committed_available_cents"] == FUND_WORKED_COMMITTED == 580000000
    rows, meta = validate_paginated(
        api.list_expenditures(
            headers=make_finance_officer_headers(), params={"fund_id": fund["id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected expenditure left no trace"
    assert rows[0]["amount_cents"] == FUND_WORKED_POSTED and rows[0]["status"] == "POSTED"


def test_fund_frozen_state_beats_fiscal_rejected(api):
    """PRD §2.8: "When several checks would fail, the earliest check in this order produces the error, and later checks are never evaluated:"
    PRD §2.8: "6. **Fund availability of status** — the fund is `ACTIVE` for expenditure creation and for acquisition decision and execution, else `ERR_FUND_FROZEN`." (ordered before item 20)
    PRD §2.8: "20. **Fund sufficiency** — the amount does not exceed the fund's committed availability, else `ERR_INSUFFICIENT_FUND_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/fund_frozen_state_beats_fiscal_rejected
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=100000000)
    post_expenditure(
        fund["id"], amount_cents=90000000, activity_type="OPERATIONS", memo="Security contract"
    )
    freeze_fund(fund["id"])
    # Both the frozen gate (priority 6) and the sufficiency gate (priority 20 —
    # 50,000,000 > 10,000,000 committed) would fail; the state error wins.
    resp = api.create_expenditure(
        fund["id"],
        {"amount_cents": 50000000, "activity_type": "OPERATIONS", "memo": "Elevator repair"},
        headers=make_finance_officer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FUND_FROZEN)
    fund_after = get_fund(fund["id"])
    assert fund_after["settled_available_cents"] == 10000000
    _, meta = validate_paginated(
        api.list_expenditures(
            headers=make_finance_officer_headers(), params={"fund_id": fund["id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected expenditure left no trace"


def test_expenditure_void_restores_fund_dollars(api):
    """PRD §3.7: "The compensating action is voiding, again by a `FinanceOfficer`: the expenditure moves `POSTED` to `VOIDED`, and the fund's settled and committed availability rise by the voided `amount_cents`, since only `POSTED` expenditures count against the fund."
    PRD §2.7: "The settled figure, `settled_available_cents`, is the fund's `appropriation_cents` plus its `receipts_cents`, minus the summed `amount_cents` of its expenditures still in `POSTED` status (`VOIDED` expenditures are excluded)."

    Design: Difficulty/compensating_invariant/expenditure_void_restores_fund_dollars
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=500000000)
    assert get_fund(fund["id"])["settled_available_cents"] == 500000000
    expenditure = post_expenditure(
        fund["id"], amount_cents=100000000, activity_type="OPERATIONS", memo="Galas and openings"
    )
    assert get_fund(fund["id"])["settled_available_cents"] == 400000000, (
        "the forward action debited 100,000,000"
    )
    voided = void_expenditure(expenditure["id"])
    assert voided["status"] == "VOIDED"
    fund_after = get_fund(fund["id"])
    assert fund_after["settled_available_cents"] == 500000000, (
        "post + void conserve fund dollars with no drift"
    )
    assert fund_after["committed_available_cents"] == 500000000


def test_federal_fund_activity_separation(api):
    """PRD §2.7: "Appropriated funds may support only `OPERATIONS` and `EDUCATION` activity; charging `ACQUISITION` or `EXHIBITION` activity to a `FEDERAL` fund is rejected with `ERR_FUND_ACTIVITY_NOT_PERMITTED` (HTTP 422). A `TRUST` fund permits all four activity types — `OPERATIONS`, `EDUCATION`, `ACQUISITION`, and `EXHIBITION`."

    Design: Corner/errors/federal_fund_activity_separation
    """
    reset_clock()
    fund = create_federal_fund(appropriation_cents=1000000000)
    # An ACQUISITION charge against a federal appropriation is forbidden.
    resp_exp = api.create_expenditure(
        fund["id"],
        {"amount_cents": 100, "activity_type": "ACQUISITION", "memo": "Direct federal acquisition attempt"},
        headers=make_finance_officer_headers(),
    )
    validate_error(resp_exp, ApiErrorId.ERR_FUND_ACTIVITY_NOT_PERMITTED)
    # OPERATIONS on the same FEDERAL fund is permitted.
    ok = post_expenditure(
        fund["id"], amount_cents=100, activity_type="OPERATIONS", memo="Guard salaries"
    )
    assert ok["status"] == "POSTED"
