"""Stale product claims: provisional vs cap-applied credit, the NEEDS_INFO
loop, weekly cap consumption, and the decide-state gate.

Covers PRD §3.6 (provisional credit, approve/resubmit/issue, weekly cap).
Instances:
Difficulty/dual_variant_calc/stale_credit_provisional_uncapped_vs_final_capped,
Corner/state_machines/claim_needs_info_resubmit_recomputes_provisional,
Corner/calculations/stale_cap_full_partial_then_exhausted,
Corner/state_machines/decide_on_needs_info_claim_not_reviewable.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_item,
    create_stale_claim,
    decide_claim,
    decide_claim_payload,
    get_distributor,
    issue_credit,
    list_stale_claims,
    order_line,
    resubmit_claim,
    set_clock,
    setup_active_cash_agreement,
    setup_delivered_order,
    setup_submitted_claim,
    validate_error,
)

_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]
_CREDIT = TEST_USERS["credit_analyst_headers"]


def _find_claim(distributor_id: str, claim_id: str) -> dict:
    matches = [c for c in list_stale_claims(distributor_id) if c["id"] == claim_id]
    assert len(matches) == 1, f"claim {claim_id} not found"
    return matches[0]


def test_stale_credit_provisional_is_uncapped(api):
    """PRD §3.6: "each item's base is the eligible quantity multiplied by the
    unit charge and by three quarters — a stale credit rate of 0.75 — rounded
    half-up to whole cents; and the provisional credit is the sum of the item
    bases. The provisional figure is uncapped: the weekly cap described below
    does not apply at filing."
    PRD §3.6: "`APPROVE` recomputes the uncapped credit on the claim's current
    items and freezes it as `approved_credit_cents`, moving the claim to
    `APPROVED`."

    Design: Difficulty/dual_variant_calc/stale_credit_provisional_uncapped_vs_final_capped
    """
    ctx = setup_active_cash_agreement()
    setup_delivered_order(
        ctx, "2026-09-07", [order_line("WHT-24", 5), order_line("BUN-12", 10)]
    )
    set_clock("2026-09-12T09:00:00Z")
    claim = create_stale_claim(
        ctx["distributor"],
        [claim_item("WHT-24", "2026-09-07", 4, "2026-09-12")],
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["provisional_credit_cents"] == 768, (
        "uncapped: round_half_up(4 * 256 * 0.75); the 320 weekly cap does not "
        "apply at filing"
    )
    approved = decide_claim(claim["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["approved_credit_cents"] == 768, (
        "approval freezes the uncapped recompute"
    )


def test_stale_credit_final_applies_weekly_cap(api):
    """PRD §3.6: "When the remaining cap is zero, issuance is rejected with
    `ERR_STALE_CAP_EXHAUSTED`; otherwise the issued amount is the lesser of
    `approved_credit_cents` and the remaining cap, and issuing exactly the
    remaining cap is allowed. The claim moves to `CREDIT_ISSUED` with
    `issued_credit_cents` recording what was actually paid and
    `cap_truncated_cents` recording the approved amount minus the issued
    amount, so a claim approved above the cap visibly issues for less than its
    provisional estimate."
    PRD §2.9: "Exactly three events move it: recording a delivery adds the
    order's computed charge; reconciling a delivered order subtracts the
    verified shortage credit; issuing an approved stale credit subtracts the
    issued amount."

    Design: Difficulty/dual_variant_calc/stale_credit_provisional_uncapped_vs_final_capped
    """
    ctx = setup_active_cash_agreement()
    setup_delivered_order(
        ctx, "2026-09-07", [order_line("WHT-24", 5), order_line("BUN-12", 10)]
    )
    set_clock("2026-09-12T09:00:00Z")
    claim = create_stale_claim(
        ctx["distributor"],
        [claim_item("WHT-24", "2026-09-07", 4, "2026-09-12")],
    )
    decide_claim(claim["id"], "APPROVE")
    issued = issue_credit(claim["id"])
    assert issued["status"] == "CREDIT_ISSUED"
    assert issued["issued_credit_cents"] == 320, (
        "capped: week-37 gross 3200 * 0.10"
    )
    assert issued["cap_truncated_cents"] == 448, "768 - 320"
    assert issued["issued_credit_cents"] != issued["provisional_credit_cents"]
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["trade_balance_cents"] == 2880, "3200 - 320"


def test_claim_needs_info_resubmit_recomputes_provisional(api):
    """PRD §3.6: "`REQUEST_INFO` parks the claim in `NEEDS_INFO`, from which
    the distributor resubmits with a corrected `items` payload; resubmission
    re-runs every submission validation — the timing windows, the eligibility
    ceiling, and the sku check — recomputes `provisional_credit_cents`, and
    returns the claim to `SUBMITTED`."

    Design: Corner/state_machines/claim_needs_info_resubmit_recomputes_provisional
    """
    ctx = setup_active_cash_agreement()
    _, _, claim = setup_submitted_claim(
        ctx,
        "2026-09-07",
        [order_line("BUN-12", 10)],
        [claim_item("BUN-12", "2026-09-07", 2, "2026-09-11")],
        file_clock="2026-09-11T09:00:00Z",
    )
    assert claim["provisional_credit_cents"] == 288, (
        "BUN-12 x2: round_half_up(2 * 192 * 0.75)"
    )
    parked = decide_claim(claim["id"], "REQUEST_INFO")
    assert parked["status"] == "NEEDS_INFO"

    resubmitted = resubmit_claim(
        claim, [claim_item("BUN-12", "2026-09-07", 1, "2026-09-11")]
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["provisional_credit_cents"] == 144, (
        "recomputed from the corrected qty 1"
    )

    decide_claim(claim["id"], "APPROVE")
    issued = issue_credit(claim["id"])
    assert issued["status"] == "CREDIT_ISSUED"
    assert issued["issued_credit_cents"] == 144, "under the weekly cap"
    assert issued["cap_truncated_cents"] == 0
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["trade_balance_cents"] == 1776, "1920 - 144"


def test_stale_cap_full_partial_then_exhausted(api):
    """PRD §3.6: "The cap is 10% of the distributor's gross delivered charges
    whose record-delivery date falls inside that week, rounded half-up to whole
    cents; the used amount is the sum of credits already issued on this
    distributor's claims submitted inside the same week; and the remaining cap
    is the difference. When the remaining cap is zero, issuance is rejected
    with `ERR_STALE_CAP_EXHAUSTED`; otherwise the issued amount is the lesser
    of `approved_credit_cents` and the remaining cap, and issuing exactly the
    remaining cap is allowed."

    Design: Corner/calculations/stale_cap_full_partial_then_exhausted
    """
    ctx = setup_active_cash_agreement()
    # Week-37 gross charges 3200 (WHT-24 x5 + BUN-12 x10 delivered 2026-09-07)
    # -> weekly stale cap round_half_up(0.10 * 3200) == 320.
    setup_delivered_order(
        ctx, "2026-09-07", [order_line("WHT-24", 5), order_line("BUN-12", 10)]
    )
    set_clock("2026-09-11T09:00:00Z")
    dist = ctx["distributor"]

    claim1 = create_stale_claim(
        dist, [claim_item("BUN-12", "2026-09-07", 2, "2026-09-11")]
    )
    decide_claim(claim1["id"], "APPROVE")
    issued1 = issue_credit(claim1["id"])
    assert issued1["issued_credit_cents"] == 288, "base 288 in full"
    assert issued1["cap_truncated_cents"] == 0

    claim2 = create_stale_claim(
        dist, [claim_item("BUN-12", "2026-09-07", 1, "2026-09-11")]
    )
    decide_claim(claim2["id"], "APPROVE")
    issued2 = issue_credit(claim2["id"])
    assert issued2["issued_credit_cents"] == 32, (
        "base 144 truncated to the remaining 320 - 288"
    )
    assert issued2["cap_truncated_cents"] == 112

    claim3 = create_stale_claim(
        dist, [claim_item("BUN-12", "2026-09-07", 1, "2026-09-11")]
    )
    decide_claim(claim3["id"], "APPROVE")
    resp = api_client.issue_credit(claim3["id"], _CREDIT)
    validate_error(resp, ApiErrorId.ERR_STALE_CAP_EXHAUSTED)
    current = _find_claim(dist["id"], claim3["id"])
    assert current["status"] == "APPROVED", "exhausted cap leaves the claim"

    distributor = get_distributor(dist["id"])
    assert distributor["trade_balance_cents"] == 2880, "3200 - 288 - 32"


def test_decide_on_needs_info_claim_not_reviewable(api):
    """PRD §3.6: "Review belongs to a `RouteOpsManager` and only while the
    claim is `SUBMITTED`; deciding a claim in any other state is rejected with
    `ERR_CLAIM_NOT_REVIEWABLE`."

    Design: Corner/state_machines/decide_on_needs_info_claim_not_reviewable
    """
    ctx = setup_active_cash_agreement()
    _, _, claim = setup_submitted_claim(
        ctx,
        "2026-09-04",
        [order_line("WHT-24", 5)],
        [claim_item("WHT-24", "2026-09-04", 1, "2026-09-10")],
        file_clock="2026-09-10T09:00:00Z",
    )
    parked = decide_claim(claim["id"], "REQUEST_INFO", "need pull photos")
    assert parked["status"] == "NEEDS_INFO"

    resp = api_client.decide_claim(
        claim["id"], decide_claim_payload("APPROVE"), _ROUTE_OPS
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE)
    current = _find_claim(ctx["distributor"]["id"], claim["id"])
    assert current["status"] == "NEEDS_INFO"
    assert current["approved_credit_cents"] is None
