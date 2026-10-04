"""Closing-statement calculation, dual variants, and the closing cascade.

Covers the difficulty-design instances for dual_variant_calc,
combinatorial_formula (closing order), transitive_cascade (close), and the
consistency-model corner.
"""
from test_helpers import (
    ADMIN, BOR, MB, TA,
    AgentStatus, ClosingLineType, ClosingLineVariant, EntryKind, EntryStatus,
    ReferralStatus, TransactionStatus,
    assert_agent, assert_office, assert_transaction,
    create_active_agent, create_agent, create_offer, create_second_office,
    create_transaction_under_contract, create_cda, approve_cda_fully,
    get_success_data, is_iso8601_timestamp,
    list_agent_invoice_rows, propose_and_accept_assignment,
    set_clock, setup_office_with_active_agent, setup_office_with_schedule,
    setup_office_with_two_active_agents, setup_pending_close_transaction,
    validate_error, validate_paginated, validate_success,
    make_agent_headers, generate_september_invoices, create_referral_agreement_payload,
    api_client,
)


def _lines_by_type(api, txn_id, headers=TA):
    rows, _meta = validate_paginated(
        api.list_transaction_closing_lines(txn_id, headers))
    by_type = {}
    for row in rows:
        by_type.setdefault(row["line_type"], []).append(row)
    return rows, by_type


def test_closing_statement_standard_variant_computes_pinned_line_amounts(api):
    """PRD §3.7: "Multiply the net GCI by the schedule's `overhead_share_bps`,
    divide by 10000, and round half-up to whole cents to obtain
    `overhead_share_cents`."
    PRD §3.7: "The office's remainder is the net GCI minus the agent retention
    minus the overhead share."
    PRD §3.7: "The `STANDARD` variant applies when the selling agent is
    `ACTIVE` at close: the full formula above runs and the disbursement entries
    are posted as agent-payable."

    Design: Difficulty/dual_variant_calc/closing_statement_standard_vs_former_agent_overhead_waiver
    """
    ctx = setup_pending_close_transaction()
    resp = api.close_transaction(ctx["txn"]["id"], MB)
    txn = validate_success(resp)
    assert txn["status"] == TransactionStatus.CLOSED.value

    rows, by_type = _lines_by_type(api, ctx["txn"]["id"])
    assert all(r["variant"] == ClosingLineVariant.STANDARD.value for r in rows)
    assert all(r["status"] == "FINAL" for r in rows)

    amounts = {}
    for ltype, group in by_type.items():
        total = sum(r["amount_cents"] for r in group)
        amounts[ltype] = total
    # PRD pins the magnitudes (referral off gross, retention/overhead off net)
    # and that the signed lines sum to zero; the sign convention itself
    # (GCI positive vs distributions positive) is not pinned by the PRD, so
    # magnitudes are asserted sign-agnostically.
    assert abs(amounts[ClosingLineType.GCI.value]) == 1000000
    assert abs(amounts[ClosingLineType.REFERRAL_FEE.value]) == 250000
    assert abs(amounts[ClosingLineType.AGENT_RETENTION.value]) == 712500
    assert abs(amounts[ClosingLineType.OVERHEAD_SHARE.value]) == 37500
    assert amounts[ClosingLineType.OFFICE_SPLIT.value] == 0
    assert sum(r["amount_cents"] for r in rows) == 0

    # Standard variant routes retention into an AGENT_PAYABLE entry.
    entries, _m = validate_paginated(api.list_commission_entries(
        TA, params={"transaction_id": ctx["txn"]["id"]}))
    payable = [e for e in entries
               if e["entry_kind"] == EntryKind.AGENT_DISBURSEMENT.value
               and e["status"] == EntryStatus.AGENT_PAYABLE.value]
    assert payable, "expected an AGENT_DISBURSEMENT entry in AGENT_PAYABLE status"


def test_closing_statement_former_agent_variant_waives_overhead(api):
    """PRD §3.7: "The `FORMER_AGENT` variant applies when the selling agent is
    in `TERMINATION_PENDING` or `TERMINATED` at close: the retention figure is
    computed identically, but it is routed into departure-hold ledger entries
    rather than agent-payable ones, and the overhead share is waived entirely —
    departing agents do not carry overhead share, so the `OVERHEAD_SHARE` line
    is zero."

    Design: Difficulty/dual_variant_calc/closing_statement_standard_vs_former_agent_overhead_waiver
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    bob = create_active_agent(
        office["id"], schedule, name="Bob Agent", email="bob@x.com",
        license_number="LIC-B-002")

    # Two transactions, one per seller, both PENDING_CLOSE with approved CDAs.
    offer_a, txn_a = create_transaction_under_contract(office["id"], alice,
                                                       listing_reference="L-100")
    cda_a = create_cda(txn_a["id"])
    approve_cda_fully(cda_a["id"])
    validate_success(api.request_close(txn_a["id"], make_agent_headers(alice["id"])))

    offer_b, txn_b = create_transaction_under_contract(office["id"], bob,
                                                       listing_reference="L-200")
    cda_b = create_cda(txn_b["id"])
    approve_cda_fully(cda_b["id"])
    validate_success(api.request_close(txn_b["id"], make_agent_headers(bob["id"])))

    # Bob initiates termination AFTER his CDA approved but BEFORE his close.
    validate_success(api.terminate_agent(bob["id"], make_agent_headers(bob["id"])))

    validate_success(api.close_transaction(txn_a["id"], MB))
    validate_success(api.close_transaction(txn_b["id"], MB))

    rows_a, by_a = _lines_by_type(api, txn_a["id"])
    rows_b, by_b = _lines_by_type(api, txn_b["id"])
    assert all(r["variant"] == ClosingLineVariant.STANDARD.value for r in rows_a)
    assert all(r["variant"] == ClosingLineVariant.FORMER_AGENT.value for r in rows_b)

    def amounts(by):
        return {lt: sum(r["amount_cents"] for r in grp) for lt, grp in by.items()}

    amt_a, amt_b = amounts(by_a), amounts(by_b)
    # Magnitudes pinned by PRD §3.7; sign convention is not (the PRD pins only
    # that the signed lines sum to zero), so magnitudes assert with abs().
    assert abs(amt_a[ClosingLineType.REFERRAL_FEE.value]) == 250000
    assert abs(amt_a[ClosingLineType.AGENT_RETENTION.value]) == 712500
    assert abs(amt_a[ClosingLineType.OVERHEAD_SHARE.value]) == 37500
    assert amt_a[ClosingLineType.OFFICE_SPLIT.value] == 0
    assert abs(amt_b[ClosingLineType.REFERRAL_FEE.value]) == 250000
    assert abs(amt_b[ClosingLineType.AGENT_RETENTION.value]) == 712500
    assert amt_b[ClosingLineType.OVERHEAD_SHARE.value] == 0
    assert abs(amt_b[ClosingLineType.OFFICE_SPLIT.value]) == 37500
    assert sum(r["amount_cents"] for r in rows_a) == 0
    assert sum(r["amount_cents"] for r in rows_b) == 0

    # Bob's retention is routed into a DEPARTURE_HOLD entry.
    entries_b, _m = validate_paginated(api.list_commission_entries(
        TA, params={"transaction_id": txn_b["id"]}))
    holds = [e for e in entries_b
             if e["entry_kind"] == EntryKind.AGENT_DISBURSEMENT.value
             and e["status"] == EntryStatus.DEPARTURE_HOLD.value]
    assert holds, "former-agent retention must be routed to DEPARTURE_HOLD entries"


def test_closing_statement_pinned_evaluation_order_overhead_off_net_gci(api):
    """PRD §3.7: "The closing-statement calculation is pinned in evaluation
    order because the overhead share keys off net GCI rather than gross: the
    overhead line can only be computed once the referral tier has been
    removed."
    PRD §3.7: "The office's remainder is the net GCI minus the agent retention
    minus the overhead share."

    Design: Difficulty/combinatorial_formula/closing_statement_pinned_evaluation_order_overhead_off_net_gci
    """
    ctx = setup_pending_close_transaction()
    validate_success(api.close_transaction(ctx["txn"]["id"], MB))
    rows, by_type = _lines_by_type(api, ctx["txn"]["id"])

    amounts = {lt: sum(r["amount_cents"] for r in grp) for lt, grp in by_type.items()}
    # PRD §3.7 pins the magnitudes and the evaluation order (referral off
    # gross; retention and overhead off net), and that the signed lines sum
    # to zero; the sign convention itself is not pinned, so use abs().
    assert abs(amounts[ClosingLineType.GCI.value]) == 1000000
    # Referral computed first, off gross.
    assert abs(amounts[ClosingLineType.REFERRAL_FEE.value]) == 250000
    # Retention off net 750000.
    assert abs(amounts[ClosingLineType.AGENT_RETENTION.value]) == 712500
    # Overhead off net 750000 — NOT 50000 off gross.
    assert abs(amounts[ClosingLineType.OVERHEAD_SHARE.value]) == 37500
    # Residual last.
    assert amounts[ClosingLineType.OFFICE_SPLIT.value] == 0
    # Signed lines sum to zero.
    assert sum(r["amount_cents"] for r in rows) == 0


def test_closing_statement_line_amounts_are_signed_and_sum_to_zero(api):
    """PRD §3.7: "Each line is signed so that the sum over all lines of a
    closed statement equals zero."

    Design: Difficulty/combinatorial_formula/closing_statement_pinned_evaluation_order_overhead_off_net_gci
    """
    ctx = setup_pending_close_transaction()
    validate_success(api.close_transaction(ctx["txn"]["id"], MB))
    rows, _by = _lines_by_type(api, ctx["txn"]["id"])
    assert len(rows) >= 5, f"expected the full line set, got {len(rows)} rows"
    total = sum(r["amount_cents"] for r in rows)
    assert total == 0, f"closing statement lines must sum to zero, got {total}"
    # Office-side lines carry a null agent_id; agent-side lines name the agent.
    for r in rows:
        if r["line_type"] in (ClosingLineType.REFERRAL_FEE.value,
                              ClosingLineType.OFFICE_SPLIT.value):
            assert r.get("agent_id") is None, (
                f"office-side line {r['line_type']} must carry null agent_id")


def test_close_cascade_posts_receipt_split_and_fulfills_referral(api):
    """PRD §3.8: "The first hop posts a `GCI_RECEIPT` entry in `ESCROW_HELD`
    status for the gross commission income arriving into trust. The second hop
    splits the receipt: an `AGENT_DISBURSEMENT` entry per agent in
    `AGENT_PAYABLE` status for the agent's disbursement, and an
    `OFFICE_FEE_ACCRUAL` entry in `OFFICE_FEE_ACCRUED` status for the office's
    split and fee accrual. The third hop fires only when an `ACTIVE` referral
    agreement covers the deal: a `REFERRAL_PAYOUT` entry in `REFERRAL_PAYABLE`
    status for the cross-office fee, and the covering referral agreement is
    advanced to `FULFILLED` with `fulfilled_transaction_id` set to the closing
    transaction (see §3.11)."

    Design: Difficulty/transitive_cascade/close_cascade_receipt_to_split_to_referral_fulfillment
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    office2 = create_second_office()
    # Cross-market referral: Phoenix refers into Denver, agent Alice, 2000 bps.
    ref = get_success_data(api.create_referral_agreement(
        create_referral_agreement_payload(
            referring_office_id=office2["id"], receiving_office_id=office["id"],
            agent_id=alice["id"], referral_fee_bps=2000), MB))
    validate_success(api.accept_referral_agreement(ref["id"], MB))

    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    approve_cda_fully(cda["id"])
    validate_success(api.request_close(txn["id"], make_agent_headers(alice["id"])))
    validate_success(api.close_transaction(txn["id"], MB))

    entries, _m = validate_paginated(api.list_commission_entries(
        TA, params={"transaction_id": txn["id"]}))

    def amounts_for(kind, status):
        return [e["amount_cents"] for e in entries
                if e["entry_kind"] == kind and e["status"] == status]

    # Hop 1: receipt held in escrow.
    assert amounts_for(EntryKind.GCI_RECEIPT.value, EntryStatus.ESCROW_HELD.value) == [1000000]
    # Hop 2: split computed off net 800000 because the agreement's 2000 bps
    # overrides the schedule's 2500 bps.
    assert amounts_for(EntryKind.AGENT_DISBURSEMENT.value, EntryStatus.AGENT_PAYABLE.value) == [760000]
    assert amounts_for(EntryKind.OFFICE_FEE_ACCRUAL.value, EntryStatus.OFFICE_FEE_ACCRUED.value) == [40000]
    assert amounts_for(EntryKind.REFERRAL_PAYOUT.value, EntryStatus.REFERRAL_PAYABLE.value) == [200000]

    # Hop 3: the covering agreement is fulfilled with the transaction stamped.
    agreement = validate_success(api.get_referral_agreement(ref["id"], MB))
    assert agreement["status"] == ReferralStatus.FULFILLED.value
    assert agreement["fulfilled_transaction_id"] == txn["id"]


def test_close_cascade_referral_entries_visible_via_transaction_filter(api):
    """PRD §3.8: "The ledger can be read entry-by-entry or listed per office,
    with `office_id`, `transaction_id`, `status`, `entry_kind`, and
    `entry_month` filters;"

    Design: Difficulty/transitive_cascade/close_cascade_receipt_to_split_to_referral_fulfillment
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    office2 = create_second_office()
    ref = get_success_data(api.create_referral_agreement(
        create_referral_agreement_payload(
            referring_office_id=office2["id"], receiving_office_id=office["id"],
            agent_id=alice["id"], referral_fee_bps=2000), MB))
    validate_success(api.accept_referral_agreement(ref["id"], MB))
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    approve_cda_fully(cda["id"])
    validate_success(api.request_close(txn["id"], make_agent_headers(alice["id"])))
    validate_success(api.close_transaction(txn["id"], MB))

    entries, _m = validate_paginated(api.list_commission_entries(
        TA, params={"transaction_id": txn["id"]}))
    kinds = {e["entry_kind"] for e in entries}
    assert kinds == {
        EntryKind.GCI_RECEIPT.value,
        EntryKind.AGENT_DISBURSEMENT.value,
        EntryKind.OFFICE_FEE_ACCRUAL.value,
        EntryKind.REFERRAL_PAYOUT.value,
    }
    statuses = {(e["entry_kind"], e["status"]) for e in entries}
    assert (EntryKind.GCI_RECEIPT.value, EntryStatus.ESCROW_HELD.value) in statuses
    assert (EntryKind.AGENT_DISBURSEMENT.value, EntryStatus.AGENT_PAYABLE.value) in statuses
    assert (EntryKind.OFFICE_FEE_ACCRUAL.value, EntryStatus.OFFICE_FEE_ACCRUED.value) in statuses
    assert (EntryKind.REFERRAL_PAYOUT.value, EntryStatus.REFERRAL_PAYABLE.value) in statuses


def test_close_effects_visible_immediately_in_same_read(api):
    """PRD §3.8: "Within the same close, the advance-recovery waterfall (§3.9)
    is applied against the agent's open balances, and the transaction's
    `version` is incremented."
    PRD §3.7: "In both variants the closing statement lines are born
    `PROVISIONAL` and finalize atomically with the close, ending in `FINAL`."

    Design: Corner/consistency_model/immediate_consistency_close_effects_visible_in_same_read
    """
    ctx = setup_pending_close_transaction()
    resp = api.close_transaction(ctx["txn"]["id"], MB)
    txn = validate_success(resp)
    assert txn["status"] == TransactionStatus.CLOSED.value
    assert is_iso8601_timestamp(txn["closed_at"])

    rows, _m = validate_paginated(
        api.list_transaction_closing_lines(txn["id"], TA))
    assert rows, "closing lines must be visible immediately after close"
    assert all(r["status"] == "FINAL" for r in rows)

    entries, _m = validate_paginated(api.list_commission_entries(
        TA, params={"transaction_id": txn["id"]}))
    kinds = {e["entry_kind"] for e in entries}
    assert EntryKind.GCI_RECEIPT.value in kinds
    assert EntryKind.AGENT_DISBURSEMENT.value in kinds
    assert EntryKind.OFFICE_FEE_ACCRUAL.value in kinds
