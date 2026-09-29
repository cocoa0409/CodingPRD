"""Intervals competing for the same resource.

Two settlement windows on one bank account are closed intervals extended by a
buffer at both ends, so windows that merely touch conflict; two payroll periods
are half-open, so periods that merely touch do not.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_FUNDING_WINDOW_CONFLICT, ERR_PAY_PERIOD_OVERLAP
from test_helpers.constants import (
    CYCLE_DRAFT,
    CYCLE_RESULTS_APPROVED,
    FUNDING_APPROVED,
)
from test_helpers.test_users import OPS_HEADERS, TREASURY_RELEASER_HEADERS

_FIRST_WINDOW_START = "2026-08-10T00:00:00.000Z"
_FIRST_WINDOW_END = "2026-08-11T00:00:00.000Z"
_SECOND_WINDOW_START = "2026-08-11T00:00:00.000Z"
_SECOND_WINDOW_END = "2026-08-12T00:00:00.000Z"


def _two_instructions_on_one_account(api):
    """One released instruction, then a second whose window abuts the first."""
    ctx = fx.setup_active_engagement(api)
    ctx = fx.setup_verified_bank_account(api, ctx)
    ctx = fx.setup_draft_cycle(api, ctx)
    ctx = fx.setup_validated_extract(api, ctx)
    ctx = fx.setup_locked_cycle(api, ctx)
    ctx = fx.setup_scored_run(api, ctx)
    ctx = fx.setup_results_approved_cycle(api, ctx)
    ctx = fx.setup_drafted_funding(api, ctx)
    ctx = fx.setup_approved_funding(api, ctx)
    ctx = fx.setup_funded_cycle(api, ctx)

    first_funding_id = ctx["funding_id"]
    ctx = fx.setup_second_results_approved_period(api, ctx)
    ctx = fx.setup_drafted_funding(
        api, ctx, funding_overrides={"value_date": "2026-08-11"}
    )
    ctx = fx.setup_approved_funding(api, ctx)
    ctx = dict(ctx)
    ctx["first_funding_id"] = first_funding_id
    return ctx


def _three_periods(api):
    """August, then the adjacent September, then a period straddling both."""
    ctx = fx.setup_draft_cycle(api)
    adjacent = api.create_cycle(
        f.september_cycle_payload(ctx["engagement_id"]), OPS_HEADERS
    )
    straddling = api.create_cycle(
        f.cycle_payload(
            ctx["engagement_id"],
            period_label="2026-09-MID",
            period_start_date="2026-09-15",
            period_end_date="2026-10-15",
            pay_date="2026-10-14",
        ),
        OPS_HEADERS,
    )
    return ctx, adjacent, straddling


def test_abutting_settlement_windows_on_one_account_conflict(api):
    """The second instruction's window starts at the instant the first one ends, and
    with the buffer applied at both ends the two closed intervals intersect.

    PRD 3.6: "Then the temporal window check: treat this instruction's settlement
    interval as the closed interval running from `window_start_at` to `window_end_at`,
    and extend it by the account's `buffer_hours` at both ends; if that extended
    interval intersects the closed settlement interval of any other already-`RELEASED`
    instruction on the same `bank_account_id`, the release is rejected with
    `ERR_FUNDING_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bank_account_settlement_windows_conflict_across_the_buffer_gap
    """
    ctx = _two_instructions_on_one_account(api)

    response = api.release_funding_instruction(
        ctx["funding_id"], TREASURY_RELEASER_HEADERS
    )
    validate_error(response, ERR_FUNDING_WINDOW_CONFLICT, 409)

    first = fx.read_funding(api, ctx["first_funding_id"])
    a.assert_instant_equals(
        first["window_start_at"], _FIRST_WINDOW_START, "window_start_at"
    )
    a.assert_instant_equals(first["window_end_at"], _FIRST_WINDOW_END, "window_end_at")

    second = fx.read_funding(api, ctx["funding_id"])
    a.assert_instant_equals(
        second["window_start_at"], _SECOND_WINDOW_START, "window_start_at"
    )
    a.assert_instant_equals(second["window_end_at"], _SECOND_WINDOW_END, "window_end_at")


def test_window_conflict_leaves_the_commitment_at_the_first_release_only(api):
    """The refused release commits nothing, so the engagement carries exactly the one
    amount the successful release added.

    PRD 2.12: "A release adds the instruction's `funded_source_minor`; a recall removes
    exactly the same amount; instructions in `DRAFT`, `APPROVED` or `VOIDED` never
    contribute."

    Design: Difficulty/resource_temporal_overlap/bank_account_settlement_windows_conflict_across_the_buffer_gap
    """
    ctx = _two_instructions_on_one_account(api)

    api.release_funding_instruction(ctx["funding_id"], TREASURY_RELEASER_HEADERS)

    second = fx.read_funding(api, ctx["funding_id"])
    assert second["status"] == FUNDING_APPROVED, (
        f"the blocked instruction is still approved, got {second['status']}"
    )
    a.assert_null_fields(second, ["releaser_user_id"])

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_RESULTS_APPROVED)
    a.assert_minor_amount(cycle["funded_total_minor"], 0, "funded_total_minor")

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    a.assert_minor_amount(
        engagement["treasury_committed_minor"], 9543206, "treasury_committed_minor"
    )


def test_period_that_merely_touches_the_previous_one_is_accepted(api):
    """September starts on the date August's half-open period excludes, so the two do
    not overlap and the adjacent period opens normally.

    PRD 3.3: "Two periods that merely touch — one ending on the very date the next
    starts — do not overlap, because the end date is excluded."

    Design: Difficulty/resource_temporal_overlap/payroll_period_adjacency_allowed_but_overlap_rejected
    """
    _, adjacent, _ = _three_periods(api)

    cycle = validate_success(adjacent, 201)
    a.assert_cycle_state(cycle, CYCLE_DRAFT)
    a.assert_field_values(
        cycle,
        {
            "period_label": "2026-09",
            "period_start_date": "2026-09-01",
            "period_end_date": "2026-10-01",
        },
    )


def test_period_that_genuinely_straddles_two_others_is_rejected(api):
    """A 30-day period is inside the monthly band, but it covers dates both existing
    periods already own, so it is refused as an overlap.

    PRD 3.3: "and the new half-open period must not overlap the half-open period of
    any other cycle of the same engagement whose status is not `CANCELLED`, otherwise
    `ERR_PAY_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/payroll_period_adjacency_allowed_but_overlap_rejected
    """
    ctx, _, straddling = _three_periods(api)

    validate_error(straddling, ERR_PAY_PERIOD_OVERLAP, 409)

    cycles, meta = validate_paginated(
        api.list_cycles(OPS_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=2, expected_has_more=False)
    assert [c["period_label"] for c in cycles] == ["2026-08", "2026-09"], (
        f"only the two accepted periods exist, got {[c['period_label'] for c in cycles]}"
    )
