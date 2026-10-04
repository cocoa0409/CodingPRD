"""The net settlement waterfall: pass-through and errors-and-omissions pools."""
from test_helpers import (
    setup_funded_period, advance_period, net_settlement,
    create_pass_through, refresh_advisor,
)


def _institutional_small_basis(advisor_code):
    """An INSTITUTIONAL advisor whose 500 bps floor keeps the payout basis tiny.

    The four entries stay inside the first tier, so the 6,500-point institutional
    offset drives every one of them to the 500-basis-point floor. The resulting
    845,000 payout basis cannot absorb the 3,000,000 flat technology charge,
    which makes both the zero floor and the replay idempotence observable.
    """
    ctx = setup_funded_period(
        advisor_code=advisor_code, affiliation_model="INSTITUTIONAL",
        projected_annual_production_cents=500_000,
        entries=((500_000, "2026-09-01", "EQUITY"),
                 (15_000_000, "2026-09-01", "EQUITY"),
                 (1_000_000, "2026-09-01", "EQUITY"),
                 (400_000, "2026-09-01", "EQUITY")),
        release=True)
    advisor = ctx["advisor"]
    period = ctx["period"]
    ctx["tech_row"] = create_pass_through(advisor, period["id"], "TECHNOLOGY",
                                          "FLAT_MONTHLY")
    ctx["eo_row"] = create_pass_through(advisor, period["id"], "E_AND_O",
                                        "PCT_OF_GROSS")
    # The line's release amount is what carries the payout basis, and a line is
    # released when the period is posted, so the settlement is computed on a
    # posted period.
    advance_period(period["id"], "CLOSED", ctx["branch"]["branch_code"])
    advance_period(period["id"], "PAID", ctx["branch"]["branch_code"])
    return ctx


# ─── compensating_invariant ───────────────────────────

def test_recalling_the_settlement_leaves_the_pools_unchanged():
    """PRD §3.5: "The running total after all rows is the `pass_through_cents`."
    PRD §3.5: "Every such row takes the payout basis multiplied by the
    errors-and-omissions rate for the advisor's `eo_coverage_level` and divided by 10000,
    rounded half up".

    Design: Difficulty/compensating_invariant/net_settlement_post_once_preserves_the_pool_identity
    """
    ctx = _institutional_small_basis("A-4004")
    first = net_settlement(ctx["period"]["id"], ctx["advisor"]["advisor_code"])
    #  TIER_1_APPLIED_BPS = 7000 - 6500 = 500, so the entries pay 25000, 750000,
    #  50000 and 20000, a payout basis of 845000. The flat technology charge is
    #  clipped to what that basis can still absorb, 845000, and the errors-and-
    #  omissions row is 120 basis points of the pre-expense basis, 10140.
    assert first["pass_through_cents"] == 845_000
    assert first["eo_charge_cents"] == 10_140, (
        "120 basis points of the payout basis, computed before the expense pool")

    second = net_settlement(ctx["period"]["id"], ctx["advisor"]["advisor_code"])
    assert second["pass_through_cents"] == first["pass_through_cents"]
    assert second["eo_charge_cents"] == first["eo_charge_cents"]


def test_settlement_floors_the_net_at_zero_and_replays_without_drift():
    """PRD §3.5: "The `net_settlement_cents` is the payout basis minus the
    `pass_through_cents` minus the `eo_charge_cents`, floored at zero so that a settlement
    is never negative."
    PRD §3.5: "the annual gross payout cap that flips `annual_payout_cap_hit` is
    500,000,000 cents".

    Design: Difficulty/compensating_invariant/net_settlement_post_once_preserves_the_pool_identity
    """
    ctx = _institutional_small_basis("A-4005")
    first = net_settlement(ctx["period"]["id"], ctx["advisor"]["advisor_code"])
    assert first["pass_through_cents"] == 845_000, (
        "the flat technology charge is clipped to what the 845,000 basis can absorb")
    assert first["net_settlement_cents"] == 0, (
        "the basis cannot absorb the pools and the errors-and-omissions charge, so the floor "
        "at zero clamps the net")

    second = net_settlement(ctx["period"]["id"], ctx["advisor"]["advisor_code"])
    assert second["net_settlement_cents"] == 0
    assert second["pass_through_cents"] == first["pass_through_cents"]
    assert second["eo_charge_cents"] == first["eo_charge_cents"]

    advisor = refresh_advisor(ctx["advisor"]["id"])
    assert advisor["annual_payout_cap_hit"] is False