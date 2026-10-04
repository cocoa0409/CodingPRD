"""Statement payment rules: dispute deadline, fiscal floor on adjustments,
pay gating, the compound pool-paid derivation, and the exit fiscal blocker."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, api_client,
    set_clock, get_pool, get_statement, get_planting, complete_planting,
    dispute_statement, resolve_statement, pay_statement, exit_grower,
    make_grower_principal_headers,
)
from test_10_pool_close_membership import _corner_pool

SETTLEMENT = TEST_USERS["settlement_officer_headers"]


def test_dispute_window_expired_on_issued_statement(api):
    """PRD section 3.9: "the logical clock must not have passed
    `dispute_deadline`, or the dispute is rejected with
    `ERR_DISPUTE_WINDOW_EXPIRED`."
    PRD section 3.9: "Issuance stamps `issued_at` from the logical clock and
    sets `dispute_deadline` to `issued_at` plus fourteen days."

    Design: Corner/validations/dispute_window_expired_on_issued_statement
    """
    s = _corner_pool(api, settle=True)  # stmt ISSUED, deadline 2026-10-26
    stmt = s["statement"]
    assert stmt["status"] == "ISSUED"
    set_clock("2026-10-27T00:00:01Z")
    resp = api_client.dispute_statement(
        stmt["id"], {"reason": "late dispute"},
        make_grower_principal_headers(s["bundle"]["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)
    current = get_statement(stmt["id"])
    assert current["status"] == "ISSUED"
    assert current["dispute_count"] == 0


def test_negative_settlement_adjustment_rejected(api):
    """PRD section 3.9: "An `ADJUST` resolution applies a signed
    `adjustment_cents`: the adjustment must not be zero (`ERR_INVALID_REQUEST`),
    and it must not drive `net_cents` below zero (`ERR_NEGATIVE_SETTLEMENT`)."

    Design: Corner/validations/negative_settlement_adjustment_rejected
    """
    s = _corner_pool(api, settle=True)  # net 562120
    stmt = s["statement"]
    dispute_statement(stmt["id"], s["bundle"]["grower"], reason="audit dispute")
    resp = api_client.resolve_statement(
        stmt["id"], {"resolution": "ADJUST", "adjustment_cents": -562121},
        SETTLEMENT)
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_SETTLEMENT)
    current = get_statement(stmt["id"])
    assert current["status"] == "DISPUTED"
    assert current["net_cents"] == 562120
    assert current["adjustment_total_cents"] == 0


def test_pay_before_dispute_deadline_rejected(api):
    """PRD section 3.9: "An `ISSUED` statement can be paid only once the logical
    clock has passed its `dispute_deadline`; before that — and for statements
    in `PROVISIONAL` or `DISPUTED` — payment is rejected with
    `ERR_STATEMENT_NOT_PAYABLE`."

    Design: Corner/errors/pay_before_dispute_deadline_rejected
    """
    s = _corner_pool(api, settle=True)  # clock still 2026-10-12
    stmt = s["statement"]
    resp = api_client.pay_statement(stmt["id"], SETTLEMENT)
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_PAYABLE)
    current = get_statement(stmt["id"])
    assert current["status"] == "ISSUED"
    assert current["paid_at"] is None
    assert current["net_cents"] == 562120


def test_pool_marked_paid_when_last_statement_paid(api):
    """PRD section 3.9: "Payment moves the statement to `PAID` and stamps
    `paid_at` from the logical clock. When the last unpaid statement of a pool
    reaches `PAID`, the pool itself derives `SETTLED → PAID` automatically,
    and `PAID` is terminal for both resources."

    Design: Corner/state_machines/pool_marked_paid_when_last_statement_paid
    """
    s = _corner_pool(api, settle=True)
    stmt = s["statement"]
    assert stmt["net_cents"] == 562120
    assert stmt["dispute_deadline"].startswith("2026-10-26")
    assert get_pool(s["pool"]["id"])["status"] == "SETTLED"
    set_clock("2026-10-27T00:00:01Z")  # past the dispute deadline
    paid = pay_statement(stmt["id"])
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None
    pool = get_pool(s["pool"]["id"])
    assert pool["status"] == "PAID", "the pool's only statement is PAID"


def test_grower_cannot_pay_own_statement(api):
    """PRD section 2.1: "`SettlementOfficer` operates pool settlement: opening,
    closing, and settling pools, and resolving and paying statements."
    PRD section 2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/grower_cannot_pay_own_statement
    """
    s = _corner_pool(api, settle=True)
    stmt = s["statement"]
    set_clock("2026-10-27T00:00:01Z")  # past the dispute deadline
    resp = api_client.pay_statement(
        stmt["id"],
        make_grower_principal_headers(s["bundle"]["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_statement(stmt["id"])["status"] == "ISSUED"


def test_exit_blocked_by_unsettled_statements(api):
    """PRD section 3.2: "if any settlement statement of this grower has a
    `status` other than `PAID`, it is rejected with
    `ERR_GROWER_HAS_UNSETTLED_STATEMENTS`."

    Design: Corner/errors/exit_blocked_by_unsettled_statements
    """
    s = _corner_pool(api, settle=True)  # H1 SETTLED, HY GRADED
    grower = s["bundle"]["grower"]
    planting = get_planting(s["bundle"]["planting"]["id"])
    done = complete_planting(planting, grower)
    assert done["status"] == "COMPLETED", "no live plantings remain"
    resp = api_client.exit_grower(grower["id"], TEST_USERS["compliance_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_GROWER_HAS_UNSETTLED_STATEMENTS)
