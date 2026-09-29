"""Post-show attribution decay and the compliance cost of a late disclosure."""

from test_helpers import (
    MERCHANDISER,
    PRODUCER,
    build_scenario,
    acknowledge_disclosure,
    checkout,
    end_show,
    hold_line,
    publish_marker,
    read_show,
    read_slot,
    register_disclosure,
    replay_conversion_payload,
    set_clock,
    set_marker,
    validate_success,
)


def _ended_show_with_a_published_marker():
    """A broadcast that ended at 19:00Z whose first segment carries a live replay link."""
    scenario = build_scenario(take_live=True, clock_live=None)
    set_clock("2026-08-10T19:00:00Z")
    assert end_show(scenario.show_id)["status"] == "ENDED"
    set_marker(scenario.slot_id, marker_offset_sec=600)
    slot = publish_marker(scenario.slot_id)
    assert slot["replay_marker_status"] == "PUBLISHED"
    set_clock("2026-08-13T21:00:00Z")
    return scenario


def _convert(api, slot_id, viewer_id, occurred_at):
    """Records one post-show conversion of 40 dollars against the segment."""
    return validate_success(
        api.record_replay_conversion(
            slot_id,
            replay_conversion_payload(
                viewer_id, net_revenue_cents=4000, occurred_at=occurred_at
            ),
            MERCHANDISER,
        ),
        201,
    )


def test_attribution_decays_step_by_step_at_each_inclusive_day_boundary(api):
    """Replay revenue is credited in full for a day, then at six tenths, then at
    three tenths, and each boundary hour is still inside the better bucket.

    PRD 3.9: "Within the first day — an elapsed figure of 24 hours or fewer — the
    conversion carries full weight of `1.0`. Beyond that but within two days — 48
    hours or fewer — it carries `0.6`. Beyond that but within three days — 72 hours
    or fewer — it carries `0.3`."
    PRD 3.9: "The boundaries are inclusive, so exactly 24 hours still weights `1.0`,
    exactly 48 weights `0.6`, exactly 72 weights `0.3`, and 73 hours weights `0.0`."
    PRD 3.9: "The slot's `replay_attributed_revenue_cents` is increased by
    `net_revenue_cents` multiplied by that weight, rounded half up to a whole cent
    **per conversion** before it is added to the running total."

    Design: Corner/calculations/replay_decay_weights_applied_at_every_bucket_boundary
    """
    scenario = _ended_show_with_a_published_marker()
    viewer_id = scenario.viewer_id

    first = _convert(api, scenario.slot_id, viewer_id, "2026-08-11T19:00:00Z")
    assert first["replay_attributed_revenue_cents"] == 4000, "exactly 24 hours: full weight"
    assert first["replay_conversions_count"] == 1

    second = _convert(api, scenario.slot_id, viewer_id, "2026-08-12T19:00:00Z")
    assert second["replay_attributed_revenue_cents"] == 6400, "exactly 48 hours adds 2400"
    assert second["replay_conversions_count"] == 2

    third = _convert(api, scenario.slot_id, viewer_id, "2026-08-13T19:00:00Z")
    assert third["replay_attributed_revenue_cents"] == 7600, "exactly 72 hours adds 1200"
    assert third["replay_conversions_count"] == 3


def test_a_conversion_beyond_the_horizon_is_counted_but_earns_nothing(api):
    """An hour past the third day the sale no longer earns the show any attributed
    revenue, yet it is still recorded as a conversion.

    PRD 3.9: "The boundaries are inclusive, so exactly 24 hours still weights `1.0`,
    exactly 48 weights `0.6`, exactly 72 weights `0.3`, and 73 hours weights `0.0`."
    PRD 3.9: "The slot's `replay_conversions_count` is incremented by one **even when
    the weight is zero** — a conversion outside the attribution horizon is still a
    conversion and still counts toward the host's attributed score."
    PRD 3.9: "The show's `replay_attributed_revenue_cents` is then recomputed as the
    sum of `replay_attributed_revenue_cents` across all of that show's slots"

    Design: Corner/calculations/replay_decay_weights_applied_at_every_bucket_boundary
    """
    scenario = _ended_show_with_a_published_marker()
    viewer_id = scenario.viewer_id
    for occurred_at in (
        "2026-08-11T19:00:00Z",
        "2026-08-12T19:00:00Z",
        "2026-08-13T19:00:00Z",
    ):
        _convert(api, scenario.slot_id, viewer_id, occurred_at)

    late = _convert(api, scenario.slot_id, viewer_id, "2026-08-13T20:00:00Z")

    assert late["replay_attributed_revenue_cents"] == 7600, "73 hours earns nothing"
    assert late["replay_conversions_count"] == 4, "a zero-weight conversion still counts"
    assert late["replay_marker_status"] == "PUBLISHED"

    slot = read_slot(scenario.slot_id)
    assert slot["replay_attributed_revenue_cents"] == 7600
    assert slot["replay_conversions_count"] == 4
    assert read_show(scenario.show_id)["replay_attributed_revenue_cents"] == 7600


def _show_with_one_late_disclosure():
    """A LIVE show where the host spoke the second disclosure only after going on air."""
    scenario = build_scenario(take_live=True, activate=True, num_carts=1)
    late = register_disclosure(
        scenario.show_id,
        scenario.bookings[0]["id"],
        disclosure_type="MATERIAL_CONNECTION",
        required_script_code="SCRIPT-PAID-02",
    )
    late = acknowledge_disclosure(
        late["id"], scenario.host_id, script_code_spoken="SCRIPT-PAID-02"
    )
    return scenario, late


def test_a_disclosure_spoken_after_going_on_air_is_flagged_late(api):
    """The flag that costs the host points is set by comparing the moment the
    disclosure was spoken with the moment the broadcast opened.

    PRD 3.1: "Acknowledgement moves the record `PENDING → ACKNOWLEDGED`, stamps
    `acknowledged_at` with the logical instant, increments `version`, and computes
    `acknowledged_late`: the flag is true when `acknowledged_at` is set, the show's
    `went_live_at` is set, and `acknowledged_at` is strictly later than `went_live_at`
    — that is, when the host spoke the disclosure only after the broadcast had already
    started. Otherwise the flag is false."

    Design: Corner/calculations/host_score_late_acknowledgement_costs_the_compliance_component
    """
    scenario, late = _show_with_one_late_disclosure()

    early = validate_success(api.get_disclosure_record(scenario.disclosure["id"], PRODUCER))
    assert early["status"] == "ACKNOWLEDGED"
    assert early["acknowledged_late"] is False, "this one was spoken before air"

    assert late["status"] == "ACKNOWLEDGED"
    assert late["acknowledged_late"] is True, "this one was spoken after the show opened"


def test_one_late_disclosure_costs_the_host_twenty_five_compliance_points(api):
    """A single late disclosure drops the compliance component from a hundred to
    seventy-five, and with a perfect conversion rate and no interaction at all the
    host's live-window score lands on sixty-five.

    PRD 3.9: "The `compliance_component` starts at 100, subtracts 25 points for each
    late disclosure acknowledgement and a further 50 points if the
    unsubstantiated-claim indicator is 1, and floors the result at 0."
    PRD 3.9: "The `conversion_component` divides the effective order count by the
    larger of `unique_cart_count` and 1, multiplies by 100, rounds half up, and caps
    the result at 100. The `engagement_component` awards 10 points per answered
    question and 2 points per poll vote, capped at 100."
    PRD 3.9: "The `effectiveness_score` is then the weighted sum of the three — the
    conversion component at a weight of `0.5`, the engagement component at `0.3`, and
    the compliance component at `0.2` — rounded half up exactly once at the end."
    PRD 3.9: "Requesting the live-window variant stamps its result into the host's
    `effectiveness_score_live`"

    Design: Corner/calculations/host_score_late_acknowledgement_costs_the_compliance_component
    """
    scenario, _late = _show_with_one_late_disclosure()
    hold_line(scenario, 1, cart_index=0)
    order = checkout(scenario.carts[0]["id"], scenario.viewers[0]["id"])
    assert order["payment_state"] == "AUTHORIZED"

    result = validate_success(
        api.get_host_performance(
            scenario.host_id,
            PRODUCER,
            params={"variant": "LIVE_WINDOW", "show_id": scenario.show_id},
        )
    )

    assert result["effectiveness_score"] == 65, (
        "half of 100 plus three tenths of 0 plus a fifth of 75 is 65"
    )

    host = validate_success(api.get_host(scenario.host_id, PRODUCER))
    assert host["effectiveness_score_live"] == 65, (
        "the live-window read stamps its result onto the host"
    )
