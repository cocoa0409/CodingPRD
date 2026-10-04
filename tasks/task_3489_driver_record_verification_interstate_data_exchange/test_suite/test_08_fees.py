"""Association dues: the provisional and audited assessments, the dispute
loop, exact-change settlement, and the audit reconciliation."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    AUDIT_AUTHORITY_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fee_invoice,
    create_jurisdiction,
    dispute_invoice,
    fee_invoice_payload,
    finalize_audit,
    issue_fee_invoice,
    list_jurisdiction_invoices,
    make_jurisdiction_registrar_headers,
    reissue_invoice,
    settle_payload,
    setup_certified_jurisdiction,
    setup_invoice,
)


def test_dues_provisional_vs_audited_settlement(api):
    """PRD §3.8: "The provisional amount is then the 2,500,000-cent base fee plus the
    transaction fee scaled by the multiplier, capped at 20,000,000 cents, and rounded
    half up to whole cents exactly once, after the cap."
    PRD §3.8: "for each quarter in turn, the charge is one quarter of the 2,500,000-cent
    base fee plus the same three-bracket marginal fee priced on that quarter's volume
    and scaled by the multiplier — but with `n` taken as the jurisdiction's current
    `certified_systems_count` at audit time rather than the pinned snapshot — and each
    quarter's charge is rounded half up to whole cents before the four rounded quarters
    are summed into `final_amount_cents`."
    PRD §3.8: "The `adjustment_amount_cents` is the final amount minus the settled
    amount: positive means an underpayment still due from the jurisdiction, negative
    means a credit owed back to it."

    Design: Difficulty/dual_variant_calc/dues_provisional_vs_audited_settlement
    """
    # One certified system -> multiplier exactly 1.00 on both variants here.
    ctx = setup_invoice(api, code="AA", projected_volume=8000, stage="SETTLED")
    assert ctx["provisional_amount_cents"] == 2600000, (
        "single annual rounding: 2500000 + 12.5 * 8000 * 1.00"
    )
    audited = finalize_audit(api, ctx["invoice_id"], [1000, 2000, 3000, 4000])
    assert_fee_invoice(audited)
    assert audited["status"] == "AUDITED"
    # Per-quarter rounding: 637500 + 650000 + 662500 + 675000.
    assert audited["final_amount_cents"] == 2625000
    assert audited["settled_amount_cents"] == 2600000
    assert audited["provisional_amount_cents"] == 2600000
    assert audited["adjustment_amount_cents"] == 25000


def test_dues_multiplier_tier_cap_interplay(api):
    """PRD §3.8: "The multiplier starts at one and drops by five hundredths for each
    certified system beyond the first — one certified system multiplies by exactly 1,
    two by 0.95, three by 0.90 — but never falls below the floor of 0.85, which binds
    from four systems onward."
    PRD §3.8: "the first ten thousand transactions at 12.5 cents each, the next forty
    thousand — from the ten-thousand-and-first through the fifty-thousandth — at 10.5
    cents each, and every transaction beyond the fifty-thousandth at 8.5 cents each,
    with any bracket the volume does not reach contributing nothing."
    PRD §3.8: "At issuance the server pins `certified_count_at_issue` to the
    jurisdiction's current `certified_systems_count` and computes the
    `provisional_amount_cents`".

    Design: Difficulty/combinatorial_formula/dues_multiplier_tier_cap_interplay
    """
    ctx = setup_certified_jurisdiction(
        api, code="AA", systems=("POINTER_NETWORK", "TITLE_NETWORK")
    )
    invoice = issue_fee_invoice(api, ctx["jurisdiction_id"], 2027, 60000)
    assert_fee_invoice(invoice)
    assert invoice["status"] == "ISSUED"
    assert invoice["certified_count_at_issue"] == 2
    # fee(60000) = 125000 + 420000 + 85000 = 630000; 2500000 + 630000 * 0.95.
    assert invoice["provisional_amount_cents"] == 3098500


def test_audit_quarterly_rounding_order(api):
    """PRD §3.8: "each quarter's charge is rounded half up to whole cents before the
    four rounded quarters are summed into `final_amount_cents`. Summing first and
    rounding once would be a different, incorrect result whenever a quarter's raw charge
    lands on a fractional cent".

    Design: Difficulty/combinatorial_formula/audit_quarterly_rounding_order
    """
    ctx = setup_invoice(api, code="AA", projected_volume=14, stage="SETTLED")
    # Annual single rounding: 2500000 + 12.5 * 14 = 2500175.
    assert ctx["provisional_amount_cents"] == 2500175
    audited = finalize_audit(api, ctx["invoice_id"], [7, 7, 0, 0])
    assert_fee_invoice(audited)
    # Each 7-transaction quarter rounds 625087.5 up to 625088; the two empty quarters
    # contribute 625000 each: 625088 + 625088 + 625000 + 625000.
    assert audited["final_amount_cents"] == 2500176
    assert audited["adjustment_amount_cents"] == 1, (
        "the one-cent delta exists only because rounding happens per quarter"
    )


def test_settle_then_audit_conserves_recognized_dues(api):
    """PRD §3.8: "The `adjustment_amount_cents` is the final amount minus the settled
    amount: positive means an underpayment still due from the jurisdiction, negative
    means a credit owed back to it."
    PRD §3.8: "An `AuditAuthority` finalizes a `SETTLED` invoice by supplying
    `actual_volume_quarters` — exactly four non-negative integer volumes in quarter
    order, first quarter through fourth, anything else rejected as
    `ERR_INVALID_REQUEST` — moving the invoice `SETTLED` → `AUDITED`, its terminal
    state."

    Design: Difficulty/compensating_invariant/settle_then_audit_conserves_recognized_dues
    """
    ctx = setup_invoice(api, code="AA", projected_volume=8000, stage="SETTLED")
    audited = finalize_audit(api, ctx["invoice_id"], [1000, 2000, 3000, 4000])
    assert audited["status"] == "AUDITED", "the audited state is terminal"
    assert audited["final_amount_cents"] == 2625000
    assert audited["adjustment_amount_cents"] == 25000
    assert (
        audited["settled_amount_cents"] + audited["adjustment_amount_cents"]
        == audited["final_amount_cents"]
    ), "settled 2600000 + adjustment 25000 reconciles to the final 2625000"


def test_fee_invoice_dispute_reissue_loop(api):
    """PRD §3.8: "A registrar of the invoiced jurisdiction may dispute an `ISSUED`
    invoice with a `reason`; the invoice moves `ISSUED` → `DISPUTED` and the reason is
    recorded as `dispute_reason`."
    PRD §3.8: "an administrator supplies a corrected `projected_volume`, the provisional
    amount is recomputed — still with the multiplier built from the original pinned
    `certified_count_at_issue`, even if the live certified count has moved since first
    issuance — the `dispute_reason` is cleared to null, and the invoice returns
    `DISPUTED` → `ISSUED`. This dispute loop may repeat."

    Design: Corner/state_machines/fee_invoice_dispute_reissue_loop
    """
    ctx = setup_invoice(api, code="AA", projected_volume=8000, stage="DISPUTED")
    reissued = reissue_invoice(api, ctx["invoice_id"], 60000)
    assert_fee_invoice(reissued)
    assert reissued["status"] == "ISSUED", "the dispute loop closed"
    # Pinned n stays 1 -> multiplier 1.00: 2500000 + 630000 * 1.00.
    assert reissued["provisional_amount_cents"] == 3130000
    assert reissued["certified_count_at_issue"] == 1
    assert reissued["dispute_reason"] is None
    rows, meta = list_jurisdiction_invoices(api, ctx["jurisdiction_id"])
    assert meta["total_count"] == 1 and rows[0]["id"] == ctx["invoice_id"]


def test_settle_issued_invoice_wrong_amount_returns_fee_mismatch(api):
    """PRD §3.8: "Settlement is exact-change only. A registrar of the invoiced
    jurisdiction settles with an `amount_cents` that must equal the
    `provisional_amount_cents` to the cent; any other figure is rejected with
    `ERR_FEE_AMOUNT_MISMATCH`."

    Design: Corner/validations/settle_issued_invoice_wrong_amount_returns_fee_mismatch
    """
    ctx = setup_invoice(api, code="AA", projected_volume=8000, stage="ISSUED")
    assert ctx["provisional_amount_cents"] == 2600000
    resp = api.settle_invoice(
        ctx["invoice_id"],
        settle_payload(2599999),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH)
    rows, _ = list_jurisdiction_invoices(api, ctx["jurisdiction_id"])
    assert rows[0]["status"] == "ISSUED", "a rejected settle leaves the invoice ISSUED"


def test_settle_disputed_invoice_state_beats_fiscal(api):
    """PRD §2.6: "Every mutating request passes through the same ordered gauntlet of
    checks, and the order is part of the contract: when several checks could reject the
    same request, the first failing rung on this ladder determines which error
    surfaces."
    PRD §2.6: "**State-machine arcs.** The target resource must be in a state from which
    the requested transition is declared." (rung 6) sits above "**Fiscal integrity.**
    Settlement amounts must match the assessed amount to the cent, else
    `ERR_FEE_AMOUNT_MISMATCH` (HTTP 402)." (rung 11).

    Design: Difficulty/priority_pair_validation_conflict/settle_disputed_invoice_state_beats_fiscal
    """
    ctx = setup_invoice(api, code="AA", projected_volume=8000, stage="DISPUTED")
    resp = api.settle_invoice(
        ctx["invoice_id"],
        settle_payload(999999),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_INVALID_STATE), (
        "the state-arc violation (rung 6) wins over the fiscal violation (rung 11)"
    )
    rows, _ = list_jurisdiction_invoices(api, ctx["jurisdiction_id"])
    assert rows[0]["status"] == "DISPUTED"
    assert rows[0]["settled_amount_cents"] is None, "no partial side effects"


def test_fee_invoice_create_response_includes_computed_provisional(api):
    """PRD §3.8: "At issuance the server pins `certified_count_at_issue` to the
    jurisdiction's current `certified_systems_count` and computes the
    `provisional_amount_cents`; the invoice is created `ISSUED`, with `dispute_reason`,
    `settled_amount_cents`, `actual_volume_quarters`, and the final audit figures all
    still null."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/fee_invoice_create_response_includes_computed_provisional
    """
    ctx = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    resp = api.create_fee_invoice(
        fee_invoice_payload(ctx["jurisdiction_id"], 2027, 8000),
        ASSOCIATION_ADMIN_HEADERS,
    )
    invoice = assert_created(resp)
    assert_fee_invoice(invoice)
    assert invoice["status"] == "ISSUED"
    assert invoice["certified_count_at_issue"] == 1
    assert invoice["provisional_amount_cents"] == 2600000, (
        "the creation response already carries the computed provisional amount"
    )


def test_settle_unknown_invoice_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_INVOICE_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/settle_unknown_invoice_not_found
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    resp = api.settle_invoice(
        NON_EXISTENT_UUID,
        settle_payload(1),
        make_jurisdiction_registrar_headers(jurisdiction["id"]),
    )
    assert_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)


def test_auditor_cannot_create_fee_invoice(api):
    """PRD §2.1: "`AuditAuthority` is an independent auditor who records judicial
    disqualifications and performs dues audits and, by segregation of duties, may never
    issue invoices."
    PRD §2.1: "a role outside that set is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/auditor_cannot_create_fee_invoice
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    resp = api.create_fee_invoice(
        fee_invoice_payload(jurisdiction["id"], 2027, 8000),
        AUDIT_AUTHORITY_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_fee_settle_by_other_jurisdiction_forbidden(api):
    """PRD §2.6: "When a `JurisdictionRegistrar` acts on a jurisdiction-scoped resource,
    `X-User-ID` must equal the `id` of the jurisdiction that owns — or will own — the
    resource: the record-holding jurisdiction for conviction posting; the issuing
    jurisdiction for license reinstatement; the invoiced jurisdiction for invoice
    dispute and settlement; the `from_jurisdiction_id` for recording a surrender; the
    `to_jurisdiction_id` for initiating, contesting, or completing a license transfer or
    completing a title transfer; and the registrar's own jurisdiction for enrolling in
    a system, claiming a record, issuing a license, titling a vehicle, or requesting a
    re-titling. A mismatch is `ERR_JURISDICTION_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/fee_settle_by_other_jurisdiction_forbidden
    """
    ctx = setup_invoice(api, code="AA", projected_volume=8000, stage="ISSUED")
    other = create_jurisdiction(api, code="BB", name="State B", fee_tier="TIER_2")
    resp = api.settle_invoice(
        ctx["invoice_id"],
        settle_payload(ctx["provisional_amount_cents"]),
        make_jurisdiction_registrar_headers(other["id"]),
    )
    assert_error(resp, ApiErrorId.ERR_JURISDICTION_OWNERSHIP_MISMATCH), (
        "amount correctness is irrelevant when ownership fails"
    )
    rows, _ = list_jurisdiction_invoices(api, ctx["jurisdiction_id"])
    assert rows[0]["status"] == "ISSUED"
