"""Reversals that must restore a conserved aggregate exactly.

Recalling a released funding instruction has to return the engagement to the
commitment it carried before the release, and cancelling a period has to return
the country's live obligation count to the value it held before the lock.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CTRL_FUNDING_DUAL_AUTH,
    CYCLE_CANCELLED,
    CYCLE_RESULTS_APPROVED,
    FILING_VOIDED,
    FUNDING_RECALLED,
    INPUT_FILE_VALIDATED,
    PENALTY_NONE,
    PENALTY_OWNER_NONE,
    PROVIDER_ACTIVE,
)
from test_helpers.test_users import AUDITOR_HEADERS, OPS_HEADERS, TREASURY_RELEASER_HEADERS

_RECALL_REASON = "Value date moved after the treasury cut-off."


def _funded_then_recalled(api):
    """A funded cycle, its pre-recall commitment, and the recalled instruction."""
    ctx = fx.setup_funded_cycle(api)
    committed_before = fx.read_engagement(api, ctx["engagement_id"])[
        "treasury_committed_minor"
    ]
    recalled = validate_success(
        api.recall_funding_instruction(
            ctx["funding_id"],
            f.recall_payload(_RECALL_REASON),
            TREASURY_RELEASER_HEADERS,
        )
    )
    return ctx, committed_before, recalled


def _locked_then_cancelled(api):
    """A locked period whose obligations are minted and then voided by cancellation."""
    ctx = fx.setup_validated_extract(api)
    before_lock = fx.read_country(api, ctx["country_id"])["open_filing_obligation_count"]
    ctx = fx.setup_locked_cycle(api, ctx)
    after_lock = fx.read_country(api, ctx["country_id"])["open_filing_obligation_count"]
    cancelled = fx.cancel_cycle(api, ctx["cycle_id"])
    return ctx, before_lock, after_lock, cancelled


def test_recall_returns_the_engagement_to_its_prior_commitment(api):
    """The recall removes precisely the amount the release added, so the conserved
    commitment lands back on its pre-release value.

    PRD 2.12: "Releasing and then recalling one instruction must therefore return the
    engagement to precisely the commitment it had before, and the cycle's
    `funded_total_minor` must return to its prior value in the same request."

    Design: Difficulty/compensating_invariant/funding_recall_restores_engagement_treasury_commitment
    """
    ctx, committed_before, recalled = _funded_then_recalled(api)

    a.assert_minor_amount(committed_before, 9543206, "treasury_committed_minor")
    assert recalled["status"] == FUNDING_RECALLED, (
        f"the instruction is recalled, got {recalled['status']}"
    )
    a.assert_minor_amount(recalled["funded_source_minor"], 9543206, "funded_source_minor")
    assert recalled["recall_reason"] == _RECALL_REASON, (
        f"the recall reason is persisted, got {recalled['recall_reason']!r}"
    )

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    a.assert_minor_amount(
        engagement["treasury_committed_minor"], 0, "treasury_committed_minor"
    )


def test_recall_unfunds_the_cycle_without_erasing_its_evidence(api):
    """The cycle falls back to the approved state with a zero funded total, but the
    dual-authorization control it once exercised remains on the record.

    PRD 3.6: "On success the instruction moves `RELEASED → RECALLED`, which is
    terminal; the engagement's `treasury_committed_minor` decreases by exactly the
    `funded_source_minor` it gained on release, restoring the conserved commitment to
    its pre-release value; the cycle's `funded_total_minor` decreases by the same
    amount, returning to 0 when this was the cycle's only release; and provided no
    other instruction of the cycle is still `RELEASED`, the cycle moves
    `FUNDED → RESULTS_APPROVED`."

    Design: Difficulty/compensating_invariant/funding_recall_restores_engagement_treasury_commitment
    """
    ctx, _, _ = _funded_then_recalled(api)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_RESULTS_APPROVED)
    a.assert_minor_amount(cycle["funded_total_minor"], 0, "funded_total_minor")

    items, meta = validate_paginated(
        api.list_cycle_audit_evidence(
            ctx["cycle_id"], AUDITOR_HEADERS, {"control_ref": CTRL_FUNDING_DUAL_AUTH}
        )
    )
    a.assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
    assert items[0]["control_ref"] == CTRL_FUNDING_DUAL_AUTH, (
        f"the dual-authorization evidence survives, got {items[0]}"
    )


def test_cancellation_voids_the_minted_obligations(api):
    """Cancelling the period voids both live obligations and takes the country's
    conserved count down by exactly that many.

    PRD 3.9: "Every statutory filing of the cycle in `PENDING` or `LATE` moves to
    `VOIDED`, and the country profile's `open_filing_obligation_count` decreases by
    exactly that number of filings, restoring the conserved obligation count to the
    value it held before the cycle minted its obligations."

    Design: Difficulty/compensating_invariant/cycle_cancellation_restores_country_open_filing_obligations
    """
    ctx, before_lock, after_lock, cancelled = _locked_then_cancelled(api)

    assert before_lock == 0, f"the country opens with no obligations, got {before_lock}"
    assert after_lock == 2, f"the lock mints both obligations, got {after_lock}"
    a.assert_cycle_state(cancelled, CYCLE_CANCELLED)

    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == before_lock, (
        "the conserved count returns to its opening value, got "
        f"{country['open_filing_obligation_count']}"
    )

    filings = fx.filings_of_cycle(api, ctx["cycle_id"])
    assert len(filings) == 2, f"both filings still exist as rows, got {len(filings)}"
    for filing in filings:
        assert filing["status"] == FILING_VOIDED, (
            f"expected a voided filing, got {filing['status']}"
        )
        assert filing["penalty_status"] == PENALTY_NONE, (
            f"an unassessed obligation carries no penalty, got {filing['penalty_status']}"
        )
        assert filing["penalty_owner"] == PENALTY_OWNER_NONE, (
            f"expected penalty_owner NONE, got {filing['penalty_owner']}"
        )


def test_cancellation_reverses_only_what_the_lock_created(api):
    """The count round-trips to its opening value, while the validated extract and the
    provider's clean penalty exposure are left exactly as they were.

    PRD 2.12: "Minting obligations when a cycle locks its inputs increases it by the
    number minted; a filing moving from `PENDING` to `LATE` is count-neutral because
    both states are live; and a filing reaching `FILED`, `FILED_LATE` or `VOIDED`
    decreases it by 1."

    Design: Difficulty/compensating_invariant/cycle_cancellation_restores_country_open_filing_obligations
    """
    ctx, before_lock, _, _ = _locked_then_cancelled(api)

    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == before_lock, (
        "voiding every obligation returns the count to its opening value, got "
        f"{country['open_filing_obligation_count']}"
    )

    extracts, meta = validate_paginated(
        api.list_cycle_input_files(ctx["cycle_id"], OPS_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
    assert extracts[0]["status"] == INPUT_FILE_VALIDATED, (
        f"the validated extract is untouched, got {extracts[0]['status']}"
    )

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_ACTIVE, service_score=100.00, open_penalty_minor=0
    )
