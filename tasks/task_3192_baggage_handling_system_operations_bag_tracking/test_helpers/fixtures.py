"""Composite setup helpers — multi-step preconditions built from PRD endpoints.

Every fixture starts from an empty database (the harness restarts the server
before each test) and builds its state from scratch using only PRD-declared
endpoints.  Setup calls use the lenient get_success_data() validator so a
broken precondition raises a clear "Setup failed" error.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_station_payload, create_airline_payload, create_flight_payload,
    create_makeup_area_payload, create_screening_lane_payload, create_bag_payload,
    create_special_item_payload, create_connection_payload, create_report_payload,
    create_scan_payload, create_screening_payload, create_assign_makeup_payload,
    create_arrange_delivery_payload,
)
from .test_users import TEST_USERS, make_passenger_headers
from .constants import (
    CLOCK_START, FLIGHT_DL1423_DEP, FLIGHT_MAKEUP_OPEN_UTC, MAKEUP_INTERVAL_MINUTES,
)


# ---------------------------------------------------------------------------
# clock helpers
# ---------------------------------------------------------------------------

def parse_utc(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fmt_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def advance_utc(iso: str, minutes: int) -> str:
    return fmt_utc(parse_utc(iso) + timedelta(minutes=minutes))


def set_clock(to_iso8601: str = CLOCK_START):
    return api_client.set_clock(to_iso8601, TEST_USERS["platform_admin_headers"])


def run_ops(station_id: str):
    return api_client.run_ops(station_id, TEST_USERS["platform_admin_headers"])


def _ok(response, what: str) -> dict:
    data = get_success_data(response)
    assert isinstance(data, dict), f"Setup failed: {what} returned no object"
    return data


def list_rows(response, what: str = "list") -> list:
    """Read a collection endpoint's rows (data is an array envelope)."""
    data = get_success_data(response)
    assert isinstance(data, list), f"{what} must return an array payload"
    return data


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def base_scenario(makeup_capacity_slots: int = 2, buffer_minutes: int = 15,
                  station_overrides: dict = None, airline_overrides: dict = None,
                  flight_overrides: dict = None, birthday_clock: str = CLOCK_START,
                  makeup_code: str = "MA-3", lane_code: str = "EDS-2"):
    """Clock + station + airline + make-up area + lane + flight DL1423.

    Returns a dict of ids (and the created rows) that every other fixture
    threads through.  This is the shared preamble for nearly every claim.
    """
    set_clock(birthday_clock)
    st = _ok(api_client.create_station(
        create_station_payload(**(station_overrides or {})),
        TEST_USERS["platform_admin_headers"]), "create station")
    al = _ok(api_client.create_airline(
        create_airline_payload(**(airline_overrides or {})),
        TEST_USERS["platform_admin_headers"]), "create airline")
    ma = _ok(api_client.create_makeup_area(
        create_makeup_area_payload(st["id"], code=makeup_code,
                                   capacity_slots=makeup_capacity_slots,
                                   buffer_minutes=buffer_minutes),
        TEST_USERS["platform_admin_headers"]), "create make-up area")
    lane = _ok(api_client.create_screening_lane(
        create_screening_lane_payload(st["id"], lane_code=lane_code),
        TEST_USERS["platform_admin_headers"]), "create screening lane")
    f1 = _ok(api_client.create_flight(
        create_flight_payload(st["id"], al["id"], **(flight_overrides or {})),
        TEST_USERS["platform_admin_headers"]), "create flight")
    return {"station": st, "airline": al, "area": ma, "lane": lane, "flight": f1,
            "st": st["id"], "al": al["id"], "ma": ma["id"], "lane": lane["id"],
            "f1": f1["id"]}


def make_flight(scenario, flight_number="DL1788", bank_code="B2",
                scheduled_departure_utc="2026-09-01T17:30:00Z"):
    return _ok(api_client.create_flight(
        create_flight_payload(scenario["st"], scenario["al"],
                              flight_number=flight_number, bank_code=bank_code,
                              scheduled_departure_utc=scheduled_departure_utc),
        TEST_USERS["platform_admin_headers"]), "create extra flight")


# ---------------------------------------------------------------------------
# Tier 1/3: bag lifecycle
# ---------------------------------------------------------------------------

def accept_bag(scenario, flight_id="__default__", **bag_overrides):
    """Accept a bag (PRD §3.1).  Pass flight_id=None for an unassigned bag."""
    if flight_id == "__default__":
        flight_id = scenario["f1"]
    payload = create_bag_payload(scenario["st"], **bag_overrides)
    if flight_id is not None:
        payload["flight_id"] = flight_id
    return _ok(api_client.create_bag(payload, TEST_USERS["acceptance_agent_headers"]),
               "accept bag")


def weigh(bag_id, scale_weight_lb=48.0):
    return api_client.weigh_bag(bag_id, scale_weight_lb,
                                TEST_USERS["acceptance_agent_headers"])


def weigh_ok(bag_id, scale_weight_lb=48.0):
    return _ok(weigh(bag_id, scale_weight_lb), "weigh bag")


def screen(bag_id, lane_id, start_utc, alarm_code=None):
    payload = create_screening_payload(bag_id, lane_id, start_utc)
    if alarm_code is not None:
        payload["alarm_code"] = alarm_code
    return api_client.create_screening(payload, TEST_USERS["screener_headers"])


def screen_ok(bag_id, lane_id, start_utc, alarm_code=None):
    return _ok(screen(bag_id, lane_id, start_utc, alarm_code), "screen bag")


def get_bag(bag_id, role_headers=None):
    return _ok(api_client.get_bag(bag_id, role_headers or TEST_USERS["acceptance_agent_headers"]),
               "get bag")


def get_report(report_id, role_headers=None):
    return _ok(api_client.get_report(
        report_id, role_headers or TEST_USERS["baggage_service_agent_headers"]),
        "get report")


def get_station(station_id):
    return _ok(api_client.get_station(station_id, TEST_USERS["platform_admin_headers"]),
               "get station")


def get_area(area_id):
    return _ok(api_client.get_makeup_area(area_id, TEST_USERS["sortation_agent_headers"]),
               "get make-up area")


def get_flight(flight_id):
    return _ok(api_client.get_flight(flight_id, TEST_USERS["sortation_agent_headers"]),
               "get flight")


def make_sorted_bag(scenario, bag_index=0, screen_start_utc=None, **bag_overrides):
    """Accept -> weigh -> clean screen, leaving custody SORTED / screening CLEARED.

    Lane buckets are 20 minutes wide, so consecutive bags get consecutive
    buckets to avoid an interval conflict.
    """
    bag = accept_bag(scenario, **bag_overrides)
    weigh_ok(bag["id"], bag_overrides.get("scale_weight_lb", 48.0))
    start = screen_start_utc or advance_utc(CLOCK_START, 20 * bag_index)
    screen_ok(bag["id"], scenario["lane"], start)
    return get_bag(bag["id"])


def make_in_makeup_bag(scenario, bag_index=0, induction_utc=None,
                       screen_start_utc=None, **bag_overrides):
    """Accept -> weigh -> clean screen -> assign a make-up interval."""
    bag = make_sorted_bag(scenario, bag_index=bag_index,
                          screen_start_utc=screen_start_utc, **bag_overrides)
    induction = induction_utc or advance_utc(FLIGHT_MAKEUP_OPEN_UTC, 12 * bag_index)
    set_clock(induction)
    _ok(api_client.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(bag["version"], scenario["ma"], induction,
                                     MAKEUP_INTERVAL_MINUTES),
        TEST_USERS["sortation_agent_headers"]), "assign make-up")
    return get_bag(bag["id"])


def make_loaded_bag(scenario, bag_index=0, load_utc="2026-09-01T13:50:00Z",
                    **bag_overrides):
    """Accept -> weigh -> clean screen -> assign -> load."""
    bag = make_in_makeup_bag(scenario, bag_index=bag_index, **bag_overrides)
    set_clock(load_utc)
    _ok(api_client.load_bag(bag["id"], TEST_USERS["load_agent_headers"]), "load bag")
    return get_bag(bag["id"])


# ---------------------------------------------------------------------------
# Tier 3: flight lifecycle shortcuts
# ---------------------------------------------------------------------------

def open_flight_for_sortation(scenario, flight_id=None, clock_utc="2026-09-01T13:05:00Z"):
    """Advance the clock past sortation_open_utc and run the checkpoint."""
    fid = flight_id or scenario["f1"]
    set_clock(clock_utc)
    _ok(run_ops(scenario["st"]), "run ops")
    return get_flight(fid)


def board_and_depart(scenario, flight_id="__default__", clock_utc="2026-09-01T14:05:00Z"):
    """Walk a flight through the automatic sweep to DEPARTED.

    PRD §3.13 advances one status per checkpoint: a SCHEDULED flight opens for
    sortation once the clock reaches `sortation_open_utc`, and the *next* pass
    moves the ready flight to BOARDING, which is the only state the departure
    act admits.  The clock is therefore parked past the flight's
    `sortation_close_utc` before the second pass so departure is admissible.
    """
    fid = scenario["f1"] if flight_id == "__default__" else flight_id
    set_clock(clock_utc)
    _ok(run_ops(scenario["st"]), "run ops")
    close = get_flight(fid)["sortation_close_utc"]
    set_clock(max(parse_utc(clock_utc), parse_utc(close)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _ok(run_ops(scenario["st"]), "run ops")
    _ok(api_client.depart_flight(fid, TEST_USERS["platform_admin_headers"]), "depart flight")
    return get_flight(fid)


def delivered_bag_with_report(scenario, report_type="DAMAGED", item_type="OVERSIZE",
                              declared_value_cents=120000, weight_lb=48,
                              dimensions=(20, 14, 16), scale_weight_lb=48.0,
                              deliver_utc="2026-09-01T13:40:00Z",
                              anomaly_note=None, add_item=True,
                              arrivals_utc=None):
    """Full pipeline to a DELIVERED bag plus a REPORTED report on it.

    Returns (scenario, bag, report).
    """
    length_in, width_in, height_in = dimensions
    bag = accept_bag(scenario, weight_lb=weight_lb, length_in=length_in,
                     width_in=width_in, height_in=height_in)
    if add_item:
        _ok(api_client.add_special_item(
            bag["id"], create_special_item_payload(item_type=item_type,
                                                   declared_value_cents=declared_value_cents),
            TEST_USERS["acceptance_agent_headers"]), "register special item")
    weigh_ok(bag["id"], scale_weight_lb)
    screen_ok(bag["id"], scenario["lane"], arrivals_utc or advance_utc(CLOCK_START, 20))
    set_clock(deliver_utc)
    bag = get_bag(bag["id"])
    _ok(api_client.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(bag["version"], scenario["ma"], deliver_utc,
                                     MAKEUP_INTERVAL_MINUTES),
        TEST_USERS["sortation_agent_headers"]), "assign make-up")
    _ok(api_client.load_bag(bag["id"], TEST_USERS["load_agent_headers"]), "load bag")
    board_and_depart(scenario)
    _ok(api_client.deliver_bag(bag["id"], TEST_USERS["load_agent_headers"]), "deliver bag")

    report_payload = create_report_payload(bag["id"], scenario["st"], report_type=report_type)
    if anomaly_note is not None:
        report_payload["anomaly_note"] = anomaly_note
    report = _ok(api_client.create_report(report_payload,
                                          TEST_USERS["baggage_service_agent_headers"]),
                 "file report")
    return scenario, get_bag(bag["id"]), report


def report_through_delivered(report_id, delivery_method="COURIER",
                             scheduled_utc="2026-09-01T14:20:00Z"):
    """investigate -> arrange-delivery -> mark-delivered.

    Idempotent: each step is applied only while the report still sits in the
    status that step consumes, so a caller may run part of the chain itself and
    still reach DELIVERED through this helper.
    """
    current = get_report(report_id)
    if current["status"] == "REPORTED":
        _ok(api_client.investigate_report(report_id, TEST_USERS["baggage_service_agent_headers"]),
            "investigate report")
        current = get_report(report_id)
    if current["status"] == "INVESTIGATING":
        _ok(api_client.arrange_delivery(
            report_id,
            create_arrange_delivery_payload(delivery_method=delivery_method,
                                            scheduled_utc=scheduled_utc),
            TEST_USERS["baggage_service_agent_headers"]), "arrange delivery")
        current = get_report(report_id)
    if current["status"] == "DELIVERY_ARRANGED":
        _ok(api_client.mark_report_delivered(report_id, TEST_USERS["baggage_service_agent_headers"]),
            "mark report delivered")
    return _ok(api_client.get_report(report_id, TEST_USERS["baggage_service_agent_headers"]),
               "get report")


def approve_claim(report_id, requested_amount_cents, approved_amount_cents=None):
    """File a claim and approve it (PRD §3.12)."""
    claim = _ok(api_client.file_claim(report_id, requested_amount_cents,
                                      TEST_USERS["baggage_service_agent_headers"]),
                "file claim")
    payload = {"decision": "APPROVED"}
    if approved_amount_cents is not None:
        payload["approved_amount_cents"] = approved_amount_cents
    _ok(api_client.decide_claim(claim["id"], payload,
                                TEST_USERS["baggage_service_agent_headers"]),
        "decide claim")
    return claim


def report_through_compensated(scenario, report_id, requested_amount_cents=25000,
                               approved_amount_cents=25000,
                               far_clock_utc="2026-09-01T13:00:00Z"):
    """Drive a report all the way to COMPENSATED (the report-side terminal pair).

    The bag's report is delivered, a claim filed and approved, and compensation
    paid; the return value carries every intermediate row a test may assert on.
    """
    report = report_through_delivered(report_id)
    approve_claim(report_id, requested_amount_cents, approved_amount_cents)
    _ok(api_client.compensate_report(report_id,
                                     TEST_USERS["baggage_service_agent_headers"]),
        "compensate report")
    return _ok(api_client.get_report(report_id, TEST_USERS["baggage_service_agent_headers"]),
               "get report")


def compensate_and_reopen(scenario, report_id, requested_amount_cents=25000,
                          approved_amount_cents=25000):
    """Compensate a delivered report then reopen it with its current version."""
    compensated = report_through_compensated(
        scenario, report_id, requested_amount_cents, approved_amount_cents)
    response = api_client.reopen_report(
        report_id, compensated["version"], TEST_USERS["baggage_service_agent_headers"])
    reopened = _ok(response, "reopen report")
    return compensated, reopened


def cycle_report_to_closed(scenario, report_id, requested_amount_cents=25000,
                           approved_amount_cents=25000):
    """Delivered -> compensate -> close, returning the CLOSED report."""
    report_through_compensated(scenario, report_id, requested_amount_cents,
                               approved_amount_cents)
    _ok(api_client.close_report(report_id, TEST_USERS["baggage_service_agent_headers"]),
        "close report")
    return _ok(api_client.get_report(report_id, TEST_USERS["baggage_service_agent_headers"]),
               "get report")


# ---------------------------------------------------------------------------
# alarm / inspection fixtures
# ---------------------------------------------------------------------------

def raise_alarm(bag_id, lane_id, start_utc, alarm_code="EDS_ALARM_A1"):
    return screen_ok(bag_id, lane_id, start_utc, alarm_code=alarm_code)


def make_alarmed_bag(scenario, bag_index=0, alarm_start_utc=None,
                     alarm_code="EDS_ALARM_A1", station_outage=False, **bag_overrides):
    """Accept -> weigh -> alarmed screening: custody HELD, screening ALARMED."""
    if station_outage:
        declare_outage(scenario)
    bag = accept_bag(scenario, **bag_overrides)
    weigh_ok(bag["id"], bag_overrides.get("scale_weight_lb", 48.0))
    start = alarm_start_utc or advance_utc(CLOCK_START, 20 * (bag_index + 1))
    event = raise_alarm(bag["id"], scenario["lane"], start, alarm_code)
    return get_bag(bag["id"]), event


def make_inspection_task(scenario, item_type="MOBILITY_DEVICE",
                         declared_value_cents=400000, induction_utc="2026-09-01T13:40:00Z",
                         screen_start_utc=None, **bag_overrides):
    """A sorted bag carrying a manually-screened item, assigned to make-up.

    The special-item safeguard opens a QUEUED inspection task during sortation.
    Returns (bag, task).
    """
    bag = accept_bag(scenario, **bag_overrides)
    _ok(api_client.add_special_item(
        bag["id"], create_special_item_payload(item_type=item_type,
                                               declared_value_cents=declared_value_cents),
        TEST_USERS["acceptance_agent_headers"]), "register special item")
    weigh_ok(bag["id"], 48.0)
    screen_ok(bag["id"], scenario["lane"], screen_start_utc or advance_utc(CLOCK_START, 20))
    set_clock(induction_utc)
    bag = get_bag(bag["id"])
    _ok(api_client.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(bag["version"], scenario["ma"], induction_utc,
                                     MAKEUP_INTERVAL_MINUTES),
        TEST_USERS["sortation_agent_headers"]), "assign make-up")
    tasks = list_rows(api_client.list_inspections(
        TEST_USERS["screener_headers"],
        {"station_id": scenario["st"], "status": "QUEUED"}), "inspections")
    assert tasks, "Setup failed: no inspection task was opened"
    return get_bag(bag["id"]), tasks[0]


def make_alarmed_inspection_task(scenario, alarm_start_utc=None,
                                 alarm_code="EDS_ALARM_A1", **bag_overrides):
    """A live manual inspection task on the alarm route (PRD §3.3).

    The task is opened against the ALARMED screening event that raised it, which
    is the only state §3.3's claim and resolve operations admit.  Returns
    (bag, event, task).
    """
    bag, event = make_alarmed_bag(scenario, alarm_start_utc=alarm_start_utc,
                                  alarm_code=alarm_code, **bag_overrides)
    tasks = list_rows(api_client.list_inspections(
        TEST_USERS["screener_headers"],
        {"station_id": scenario["st"], "screening_event_id": event["id"]}), "inspections")
    assert tasks, "Setup failed: no inspection task was opened for the alarm"
    return bag, event, tasks[0]


def make_failed_screening_bag(scenario, alarm_start_utc=None, **bag_overrides):
    """Accept -> weigh -> alarm -> resolve REJECTED: screening FAILED, custody HELD."""
    bag, event = make_alarmed_bag(scenario, alarm_start_utc=alarm_start_utc,
                                  **bag_overrides)
    _ok(api_client.resolve_screening(event["id"], "REJECTED",
                                     TEST_USERS["screener_headers"]),
        "resolve screening rejected")
    return get_bag(bag["id"]), event


# ---------------------------------------------------------------------------
# connection fixtures
# ---------------------------------------------------------------------------

def make_connection(bag_id, inbound_flight_id, onward_flight_id, required_mct_minutes=75):
    return _ok(api_client.create_connection(
        create_connection_payload(bag_id, inbound_flight_id, onward_flight_id,
                                  required_mct_minutes=required_mct_minutes),
        TEST_USERS["transfer_agent_headers"]), "create connection")


def make_transfer_bag(scenario, onward_flight=None, required_mct_minutes=75,
                      alarmed=False, alarm_start_utc=None, screen_start_utc=None,
                      **bag_overrides):
    """A bag with a Connection onto a second flight.

    Returns (bag, connection, onward_flight).
    """
    onward = onward_flight or make_flight(scenario)
    bag = accept_bag(scenario, **bag_overrides)
    weigh_ok(bag["id"], bag_overrides.get("scale_weight_lb", 48.0))
    connection = make_connection(bag["id"], scenario["f1"], onward["id"],
                                 required_mct_minutes)
    if alarmed:
        event = raise_alarm(bag["id"], scenario["lane"],
                            alarm_start_utc or advance_utc(CLOCK_START, 20))
        return get_bag(bag["id"]), connection, onward, event
    screen_ok(bag["id"], scenario["lane"],
              screen_start_utc or advance_utc(CLOCK_START, 20))
    return get_bag(bag["id"]), connection, onward


# ---------------------------------------------------------------------------
# outage fixtures
# ---------------------------------------------------------------------------

def declare_outage(scenario):
    return _ok(api_client.declare_outage(scenario["st"],
                                         TEST_USERS["platform_admin_headers"]),
               "declare outage")


def clear_outage(scenario):
    return _ok(api_client.clear_outage(scenario["st"],
                                       TEST_USERS["platform_admin_headers"]),
               "clear outage")


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_makeup_bucket_scenario(scenario, induction_utc="2026-09-01T13:36:00Z",
                                 second_induction_utc="2026-09-01T13:48:00Z"):
    """A sorted bag plus a clock parked inside the 13:30 identity bucket."""
    bag = make_sorted_bag(scenario)
    set_clock(induction_utc)
    bag = get_bag(bag["id"])
    _ok(api_client.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(bag["version"], scenario["ma"], induction_utc,
                                     MAKEUP_INTERVAL_MINUTES),
        TEST_USERS["sortation_agent_headers"]), "assign make-up")
    return get_bag(bag["id"]), get_area(scenario["ma"])


def setup_oversize_fragile_items(scenario, item_count=3, declared_value_cents=30000,
                                 dimensions=(40, 40, 40)):
    """A sorted bag measuring 120 linear inches carrying N FRAGILE items."""
    length_in, width_in, height_in = dimensions
    bag = accept_bag(scenario, weight_lb=48, length_in=length_in,
                     width_in=width_in, height_in=height_in)
    items = []
    for _ in range(item_count):
        items.append(_ok(api_client.add_special_item(
            bag["id"], create_special_item_payload(item_type="FRAGILE",
                                                   declared_value_cents=declared_value_cents),
            TEST_USERS["acceptance_agent_headers"]), "register special item"))
    weigh_ok(bag["id"], 48.0)
    return get_bag(bag["id"]), items


# ---------------------------------------------------------------------------
# Tier 5: finalization / terminal state
# ---------------------------------------------------------------------------

def setup_compensated_report(scenario, report_type="DAMAGED",
                             declared_value_cents=120000, requested_amount_cents=25000,
                             approved_amount_cents=25000, deliver_utc="2026-09-01T13:40:00Z"):
    """Full pipeline to a bag whose report is COMPENSATED.

    Returns (bag, report) with final_liability_cents already realised.
    """
    _, bag, report = delivered_bag_with_report(
        scenario, report_type=report_type, declared_value_cents=declared_value_cents,
        deliver_utc=deliver_utc)
    compensated = report_through_compensated(
        scenario, report["id"], requested_amount_cents, approved_amount_cents)
    return bag, compensated