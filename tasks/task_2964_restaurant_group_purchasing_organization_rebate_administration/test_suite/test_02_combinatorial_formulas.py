"""Combinatorial formula tests: nested conditionals, rounding order and the
frozen input that breaks the admin-fee circularity.

Every test builds its whole world through API calls because the database is
empty before each one. The call under test is always issued through the raw
api_client so its status code is asserted alongside its effects.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_member_ledger, assert_split
from test_helpers.test_users import (
    make_analyst_headers,
    make_gpo_admin_headers,
)
from test_helpers.types import (
    AccrualBasis,
    AuditStatus,
    NormalizationStatus,
    RateType,
)

ANALYST = make_analyst_headers()
ADMIN = make_gpo_admin_headers()

# The design pins reversal_posture_limit to 1 on every instance's ELITE tier.
TIER_OVERRIDES = {"reversal_posture_limit": 1}

# The superseded-rate mode (a) fixture: a fatter flat card whose window sits a
# whole year before the June 2026 invoices.
OLD_CARD_FLAT_RATE_CENTS_PER_CASE = 200
OLD_CARD_FROM = "2025-01-01"
OLD_CARD_TO = "2025-12-31"

# mode (c) July feed literals
JULY_LINE_C_INVOICE_DATE = "2026-07-06"
JULY_LINE_D_INVOICE_DATE = "2026-07-18"
BIG_LINE_CASES = 25_000


def accrual_rows_for_line(line_id: str):
    """The accrual rows the /accruals list endpoint reports for one line."""
    rows, meta = validate_paginated(
        api_client.list_accruals(
            ANALYST, {"purchase_line_id": line_id, "limit": C.MAX_LIMIT}
        )
    )
    return rows, meta


def program_with_out_of_window_flat_card() -> dict:
    """An ACTIVE member/deal whose beef item carries TWO approved cards: an old
    flat 200 cents/case card for 2025 and the 0/50/200 tiered ladder for
    2026-2028. Built card-by-card so the old card is proposed and approved
    first, exactly as the design's setup_api_calls order it."""
    tier = fx.create_tier(**TIER_OVERRIDES)
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    old_card = fx.approved_card(
        item["id"],
        RateType.PER_CASE.value,
        flat_rate_cents_per_case=OLD_CARD_FLAT_RATE_CENTS_PER_CASE,
        effective_from=OLD_CARD_FROM,
        effective_to=OLD_CARD_TO,
    )
    tiered_card = fx.approved_card(item["id"], RateType.TIERED_VOLUME.value)
    deal = fx.activate_deal(deal["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "member": member,
        "deal": deal,
        "item": item,
        "old_card": old_card,
        "card": tiered_card,
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "deal_id": deal["id"],
        "item_id": item["id"],
    }


def normalized_june_feed(ctx: dict) -> dict:
    """Open the June feed, ingest the 30-case then the 40-case beef line and
    normalize it, leaving the batch at NORMALIZED."""
    batch = fx.create_batch(ctx["distributor_id"])
    ctx["batch_id"] = batch["id"]
    ctx["line_a"] = fx.create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])
    ctx["line_b"] = fx.create_line_b(
        batch["id"], ctx["member_id"], ctx["distributor_id"]
    )
    ctx["batch"] = fx.normalize(batch["id"])
    return ctx


def june_closed_on_one_big_line() -> dict:
    """June holds ONE matched line of 25000 cases; it is accrued at the
    MARGINAL_BATCH ladder and then the June period is closed, which rebases it
    and refreezes the member's admin-fee snapshot."""
    ctx = fx.setup_tiered_program(tier_overrides=TIER_OVERRIDES)
    batch = fx.create_batch(ctx["distributor_id"])
    ctx["batch_id"] = batch["id"]
    ctx["big_line"] = fx.create_line(
        batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        cases_shipped=BIG_LINE_CASES,
    )
    fx.normalize(batch["id"])
    ctx["batch"] = fx.accrue(batch["id"])
    ctx["deal"] = fx.close_period(ctx["deal_id"], C.JUNE_START, C.JUNE_END)
    return ctx


def normalized_july_feed(ctx: dict) -> dict:
    """A July feed of 30 then 40 cases, normalized but not yet accrued."""
    july = fx.create_july_batch(ctx["distributor_id"])
    ctx["july_batch_id"] = july["id"]
    ctx["line_c"] = fx.create_line(
        july["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        invoice_date=JULY_LINE_C_INVOICE_DATE,
    )
    ctx["line_d"] = fx.create_line(
        july["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        cases_shipped=C.LINE_B_CASES,
        distributor_base_cost_cents=C.LINE_B_BASE_COST_CENTS,
        invoice_date=JULY_LINE_D_INVOICE_DATE,
    )
    ctx["july_batch"] = fx.normalize(july["id"])
    return ctx


# ============================================================================
# mode (a) — nested conditional: pick the card, then walk the ladder per case
# ============================================================================

def test_marginal_ladder_splits_the_forty_case_line_across_the_fifty_break():
    """The 30-case line pays 3600 and the 40-case line pays 6000 because the
    second line straddles the 50-case break inside the batch-scoped ladder:
    20 cases at 120 plus 20 cases at 180, not 40 at 120 and not 40 at 180.

    PRD: "Because the count is marginal, a line that straddles a `min_cases`
    threshold is split: the cases falling below the threshold are paid at the
    lower tier's `rate_cents_per_case` and the cases at or above it at the
    higher tier's, each slice at its own rate, and the slices are summed."

    Design: Difficulty/combinatorial_formula/mode_a_nested_tier_ladder_straddle_and_card_selection
    """
    ctx = normalized_june_feed(program_with_out_of_window_flat_card())

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)
    batch = validate_success(response, 200)

    rows_a, meta_a = accrual_rows_for_line(ctx["line_a"]["id"])
    assert meta_a["total_count"] == 1, "exactly one accrual monetizes the 30-case line"
    assert len(rows_a) == 1
    accrual_a = rows_a[0]
    assert accrual_a["gross_rebate_cents"] == 3600, (
        "30 cases sit wholly inside the 0/120 tier: 30 * 120 == 3600"
    )
    assert accrual_a["accrued_cases"] == 30
    assert accrual_a["basis"] == AccrualBasis.MARGINAL_BATCH.value

    rows_b, meta_b = accrual_rows_for_line(ctx["line_b"]["id"])
    assert meta_b["total_count"] == 1, "exactly one accrual monetizes the 40-case line"
    assert len(rows_b) == 1
    accrual_b = rows_b[0]
    assert accrual_b["gross_rebate_cents"] == 6000, (
        "the 40-case line straddles the 50-case break: 20 * 120 + 20 * 180 == 6000, "
        "never 40 * 120 == 4800 and never 40 * 180 == 7200"
    )
    assert accrual_b["accrued_cases"] == 40
    assert accrual_b["basis"] == AccrualBasis.MARGINAL_BATCH.value

    assert batch["matched_cases"] == 70
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value


def test_rate_selection_ignores_the_flat_card_whose_window_misses_june():
    """Both June accruals cite the 2026-2028 tiered card. The fatter flat
    200 cents/case card is APPROVED but its 2025 window does not contain either
    invoice date, so it is not a candidate at all.

    PRD: "The candidates are the rate cards whose `contracted_item_id` is the
    line's resolved item, whose `status` is `APPROVED`, and whose closed
    `effective_from` through `effective_to` range contains the line's
    `invoice_date`"

    Design: Difficulty/combinatorial_formula/mode_a_nested_tier_ladder_straddle_and_card_selection
    """
    ctx = normalized_june_feed(program_with_out_of_window_flat_card())
    tiered_card_id = ctx["card"]["id"]
    old_card_id = ctx["old_card"]["id"]

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)
    validate_success(response, 200)

    rows_a, _ = accrual_rows_for_line(ctx["line_a"]["id"])
    rows_b, _ = accrual_rows_for_line(ctx["line_b"]["id"])
    assert len(rows_a) == 1 and len(rows_b) == 1
    assert rows_a[0]["rate_card_id"] == tiered_card_id
    assert rows_b[0]["rate_card_id"] == tiered_card_id

    every_accrual, _ = validate_paginated(
        api_client.list_accruals(ANALYST, {"limit": C.MAX_LIMIT})
    )
    assert every_accrual, "the run produced accruals"
    assert all(a["rate_card_id"] == tiered_card_id for a in every_accrual), (
        "no accrual may cite a card whose closed window misses the invoice date"
    )
    assert all(a["rate_card_id"] != old_card_id for a in every_accrual)

    # The flat card was excluded on its dates, not on its status: it is still
    # APPROVED and would have paid 200 cents on every one of the 70 cases.
    old_card = validate_success(api_client.get_rate_card(old_card_id, ADMIN), 200)
    assert old_card["status"] == "APPROVED"
    assert old_card["flat_rate_cents_per_case"] == OLD_CARD_FLAT_RATE_CENTS_PER_CASE


# ============================================================================
# mode (b) — rounding order: round the allowed unit cost per LINE, then sum
# ============================================================================

def test_markup_overbilling_rounds_per_line_before_summing_the_batch():
    """The allowed unit cost is rounded per line and only then multiplied by
    cases: 8533 -> 9130 -> 10 * 30 == 300 and 8540 -> 9138 -> 2 * 40 == 80,
    so the batch total is 380 and not the 379 that summing bases first gives.

    PRD: "The rounding point matters: the half-up rounding is applied to each
    line's allowed markup before the multiplication by cases, and rounding a
    batch-level total instead would produce a different answer whenever two
    lines' base costs round in opposite directions."

    Design: Difficulty/combinatorial_formula/mode_b_markup_rounding_order_per_line_then_sum
    """
    ctx = fx.setup_june_normalized(
        RateType.TIERED_VOLUME.value, tier_overrides=TIER_OVERRIDES
    )

    response = api_client.audit_markup(ctx["batch_id"], ANALYST)
    batch = validate_success(response, 200)

    line_a = validate_success(
        api_client.get_purchase_line(ctx["line_a"]["id"], ANALYST), 200
    )
    line_b = validate_success(
        api_client.get_purchase_line(ctx["line_b"]["id"], ANALYST), 200
    )
    assert line_a["overbilled_cents"] == 300, (
        "min(900, 700) == 700 bps on base 8533 rounds to 597, allowed 9130, "
        "excess 10 per case over 30 cases"
    )
    assert line_b["overbilled_cents"] == 80, (
        "700 bps on base 8540 rounds to 598, allowed 9138, excess 2 per case "
        "over 40 cases"
    )
    assert batch["overbilled_cents"] == 380, (
        "the batch total is the sum of the per-line figures, 380 — not the 379 "
        "that summing the base costs before rounding produces"
    )
    assert batch["overbilled_cents"] != 379
    assert batch["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value


def test_audit_dimension_moves_while_normalization_status_stands_still():
    """The markup audit advances only the audit dimension: the batch leaves
    NOT_AUDITED for AUDIT_OVERBILLED while its normalization_status stays
    NORMALIZED, untouched by the audit run.

    PRD: "The run leaves `normalization_status` completely untouched — the two
    dimensions genuinely are independent, and auditing a feed neither advances
    nor rewinds its accrual progress."

    Design: Difficulty/combinatorial_formula/mode_b_markup_rounding_order_per_line_then_sum
    """
    ctx = fx.setup_june_normalized(
        RateType.TIERED_VOLUME.value, tier_overrides=TIER_OVERRIDES
    )

    before = validate_success(
        api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200
    )
    assert before["audit_status"] == AuditStatus.NOT_AUDITED.value
    assert before["overbilled_cents"] == 0
    assert before["normalization_status"] == NormalizationStatus.NORMALIZED.value

    response = api_client.audit_markup(ctx["batch_id"], ANALYST)
    batch = validate_success(response, 200)

    assert batch["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value, (
        "the audit dimension moved because the batch overbilled 380 cents"
    )
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value, (
        "the normalization dimension did not move: the audit neither accrues "
        "nor unwinds the feed"
    )
    assert batch["matched_cases"] == 70
    assert batch["total_cases_ingested"] == 70

    reread = validate_success(
        api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200
    )
    assert reread["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert reread["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value


# ============================================================================
# mode (c) — circular formula cut by the frozen ytd_net_snapshot_cents input
# ============================================================================

def test_july_accruals_read_the_frozen_snapshot_for_the_high_fee_band():
    """June's close froze ytd_net_snapshot_cents at 6062500, so both July
    accruals take the 150 bps high band and the fee comes off the top first:
    3600 gross yields member_share 2660, not the 2700 that 75% of gross gives.

    PRD: "The band reads `ytd_net_snapshot_cents`, a **frozen** snapshot, and
    never the member's live running totals."

    Design: Difficulty/combinatorial_formula/mode_c_frozen_snapshot_breaks_admin_fee_circularity
    """
    ctx = normalized_july_feed(june_closed_on_one_big_line())

    before = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert before["ytd_net_snapshot_cents"] == 6_062_500, (
        "the June close rewrote the snapshot to member_share + gpo_retention"
    )
    assert before["ytd_net_snapshot_cents"] >= C.ADMIN_FEE_BAND_BREAK_CENTS

    response = api_client.accrue_batch(ctx["july_batch_id"], ANALYST)
    batch = validate_success(response, 200)
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value

    rows_c, meta_c = accrual_rows_for_line(ctx["line_c"]["id"])
    assert meta_c["total_count"] == 1
    accrual_c = rows_c[0]
    assert_split(
        accrual_c,
        gross_rebate_cents=3600,
        admin_fee_bps_applied=150,
        admin_fee_cents=54,
        net_distributable_cents=3546,
        member_share_cents=2660,
        gpo_retention_cents=886,
    )
    assert accrual_c["member_share_cents"] != 2700, (
        "the member share is 75% of the NET, not 75% of the gross"
    )
    assert accrual_c["basis"] == AccrualBasis.MARGINAL_BATCH.value

    rows_d, meta_d = accrual_rows_for_line(ctx["line_d"]["id"])
    assert meta_d["total_count"] == 1
    accrual_d = rows_d[0]
    assert_split(
        accrual_d,
        gross_rebate_cents=6000,
        admin_fee_bps_applied=150,
        admin_fee_cents=90,
        net_distributable_cents=5910,
        member_share_cents=4433,
        gpo_retention_cents=1477,
    )
    assert accrual_d["admin_fee_bps_applied"] == 150, (
        "the second accrual still reads the frozen snapshot even though the "
        "live attributed net moved during the same call"
    )

    after = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert after["ytd_net_snapshot_cents"] == 6_062_500, (
        "accrue never rewrites the snapshot — only the period close does"
    )
    assert_member_ledger(
        after,
        accrued_member_share_cents=4_553_968,
        attributed_gpo_retention_cents=1_517_988,
        attributed_admin_fee_cents=187_644,
    )
    live_attributed_net = (
        after["accrued_member_share_cents"] + after["attributed_gpo_retention_cents"]
    )
    assert live_attributed_net == 6_071_956, (
        "the live net moved past the frozen snapshot during the accrual run"
    )
    assert (
        after["accrued_member_share_cents"]
        + after["attributed_gpo_retention_cents"]
        + after["attributed_admin_fee_cents"]
    ) == 6_259_600 == 6_250_000 + 3600 + 6000


def test_close_period_is_the_only_writer_of_the_admin_fee_snapshot():
    """Closing June rebases the 25000-case accrual to one blended 250 rate,
    reuses its already-frozen 300 bps band rather than re-selecting it, and
    only then rewrites ytd_net_snapshot_cents to 6062500.

    PRD: "Each affected member's `ytd_net_snapshot_cents` is rewritten to that
    member's post-close attributed net total, namely its
    `accrued_member_share_cents` plus its `attributed_gpo_retention_cents` as
    those counters stand once every rebasing delta has been applied."

    Design: Difficulty/combinatorial_formula/mode_c_frozen_snapshot_breaks_admin_fee_circularity
    """
    ctx = fx.setup_tiered_program(tier_overrides=TIER_OVERRIDES)
    batch = fx.create_batch(ctx["distributor_id"])
    big_line = fx.create_line(
        batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        cases_shipped=BIG_LINE_CASES,
    )
    fx.normalize(batch["id"])
    fx.accrue(batch["id"])

    rows, meta = accrual_rows_for_line(big_line["id"])
    assert meta["total_count"] == 1
    accrued = rows[0]
    assert accrued["gross_rebate_cents"] == 6_233_000, (
        "at accrue time the marginal ladder pays 50*120 + 150*180 + 24800*250"
    )
    assert accrued["basis"] == AccrualBasis.MARGINAL_BATCH.value
    assert accrued["admin_fee_bps_applied"] == 300, (
        "the snapshot was still 0, strictly below the 5,000,000 cent break"
    )
    assert accrued["final_adjustment_cents"] == 0
    before = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert before["ytd_net_snapshot_cents"] == 0

    response = api_client.close_period(
        ctx["deal_id"],
        {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
        ADMIN,
    )
    validate_success(response, 200)

    rebased = validate_success(api_client.get_accrual(accrued["id"], ANALYST), 200)
    assert rebased["basis"] == AccrualBasis.BLENDED_PERIOD.value
    assert rebased["gross_rebate_cents"] == 6_250_000, (
        "the period-wide total of 25000 cases selects the single 250 rate and "
        "applies it to every case, with no straddle split"
    )
    assert rebased["final_adjustment_cents"] == 17_000, (
        "the signed delta is 6250000 - 6233000"
    )
    assert_split(
        rebased,
        gross_rebate_cents=6_250_000,
        admin_fee_bps_applied=300,
        admin_fee_cents=187_500,
        net_distributable_cents=6_062_500,
        member_share_cents=4_546_875,
        gpo_retention_cents=1_515_625,
    )
    assert rebased["admin_fee_bps_applied"] == 300, (
        "the band selection step is not re-run at close: the frozen 300 bps is "
        "reused verbatim even though the post-close net clears the high band"
    )

    after = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert_member_ledger(
        after,
        accrued_member_share_cents=4_546_875,
        attributed_gpo_retention_cents=1_515_625,
        attributed_admin_fee_cents=187_500,
    )
    assert after["ytd_net_snapshot_cents"] == 6_062_500 == (
        after["accrued_member_share_cents"] + after["attributed_gpo_retention_cents"]
    )
    assert after["ytd_net_snapshot_cents"] >= C.ADMIN_FEE_BAND_BREAK_CENTS, (
        "every accrual created after this close takes the high band"
    )
