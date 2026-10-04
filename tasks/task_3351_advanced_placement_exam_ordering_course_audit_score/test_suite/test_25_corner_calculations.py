"""Two computed fields written by a transition rather than supplied by the caller."""
from test_helpers import (
    LATE_WINDOW_CLOCK_UTC,
    get_order,
    get_registration,
    setup_aggregated_score,
    setup_fee_pending_registration,
)


def test_late_tier_registration_assessed_in_the_late_window_carries_4000():
    """PRD §3.3: "a `LATE` tier pays 4000 cents when the window is `LATE` and 4000 plus the 5500-cent closed-window addition, that is 9500 cents, when the window is `CLOSED`"
    PRD §3.3: "The assessed amount lands in `late_fee_cents`."

    Design: Corner/calculations/late_tier_registration_in_late_window_assesses_4000
    """
    bundle = setup_fee_pending_registration(clock=LATE_WINDOW_CLOCK_UTC)
    registration = bundle["registration"]

    assert registration["late_fee_cents"] == 4000, (
        f"the LATE-window rate is 4000, got {registration['late_fee_cents']}"
    )
    assert registration["status"] == "FEE_PENDING"
    assert registration["fees_paid_cents"] == 0
    assert get_order(bundle["order"]["id"])["ordering_window"] == "LATE"


def test_raw_composite_of_96_aggregates_to_a_five():
    """PRD §3.7: "a composite of 96.0 or more is a 5"
    PRD §3.7: "Band selection is performed at full floating-point precision with no intermediate rounding."
    PRD §3.7: "Aggregation writes `ap_score` using the final variant of the score-mapping calculation and fires the owning registration's move from `MATERIAL_ASSIGNED` to `SCORED`."

    Design: Corner/calculations/ap_score_at_96_boundary_maps_to_five
    """
    bundle = setup_aggregated_score(raw_composite=96.0)
    score = bundle["score"]

    assert score["ap_score"] == 5, f"96.0 sits in the AP5 band, got {score['ap_score']}"
    assert score["status"] == "AGGREGATED"
    assert score["raw_composite"] == 96.0
    assert get_registration(bundle["registration"]["id"])["status"] == "SCORED"


def test_raw_composite_below_96_stops_at_a_four():
    """PRD §3.7: "from 76.0 up to but excluding 96.0 is a 4"
    PRD §3.7: "a raw composite of 95.5 yields a final score of 4 but a marginal score of 5"

    Design: Corner/calculations/ap_score_at_96_boundary_maps_to_five
    """
    bundle = setup_aggregated_score(raw_composite=95.5)
    score = bundle["score"]

    assert score["ap_score"] == 4, (
        f"95.5 is below the AP5 edge, so the final variant maps it to 4, got {score['ap_score']}"
    )
