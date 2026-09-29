"""Dual-variant rebate arithmetic and dual-basis savings reporting.

Two independent variant pairs live here, both translated from
SCAFFOLD_DIFFICULTY_DESIGN.yaml's ``dual_variant_calc`` rule:

  * the accrue-time ``MARGINAL_BATCH`` figure versus the close-period
    ``BLENDED_PERIOD`` rebase of the very same three purchase lines, and
  * the ``AS_PURCHASED`` versus ``FULL_BASKET`` opportunity basis of one
    member's savings report over one identical June period.

The database is empty before every test, so every precondition below is built
through API calls and nothing is shared between tests.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    AccrualBasis,
    AccrualBlockReason,
    AccrualStatus,
    MatchStatus,
    ReversalReason,
    SavingsBasis,
    api_client,
    assert_accrual,
    assert_member,
    assert_member_ledger,
    assert_purchase_line,
    assert_split,
    make_gpo_admin_headers,
    make_member_operator_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx

ADMIN = make_gpo_admin_headers()

# --- the design instance's own literals -------------------------------------
# The ELITE tier of the shared fixture vocabulary pins reversal_posture_limit 1.
TIER_OVERRIDES = {"reversal_posture_limit": 1}

# The July batch of the accrual instance: one single 90-case line.
JULY_LINE_CASES = 90
JULY_LINE_INVOICE_DATE = "2026-07-10"

# The closing period spans both batches: June 1 through July 31 inclusive.
CLOSE_PERIOD_START = C.JUNE_START
CLOSE_PERIOD_END = C.JULY_END


# ======================================================= local setup helpers ==

def _two_batch_tiered_accruals() -> dict:
    """The accrual instance's fixture: three MARGINAL_BATCH accruals.

    An ACTIVE Harbor Grill on the ELITE tier, an ACTIVE PBC-2026 deal whose
    beef item carries one APPROVED TIERED_VOLUME card on the 0/50/200 ladder,
    then two accrued feeds: June holds 30 + 40 cases, July holds 90 cases.
    """
    ctx = fx.setup_tiered_program(tier_overrides=TIER_OVERRIDES)
    fx.ingest_june_feed(ctx)
    fx.normalize_june_feed(ctx)
    fx.accrue_june_feed(ctx)

    july_batch = fx.create_july_batch(ctx["distributor_id"])
    line_c = fx.create_line(
        july_batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        cases_shipped=JULY_LINE_CASES,
        distributor_base_cost_cents=C.LINE_A_BASE_COST_CENTS,
        invoice_date=JULY_LINE_INVOICE_DATE,
    )
    fx.normalize(july_batch["id"])
    fx.accrue(july_batch["id"])

    ctx["july_batch"] = july_batch
    ctx["july_batch_id"] = july_batch["id"]
    ctx["line_c"] = line_c
    ctx["accrual_c"] = fx.accrual_for_line(line_c["id"])
    ctx["member"] = fx.read_member(ctx["member_id"])
    return ctx


def _close_the_two_batch_period(ctx: dict):
    """Trigger the close over June 1 through July 31 and return the raw call."""
    return api_client.close_period(
        ctx["deal_id"],
        {"period_start": CLOSE_PERIOD_START, "period_end": CLOSE_PERIOD_END},
        ADMIN,
    )


def _read_accrual(accrual_id: str) -> dict:
    """Read one accrual back through its own raw GET, asserting HTTP 200."""
    response = api_client.get_accrual(accrual_id, fx.ANALYST)
    accrual = validate_success(response, 200)
    assert_accrual(accrual)
    return accrual


def _june_feed_with_excluded_fries() -> dict:
    """The savings instance's fixture: two matched beef lines and one EXCLUDED
    fries line whose only key candidate sits under a DRAFT deal."""
    ctx = fx.setup_tiered_program(tier_overrides=TIER_OVERRIDES)

    draft_deal = fx.create_second_deal()
    fries_item = fx.create_item(
        draft_deal["id"], payload=F.fries_item_payload(draft_deal["id"])
    )

    fx.ingest_june_feed(ctx)
    fries_line = fx.create_line(
        ctx["batch_id"],
        ctx["member_id"],
        ctx["distributor_id"],
        payload=F.fries_line_payload(ctx["batch_id"], ctx["member_id"]),
    )
    fx.normalize_june_feed(ctx)
    fx.accrue_june_feed(ctx)

    ctx["draft_deal"] = draft_deal
    ctx["fries_item"] = fries_item
    ctx["fries_line"] = fx.read_line(fries_line["id"])
    ctx["member"] = fx.read_member(ctx["member_id"])
    return ctx


def _savings_report(member_id: str, basis: str) -> dict:
    """Request one member's own June savings report under one explicit basis."""
    response = api_client.get_savings_report(
        member_id,
        make_member_operator_headers(member_id),
        F.savings_report_params(C.JUNE_START, C.JUNE_END, basis),
    )
    return validate_success(response, 200)


# =========================================== accrue-time MARGINAL_BATCH ======

def test_accrue_time_marginal_batch_restarts_the_ladder_for_every_batch():
    """Accruing two feeds prices each line against a per-batch running count,
    so the 30/40/90-case lines earn 3600, 6000 and 13200 cents gross.

    PRD: "The ladder therefore restarts at zero for every batch." and "the
    cases falling below the threshold are paid at the lower tier's
    `rate_cents_per_case` and the cases at or above it at the higher tier's,
    each slice at its own rate, and the slices are summed"

    Design: Difficulty/dual_variant_calc/accrual_marginal_batch_vs_blended_period_rebase
    """
    ctx = _two_batch_tiered_accruals()

    accrual_a = _read_accrual(ctx["accrual_a"]["id"])
    accrual_b = _read_accrual(ctx["accrual_b"]["id"])
    accrual_c = _read_accrual(ctx["accrual_c"]["id"])

    for accrual in (accrual_a, accrual_b, accrual_c):
        assert accrual["basis"] == AccrualBasis.MARGINAL_BATCH.value
        assert accrual["status"] == AccrualStatus.ACCRUED.value
        assert accrual["reversal_reason"] == ReversalReason.NONE.value
        assert accrual["final_adjustment_cents"] == 0
        assert accrual["validated_by_user_id"] is None

    assert accrual_a["accrued_cases"] == C.LINE_A_CASES
    assert accrual_b["accrued_cases"] == C.LINE_B_CASES
    assert accrual_c["accrued_cases"] == JULY_LINE_CASES

    # June line A: 30 cases wholly inside the 0-case tier at 120 cents.
    assert_split(accrual_a, 3600, 300, 108, 3492, 2619, 873)
    # June line B: the batch count runs 30 -> 70, so 20 cases at 120 and 20 at 180.
    assert_split(accrual_b, 6000, 300, 180, 5820, 4365, 1455)
    # July line C: the ladder restarts, so 50 cases at 120 and 40 at 180.
    assert_split(accrual_c, 13200, 300, 396, 12804, 9603, 3201)


# ========================================= close-time BLENDED_PERIOD ======

def test_close_period_rebases_every_accrual_onto_the_blended_period_variant():
    """Closing June 1 through July 31 rebases the same three accruals onto the
    period-wide 160-case total: one 180-cents rate on every case, so gross
    becomes 5400, 7200 and 16200 with signed deltas of 1800, 1200 and 3000.

    PRD: "One single rate is then chosen from the ladder using that period-wide
    total and applied to **all** of the line's cases, with no straddle split at
    all." and "The accrual's already-frozen `admin_fee_bps_applied` is reused
    verbatim"

    Design: Difficulty/dual_variant_calc/accrual_marginal_batch_vs_blended_period_rebase
    """
    ctx = _two_batch_tiered_accruals()

    response = _close_the_two_batch_period(ctx)
    validate_success(response, 200)

    accrual_a = _read_accrual(ctx["accrual_a"]["id"])
    accrual_b = _read_accrual(ctx["accrual_b"]["id"])
    accrual_c = _read_accrual(ctx["accrual_c"]["id"])

    for accrual in (accrual_a, accrual_b, accrual_c):
        assert accrual["basis"] == AccrualBasis.BLENDED_PERIOD.value
        assert accrual["admin_fee_bps_applied"] == 300

    # 30 cases at the blended 180: gross 5400, up 1800 from the marginal 3600.
    assert_split(accrual_a, 5400, 300, 162, 5238, 3929, 1309)
    assert accrual_a["final_adjustment_cents"] == 1800
    # 40 cases at 180: gross 7200, up 1200 from the marginal 6000.
    assert_split(accrual_b, 7200, 300, 216, 6984, 5238, 1746)
    assert accrual_b["final_adjustment_cents"] == 1200
    # 90 cases at 180: gross 16200, up 3000 from the marginal 13200.
    assert_split(accrual_c, 16200, 300, 486, 15714, 11786, 3928)
    assert accrual_c["final_adjustment_cents"] == 3000


def test_close_period_moves_the_member_ledger_by_the_signed_rebase_delta():
    """The member's three counters stand at 16587 / 5529 / 684 on the marginal
    figures and move by the rebase deltas to 20953 / 6983 / 864, never being
    rebuilt from scratch.

    PRD: "Each of the member's three money counters is then moved by the
    **signed delta** between the new component and the old one, so the ledger
    tracks the rebasing without being rebuilt from scratch."

    Design: Difficulty/dual_variant_calc/accrual_marginal_batch_vs_blended_period_rebase
    """
    ctx = _two_batch_tiered_accruals()

    before = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert_member(before)
    assert_member_ledger(before, 16587, 5529, 684)

    validate_success(_close_the_two_batch_period(ctx), 200)

    after = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert_member(after)
    assert_member_ledger(after, 20953, 6983, 864)
    # Each counter moved by exactly the summed signed delta of the three rebases.
    assert after["accrued_member_share_cents"] - before["accrued_member_share_cents"] == 4366
    assert (
        after["attributed_gpo_retention_cents"]
        - before["attributed_gpo_retention_cents"]
    ) == 1454
    assert (
        after["attributed_admin_fee_cents"] - before["attributed_admin_fee_cents"]
    ) == 180


def test_close_period_refreezes_the_ytd_net_snapshot_to_the_post_close_net():
    """`ytd_net_snapshot_cents` sits at 0 while the period is open — which is
    why every accrual froze the 300-bps low band — and the close rewrites it to
    the post-close 20953 + 6983 = 27936.

    PRD: "Each affected member's `ytd_net_snapshot_cents` is rewritten to that
    member's post-close attributed net total, namely its
    `accrued_member_share_cents` plus its `attributed_gpo_retention_cents` as
    those counters stand once every rebasing delta has been applied."

    Design: Difficulty/dual_variant_calc/accrual_marginal_batch_vs_blended_period_rebase
    """
    ctx = _two_batch_tiered_accruals()

    before = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert before["ytd_net_snapshot_cents"] == 0
    for accrual_key in ("accrual_a", "accrual_b", "accrual_c"):
        assert _read_accrual(ctx[accrual_key]["id"])["admin_fee_bps_applied"] == 300

    validate_success(_close_the_two_batch_period(ctx), 200)

    after = validate_success(api_client.get_member(ctx["member_id"], ADMIN), 200)
    assert after["ytd_net_snapshot_cents"] == 27936
    assert after["ytd_net_snapshot_cents"] == (
        after["accrued_member_share_cents"] + after["attributed_gpo_retention_cents"]
    )


def test_close_period_rebases_but_pays_nothing_when_no_accrual_was_validated():
    """All three accruals are still `ACCRUED` when the period closes, so the
    close rebases their money and leaves every status exactly where it was.

    PRD: "An accrual left in `ACCRUED` or `FLAGGED` status is not paid — it was
    never validated against a reconciled claim"

    Design: Difficulty/dual_variant_calc/accrual_marginal_batch_vs_blended_period_rebase
    """
    ctx = _two_batch_tiered_accruals()

    validate_success(_close_the_two_batch_period(ctx), 200)

    for accrual_key in ("accrual_a", "accrual_b", "accrual_c"):
        accrual = _read_accrual(ctx[accrual_key]["id"])
        assert accrual["status"] == AccrualStatus.ACCRUED.value
        assert accrual["status"] != AccrualStatus.PAID.value
        assert accrual["validated_by_user_id"] is None
        assert accrual["basis"] == AccrualBasis.BLENDED_PERIOD.value


# ===================================== AS_PURCHASED vs FULL_BASKET basis ======

def test_as_purchased_basis_measures_opportunity_on_the_matched_cases_only():
    """June's report on the AS_PURCHASED basis prices only the 70 MATCHED beef
    cases, giving opportunity 63000 against realized 53184 and a capture rate
    of 8441 basis points.

    PRD: "Under `AS_PURCHASED`, the basis set is the `MATCHED` lines only, so
    opportunity is measured only where the member actually bought on contract
    and an unmatched or excluded line contributes to neither side of the
    comparison."

    Design: Difficulty/dual_variant_calc/savings_report_as_purchased_vs_full_basket_opportunity
    """
    ctx = _june_feed_with_excluded_fries()

    response = api_client.get_savings_report(
        ctx["member_id"],
        make_member_operator_headers(ctx["member_id"]),
        F.savings_report_params(
            C.JUNE_START, C.JUNE_END, SavingsBasis.AS_PURCHASED.value
        ),
    )
    report = validate_success(response, 200)

    assert report["member_id"] == ctx["member_id"]
    assert report["period_start"] == C.JUNE_START
    assert report["period_end"] == C.JUNE_END
    assert report["basis"] == SavingsBasis.AS_PURCHASED.value
    assert report["realized_cents"] == 53184
    assert report["opportunity_cents"] == 63000
    assert report["missed_opportunity_cents"] == 9816
    assert report["capture_rate_bps"] == 8441


def test_full_basket_basis_prices_the_excluded_line_into_opportunity():
    """The identical stored data read on the FULL_BASKET basis additionally
    prices the 20 EXCLUDED fries cases, lifting opportunity to 75000 and
    dropping the capture rate to 7091 while realized stays 53184.

    PRD: "Under `FULL_BASKET`, the basis set additionally includes the member's
    `AMBIGUOUS` and `EXCLUDED` period lines, priced against the contracted item
    named by the line's own `normalized_item_key_reported`" and "Those extra
    lines add to `opportunity_cents` but never to `realized_cents`"

    Design: Difficulty/dual_variant_calc/savings_report_as_purchased_vs_full_basket_opportunity
    """
    ctx = _june_feed_with_excluded_fries()

    response = api_client.get_savings_report(
        ctx["member_id"],
        make_member_operator_headers(ctx["member_id"]),
        F.savings_report_params(
            C.JUNE_START, C.JUNE_END, SavingsBasis.FULL_BASKET.value
        ),
    )
    report = validate_success(response, 200)

    assert report["basis"] == SavingsBasis.FULL_BASKET.value
    assert report["realized_cents"] == 53184
    assert report["opportunity_cents"] == 75000
    assert report["missed_opportunity_cents"] == 21816
    assert report["capture_rate_bps"] == 7091


def test_the_two_savings_bases_differ_only_in_the_four_opportunity_figures():
    """Both June reports agree on 70 matched cases, 20 unmatched cases, 805800
    cents of invoice spend, 6984 cents of rebate share and 0 recovery credit;
    only the basis and its three derived figures move.

    PRD: "`invoice_spend_cents` is the sum of `invoice_extended_cents` over
    **all** the member's period lines regardless of match status."

    Design: Difficulty/dual_variant_calc/savings_report_as_purchased_vs_full_basket_opportunity
    """
    ctx = _june_feed_with_excluded_fries()

    as_purchased = _savings_report(ctx["member_id"], SavingsBasis.AS_PURCHASED.value)
    full_basket = _savings_report(ctx["member_id"], SavingsBasis.FULL_BASKET.value)

    for report in (as_purchased, full_basket):
        assert report["matched_cases"] == 70
        assert report["unmatched_cases"] == 20
        assert report["invoice_spend_cents"] == 805800
        assert report["rebate_member_share_cents"] == 6984
        assert report["recovery_credit_cents"] == 0
        assert report["realized_cents"] == 53184

    assert set(as_purchased.keys()) == set(full_basket.keys())
    differing = {
        key for key in as_purchased if as_purchased[key] != full_basket[key]
    }
    assert differing == {
        "basis",
        "opportunity_cents",
        "missed_opportunity_cents",
        "capture_rate_bps",
    }, f"the two bases must differ in exactly four fields, got {sorted(differing)}"


def test_the_excluded_fries_line_earns_no_rebate_under_either_basis():
    """The fries line's only key candidate sits under a DRAFT deal, so it is
    EXCLUDED with DEAL_NOT_ACTIVE, monetizes nothing, and contributes to
    unmatched cases and to the FULL_BASKET opportunity alone.

    PRD: "when key candidates exist but none is eligible, `match_status`
    becomes `EXCLUDED` and `accrual_block_reason` records why: `ITEM_DELISTED`
    when every key candidate has `status` of `DELISTED`, and `DEAL_NOT_ACTIVE`
    otherwise."

    Design: Difficulty/dual_variant_calc/savings_report_as_purchased_vs_full_basket_opportunity
    """
    ctx = _june_feed_with_excluded_fries()

    fries_line = validate_success(
        api_client.get_purchase_line(ctx["fries_line"]["id"], fx.ANALYST), 200
    )
    assert_purchase_line(fries_line)
    assert fries_line["match_status"] == MatchStatus.EXCLUDED.value
    assert fries_line["accrual_block_reason"] == AccrualBlockReason.DEAL_NOT_ACTIVE.value
    assert fries_line["contracted_item_id"] is None
    assert fries_line["invoice_extended_cents"] == 166000

    accruals = fx.accruals_for_member(ctx["member_id"])
    assert len(accruals) == 2, "only the two matched beef lines are monetized"
    assert all(a["purchase_line_id"] != fries_line["id"] for a in accruals)

    for basis in (SavingsBasis.AS_PURCHASED.value, SavingsBasis.FULL_BASKET.value):
        report = _savings_report(ctx["member_id"], basis)
        assert report["rebate_member_share_cents"] == 6984
        assert report["realized_cents"] == 53184
        assert report["unmatched_cases"] == 20
