"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment, so each test has to build the
world it needs from scratch. These helpers do that walking through the public
API only - no direct data writes - and return the identifiers, headers and
observed versions the test then asserts against.

They are organised from the simplest to the most far-reaching:

  Tier 1  the logical clock and the physical network (host, corridor, segments)
  Tier 2  the operating agreement and its activation
  Tier 3  timetable lifecycle up to publication
  Tier 4  running trains: departure, passage actualization, completion
  Tier 5  incidents, disputes, statements, projects, windows, disruptions

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient
from . import factories as f
from .test_users import (
    PASSENGER_OPERATOR_HEADERS,
    STATE_SPONSOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    make_host_rep_headers,
)

# The instant the clock reports on a fresh deployment, before any clock call.
BASE_CLOCK = "2026-09-01T00:00:00Z"


# === Tier 1: clock and physical network =====================================

def set_clock(api: ApiClient, to_iso8601: str = BASE_CLOCK) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), SYSTEM_ADMIN_HEADERS))


def create_host(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_host_railroad(f.host_railroad_payload(**overrides), SYSTEM_ADMIN_HEADERS))


def create_corridor(api: ApiClient, host_railroad_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_corridor(f.corridor_payload(host_railroad_id, **overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_segment(api: ApiClient, corridor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_track_segment(f.track_segment_payload(corridor_id, **overrides), SYSTEM_ADMIN_HEADERS)
    )


def setup_network(api: ApiClient) -> Dict[str, Any]:
    """The canonical network: one host, one corridor, two segments.

    Segment 1 lies in IL over mileposts 0.0-10.0 with a pure run of 21 minutes;
    segment 2 lies in MO over mileposts 10.0-40.0 with a pure run of 40 minutes.
    Both are SINGLE-track with capacity 20 trains per day and no dwell.
    """
    set_clock(api, BASE_CLOCK)
    host = create_host(api)
    corridor = create_corridor(api, host["id"])
    seg1 = create_segment(
        api,
        corridor["id"],
        sequence_no=1,
        milepost_start=0.0,
        milepost_end=10.0,
        state_code="IL",
        track_class="SINGLE",
        capacity_trains_per_day=20,
        pure_run_minutes=21,
        dwell_after_minutes=0,
    )
    seg2 = create_segment(
        api,
        corridor["id"],
        sequence_no=2,
        milepost_start=10.0,
        milepost_end=40.0,
        state_code="MO",
        track_class="SINGLE",
        capacity_trains_per_day=20,
        pure_run_minutes=40,
        dwell_after_minutes=0,
    )
    return {
        "host": host,
        "host_headers": make_host_rep_headers(host["id"]),
        "corridor": corridor,
        "seg1": seg1,
        "seg2": seg2,
    }


def read_corridor(api: ApiClient, corridor_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_corridor(corridor_id, headers or SYSTEM_ADMIN_HEADERS))


def read_segment(api: ApiClient, segment_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_track_segment(segment_id, headers or SYSTEM_ADMIN_HEADERS))


# === Tier 2: operating agreement ============================================

def create_agreement(api: ApiClient, net: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    host_railroad_id = overrides.pop("host_railroad_id", net["host"]["id"])
    corridor_id = overrides.pop("corridor_id", net["corridor"]["id"])
    return get_success_data(
        api.create_operating_agreement(
            f.operating_agreement_payload(host_railroad_id, corridor_id, **overrides),
            PASSENGER_OPERATOR_HEADERS,
        )
    )


def activate_agreement(api: ApiClient, net: Dict[str, Any], agreement_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_operating_agreement(agreement_id, net["host_headers"]))


def read_agreement(api: ApiClient, agreement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_operating_agreement(agreement_id, headers or SYSTEM_ADMIN_HEADERS))


def setup_draft_agreement(api: ApiClient) -> Dict[str, Any]:
    """The network plus a DRAFT operating agreement (never activated)."""
    net = setup_network(api)
    net["agreement"] = create_agreement(api, net)
    return net


def setup_active_agreement(api: ApiClient) -> Dict[str, Any]:
    """The network plus an ACTIVE operating agreement (version observed)."""
    net = setup_draft_agreement(api)
    net["agreement"] = activate_agreement(api, net, net["agreement"]["id"])
    net["agreement_version"] = net["agreement"]["version"]
    return net


# === Tier 3: timetable lifecycle =============================================

def create_timetable(
    api: ApiClient,
    net: Dict[str, Any],
    service_date_start: str = "2026-09-02",
    service_date_end: str = "2026-09-02",
    trains_per_day: int = 1,
    departure_time_of_day: str = "08:00",
    headway_minutes: int = 120,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_timetable(
            f.timetable_payload(
                net["corridor"]["id"],
                net["agreement"]["id"],
                service_date_start=service_date_start,
                service_date_end=service_date_end,
                trains_per_day=trains_per_day,
                departure_time_of_day=departure_time_of_day,
                headway_minutes=headway_minutes,
                **overrides,
            ),
            PASSENGER_OPERATOR_HEADERS,
        )
    )


def propose_timetable(api: ApiClient, timetable_id: str) -> Dict[str, Any]:
    return get_success_data(api.propose_timetable(timetable_id, PASSENGER_OPERATOR_HEADERS))


def review_timetable(api: ApiClient, net: Dict[str, Any], timetable_id: str) -> Dict[str, Any]:
    return get_success_data(api.review_timetable(timetable_id, net["host_headers"]))


def ratify_timetable(api: ApiClient, net: Dict[str, Any], timetable_id: str) -> Dict[str, Any]:
    return get_success_data(api.ratify_timetable(timetable_id, net["host_headers"]))


def publish_timetable(api: ApiClient, timetable_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_timetable(timetable_id, PASSENGER_OPERATOR_HEADERS))


def read_timetable(api: ApiClient, timetable_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_timetable(timetable_id, headers or SYSTEM_ADMIN_HEADERS))


def timetable_to_under_review(api: ApiClient, net: Dict[str, Any], **timetable_kwargs: Any) -> Dict[str, Any]:
    """A timetable walked to UNDER_REVIEW (agreement may be DRAFT or ACTIVE)."""
    timetable = create_timetable(api, net, **timetable_kwargs)
    propose_timetable(api, timetable["id"])
    review_timetable(api, net, timetable["id"])
    return read_timetable(api, timetable["id"])


def timetable_to_ratified(api: ApiClient, net: Dict[str, Any], **timetable_kwargs: Any) -> Dict[str, Any]:
    """A timetable walked to RATIFIED (requires an ACTIVE agreement)."""
    timetable = timetable_to_under_review(api, net, **timetable_kwargs)
    ratify_timetable(api, net, timetable["id"])
    return read_timetable(api, timetable["id"])


def list_runs(api: ApiClient, timetable_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api.list_train_runs(PASSENGER_OPERATOR_HEADERS, params={"timetable_id": timetable_id})
    )
    return rows


def list_passages(api: ApiClient, run_id: str, headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api.list_segment_passages(headers or PASSENGER_OPERATOR_HEADERS, params={"train_run_id": run_id})
    )
    return rows


def publish_and_collect(api: ApiClient, timetable_id: str) -> Tuple[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    """Publish and return (runs, passages-per-run) in schedule order."""
    publish_timetable(api, timetable_id)
    runs = list_runs(api, timetable_id)
    passages = [list_passages(api, run["id"]) for run in runs]
    return runs, passages


def setup_published_timetable(
    api: ApiClient,
    trains_per_day: int = 1,
    service_date: str = "2026-09-02",
    departure_time_of_day: str = "08:00",
    headway_minutes: int = 120,
) -> Dict[str, Any]:
    """Full walk: ACTIVE agreement plus a PUBLISHED timetable.

    Returns the network dict extended with the timetable, its materialized runs
    (ascending by scheduled departure) and each run's passages in segment order.
    """
    net = setup_active_agreement(api)
    timetable = timetable_to_ratified(
        api,
        net,
        service_date_start=service_date,
        service_date_end=service_date,
        trains_per_day=trains_per_day,
        departure_time_of_day=departure_time_of_day,
        headway_minutes=headway_minutes,
    )
    runs, passages = publish_and_collect(api, timetable["id"])
    net.update({"timetable": timetable, "runs": runs, "passages": passages})
    return net


# === Tier 4: running trains ===================================================

def depart_run(api: ApiClient, net: Dict[str, Any], run_id: str, actual_departure_at: str) -> Dict[str, Any]:
    return get_success_data(
        api.depart_train_run(run_id, f.depart_payload(actual_departure_at), net["host_headers"])
    )


def actualize_passage(
    api: ApiClient, net: Dict[str, Any], passage_id: str, actual_entry_at: str, actual_exit_at: str
) -> Dict[str, Any]:
    return get_success_data(
        api.actualize_segment_passage(
            passage_id, f.actualize_payload(actual_entry_at, actual_exit_at), net["host_headers"]
        )
    )


def complete_run(api: ApiClient, net: Dict[str, Any], run_id: str, actual_arrival_at: str) -> Dict[str, Any]:
    return get_success_data(
        api.complete_train_run(run_id, f.complete_payload(actual_arrival_at), net["host_headers"])
    )


def read_run(api: ApiClient, run_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_train_run(run_id, headers or SYSTEM_ADMIN_HEADERS))


def read_passage(api: ApiClient, passage_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_segment_passage(passage_id, headers or SYSTEM_ADMIN_HEADERS))


def run_0902_completed_20_late(api: ApiClient) -> Dict[str, Any]:
    """The canonical 1-run timetable whose single run completed 20 minutes late.

    The 2026-09-02 run departs on time at 08:00; both passages actualize with
    exits 16 and 18 minutes late; the destination arrival at 09:35 is 20
    minutes late against the scheduled 09:17. Returns the extended world dict
    with ``run``, ``passage_ids`` and the completed run snapshot.
    """
    net = setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]
    p1, p2 = net["passages"][0]
    depart_run(api, net, run["id"], "2026-09-02T08:00:00Z")
    actualize_passage(api, net, p1["id"], "2026-09-02T08:00:00Z", "2026-09-02T08:43:00Z")
    actualize_passage(api, net, p2["id"], "2026-09-02T08:43:00Z", "2026-09-02T09:35:00Z")
    completed = complete_run(api, net, run["id"], "2026-09-02T09:35:00Z")
    net.update({"run": run, "passage_ids": (p1["id"], p2["id"]), "completed_run": completed})
    return net


def runs_0903_one_ontime_one_late(api: ApiClient) -> Dict[str, Any]:
    """The canonical 2-run day on 2026-09-03: run1 on time, run2 one minute past the threshold.

    Run1 departs 08:00, passages exit at 08:27 and 09:32, arrival 09:32 (delay 15,
    exactly at the 15-minute threshold). Run2 departs 10:00, passages exit at
    10:27 and 11:33, arrival 11:33 (delay 16, one minute past the threshold).
    Returns the world dict with ``runs`` and ``passages``.
    """
    net = setup_published_timetable(api, trains_per_day=2, service_date="2026-09-03")
    r1, r2 = net["runs"]
    (r1p1, r1p2), (r2p1, r2p2) = net["passages"]
    depart_run(api, net, r1["id"], "2026-09-03T08:00:00Z")
    actualize_passage(api, net, r1p1["id"], "2026-09-03T08:00:00Z", "2026-09-03T08:27:00Z")
    actualize_passage(api, net, r1p2["id"], "2026-09-03T08:27:00Z", "2026-09-03T09:32:00Z")
    complete_run(api, net, r1["id"], "2026-09-03T09:32:00Z")
    depart_run(api, net, r2["id"], "2026-09-03T10:00:00Z")
    actualize_passage(api, net, r2p1["id"], "2026-09-03T10:00:00Z", "2026-09-03T10:27:00Z")
    actualize_passage(api, net, r2p2["id"], "2026-09-03T10:27:00Z", "2026-09-03T11:33:00Z")
    complete_run(api, net, r2["id"], "2026-09-03T11:33:00Z")
    net.update({"run1": r1, "run2": r2, "passage1_ids": (r1p1["id"], r1p2["id"]), "passage2_ids": (r2p1["id"], r2p2["id"])})
    return net


# === Tier 5: incidents, disputes, statements, projects, windows ==============

def code_incident(
    api: ApiClient,
    net: Dict[str, Any],
    run_id: str,
    cause_code: str,
    delay_minutes: int,
    segment_passage_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if segment_passage_id is not None:
        payload["segment_passage_id"] = segment_passage_id
    return get_success_data(
        api.create_delay_incident(
            f.delay_incident_payload(run_id, cause_code, delay_minutes, **payload),
            net["host_headers"],
        )
    )


def confirm_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    return get_success_data(api.confirm_delay_incident(incident_id, PASSENGER_OPERATOR_HEADERS))


def dispute_incident(api: ApiClient, incident_id: str, reason: Optional[str] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api.dispute_delay_incident(incident_id, payload, headers or PASSENGER_OPERATOR_HEADERS)
    )


def read_incident(api: ApiClient, incident_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_delay_incident(incident_id, headers or SYSTEM_ADMIN_HEADERS))


def read_dispute(api: ApiClient, dispute_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_dispute(dispute_id, headers or SYSTEM_ADMIN_HEADERS))


def escalate_dispute(api: ApiClient, dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api.escalate_dispute(dispute_id, PASSENGER_OPERATOR_HEADERS))


def resolve_dispute(api: ApiClient, dispute_id: str, resolution: str) -> Dict[str, Any]:
    return get_success_data(api.resolve_dispute(dispute_id, {"resolution": resolution}, SYSTEM_ADMIN_HEADERS))


def create_statement(
    api: ApiClient,
    net: Dict[str, Any],
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_settlement_statement(
            f.settlement_statement_payload(
                net["agreement"]["id"], period_start=period_start, period_end=period_end
            ),
            PASSENGER_OPERATOR_HEADERS,
        )
    )


def issue_statement(api: ApiClient, statement_id: str) -> Dict[str, Any]:
    return get_success_data(api.issue_settlement_statement(statement_id, PASSENGER_OPERATOR_HEADERS))


def dispute_statement(api: ApiClient, net: Dict[str, Any], statement_id: str) -> Dict[str, Any]:
    return get_success_data(api.dispute_settlement_statement(statement_id, {}, net["host_headers"]))


def reissue_statement(api: ApiClient, statement_id: str) -> Dict[str, Any]:
    return get_success_data(api.reissue_settlement_statement(statement_id, PASSENGER_OPERATOR_HEADERS))


def read_statement(api: ApiClient, statement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_settlement_statement(statement_id, headers or SYSTEM_ADMIN_HEADERS))


def create_project(
    api: ApiClient,
    net: Dict[str, Any],
    track_segment_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_capital_project(
            f.capital_project_payload(
                net["agreement"]["id"], track_segment_id or net["seg1"]["id"], **overrides
            ),
            PASSENGER_OPERATOR_HEADERS,
        )
    )


def approve_project(api: ApiClient, net: Dict[str, Any], project_id: str, expected_version: int) -> Dict[str, Any]:
    return get_success_data(
        api.approve_capital_project(
            project_id, {"expected_operating_agreement_version": expected_version}, net["host_headers"]
        )
    )


def read_project(api: ApiClient, project_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_capital_project(project_id, headers or SYSTEM_ADMIN_HEADERS))


def create_window(
    api: ApiClient,
    net: Dict[str, Any],
    track_segment_id: Optional[str] = None,
    window_start_at: str = "2026-09-07T06:00:00Z",
    window_end_at: str = "2026-09-07T16:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_maintenance_window(
            f.maintenance_window_payload(
                track_segment_id or net["seg1"]["id"], window_start_at, window_end_at, **overrides
            ),
            net["host_headers"],
        )
    )


def lock_window(api: ApiClient, net: Dict[str, Any], window_id: str) -> Dict[str, Any]:
    return get_success_data(api.lock_maintenance_window(window_id, net["host_headers"]))


def release_window(api: ApiClient, net: Dict[str, Any], window_id: str) -> Dict[str, Any]:
    return get_success_data(api.release_maintenance_window(window_id, net["host_headers"]))


def read_window(api: ApiClient, window_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_maintenance_window(window_id, headers or SYSTEM_ADMIN_HEADERS))


def create_disruption(api: ApiClient, net: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_disruption(
            f.service_disruption_payload(net["corridor"]["id"], **overrides), net["host_headers"]
        )
    )


def read_disruption(api: ApiClient, disruption_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_service_disruption(disruption_id, headers or SYSTEM_ADMIN_HEADERS))


def create_funding(
    api: ApiClient,
    net: Dict[str, Any],
    state_code: str,
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_funding_agreement(
            f.funding_agreement_payload(
                net["corridor"]["id"], state_code, period_start=period_start, period_end=period_end
            ),
            STATE_SPONSOR_HEADERS,
        )
    )


def commit_funding(api: ApiClient, funding_id: str) -> Dict[str, Any]:
    return get_success_data(api.commit_funding_agreement(funding_id, STATE_SPONSOR_HEADERS))


def read_funding(api: ApiClient, funding_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_funding_agreement(funding_id, headers or STATE_SPONSOR_HEADERS))
