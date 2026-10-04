"""Settlement statements: the ISSUED → DISPUTED → ISSUED cycle with refreshed
deadline, the UPHOLD exit to FINAL, and the state-gate-beats-deadline pair."""
from test_helpers import (
    validate_error, ApiErrorId, api_client, make_grower_principal_headers,
    set_clock, get_pool, get_statement,
    dispute_statement, resolve_statement, pay_statement,
)
from test_09_pool_pipeline import _canonical_pool


def test_statement_adjust_reopens_dispute_window(api):
    """PRD section 3.9: "A successful dispute moves the statement `ISSUED →
    DISPUTED`, records `dispute_reason`, increments `dispute_count` by 1 (it
    starts at 0), and increments the statement's `version` by 1."
    PRD section 3.9: "A successful adjustment adds `adjustment_cents` to
    `net_cents` and to `adjustment_total_cents` — the cumulative signed total
    of all adjustments on the statement, starting at 0 — and returns the
    statement `DISPUTED → ISSUED` with `issued_at` refreshed to the logical
    clock and `dispute_deadline` recomputed from the refreshed `issued_at`".

    Design: Difficulty/non_linear_state_machine/statement_dispute_resolve_cycle
    """
    s = _canonical_pool(api, settle=True)
    stmt = s["s1"]
    assert stmt["status"] == "ISSUED"
    assert stmt["net_cents"] == 964093
    assert stmt["dispute_deadline"].startswith("2026-10-26")
    disputed = dispute_statement(stmt["id"], s["g1"],
                                 reason="cold-chain deduction misapplied")
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 1
    adjusted = resolve_statement(stmt["id"], "ADJUST", adjustment_cents=-500)
    assert adjusted["status"] == "ISSUED"
    assert adjusted["net_cents"] == 963593, "964093 - 500"
    assert adjusted["adjustment_total_cents"] == -500
    assert adjusted["resolution"] == "ADJUST"
    assert adjusted["dispute_deadline"].startswith("2026-10-26"), (
        "deadline recomputed from the refreshed issued_at — window re-opened")


def test_statement_cycle_exits_via_uphold_then_pay(api):
    """PRD section 3.9: "An `UPHOLD` resolution moves the statement `DISPUTED
    → FINAL` with no amount changes, incrementing its `version` by 1."
    PRD section 3.9: "A `FINAL` statement can always be paid."
    PRD section 3.9: "When the last unpaid statement of a pool reaches `PAID`,
    the pool itself derives `SETTLED → PAID` automatically".

    Design: Difficulty/non_linear_state_machine/statement_dispute_resolve_cycle
    """
    s = _canonical_pool(api, settle=True)
    stmt = s["s1"]
    dispute_statement(stmt["id"], s["g1"], reason="cold-chain deduction misapplied")
    resolve_statement(stmt["id"], "ADJUST", adjustment_cents=-500)
    second = dispute_statement(stmt["id"], s["g1"],
                               reason="second review of adjusted figures")
    assert second["status"] == "DISPUTED"
    assert second["dispute_count"] == 2, "the window re-opened after ADJUST"
    upheld = resolve_statement(stmt["id"], "UPHOLD")
    assert upheld["status"] == "FINAL"
    assert upheld["net_cents"] == 963593, "UPHOLD changes no amounts"
    assert upheld["resolution"] == "UPHOLD"
    paid = pay_statement(stmt["id"])
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None
    pool = get_pool(s["pool"]["id"])
    assert pool["status"] == "SETTLED", "G2's statement is still ISSUED"


def test_late_dispute_on_final_statement_yields_state_error(api):
    """PRD section 2.8: "Because the state-gate tier outranks the temporal
    tier, disputing a statement that is not currently `ISSUED` yields
    `ERR_STATEMENT_NOT_DISPUTABLE` even when its dispute window has also
    expired; the deadline check only applies once the state gate passes."

    Design: Difficulty/priority_pair_validation_conflict/dispute_state_gate_beats_temporal_gate
    """
    s = _canonical_pool(api, settle=True)
    stmt = s["s1"]
    dispute_statement(stmt["id"], s["g1"], reason="audit dispute")
    resolve_statement(stmt["id"], "UPHOLD")  # → FINAL
    set_clock("2026-10-27T00:00:01Z")  # past the 2026-10-26 deadline
    resp = api_client.dispute_statement(
        stmt["id"], {"reason": "late dispute"},
        make_grower_principal_headers(s["g1"]["id"]))
    err = validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_DISPUTABLE)
    assert err["error_id"] != "ERR_DISPUTE_WINDOW_EXPIRED"
    current = get_statement(stmt["id"])
    assert current["status"] == "FINAL"
    assert current["dispute_count"] == 1


def test_dispute_on_final_statement_within_window_still_state_error(api):
    """PRD section 3.9: "the statement must currently be `ISSUED` — a dispute
    against any other state is rejected with `ERR_STATEMENT_NOT_DISPUTABLE`,
    and this state gate is checked before the deadline gate".

    Design: Difficulty/priority_pair_validation_conflict/dispute_state_gate_beats_temporal_gate
    """
    s = _canonical_pool(api, settle=True)
    stmt = s["s1"]
    dispute_statement(stmt["id"], s["g1"], reason="audit dispute")
    resolve_statement(stmt["id"], "UPHOLD")  # → FINAL, clock still 2026-10-12
    resp = api_client.dispute_statement(
        stmt["id"], {"reason": "second dispute on FINAL"},
        make_grower_principal_headers(s["g1"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_DISPUTABLE)
    current = get_statement(stmt["id"])
    assert current["status"] == "FINAL"
    assert current["dispute_count"] == 1
