"""Residual disposition: zero-claimant escheat, the exact 0.60 claim-rate
boundary, and the outstanding-checks gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    close_claims_window,
    enter_residual_disposition,
    get_fund,
    make_claimant_specs,
    redress_fund_transition_payload,
    setup_check_issued_fund,
    setup_open_fund,
    setup_residual_ready_fund,
    start_disbursing,
    validate_error,
)

_ADMIN = TEST_USERS["fund_administrator_headers"]  # fa-1


def test_zero_claimants_residual_disposition_escheats_full_pool():
    """PRD section 3.8: "a fund with no claimants at all has a claim rate of
    0. If the rate is at least 0.60, `residual_disposition` is set to
    `CY_PRES` — and exactly 0.60 qualifies — otherwise it is set to
    `TREASURY_ESCHEAT`. Either way, `residual_cents` captures the fund's
    remaining `available_cents` — the uncashed and unawarded money —
    `available_cents` falls to 0, the `residual_recipient_name` is recorded".
    PRD section 3.6: "With no approved claims, the total is 0."

    Design: Difficulty/boundary_precision_check/zero_claimants_residual_disposition_escheats_full_pool
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        reporting_frequency_months=12,
        monitoring_term_years=3,
        claimant_specs=None,
    )
    fund_id = bundle["fund"]["id"]

    closed = close_claims_window(fund_id)
    assert closed["admin_reserve_cents"] == 0, "zero eligible claims collapse the reserve"
    assert closed["distributable_pool_cents"] == 1_500_000

    disbursing = start_disbursing(fund_id)
    assert disbursing["allocated_cents"] == 0
    assert disbursing["available_cents"] == 1_500_000

    disposed = enter_residual_disposition(fund_id, residual_recipient_name="Consumer Education Trust")
    assert disposed["residual_disposition"] == "TREASURY_ESCHEAT", "claim rate 0 < 0.60"
    assert disposed["residual_cents"] == 1_500_000, "the entire pool escheats"
    assert disposed["available_cents"] == 0
    assert disposed["residual_recipient_name"] == "Consumer Education Trust"


def test_claim_rate_exactly_060_selects_cy_pres():
    """PRD section 3.8: "The final claim rate is the number of the fund's
    claims that reached `APPROVED` at any point — claims now standing in
    `APPROVED` or `PAID`, excluding both `DENIED` claims and any claim that
    never left `FILED` or `UNDER_REVIEW` before the window closed — divided
    by the total count of the fund's claimant records in any status".
    PRD section 3.8: "If the rate is at least 0.60, `residual_disposition` is
    set to `CY_PRES` — and exactly 0.60 qualifies — otherwise it is set to
    `TREASURY_ESCHEAT`."

    Design: Corner/calculations/claim_rate_exactly_060_selects_cy_pres
    """
    # 3 approved (and cashed out to PAID) of 5 identified claimants: exactly 0.60.
    bundle = setup_residual_ready_fund(
        losses=(100_000, 100_000, 100_000),
        judgment_amount_cents=2_000_000,
        monetary_relief_cents=2_000_000,
        claimant_specs=make_claimant_specs(5),
    )
    fund_id = bundle["fund"]["id"]

    disposed = enter_residual_disposition(fund_id, residual_recipient_name="Consumer Education Trust")
    assert disposed["residual_disposition"] == "CY_PRES", (
        "3 approved / 5 identified == 0.60 exactly, and the >= boundary selects cy pres"
    )
    # reserve 30,000; pool 1,970,000; disbursed 300,000 -> residual 1,670,000.
    assert disposed["residual_cents"] == 1_670_000
    assert disposed["available_cents"] == 0
    assert disposed["disbursed_cents"] == 300_000
    assert disposed["residual_recipient_name"] == "Consumer Education Trust"


def test_residual_disposition_with_outstanding_check_rejected():
    """PRD section 3.8: "every refund check of the fund's claims must already
    sit in `CASHED` or `VOIDED`, so a single check still `ISSUED` or `STALE`
    blocks the transition with `ERR_CHECKS_OUTSTANDING`."

    Design: Corner/validations/residual_disposition_with_outstanding_check_rejected
    """
    bundle = setup_check_issued_fund(
        losses=(500_000,), judgment_amount_cents=1_500_000, monetary_relief_cents=1_500_000
    )
    fund_id = bundle["fund"]["id"]
    fund = get_fund(fund_id)

    resp = api_client.transition_redress_fund(
        fund_id,
        redress_fund_transition_payload(
            "RESIDUAL_DISPOSITION",
            fund["version"],
            residual_recipient_name="Consumer Education Trust",
        ),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CHECKS_OUTSTANDING)

    after = get_fund(fund_id)
    assert after["status"] == "DISBURSING"
    assert after["residual_cents"] == 0
