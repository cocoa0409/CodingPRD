"""Destination health: failure, recovery, and how the show-level grade is formed."""

from test_helpers import (
    PRODUCER,
    build_scenario,
    health_report_payload,
    read_channel,
    report_health,
    read_show,
    validate_paginated,
    validate_success,
)


def _ready_show_with_one_destination():
    """A READY show carrying exactly one healthy destination and no flash pricing."""
    scenario = build_scenario(
        with_disclosure=False,
        offers=[],
        channels=[
            {
                "platform": "FLAGSHIP_APP",
                "target_latency_ms": 1500,
                "is_primary": True,
                "latency_ms": 1500,
                "dropped_frame_pct": 0.0,
            }
        ],
        run_ready=True,
    )
    assert read_show(scenario.show_id)["status"] == "READY"
    return scenario


def test_a_failing_destination_takes_readiness_away_from_the_show(api):
    """A destination reporting five seconds of latency and half its frames lost is
    unfit to carry the broadcast; with no other pipe left in service the show loses
    its readiness.

    PRD 3.3: "A destination whose recomputed `readiness_index` falls **below 40**
    is unfit to carry the broadcast and transitions to `FAILED` — from
    `PROVISIONED` or from `LIVE` alike."
    PRD 3.3: "when the failure leaves a show sitting in `READY` with **zero**
    destinations remaining in `PROVISIONED` or `LIVE`, that show falls back `READY
    → DRAFT`."
    PRD 3.3: "`Show.simulcast_readiness_index` is the *minimum* `readiness_index`
    across the show's destinations whose status is `PROVISIONED` or `LIVE`; when
    that set is empty the show-level figure is 0."
    PRD 3.3: "The report is stored onto the destination as its latest `latency_ms`
    and `dropped_frame_pct`, `health_report_count` is incremented, and the
    destination's `version` is incremented."

    Design: Corner/state_machines/channel_failure_reverts_ready_show_and_reprovision_closes_the_cycle
    """
    scenario = _ready_show_with_one_destination()

    channel = validate_success(
        api.report_channel_health(
            scenario.channel_id,
            health_report_payload(latency_ms=5000, dropped_frame_pct=0.5),
            PRODUCER,
        )
    )

    assert channel["status"] == "FAILED"
    assert channel["readiness_index"] == 0, (
        "a latency penalty of 70 plus a frame-loss penalty of 200 clamps the grade to 0"
    )
    assert channel["health_report_count"] == 2, "the perfect sample and this one"

    show = read_show(scenario.show_id)
    assert show["status"] == "DRAFT", "the show has no serviceable destination left"
    assert show["simulcast_readiness_index"] == 0


def test_reprovisioning_a_failed_destination_lets_the_show_be_declared_ready_again(api):
    """Bringing a failed pipe back into service is the producer's remedy, but
    service alone does not restore readiness: only a healthy sample restores the
    grade, and only then does the gate pass again.

    PRD 3.3: "Provisioning takes the destination `DRAFT → PROVISIONED` and is
    permitted while the show is in `DRAFT` or `READY`; the same operation also
    serves as recovery, taking a destination `FAILED → PROVISIONED` and closing the
    `PROVISIONED → FAILED → PROVISIONED` cycle."
    PRD 3.3: "A destination that has been provisioned but has never filed a report
    keeps `readiness_index` at 0 and is excluded from the spread calculation, but
    it is still a member of the `PROVISIONED` set"
    PRD 3.4: "A show that clears all six recomputes `simulcast_readiness_index`
    from the current destination health, stamps `readiness_checked_at` with the
    logical instant, and increments its `version`."

    Design: Corner/state_machines/channel_failure_reverts_ready_show_and_reprovision_closes_the_cycle
    """
    scenario = _ready_show_with_one_destination()
    validate_success(
        api.report_channel_health(
            scenario.channel_id,
            health_report_payload(latency_ms=5000, dropped_frame_pct=0.5),
            PRODUCER,
        )
    )

    recovered = validate_success(
        api.provision_stream_channel(scenario.channel_id, PRODUCER)
    )
    assert recovered["status"] == "PROVISIONED", "the failed destination is back in service"
    assert recovered["readiness_index"] == 0, "service alone files no measurement"
    assert read_show(scenario.show_id)["status"] == "DRAFT", (
        "restoring a pipe never promotes the show by itself"
    )

    healthy = validate_success(
        api.report_channel_health(
            scenario.channel_id,
            health_report_payload(latency_ms=1500, dropped_frame_pct=0.0),
            PRODUCER,
        )
    )
    assert healthy["readiness_index"] == 100
    assert healthy["health_report_count"] == 3
    assert read_show(scenario.show_id)["simulcast_readiness_index"] == 100

    show = validate_success(api.ready_show(scenario.show_id, PRODUCER))
    assert show["status"] == "READY", "the recovery cycle closes and the gate passes"
    assert show["simulcast_readiness_index"] == 100


def _show_with_one_reporting_and_one_silent_destination():
    """A show whose flagship pipe reports perfectly and whose social pipe never does.

    The flagship files its sample again after the social pipe enters service, so
    the show-level figure is recomputed with both destinations in the set.
    """
    scenario = build_scenario(
        products=[{"substantiate": False}],
        with_booking=False,
        with_disclosure=False,
        offers=[],
        channels=[
            {
                "platform": "FLAGSHIP_APP",
                "target_latency_ms": 1500,
                "is_primary": True,
                "latency_ms": 1500,
                "dropped_frame_pct": 0.0,
            },
            {
                "platform": "SOCIAL_A",
                "target_latency_ms": 2000,
                "latency_ms": None,
            },
        ],
    )
    report_health(scenario.channel_id, 1500, 0.0)
    return scenario


def test_one_silent_destination_floors_the_whole_shows_grade(api):
    """The show-level grade is the worst grade in service, so a destination that has
    been put into service but has never sent a measurement drags the whole
    broadcast's grade to zero.

    PRD 3.3: "`Show.simulcast_readiness_index` is the *minimum* `readiness_index`
    across the show's destinations whose status is `PROVISIONED` or `LIVE`; when
    that set is empty the show-level figure is 0."
    PRD 3.3: "A destination that has been provisioned but has never filed a report
    keeps `readiness_index` at 0 and is excluded from the spread calculation, but it
    is still a member of the `PROVISIONED` set — so a single silent destination
    floors the whole show's index at 0."
    PRD 3.3: "the report recomputes `readiness_index` for **every** reported
    destination of the show, not just the one that filed the report, and only then
    recomputes the show-level figure."

    Design: Corner/calculations/show_index_is_zero_while_a_provisioned_channel_has_never_reported
    """
    scenario = _show_with_one_reporting_and_one_silent_destination()

    show = read_show(scenario.show_id)
    assert show["simulcast_readiness_index"] == 0, (
        "the silent destination is the minimum of the in-service set"
    )

    silent = read_channel(scenario.channels[1]["id"])
    assert silent["status"] == "PROVISIONED"
    assert silent["readiness_index"] == 0
    assert silent["latency_ms"] is None
    assert silent["health_report_count"] == 0


def test_a_silent_destination_does_not_dent_the_destination_that_did_report(api):
    """Drift is measured only across destinations that actually reported, so the
    silent pipe cannot invent a latency spread that penalises the pipe reporting
    perfectly.

    PRD 3.3: "Across the show's *reported* destinations — those whose status is
    `PROVISIONED` or `LIVE` and whose `latency_ms` is not null — take the largest
    reported `latency_ms` minus the smallest; that difference is the spread."
    PRD 3.3: "A destination that has been provisioned but has never filed a report
    keeps `readiness_index` at 0 and is excluded from the spread calculation"

    Design: Corner/calculations/show_index_is_zero_while_a_provisioned_channel_has_never_reported
    """
    scenario = _show_with_one_reporting_and_one_silent_destination()

    reporting = read_channel(scenario.channel_id)
    assert reporting["readiness_index"] == 100, (
        "one reported sample means a spread of zero, so no drift penalty applies"
    )
    assert reporting["latency_ms"] == 1500
    assert reporting["health_report_count"] == 2

    rows, meta = validate_paginated(
        api.list_stream_channels(PRODUCER, params={"show_id": scenario.show_id})
    )
    assert meta["total_count"] == 2
    by_platform = {row["platform"]: row for row in rows}
    assert by_platform["FLAGSHIP_APP"]["readiness_index"] == 100
    assert by_platform["SOCIAL_A"]["readiness_index"] == 0
