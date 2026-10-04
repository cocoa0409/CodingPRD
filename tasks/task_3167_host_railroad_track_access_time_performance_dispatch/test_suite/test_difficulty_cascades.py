"""Transitive cascades: the disruption bridge chain and the agreement suspension chain."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import PASSENGER_OPERATOR_HEADERS, fixtures


def _published_world_with_disruption(api):
    """A published 1-run timetable on 2026-09-02 plus an OPEN disruption at 08:00."""
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    disruption = fixtures.create_disruption(
        api,
        net,
        disruption_type="TRACK_FAILURE",
        started_at="2026-09-02T08:00:00Z",
        reaccommodation_policy="BUS_BRIDGE",
    )
    net["disruption"] = disruption
    return net


def test_bridge_cascades_run_passages_and_auto_incident(api):
    """Bridging a disruption disrupts the run, skips its passages, and auto-codes 77 minutes.

    The run's scheduled arrival is 09:17 and the disruption started at 08:00,
    so the auto-created incident carries 77 whole minutes.

    PRD: "Link one: every `SCHEDULED` or `EN_ROUTE` train run on the corridor whose `scheduled_departure_at` is at or after `started_at` and whose service date overlaps the disruption moves to `DISRUPTED` with `cancellation_reason` `DISRUPTION`. Link two: each disrupted run's still-`PLANNED` segment passages flip to `SKIPPED`. Link three: when a run's final `PLANNED` passage flips to `SKIPPED`, the system auto-creates a delay incident for that run with `cause_code` `DISRUPTION`, `origin` `SYSTEM_DISRUPTION`, `delay_minutes` equal to the whole minutes from the disruption's `started_at` to the run's `scheduled_arrival_at` with negative values clamped to zero, and `status` `OPEN` — ready for the normal confirm/dispute flow of §3.5."
    Design: Difficulty/transitive_cascade/disruption_bridge_three_hop_cascade
    """
    net = _published_world_with_disruption(api)
    run = net["runs"][0]

    bridged = get_success_data(api.bridge_service_disruption(net["disruption"]["id"], net["host_headers"]))

    assert bridged["status"] == "BRIDGED"
    assert bridged["bus_bridge_active"] is True

    disrupted_run = fixtures.read_run(api, run["id"])
    assert disrupted_run["status"] == "DISRUPTED"
    assert disrupted_run["cancellation_reason"] == "DISRUPTION"

    passages = fixtures.list_passages(api, run["id"])
    assert [p["status"] for p in passages] == ["SKIPPED", "SKIPPED"]

    incidents, meta = validate_paginated(
        api.list_delay_incidents(PASSENGER_OPERATOR_HEADERS, params={"train_run_id": run["id"]})
    )
    assert meta["total_count"] == 1
    auto = incidents[0]
    assert auto["cause_code"] == "DISRUPTION"
    assert auto["origin"] == "SYSTEM_DISRUPTION"
    assert auto["delay_minutes"] == 77
    assert auto["host_attributable"] is False
    assert auto["status"] == "OPEN"


def test_bridge_auto_incident_is_not_host_attributable(api):
    """The cascade's auto-coded DISRUPTION incident carries host_attributable false.

    PRD: "A coded incident is born `OPEN` with `origin` `CODED`, and its `host_attributable` flag is derived from the cause: exactly the codes `HOST_FREIGHT_HOLD`, `HOST_SIGNAL`, and `HOST_TRACK` are host-attributable, while `MECHANICAL`, `STATION_DWELL`, `WEATHER`, and `DISRUPTION` are not."
    Design: Difficulty/transitive_cascade/disruption_bridge_three_hop_cascade
    """
    net = _published_world_with_disruption(api)
    run = net["runs"][0]

    api.bridge_service_disruption(net["disruption"]["id"], net["host_headers"])

    incidents, meta = validate_paginated(
        api.list_delay_incidents(PASSENGER_OPERATOR_HEADERS, params={"train_run_id": run["id"]})
    )
    assert meta["total_count"] == 1
    assert incidents[0]["cause_code"] == "DISRUPTION"
    assert incidents[0]["host_attributable"] is False
    assert incidents[0]["origin"] == "SYSTEM_DISRUPTION"
    assert incidents[0]["delay_minutes"] == 77


def test_suspending_agreement_suspends_timetable_and_cancels_runs(api):
    """Suspension cascades from the agreement to its published timetables and their runs.

    PRD: "Suspension is also the host's act, restricted to a `HostRailroadRep` who owns the agreement, and it is deliberately severe: the agreement moves `ACTIVE` → `SUSPENDED`, its `version` increments, and the suspension cascades outward — every `PUBLISHED` timetable of the agreement moves to `SUSPENDED`, and each suspended timetable's `SCHEDULED` train runs are cancelled with `cancellation_reason` set to `AGREEMENT_SUSPENDED`."
    Design: Difficulty/transitive_cascade/agreement_suspend_two_hop_cascade
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]

    suspended = get_success_data(api.suspend_operating_agreement(net["agreement"]["id"], {"reason": "host embargo"}, net["host_headers"]))

    assert suspended["status"] == "SUSPENDED"
    timetable = fixtures.read_timetable(api, net["timetable"]["id"])
    assert timetable["status"] == "SUSPENDED"
    cancelled_run = fixtures.read_run(api, run["id"])
    assert cancelled_run["status"] == "CANCELLED"
    assert cancelled_run["cancellation_reason"] == "AGREEMENT_SUSPENDED"


def test_suspension_cascade_stamps_agreement_suspended_reason_on_each_run(api):
    """Each cancelled run of the suspended timetable carries AGREEMENT_SUSPENDED.

    PRD: "the suspension cascades outward — every `PUBLISHED` timetable of the agreement moves to `SUSPENDED`, and each suspended timetable's `SCHEDULED` train runs are cancelled with `cancellation_reason` set to `AGREEMENT_SUSPENDED`"
    Design: Difficulty/transitive_cascade/agreement_suspend_two_hop_cascade
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=2, service_date="2026-09-03")

    api.suspend_operating_agreement(net["agreement"]["id"], {}, net["host_headers"])

    assert fixtures.read_agreement(api, net["agreement"]["id"])["status"] == "SUSPENDED"
    assert fixtures.read_timetable(api, net["timetable"]["id"])["status"] == "SUSPENDED"
    for run in net["runs"]:
        cancelled = fixtures.read_run(api, run["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "AGREEMENT_SUSPENDED"
