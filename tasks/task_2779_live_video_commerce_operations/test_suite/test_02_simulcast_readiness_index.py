"""Grading the simulcast: three penalties, a cross-channel spread and a minimum."""

from test_helpers import (
    build_scenario,
    read_channel,
    read_show,
    report_health,
)


def _three_provisioned_channels():
    """A DRAFT show with a flagship, a social and a partner destination, none reporting yet."""
    return build_scenario(
        channels=[
            {"platform": "FLAGSHIP_APP", "target_latency_ms": 1500, "is_primary": True, "latency_ms": None},
            {"platform": "SOCIAL_A", "target_latency_ms": 1500, "latency_ms": None},
            {"platform": "PARTNER_APP", "target_latency_ms": 1500, "latency_ms": None},
        ]
    )


def test_first_health_report_grades_absolute_latency_and_frame_loss():
    """A destination 100 ms over the reference losing 2 percent of frames grades 90.

    The PRD: "take the destination's reported latency_ms, subtract 1,500
    milliseconds, divide by 50 milliseconds, and floor the result at zero", and the
    frame penalty is "the reported dropped_frame_pct multiplied by 400"; with one
    reported destination the spread is zero, so the three penalties sum to 10.

    Design: Difficulty/combinatorial_formula/simulcast_index_three_input_nonlinear
    """
    scenario = _three_provisioned_channels()

    report_health(scenario.channels[0]["id"], 1600, 0.02)

    assert read_channel(scenario.channels[0]["id"])["readiness_index"] == 90


def test_show_index_stays_zero_while_a_provisioned_destination_has_never_reported():
    """One silent destination floors the whole show's index even though another grades 90.

    The PRD: "A destination that has been provisioned but has never filed a report
    keeps readiness_index at 0 and is excluded from the spread calculation, but it
    is still a member of the PROVISIONED set — so a single silent destination floors
    the whole show's index at 0."

    Design: Difficulty/combinatorial_formula/simulcast_index_three_input_nonlinear
    """
    scenario = _three_provisioned_channels()

    report_health(scenario.channels[0]["id"], 1600, 0.02)

    assert read_channel(scenario.channels[0]["id"])["readiness_index"] == 90
    assert read_show(scenario.show_id)["simulcast_readiness_index"] == 0


def test_a_second_destinations_report_reprices_the_destination_that_did_not_report():
    """A 1000 ms spread costs the flagship two points without it filing a new report.

    The PRD: "Because the spread changes, the report recomputes readiness_index for
    every reported destination of the show, not just the one that filed the report",
    the spread being "the largest reported latency_ms minus the smallest" less a
    tolerance of 800 milliseconds, divided by 100.

    Design: Difficulty/combinatorial_formula/simulcast_index_three_input_nonlinear
    """
    scenario = _three_provisioned_channels()

    report_health(scenario.channels[0]["id"], 1600, 0.02)
    report_health(scenario.channels[1]["id"], 2600, 0.01)

    assert read_channel(scenario.channels[0]["id"])["readiness_index"] == 88
    assert read_channel(scenario.channels[1]["id"])["readiness_index"] == 72


def test_partner_destination_is_exempt_from_the_drift_penalty():
    """Two destinations reporting identical latency and frame loss grade differently.

    The PRD: "Destinations on PARTNER_APP are exempt: their drift penalty is always
    zero, because the partner surface is not expected to stay in sync with the
    flagship. For every other platform, the drift penalty applies in full."

    Design: Difficulty/combinatorial_formula/simulcast_index_three_input_nonlinear
    """
    scenario = _three_provisioned_channels()

    report_health(scenario.channels[0]["id"], 1600, 0.02)
    report_health(scenario.channels[1]["id"], 2600, 0.01)
    report_health(scenario.channels[2]["id"], 2600, 0.01)

    social = read_channel(scenario.channels[1]["id"])
    partner = read_channel(scenario.channels[2]["id"])
    assert social["readiness_index"] == 72
    assert partner["readiness_index"] == 74


def test_show_index_is_the_minimum_across_its_serving_destinations():
    """Indices of 88, 72 and 74 give a show index of 72, not their average.

    The PRD: "Show.simulcast_readiness_index is the minimum readiness_index across
    the show's destinations whose status is PROVISIONED or LIVE".

    Design: Difficulty/combinatorial_formula/simulcast_index_three_input_nonlinear
    """
    scenario = _three_provisioned_channels()

    report_health(scenario.channels[0]["id"], 1600, 0.02)
    report_health(scenario.channels[1]["id"], 2600, 0.01)
    report_health(scenario.channels[2]["id"], 2600, 0.01)

    assert read_channel(scenario.channels[0]["id"])["readiness_index"] == 88
    assert read_show(scenario.show_id)["simulcast_readiness_index"] == 72


def test_destinations_above_the_failure_floor_all_stay_provisioned():
    """No index falls below 40, so nothing is taken out of service.

    The PRD: "A destination whose recomputed readiness_index falls below 40 is
    unfit to carry the broadcast and transitions to FAILED".

    Design: Difficulty/combinatorial_formula/simulcast_index_three_input_nonlinear
    """
    scenario = _three_provisioned_channels()

    report_health(scenario.channels[0]["id"], 1600, 0.02)
    report_health(scenario.channels[1]["id"], 2600, 0.01)
    report_health(scenario.channels[2]["id"], 2600, 0.01)

    for channel in scenario.channels:
        assert read_channel(channel["id"])["status"] == "PROVISIONED"
