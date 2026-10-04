"""Transaction fee settlement at the monthly chargeable ceiling.

The ceiling is applied with a clamp before the marginal tier schedule runs, so the boundary
is crossed exactly once: 7499 and 7500 settle differently while 7500 and 7501 settle at the
same amount.
"""
from test_helpers import (
    set_clock,
    create_clinic,
    post_fee_entry,
    reload_fee_entry,
    apply_tiers,
    SENDER_SCHEDULE,
    FEE_CEILING_BOUNDARIES,
    MONTHLY_CHARGEABLE_CEILING,
)


def test_monthly_ceiling_boundary_below_at_and_above(api):
    """PRD §3.7: "A worked illustration: on a sender cell of 500 transactions of an ordinary
    type, the charge is the standard-band count of 300 at 12 cents plus the volume-band count
    of zero, giving 3600 cents."
    PRD §3.7: "The count falling in the standard band is the smaller of the amount above the
    free bound and the band's width, floored at zero; the count falling in the volume band is
    the amount above the standard bound, floored at zero."

    Design: Difficulty/boundary_precision_check/monthly_chargeable_ceiling_boundary_at_seven_thousand_five_hundred
    """
    set_clock()
    clinic = create_clinic(volume_billing_mode="MONTHLY")

    assert apply_tiers(7499) == FEE_CEILING_BOUNDARIES[7499]
    assert apply_tiers(7500) == FEE_CEILING_BOUNDARIES[7500]

    below = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT",
        transaction_count=MONTHLY_CHARGEABLE_CEILING - 1,
    )
    at = post_fee_entry(
        clinic["id"], transaction_type="REFILL_RESPONSE", direction="SENT",
        transaction_count=MONTHLY_CHARGEABLE_CEILING,
    )
    above = post_fee_entry(
        clinic["id"], transaction_type="CHANGE_RESPONSE", direction="SENT",
        transaction_count=MONTHLY_CHARGEABLE_CEILING + 1,
    )

    assert below["fee_tier"] == "VOLUME"
    assert below["fee_cents"] == 60093
    assert below["fee_cents"] == 1800 * SENDER_SCHEDULE["default"]["R2"] + 5499 * SENDER_SCHEDULE["default"]["R3"]

    assert at["fee_cents"] == 60100
    assert at["fee_cents"] == 1800 * SENDER_SCHEDULE["default"]["R2"] + 5500 * SENDER_SCHEDULE["default"]["R3"]

    assert above["fee_cents"] == 60100
    assert below["fee_cents"] != at["fee_cents"]
    assert at["fee_cents"] == above["fee_cents"]


def test_above_ceiling_row_settles_at_the_ceiling_and_never_past_it(api):
    """PRD §3.7: "For a sender cell of a non-history type that value is 60100 cents."
    PRD §3.7: "every count at or above the ceiling settles at exactly the fee for 7500, and
    the ceiling absorbs the top `VOLUME` tier."

    Design: Difficulty/boundary_precision_check/monthly_chargeable_ceiling_boundary_at_seven_thousand_five_hundred
    """
    set_clock()
    clinic = create_clinic(volume_billing_mode="MONTHLY")

    above = post_fee_entry(
        clinic["id"], transaction_type="CHANGE_RESPONSE", direction="SENT",
        transaction_count=MONTHLY_CHARGEABLE_CEILING + 1,
    )
    # The unclamped schedule for 7501 would have been 1800*12 + 5501*7 == 60107.
    assert apply_tiers(MONTHLY_CHARGEABLE_CEILING + 1) == 60107
    assert above["fee_cents"] == 60100

    reloaded = reload_fee_entry(above["id"])
    assert reloaded["transaction_count"] == MONTHLY_CHARGEABLE_CEILING + 1
    assert reloaded["fee_cents"] == 60100
    assert reloaded["period_net_total_cents"] == reloaded["fee_cents"]