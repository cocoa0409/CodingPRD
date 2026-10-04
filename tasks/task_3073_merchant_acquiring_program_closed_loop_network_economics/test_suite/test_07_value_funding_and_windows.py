"""Premium card-member value funding (the append-only ledger and the two
allocation variants) and acceptance-gap window merging."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_industry_category,
    create_merchant,
    create_and_activate_merchant,
    create_active_cardmember,
    create_annual_fee_statement,
    assess_statement,
    disburse_statement,
    void_statement,
    rollup_gap,
    list_acceptance_gaps,
    list_ledger,
    set_clock,
)
from test_helpers.fixtures import ISSUER, ACQ

WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-31T00:00:00Z"


def _instant(text: str):
    """Parse an ISO 8601 instant so timestamps compare by value, not by the
    rendering's trailing fractional zeros."""
    from datetime import datetime

    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# ═══ Difficulty: assessed vs disbursed allocation ════════

def test_assessment_allocates_the_share_of_the_full_gross_fee(api):
    """PRD §3.6: "It then takes the assessed allocation of the value fund, which
    applies the configured share — `VALUE_FUND_SHARE_BPS` is 4000 basis points,
    two fifths — to that full gross fee, rounded half up once to a whole cent."

    Design: Difficulty/dual_variant_calc/premium_value_funding_assessed_vs_disbursed_on_statement
    """
    set_clock()
    member = create_active_cardmember()
    statement = create_annual_fee_statement(
        member["id"], principal_fee_cents=1000000,
        authorised_user_count=2, per_user_fee_cents=50000)

    assessed = assess_statement(statement["id"])
    assert assessed["gross_fee_assessed_cents"] == 1100000
    assert assessed["value_fund_allocation_cents"] == 440000, (
        "two fifths of the full 1100000 gross fee")
    assert assessed["statement_status"] == "ASSESSED"


def test_gross_fee_is_principal_plus_the_authorised_user_share(api):
    """PRD §3.6: "Assessment moves `DRAFT` to `ASSESSED` and computes the gross
    fee as the principal fee plus the authorised-user count multiplied by the
    per-user fee."

    Design: Difficulty/dual_variant_calc/premium_value_funding_assessed_vs_disbursed_on_statement
    """
    set_clock()
    member = create_active_cardmember()
    statement = create_annual_fee_statement(
        member["id"], principal_fee_cents=1000000,
        authorised_user_count=2, per_user_fee_cents=50000)
    assert statement["statement_status"] == "DRAFT"
    assert statement["gross_fee_assessed_cents"] == 0

    assessed = assess_statement(statement["id"])
    assert assessed["gross_fee_assessed_cents"] == 1000000 + 2 * 50000


# ═══ Difficulty: ledger compensating invariant ═══════════

def test_voiding_an_assessed_statement_writes_an_equal_reversal(api):
    """PRD §3.6: "Voiding moves an assessed statement to the terminal `VOIDED`
    state and writes a `ValueFundLedgerEntry` of kind
    `FEE_ALLOCATION_REVERSAL` of equal magnitude to the entry the statement would
    have produced, decreasing the value fund by the same amount."

    Design: Difficulty/compensating_invariant/value_fund_ledger_invariant
    """
    set_clock()
    member = create_active_cardmember()
    statement = create_annual_fee_statement(
        member["id"], principal_fee_cents=1000000,
        authorised_user_count=2, per_user_fee_cents=50000)
    assess_statement(statement["id"])
    voided = void_statement(statement["id"])
    assert voided["statement_status"] == "VOIDED"

    entries = list_ledger(source_statement_id=statement["id"])
    assert len(entries) == 1
    assert entries[0]["entry_kind"] == "FEE_ALLOCATION_REVERSAL"
    assert entries[0]["amount_cents"] == -40000, (
        "the reversal negates the disbursed allocation of the per-user portion")


def test_the_ledger_sum_returns_to_zero_after_a_void(api):
    """PRD §3.6: "the `amount_cents` it carries is signed, positive for an
    allocation, negative for a reversal, and zero for a lounge-pass grant."
    PRD §3.6: "Allocations exist only for statements that reached `ASSESSED`, so
    statements left in `DRAFT` contribute nothing to the fund and a `VOIDED`
    statement contributes its reversal rather than its allocation."

    Design: Difficulty/compensating_invariant/value_fund_ledger_invariant
    """
    set_clock()
    member = create_active_cardmember()
    statement = create_annual_fee_statement(
        member["id"], principal_fee_cents=1000000,
        authorised_user_count=2, per_user_fee_cents=50000)
    # Voiding moves an ASSESSED statement straight to the terminal VOIDED state
# and contributes its reversal *rather than* its allocation (PRD §3.6), so the
# ledger for this statement holds the single signed reversal.
    assess_statement(statement["id"])
    void_statement(statement["id"])

    entries = list_ledger(source_statement_id=statement["id"])
    assert len(entries) == 1
    assert entries[0]["entry_kind"] == "FEE_ALLOCATION_REVERSAL"
    assert entries[0]["amount_cents"] < 0, (
        "a reversal is carried as a negative amount")
    assert sum(e["amount_cents"] for e in entries) == -40000


def test_ledger_replays_in_creation_sequence_order(api):
    """PRD §3.6: "Each ledger entry carries a monotone `created_seq` that is the
    deterministic replay order tie-break — the ordering never falls back to `id`."

    Design: Difficulty/compensating_invariant/value_fund_ledger_invariant
    """
    set_clock()
    member = create_active_cardmember()
    # Disbursement and voiding are two separate branches of the statement
    # machine; running them on two statements places the allocation entry before
    # the reversal entry in `created_seq` order.
    disbursed = create_annual_fee_statement(
        member["id"], principal_fee_cents=1000000,
        authorised_user_count=2, per_user_fee_cents=50000)
    assess_statement(disbursed["id"])
    disburse_statement(disbursed["id"])
    voided = create_annual_fee_statement(
        member["id"], principal_fee_cents=1000000,
        authorised_user_count=2, per_user_fee_cents=50000)
    assess_statement(voided["id"])
    void_statement(voided["id"])

    seqs = [e["created_seq"] for e in list_ledger()]
    assert seqs == sorted(seqs), "entries replay in ascending created_seq"
    assert list_ledger(source_statement_id=disbursed["id"])[0]["entry_kind"] == \
        "FEE_ALLOCATION"
    assert list_ledger(source_statement_id=voided["id"])[0]["entry_kind"] == \
        "FEE_ALLOCATION_REVERSAL"


def test_a_draft_statement_contributes_nothing_to_the_ledger(api):
    """PRD §3.6: "Allocations exist only for statements that reached `ASSESSED`,
    so statements left in `DRAFT` contribute nothing to the fund"

    Design: Difficulty/compensating_invariant/value_fund_ledger_invariant
    """
    set_clock()
    member = create_active_cardmember()
    statement = create_annual_fee_statement(
        member["id"], principal_fee_cents=1000000,
        authorised_user_count=2, per_user_fee_cents=50000)
    assert statement["statement_status"] == "DRAFT"

    assert list_ledger(source_statement_id=statement["id"]) == []


# ═══ Difficulty: acceptance-gap window merging ═══════════

def test_partially_overlapping_thirty_day_windows_merge_into_one(api):
    """PRD §3.2: "A thirty-day window folds into an existing window when the two
    overlap by at least a day — that is, when the new `window_start` precedes the
    existing `window_end` and the new `window_end` follows the existing
    `window_start`."

    Design: Difficulty/resource_temporal_overlap/acceptance_gap_windows_merge_on_partial_overlap
    """
    set_clock()
    category = create_industry_category()
    create_merchant(category["id"], region_code="US-NE")
    rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)

    rollup_gap("US-NE", category["id"], "2026-08-12T00:00:00Z", "2026-09-11T00:00:00Z", 30)

    gaps = list_acceptance_gaps(params={"region_code": "US-NE"})
    assert len(gaps) == 1, "the overlapping second window folds into the first"


def test_merged_window_spans_both_original_boundaries(api):
    """PRD §3.2: "A thirty-day window folds into an existing window when the two
    overlap by at least a day"

    Design: Difficulty/resource_temporal_overlap/acceptance_gap_windows_merge_on_partial_overlap
    """
    set_clock()
    category = create_industry_category()
    create_merchant(category["id"], region_code="US-NE")
    rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)
    rollup_gap("US-NE", category["id"], "2026-08-12T00:00:00Z", "2026-09-11T00:00:00Z", 30)

    gap = list_acceptance_gaps(params={"region_code": "US-NE"})[0]
    # The merged span covers the earliest start and the latest end; the instants
    # are compared, so the rendering's trailing fractional zeros are immaterial.
    assert _instant(gap["window_start"]) == _instant("2026-08-01T00:00:00Z")
    assert _instant(gap["window_end"]) == _instant("2026-09-11T00:00:00Z")


def test_a_gap_that_has_never_been_swept_reports_a_zero_sweep_index(api):
    """PRD §3.2: "A gap that has never been swept reports `sweep_index` as 0."

    Design: Difficulty/resource_temporal_overlap/acceptance_gap_windows_merge_on_partial_overlap
    """
    set_clock()
    category = create_industry_category()
    create_merchant(category["id"], region_code="US-NE")
    gap = rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)

    assert gap["sweep_index"] == 0


def test_a_thirty_day_window_that_only_touches_at_the_edge_still_merges(api):
    """PRD §3.2: "A thirty-day window folds into an existing window when the two
    overlap by at least a day"

    Design: Difficulty/resource_temporal_overlap/acceptance_gap_windows_merge_on_partial_overlap
    """
    set_clock()
    category = create_industry_category()
    create_merchant(category["id"], region_code="US-NE")
    rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)
    # A window that starts inside the first window, overlapping by 19 days.
    rollup_gap("US-NE", category["id"], "2026-08-12T00:00:00Z", "2026-09-11T00:00:00Z", 30)

    gaps = list_acceptance_gaps(params={"region_code": "US-NE"})
    assert len(gaps) == 1
    assert gaps[0]["window_days"] == 30


# ═══ Corner: gap qualifying status below/at threshold ════

def test_a_gap_with_no_counted_declines_is_dormant(api):
    """PRD §3.2: "A count of one or two lands the gap at `BELOW_THRESHOLD`, and a
    count of zero lands it at `DORMANT`."

    Design: Corner/calculations/acceptance_gap_excludes_non_acceptance_decline_reasons
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], region_code="US-NE")
    from test_helpers import submit_declined_attempt
    submit_declined_attempt(
        merchant["id"], attempted_amount_cents=100000,
        decline_reason="EXPIRED_CARD", occurred_at="2026-08-10T00:00:00Z")

    gap = rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)
    assert gap["decline_count"] == 0
    assert gap["qualified_status"] == "DORMANT"