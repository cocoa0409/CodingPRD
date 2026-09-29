"""The scorecard: the governing rolling window against the reporting lifetime decay,
and the exact threshold at which removal becomes licensed.

Both variants read the same immutable ledger. The rolling variant sees a 90-day
window at full weight; the lifetime variant sees everything, attenuated by age. Only
the rolling figure gates anything.
"""

from test_helpers import (
    InstallerStatus,
    ScorecardEventSource,
    ScorecardEventType,
    assert_ledger_row,
    assert_score,
    assert_scorecard_dimensions,
    factories as f,
    fixtures as fx,
)

# The clock starts at 2026-08-01T00:00:00.000Z, so the rolling window opens
# inclusively at 2026-05-03T00:00:00.000Z.
FIVE_EVENTS = [
    f.scorecard_event_payload(ScorecardEventType.ON_TIME_COMPLETION,
                              "2026-07-01T00:00:00.000Z"),
    f.scorecard_event_payload(ScorecardEventType.LATE_COMPLETION,
                              "2026-06-15T00:00:00.000Z"),
    f.scorecard_event_payload(ScorecardEventType.PUNCH_MAJOR,
                              "2026-05-03T00:00:00.000Z"),
    f.csat_event_payload(2, "2026-05-02T00:00:00.000Z"),
    f.scorecard_event_payload(ScorecardEventType.WARRANTY_UPHELD,
                              "2026-01-15T00:00:00.000Z"),
]
OLD_NO_SHOW = f.scorecard_event_payload(ScorecardEventType.NO_SHOW,
                                        "2025-03-10T00:00:00.000Z")


def test_rolling_and_lifetime_composites_diverge_over_one_ledger(api):
    """Six events give a governing composite of 79.60 and a reporting composite of
    72.16, and it is the rolling figure that leaves the firm ACTIVE.

    PRD 3.9: "The same six rows therefore yield 79.60 on the governing score and 72.16
    on the reporting score, and the firm stays `ACTIVE` because it is the **rolling**
    figure that is compared with the threshold."

    Design: Difficulty/dual_variant_calc/installer_scorecard_rolling_window_versus_lifetime_decay_diverge
    """
    network = fx.installer_with_events(api, FIVE_EVENTS)
    fx.file_events(api, network["installer"]["id"], [OLD_NO_SHOW])
    installer = fx.read_installer(api, network["installer"]["id"])

    # Rolling: only the 31-, 47- and 90-day events are inside the window.
    assert_scorecard_dimensions(installer, quality=79.00, timeliness=81.00,
                                satisfaction=79.00, composite=79.60)
    # Lifetime: the 91- and 198-day events weigh 0.60 and the 509-day event 0.30.
    assert_score(installer["lifetime_composite_score"], 72.16,
                 "lifetime_composite_score")
    assert installer["rolling_event_count"] == 3
    assert installer["rolling_no_show_count"] == 0
    assert installer["removal_eligible"] is False
    assert installer["status"] == InstallerStatus.ACTIVE


def test_the_computed_read_shows_both_variants_side_by_side(api):
    """The computed scorecard read exposes the lifetime event count and both
    composites, which the installer row alone cannot supply.

    PRD 3.9: "Note that the lifetime dimension scores and `lifetime_event_count` are
    available **only** through this read; the installer row itself persists only the
    lifetime composite."

    Design: Difficulty/dual_variant_calc/installer_scorecard_rolling_window_versus_lifetime_decay_diverge
    """
    network = fx.installer_with_events(api, FIVE_EVENTS)
    written = fx.file_events(api, network["installer"]["id"], [OLD_NO_SHOW])

    # The trigger row freezes the NO_SHOW tariff and is an operator filing.
    trigger = written[0]
    assert_ledger_row(trigger)
    assert trigger["event_type"] == ScorecardEventType.NO_SHOW
    assert trigger["source"] == ScorecardEventSource.MANUAL
    assert_score(trigger["quality_delta"], -4.00, "quality_delta")
    assert_score(trigger["timeliness_delta"], -20.00, "timeliness_delta")
    assert_score(trigger["satisfaction_delta"], -10.00, "satisfaction_delta")

    scorecard = fx.read_scorecard(api, network["installer"]["id"])
    assert_score(scorecard["rolling_composite_score"], 79.60,
                 "rolling_composite_score")
    assert_score(scorecard["lifetime_composite_score"], 72.16,
                 "lifetime_composite_score")
    assert scorecard["rolling_event_count"] == 3
    assert scorecard["lifetime_event_count"] == 6
    assert scorecard["removal_eligible"] is False
    assert scorecard["probation_active"] is False


# Four events inside the rolling window leave the composite at 71.25; the fifth is
# what lands it exactly on the removal threshold.
FOUR_EVENTS = [
    f.scorecard_event_payload(ScorecardEventType.PUNCH_SAFETY,
                              "2026-07-05T00:00:00.000Z"),
    f.scorecard_event_payload(ScorecardEventType.PUNCH_MINOR,
                              "2026-07-08T00:00:00.000Z"),
    f.csat_event_payload(2, "2026-07-12T00:00:00.000Z"),
    f.csat_event_payload(2, "2026-07-16T00:00:00.000Z"),
]
FIFTH_EVENT = f.csat_event_payload(2, "2026-07-20T00:00:00.000Z")


def test_composite_landing_exactly_on_seventy_licenses_removal(api):
    """A composite of exactly 70.00 satisfies the threshold, because the comparison is
    "70.00 or below" and not "below 70.00".

    PRD 3.9: "`removal_eligible` becomes true when the rolling `composite_score` is
    70.00 or below **and** `rolling_event_count` is 3 or more, **or** when
    `rolling_no_show_count` is 3 or more, **or** when the number of `PUNCH_SAFETY`
    events inside the rolling window is 2 or more".

    Design: Difficulty/boundary_precision_check/composite_score_landing_exactly_on_70_00_makes_removal_eligible
    """
    network = fx.installer_with_events(api, FOUR_EVENTS)
    before = network["installer"]
    # 67.00 * 0.45 + 82.00 * 0.30 + 66.00 * 0.25 = 30.15 + 24.60 + 16.50 = 71.25.
    assert_score(before["composite_score"], 71.25,
                 "composite_score before the fifth event")
    assert before["removal_eligible"] is False
    assert before["status"] == InstallerStatus.PROBATION

    fx.file_events(api, before["id"], [FIFTH_EVENT])
    installer = fx.read_installer(api, before["id"])

    # 67.00 * 0.45 + 82.00 * 0.30 + 61.00 * 0.25 = 30.15 + 24.60 + 15.25 = 70.00.
    assert_scorecard_dimensions(installer, quality=67.00, timeliness=82.00,
                               satisfaction=61.00, composite=70.00)
    assert installer["removal_eligible"] is True


def test_the_threshold_event_is_counted_by_the_rolling_variant(api):
    """The fifth survey is inside the window, so it moves the governing composite off
    71.25, and the lifetime variant agrees because every event weighs 1.00.

    PRD 3.9: "The rolling variant considers only the events whose `occurred_at` is at
    or after the logical clock minus 90 days, an **inclusive** lower bound, so an event
    exactly 90 days old is still inside the window; every event inside it counts at
    full weight 1.00 and every event outside it counts for nothing at all."

    Design: Difficulty/boundary_precision_check/composite_score_landing_exactly_on_70_00_makes_removal_eligible
    """
    network = fx.installer_with_events(api, FOUR_EVENTS)
    fx.file_events(api, network["installer"]["id"], [FIFTH_EVENT])
    installer = fx.read_installer(api, network["installer"]["id"])

    assert installer["rolling_event_count"] == 5
    assert installer["rolling_no_show_count"] == 0
    assert installer["composite_score"] != 71.25, (
        "the fifth survey is inside the rolling window and must be counted"
    )
    assert installer["composite_score"] != 68.75, (
        "the composite is built from the already-rounded dimension scores"
    )
    # Every one of the five events is 90 days old or less, so no decay band applies
    # and the reporting variant lands on the same figure.
    assert_score(installer["lifetime_composite_score"], 70.00,
                 "lifetime_composite_score")
    assert installer["status"] == InstallerStatus.PROBATION
