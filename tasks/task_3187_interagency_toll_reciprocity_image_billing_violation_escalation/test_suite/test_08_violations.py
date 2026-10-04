"""Violation notices, escalation, registration holds (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_days,
    api_client,
    create_away_agency,
    create_home_agency,
    create_plate_agreement,
    create_rate_schedule,
    find_pending_image_bill,
    get_success_data,
    issue_notice,
    notice_three_times,
    post_image_trip,
    resolve_bill_to_violation,
    setup_unregistered_plate_violation,
    validate_error,
    validate_paginated,
)

VO = TEST_USERS["violations_officer_headers"]
PL = TEST_USERS["plate_lookup_agent_headers"]
SO = TEST_USERS["settlement_officer_headers"]


def _get_violation(violation_id):
    return get_success_data(api_client.get_violation(violation_id, VO))


def test_reg_hold_threshold_inclusive_boundary():
    """PRD §3.7: "When a violation in `NOTICED` has reached its third notice
    (`notice_count` is three) and at least 60 days have elapsed since
    `first_notice_day`, the sweep transitions it to `ESCALATED` — unless its
    `total_outstanding_cents` has reached 10000 cents (one hundred dollars), in
    which case it goes directly to `HOLD_REFERRED` instead."
    PRD §3.7: "once `total_outstanding_cents` is at least 10000 cents — and the
    boundary is inclusive, exactly 10000 is referred while 9999 is not — the
    violation moves to `HOLD_REFERRED`, `registration_hold_referred` is set
    true, and a referral is sent to the plate state's DMV."

    Design: Difficulty/boundary_precision_check/reg_hold_threshold_inclusive_boundary
    """
    # V-eq: toll 2000 (image_fee 0) -> total 2000+500+2500+5000 = 10000.
    ctx_eq = setup_unregistered_plate_violation(
        base_rate_cents=2000, image_fee_cents=0, plaza_code="P6", plate_number="UNREG5"
    )
    v_eq = ctx_eq["violation"]

    # V-lt: toll 1999 -> total 9999. Reuse the same away agency but a new plaza.
    away = ctx_eq["away"]
    create_rate_schedule(
        away["id"], plaza_code="P7", base_rate_cents=1999, image_fee_cents=0,
        effective_to="2027-01-01T00:00:00Z",
    )
    txn_lt = post_image_trip(away["id"], "P7", "UNREG6", "PA", "2026-09-01T09:30:00Z", "u6")
    bill_lt = find_pending_image_bill()
    resolve_bill_to_violation(bill_lt["id"])
    vios, _ = validate_paginated(api_client.list_violations(VO))
    assert len(vios) == 2
    v_lt = next(v for v in vios if v["id"] != v_eq["id"])

    # Three notices each at days 0, 30, 60.
    for v in (v_eq, v_lt):
        issue_notice(v["id"])
    advance_days(30)
    for v in (v_eq, v_lt):
        issue_notice(v["id"])
    advance_days(30)
    for v in (v_eq, v_lt):
        issue_notice(v["id"])

    advance_days(1)

    eq = _get_violation(v_eq["id"])
    assert eq["total_outstanding_cents"] == 10000
    assert eq["status"] == "HOLD_REFERRED"
    assert eq["registration_hold_referred"] is True

    lt = _get_violation(v_lt["id"])
    assert lt["total_outstanding_cents"] == 9999
    assert lt["status"] == "ESCALATED"
    assert lt["registration_hold_referred"] is False


def test_violation_branching_fork_join():
    """PRD §3.7: "An `AccountHolder` or a `ViolationsOfficer` may pay a
    violation in full from `OPEN`, `NOTICED`, `ESCALATED`, or `HOLD_REFERRED`;
    payment moves it to `PAID` and zeroes `total_outstanding_cents`."
    PRD §3.7: "When a violation in `NOTICED` has reached its third notice
    (`notice_count` is three) and at least 60 days have elapsed since
    `first_notice_day`, the sweep transitions it to `ESCALATED` — unless its
    `total_outstanding_cents` has reached 10000 cents (one hundred dollars), in
    which case it goes directly to `HOLD_REFERRED` instead."

    Design: Difficulty/non_linear_state_machine/violation_branching_fork_join
    """
    ctx1 = setup_unregistered_plate_violation(
        base_rate_cents=800, image_fee_cents=100, plaza_code="P1", plate_number="UNREG1"
    )
    away = ctx1["away"]
    create_rate_schedule(
        away["id"], plaza_code="P2", base_rate_cents=2000, image_fee_cents=100,
        effective_to="2027-01-01T00:00:00Z",
    )
    post_image_trip(away["id"], "P2", "UNREG2", "PA", "2026-09-01T09:30:00Z", "u2")
    bill2 = find_pending_image_bill()
    resolve_bill_to_violation(bill2["id"])
    vios, _ = validate_paginated(api_client.list_violations(VO))
    assert len(vios) == 2
    v_pay = ctx1["violation"]
    v_hold = next(v for v in vios if v["id"] != v_pay["id"])

    for v in (v_pay, v_hold):
        issue_notice(v["id"])
    advance_days(30)
    for v in (v_pay, v_hold):
        issue_notice(v["id"])
    advance_days(30)
    for v in (v_pay, v_hold):
        issue_notice(v["id"])
    advance_days(1)

    # Fork 1: pay the escalated one (900+8000 = 8900 < 10000 -> ESCALATED).
    resp = api_client.pay_violation(v_pay["id"], VO)
    assert resp.status_code == 200
    paid = _get_violation(v_pay["id"])
    assert paid["status"] == "PAID"
    assert paid["total_outstanding_cents"] == 0

    # Fork 2: the other went straight to HOLD_REFERRED (2100+8000 = 10100).
    hold = _get_violation(v_hold["id"])
    assert hold["status"] == "HOLD_REFERRED"
    assert hold["registration_hold_referred"] is True
    assert hold["total_outstanding_cents"] == 10100


def test_fourth_notice_rejected_at_limit():
    """PRD §3.7: "The second and third notices keep the violation in `NOTICED`
    and each require two things: `notice_count` must currently be one or two (a
    fourth notice is rejected with `ERR_NOTICE_LIMIT_REACHED`), and at least 30
    days must have elapsed since the previous notice — issuing too early is
    rejected with `ERR_NOTICE_TOO_SOON`. The second notice adds 2500 cents and
    the third adds 5000 cents to `admin_fees_cents`."

    Design: Corner/state_machines/fourth_notice_rejected_at_limit
    """
    ctx = setup_unregistered_plate_violation(
        base_rate_cents=800, image_fee_cents=100, plaza_code="P1", plate_number="UNREG7"
    )
    v = ctx["violation"]
    notice_three_times(v["id"])

    # Immediately attempt the 4th notice while still NOTICED (no sweep has
    # fired yet): notice_count==3 must be rejected with ERR_NOTICE_LIMIT_REACHED.
    resp = api_client.issue_notice(v["id"], VO)
    validate_error(resp, ApiErrorId.ERR_NOTICE_LIMIT_REACHED)

    vio = _get_violation(v["id"])
    assert vio["notice_count"] == 3
    assert vio["admin_fees_cents"] == 8000
    # toll (image gross = base 800 + image_fee 100 = 900) + admin fees 8000.
    assert vio["total_outstanding_cents"] == 8900


def test_temporal_vs_constraint_on_notice_issue():
    """PRD §3.7: "at least 30 days must have elapsed since the previous notice
    — issuing too early is rejected with `ERR_NOTICE_TOO_SOON`."
    PRD §2.8: "then whether the target resource's current state permits the
    requested transition (`ERR_INVALID_STATE_TRANSITION`). Only after those
    generic checks do business rules run"
    PRD §3.7: "Both `PAID` and `DISMISSED` are terminal."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_notice_issue
    """
    away = create_away_agency()
    provider = create_home_agency()
    create_plate_agreement(
        away["id"], provider["id"],
        covers_states=["PA"],
        effective_to="2027-01-01T00:00:00Z",
    )
    create_rate_schedule(
        away["id"], plaza_code="P1", base_rate_cents=800, image_fee_cents=100,
        effective_to="2027-01-01T00:00:00Z",
    )
    post_image_trip(away["id"], "P1", "UNREG3", "PA", "2026-09-01T09:00:00Z", "u3")
    post_image_trip(away["id"], "P1", "UNREG4", "PA", "2026-09-01T09:30:00Z", "u4")
    resp = api_client.list_image_bills(PL, params={"status": "PENDING_LOOKUP"})
    bills, _ = validate_paginated(resp)
    assert len(bills) == 2
    for b in bills:
        resolve_bill_to_violation(b["id"])
    vios, _ = validate_paginated(api_client.list_violations(VO))
    assert len(vios) == 2
    v_temp, v_state = vios[0]["id"], vios[1]["id"]

    issue_notice(v_temp)
    issue_notice(v_state)
    advance_days(5)
    get_success_data(api_client.pay_violation(v_state, VO))
    advance_days(5)

    # Temporal (10 days elapsed): too soon on the NOTICED violation.
    resp1 = api_client.issue_notice(v_temp, VO)
    validate_error(resp1, ApiErrorId.ERR_NOTICE_TOO_SOON)

    # State (priority 4) beats temporal on the PAID (terminal) violation.
    resp2 = api_client.issue_notice(v_state, VO)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_plate_lookup_agent_cannot_issue_notices():
    """PRD §4: notice issuance is listed under ViolationsOfficer only.
    PRD §2.1: "If the named role is not permitted to call the endpoint, the
    request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/roles/plate_lookup_agent_cannot_issue_notices
    """
    ctx = setup_unregistered_plate_violation(
        base_rate_cents=800, image_fee_cents=100, plaza_code="P1", plate_number="UNREG8"
    )
    v = ctx["violation"]
    resp = api_client.issue_notice(v["id"], PL)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert _get_violation(v["id"])["notice_count"] == 0
