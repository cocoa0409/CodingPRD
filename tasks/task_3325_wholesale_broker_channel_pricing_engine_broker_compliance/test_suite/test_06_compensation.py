"""Compensation election, the split waterfall and the rate impact."""
from test_helpers import (
    ANY,
    ApiErrorId,
    broker_version,
    get_broker,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    create_compensation_plan,
    setup_full_scenario,
    underwrite_loan,
)
from test_helpers.test_users import TEST_USERS, make_broker_headers


def _loan(loan_id):
    return validate_success(api_client.get_loan_submission(loan_id, ANY))


def test_lender_paid_election_materialises_the_plan_amount_and_commitment(api):
    """PRD §3.6: "When the election is `LENDER_PAID`, `lender_paid_comp_cents` is set to the
    plan's `lender_paid_amount_cents` and `borrower_paid_comp_cents` is 0."
    PRD §3.6: "The broker's `total_active_compensation_commitment_cents` is adjusted by the
    lender-paid delta"

    Design: Difficulty/compensating_invariant/compensation_commitment_zero_sum_on_submit_and_withdraw
    """
    scenario = setup_full_scenario()
    loan = _loan(scenario["loan_id"])
    assert loan["compensation_election"] == "LENDER_PAID"
    assert loan["lender_paid_comp_cents"] == 250_000
    assert loan["borrower_paid_comp_cents"] == 0

    broker = get_broker(scenario["broker_id"])
    assert broker["total_active_compensation_commitment_cents"] == 250_000


def test_borrower_paid_election_contributes_nothing_to_the_commitment(api):
    """PRD §2.5: "Because a `BORROWER_PAID` loan carries a `lender_paid_comp_cents` of 0,
    borrower-paid loans contribute nothing to the commitment."
    PRD §3.6: "When the election is `BORROWER_PAID`, `lender_paid_comp_cents` is 0 and
    `borrower_paid_comp_cents` is the plan's `borrower_paid_amount_cents`."

    Design: Difficulty/compensating_invariant/compensation_commitment_zero_sum_on_submit_and_withdraw
    """
    scenario = setup_full_scenario(with_borrower_plan=True, plan_default="BORROWER_PAID")
    loan = _loan(scenario["loan_id"])
    assert loan["compensation_election"] == "BORROWER_PAID"
    assert loan["lender_paid_comp_cents"] == 0
    assert loan["borrower_paid_comp_cents"] == 300_000

    broker = get_broker(scenario["broker_id"])
    assert broker["total_active_compensation_commitment_cents"] == 0


def test_election_increments_commitment_and_withdrawal_returns_it_to_zero(api):
    """PRD §2.5: "submitting one lender-paid loan and then withdrawing it leaves
    `total_active_compensation_commitment_cents` at precisely its pre-submission value."
    PRD §3.6: "Withdrawal sets the loan to `WITHDRAWN`, reduces the broker's
    `total_active_compensation_commitment_cents` by the loan's `lender_paid_comp_cents`"

    Design: Difficulty/compensating_invariant/compensation_commitment_zero_sum_on_submit_and_withdraw
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    loan_id = scenario["loan_id"]
    assert get_broker(b)["total_active_compensation_commitment_cents"] == 250_000

    withdrawn = validate_success(api_client.withdraw_loan(loan_id, make_broker_headers(b)))
    assert withdrawn["status"] == "WITHDRAWN"
    assert _loan(loan_id)["compensation_election"] == "LENDER_PAID"
    assert _loan(loan_id)["lender_paid_comp_cents"] == 250_000

    broker = get_broker(b)
    assert broker["total_active_compensation_commitment_cents"] == 0
    assert broker["active_loan_count"] == 0

    recon = validate_success(api_client.get_broker_reconciliation(b, ANY))
    assert recon["commitment_drift_cents"] == 0
    assert recon["active_loan_count"] == 0


def test_reconciliation_read_agrees_with_the_broker_derived_fields(api):
    """PRD §2.5: "The broker-level reconciliation read reports
    `total_active_compensation_commitment_cents`, `rolling_funded_volume_cents`,
    `active_loan_count` and a derived `commitment_drift_cents`."
    PRD §2.5: "it must be 0 after any compensating sequence"

    Design: Corner/endpoints/reconciliation_read_agrees_with_the_broker_derived_fields
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]

    recon = validate_success(api_client.get_broker_reconciliation(b, ANY))
    assert recon["total_active_compensation_commitment_cents"] == 250_000
    assert recon["active_loan_count"] == 1
    assert recon["rolling_funded_volume_cents"] == 0
    assert recon["commitment_drift_cents"] == 0

    broker = get_broker(b)
    assert recon["active_loan_count"] == broker["active_loan_count"]
    assert (recon["total_active_compensation_commitment_cents"]
            == broker["total_active_compensation_commitment_cents"])


def test_plan_default_mismatch_is_refused(api):
    """PRD §3.6: "a plan that is not active, not owned by that broker, or whose default
    differs is refused with `ERR_COMPENSATION_PLAN_MISMATCH`"

    Design: Corner/errors/compensation_plan_mismatch_rejected_when_default_disagrees
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    payload = {
        "broker_id": b,
        "pricing_quote_id": scenario["quote"]["id"],
        "borrower_name": "Mismatch Borrower",
        "property_state": "TX",
        "loan_amount_cents": 40_000_000,
        "lock_expires_at": "2027-01-01T00:00:00Z",
        "compensation_election": "BORROWER_PAID",
        "comp_plan_id": scenario["plan"]["id"],
    }
    response = api_client.create_loan_submission(payload, make_broker_headers(b))
    validate_error(response, ApiErrorId.ERR_COMPENSATION_PLAN_MISMATCH, expected_status=422)

    rows, meta = validate_paginated(
        api_client.list_loan_submissions(TEST_USERS["any_headers"], {"broker_id": b})
    )
    assert len(rows) == 1, "only the original scenario loan exists"
    assert get_broker(b)["total_active_compensation_commitment_cents"] == 250_000


def test_changing_the_election_after_underwriting_is_refused(api):
    """PRD §3.6: "A change attempted after the loan leaves `SUBMITTED`, or a call that repeats
    the already-stored value, is refused with `ERR_COMPENSATION_ELECTION_IMMUTABLE`."

    Design: Difficulty/compensating_invariant/compensation_commitment_zero_sum_on_submit_and_withdraw
    """
    scenario = setup_full_scenario(with_borrower_plan=True)
    b = scenario["broker_id"]
    loan_id = scenario["loan_id"]
    underwrite_loan(loan_id, broker_version(b))

    response = api_client.elect_compensation(
        loan_id,
        {"compensation_election": "BORROWER_PAID", "comp_plan_id": scenario["plan_borrower"]["id"]},
        make_broker_headers(b),
    )
    validate_error(response, ApiErrorId.ERR_COMPENSATION_ELECTION_IMMUTABLE, expected_status=409)
    assert _loan(loan_id)["compensation_election"] == "LENDER_PAID"


def test_plan_deactivation_must_leave_one_active_plan(api):
    """PRD §3.6: "a deactivation must leave at least one other active plan on the broker, or it
    is refused with `ERR_LAST_ACTIVE_COMPENSATION_PLAN`"

    Design: Corner/entities/compensation_plan_deactivation_must_leave_one_active_plan
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    plan = scenario["plan"]

    response = api_client.update_compensation_plan(plan["id"], {"is_active": False}, CM)
    validate_error(response, ApiErrorId.ERR_LAST_ACTIVE_COMPENSATION_PLAN, expected_status=409)

    active, meta = validate_paginated(
        api_client.list_compensation_plans(b, TEST_USERS["any_headers"], {"is_active": True})
    )
    assert len(active) == 1 and meta["total_count"] == 1

    plan_b = create_compensation_plan(
        b, plan_code="PLAN_B", default_election="BORROWER_PAID",
        lender_paid_amount_cents=200_000, borrower_paid_amount_cents=350_000,
    )
    toggled = validate_success(
        api_client.update_compensation_plan(plan["id"], {"is_active": False}, CM)
    )
    assert toggled["is_active"] is False

    still_active, meta2 = validate_paginated(
        api_client.list_compensation_plans(b, TEST_USERS["any_headers"], {"is_active": True})
    )
    assert len(still_active) == 1 and meta2["total_count"] == 1
    assert still_active[0]["id"] == plan_b["id"]


def test_election_matching_the_plan_default_carries_no_rate_impact(api):
    """PRD §3.6: "`rate_impact_pct` is `0.000` when the election equals the plan's
    `default_election`; it is `+0.250` when `LENDER_PAID` is elected against a `BORROWER_PAID`
    default, and `-0.250` in the mirrored case where `BORROWER_PAID` is elected against a
    `LENDER_PAID` default; while the election is `UNDECIDED` it is `0.000`."
    PRD §3.6: "The `final_note_rate_pct` is the quote's `note_rate_pct` plus the
    `rate_impact_pct`, summed and rounded half up to three decimal places"

    Design: Difficulty/compensating_invariant/compensation_commitment_zero_sum_on_submit_and_withdraw
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    quote = scenario["quote"]
    plan_borrower = create_compensation_plan(
        b, plan_code="PLAN_B", default_election="BORROWER_PAID",
        lender_paid_amount_cents=200_000, borrower_paid_amount_cents=300_000,
    )
    loan = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b, "pricing_quote_id": quote["id"],
                "borrower_name": "Mirrored Election Borrower", "property_state": "TX",
                "loan_amount_cents": 40_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
                "compensation_election": "BORROWER_PAID", "comp_plan_id": plan_borrower["id"],
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )
    assert loan["rate_impact_pct"] == 0.000, "the election matches the plan default"
    assert loan["final_note_rate_pct"] == quote["note_rate_pct"]
    assert loan["borrower_paid_comp_cents"] == 300_000
    assert loan["lender_paid_comp_cents"] == 0
    # A borrower-paid loan contributes nothing to the broker's compensation commitment.
    assert get_broker(b)["total_active_compensation_commitment_cents"] == 250_000