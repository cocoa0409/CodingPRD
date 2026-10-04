"""Capacity review scoring, grade banding, and portfolio headroom."""
import test_helpers as th


def test_capacity_score_exactly_60_is_adequate(api, admin_headers, finance_headers):
    """PRD §3.2: "The review's `grade` bands from the score with the low edge
    of each band inclusive: at least 80 is `STRONG`, 60 through 79 is
    `ADEQUATE`, 40 through 59 is `WEAK`, and below 40 is `FAILING`."
    PRD §3.2: "The `capacity_grade` determines `max_stores`: `STRONG` permits
    12 stores, `ADEQUATE` permits 6, `WEAK` permits 2, `FAILING` permits 0,
    and an operator with no submitted review at all has `max_stores` 0."

    Design: Difficulty/boundary_precision_check/capacity_score_exactly_60_is_adequate
    """
    # Component arithmetic (clean operator, no stores, no defaults/delinquency):
    # net = 100 * min(1, 200,000,000 / 200,000,000) = 100
    # opm = 100 * min(1, (10,000,000 / 200,000,000) / 0.25) = 20
    # port = 0; compliance = 100
    # composite = round_half_up(0.35*100 + 0.25*20 + 0.20*0 + 0.20*100) = 60
    op = th.create_operator(legal_name="Op Boundary LLC",
                            fy_net_worth_cents=200_000_000,
                            fy_operating_income_cents=10_000_000)
    review = th.create_and_submit_capacity_review(op["id"])
    assert review["composite_score"] == 60
    assert review["grade"] == "ADEQUATE"

    reviewed_op = th.validate_success(api.get_operator(op["id"], finance_headers))
    assert reviewed_op["max_stores"] == 6

    approved = th.validate_success(api.approve_operator(op["id"], admin_headers))
    assert approved["status"] == "APPROVED"


def test_capacity_score_59_is_weak_and_blocks_approval(api, admin_headers, finance_headers):
    """PRD §3.2: "The review's `grade` bands from the score with the low edge
    of each band inclusive: at least 80 is `STRONG`, 60 through 79 is
    `ADEQUATE`, 40 through 59 is `WEAK`, and below 40 is `FAILING`."
    PRD §3.2: "A `FranchisorAdmin` approves a `CANDIDATE` operator only when a
    `SUBMITTED` capacity review exists for that operator whose grade is
    `STRONG` or `ADEQUATE`; otherwise approval is rejected with
    `ERR_CAPACITY_REVIEW_REQUIRED`."

    Design: Difficulty/boundary_precision_check/capacity_score_exactly_60_is_adequate
    """
    # net 100 (200,000,000), opm 16 (income 8,000,000 -> 0.04/0.25=0.16),
    # port 0, compliance 100 -> 35+4+0+20 = 59 -> WEAK.
    op = th.create_operator(legal_name="Op Below Boundary LLC",
                            fy_net_worth_cents=200_000_000,
                            fy_operating_income_cents=8_000_000)
    review = th.create_and_submit_capacity_review(op["id"])
    assert review["composite_score"] == 59
    assert review["grade"] == "WEAK"

    reviewed_op = th.validate_success(api.get_operator(op["id"], finance_headers))
    assert reviewed_op["max_stores"] == 2

    resp = api.approve_operator(op["id"], admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_CAPACITY_REVIEW_REQUIRED, expected_status=409)


def test_headroom_zero_blocks_store_creation(api, admin_headers, finance_headers):
    """PRD §3.2: "The headroom check at store creation subtracts the operator's
    `stores_operated_count` — which counts only the operator's stores whose
    `status` is `OPEN`, excluding `SETUP`, `SUSPENDED`, and `REPOSSESSED` —
    from `max_stores`; creation requires headroom strictly greater than zero,
    and at the exact boundary where headroom is zero the creation is rejected
    with `ERR_PORTFOLIO_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/headroom_zero_blocks_store_creation
    """
    operator = th.create_strong_approved_operator(legal_name="Op Eleven LLC")
    # Build two OPEN stores for the operator.
    store_a = th.create_store_for(operator, th.create_site())
    th.activate_agreement(store_a, operator)
    th.activate_sublease(store_a, operator)
    th.validate_success(api.open_store(store_a["id"], admin_headers))
    store_b = th.create_store_for(operator, th.create_site())
    th.activate_agreement(store_b, operator)
    th.activate_sublease(store_b, operator)
    th.validate_success(api.open_store(store_b["id"], admin_headers))

    # Re-grade the operator WEAK with composite exactly 40 (two OPEN stores):
    # net = 100 * (80,000,000 / 200,000,000) = 40
    # opm = 100 * ((1,600,000 / 80,000,000) / 0.25) = 100 * 0.08 = 8
    # port = 100 * (2 / 10) = 20; compliance = 100
    # composite = round_half_up(0.35*40 + 0.25*8 + 0.20*20 + 0.20*100) = 40
    th.get_success_data(api.update_fiscal_snapshot(
        operator["id"],
        {"fy_net_worth_cents": 80_000_000, "fy_operating_income_cents": 1_600_000},
        finance_headers,
    ))
    review = th.create_and_submit_capacity_review(operator["id"], review_period="2027")
    assert review["composite_score"] == 40
    assert review["grade"] == "WEAK"

    reviewed = th.validate_success(api.get_operator(operator["id"], finance_headers))
    assert reviewed["max_stores"] == 2
    assert reviewed["stores_operated_count"] == 2

    site_c = th.create_site()
    resp = api.create_store(
        th.create_store_payload(site_c["id"], operator["id"], reviewed["version"]),
        admin_headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_PORTFOLIO_LIMIT_REACHED, expected_status=409)


def test_headroom_positive_allows_store_creation(api, admin_headers, finance_headers):
    """PRD §3.2: "The headroom check at store creation subtracts the operator's
    `stores_operated_count` — which counts only the operator's stores whose
    `status` is `OPEN`, excluding `SETUP`, `SUSPENDED`, and `REPOSSESSED` —
    from `max_stores`; creation requires headroom strictly greater than zero,
    and at the exact boundary where headroom is zero the creation is rejected
    with `ERR_PORTFOLIO_LIMIT_REACHED`."
    PRD §3.3: "Creation requires that the site be `HELD`, that the operator be
    `APPROVED`, and that the portfolio headroom rule of §3.2 passes;
    violations are rejected with `ERR_PORTFOLIO_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/headroom_zero_blocks_store_creation
    """
    # STRONG operator with one OPEN store: headroom 12 - 1 = 11 > 0 permits
    # the second store (contrast: headroom == 0 rejects).
    operator = th.create_strong_approved_operator(legal_name="Op Headroom LLC")
    store_a = th.create_store_for(operator, th.create_site())
    th.activate_agreement(store_a, operator)
    th.activate_sublease(store_a, operator)
    th.validate_success(api.open_store(store_a["id"], admin_headers))

    reviewed = th.validate_success(api.get_operator(operator["id"], finance_headers))
    assert reviewed["stores_operated_count"] == 1
    assert reviewed["max_stores"] == 12

    site_b = th.create_site()
    resp = api.create_store(
        th.create_store_payload(site_b["id"], operator["id"], reviewed["version"]),
        admin_headers,
    )
    store_b = th.validate_success(resp, expected_status=201)
    th.assert_store(store_b)
    assert store_b["status"] == "SETUP"
