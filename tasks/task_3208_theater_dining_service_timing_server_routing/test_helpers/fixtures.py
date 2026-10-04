"""Composite setup helpers for multi-step test prerequisites.

Every helper here builds its preconditions from scratch over PRD-declared
endpoints only, because the runner restarts the server before each test so each
test begins against an empty database. Setup calls use get_success_data() so a
broken precondition reports "Setup step failed" rather than a confusing
assertion mismatch further down.

Ownership threading: the Server role is entity-backed, so every action a server
performs on its own section is issued with make_server_headers(server["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, DAILY_SECTION_CAP, PAGINATION_MAX_LIMIT
from .test_users import TEST_USERS, make_server_headers

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["kitchen_lead_headers"]
PROGRAMMER = TEST_USERS["programming_coordinator_headers"]
PRODUCER = TEST_USERS["pre_show_producer_headers"]


def server_headers(server: dict) -> dict:
    """The entity-backed headers for a real Server row."""
    return make_server_headers(server["id"])


# ═══════════════════════════════════════════════════════════════════════
# Tier 0 — primitive builders
# ═══════════════════════════════════════════════════════════════════════

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, ADMIN))


def make_auditorium(name: str = None, **overrides) -> dict:
    """Create an auditorium with the PRD's declared defaults for the rates."""
    payload = {
        "name": name or "Theater Test",
        "seat_capacity": overrides.pop("seat_capacity", TEST_DEFAULTS["SEAT_CAPACITY"]),
        "screen_lead_time_minutes": overrides.pop(
            "screen_lead_time_minutes", TEST_DEFAULTS["SCREEN_LEAD_TIME_MINUTES"]
        ),
        "kitchen_point_rate": overrides.pop(
            "kitchen_point_rate", TEST_DEFAULTS["KITCHEN_POINT_RATE"]
        ),
        "alcove_point_rate": overrides.pop(
            "alcove_point_rate", TEST_DEFAULTS["ALCOVE_POINT_RATE"]
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_auditorium(payload, ADMIN))


def make_menu_item(channel: str = "ENTREE", price_cents: int = 1000,
                   prep_minutes: int = 1, is_alcoholic: bool = False,
                   catalog_name: str = None) -> dict:
    """Add one item to the master menu catalogue."""
    payload = {
        "catalog_name": catalog_name or f"Item {channel} {price_cents}",
        "channel": channel,
        "price_cents": price_cents,
        "prep_minutes": prep_minutes,
        "is_alcoholic": is_alcoholic,
    }
    return get_success_data(api_client.create_menu_item(payload, ADMIN))


def make_server(auditorium_id: str, display_name: str = None) -> dict:
    """Create a server profile hired into an auditorium."""
    payload = {
        "display_name": display_name or "Server Test",
        "home_auditorium_id": auditorium_id,
    }
    return get_success_data(api_client.create_server(payload, LEAD))


def make_showtime(auditorium_id: str, start_at_utc: str = "2026-09-01T20:00:00Z",
                  runtime_minutes: int = 100, content_type: str = "STANDARD",
                  title: str = None) -> dict:
    """Schedule a showtime; the response carries its derived window instants."""
    payload = {
        "auditorium_id": auditorium_id,
        "title": title or "Test Feature",
        "start_at_utc": start_at_utc,
        "runtime_minutes": runtime_minutes,
        "content_type": content_type,
    }
    return get_success_data(api_client.create_showtime(payload, PROGRAMMER))


def open_showtime_dining(showtime_id: str) -> dict:
    """Kitchen lead opens the seat-side seating window."""
    return get_success_data(api_client.open_dining(showtime_id, LEAD))


def make_section(showtime_id: str, server_id: str, section_label: str = "LEFT") -> dict:
    """Roster a server onto a section of a showtime."""
    payload = {
        "showtime_id": showtime_id,
        "server_id": server_id,
        "section_label": section_label,
    }
    return get_success_data(api_client.create_section_assignment(payload, LEAD))


def make_slip(showtime_id: str, section_assignment_id: str, server: dict,
              seat_number: int, lines: list, expected_showtime_version,
              capacity_ack=None) -> dict:
    """Place and accept a seat-side order slip, acting as the owning server."""
    payload = {
        "showtime_id": showtime_id,
        "section_assignment_id": section_assignment_id,
        "seat_number": seat_number,
        "lines": lines,
        "expected_showtime_version": expected_showtime_version,
    }
    if capacity_ack is not None:
        payload["capacity_ack"] = capacity_ack
    return get_success_data(api_client.create_order_slip(payload, server_headers(server)))


def make_themed_menu_item(event_id: str, menu_item_id: str,
                          theme_price_cents: int, is_signature: bool = False) -> dict:
    payload = {
        "menu_item_id": menu_item_id,
        "theme_price_cents": theme_price_cents,
        "is_signature": is_signature,
    }
    return get_success_data(api_client.attach_themed_menu_item(event_id, payload, PROGRAMMER))


def make_programming_event(auditorium_id: str, theme_name: str = None,
                           requires_themed_menu: bool = True) -> dict:
    payload = {
        "auditorium_id": auditorium_id,
        "theme_name": theme_name or "Test Theme Night",
        "requires_themed_menu": requires_themed_menu,
    }
    return get_success_data(api_client.create_programming_event(payload, PROGRAMMER))


def _current_event(event_id: str) -> dict:
    return get_success_data(api_client.get_programming_event(event_id, PROGRAMMER))


def approve_and_activate_event(event: dict, expected_version=None) -> dict:
    """Drive an event from DRAFT (or REJECTED) through approval to ACTIVATED.

    PRD §3.2 refuses activation with `ERR_NO_LINKED_SHOWTIME` unless the event
    already has "at least one linked showtime of type `SPECIAL_EVENT`", and
    §2.13 makes containment explicit: the linked showtime is the one that names
    this event's auditorium and carries `content_type` of `SPECIAL_EVENT`. A
    caller that has not yet scheduled that showtime gets the same refusal the
    platform would give it, rather than a raised setup helper.
    """
    current = _current_event(event["id"])
    if current["pre_show_content_status"] in ("PRE_SHOW_DRAFT", "PRE_SHOW_REJECTED"):
        current = get_success_data(
            api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER)
        )
    if current["pre_show_content_status"] == "PRE_SHOW_IN_REVIEW":
        current = get_success_data(
            api_client.approve_pre_show_content(event["id"], {}, PRODUCER)
        )
    version = expected_version if expected_version is not None else current["version"]
    return get_success_data(
        api_client.activate_programming_event(
            event["id"], {"expected_programming_event_version": version}, PROGRAMMER
        )
    )


# ═══════════════════════════════════════════════════════════════════════
# Tier 1/2 — the common scenario: auditorium, showtime, server, section
# ═══════════════════════════════════════════════════════════════════════

def setup_dining_open_showtime(start_at_utc: str = "2026-09-01T20:00:00Z",
                               runtime_minutes: int = 100,
                               clock: str = "2026-09-01T19:40:00Z",
                               kitchen_point_rate: int = 1,
                               alcove_point_rate: int = 3,
                               screen_lead_time_minutes: int = 20,
                               seat_capacity: int = 60,
                               section_label: str = "LEFT",
                               content_type: str = "STANDARD",
                               with_section: bool = True,
                               auditorium_name: str = None) -> dict:
    """The most-reused preamble: auditorium + server + showtime open for dining
    + (optionally) a section owned by the server.

    Returns a dict with: auditorium, server, showtime, section (or None).
    """
    set_clock(clock)
    auditorium = make_auditorium(
        name=auditorium_name,
        seat_capacity=seat_capacity,
        screen_lead_time_minutes=screen_lead_time_minutes,
        kitchen_point_rate=kitchen_point_rate,
        alcove_point_rate=alcove_point_rate,
    )
    server = make_server(auditorium["id"], "Dana")
    showtime = make_showtime(
        auditorium["id"], start_at_utc=start_at_utc,
        runtime_minutes=runtime_minutes, content_type=content_type,
    )
    showtime = open_showtime_dining(showtime["id"])
    section = (
        make_section(showtime["id"], server["id"], section_label)
        if with_section else None
    )
    return {
        "auditorium": auditorium,
        "server": server,
        "showtime": showtime,
        "section": section,
        "section_label": section_label,
    }


def begin_service(scenario: dict, clock: str = "2026-09-01T19:55:00Z") -> dict:
    """Move an already-staged dining-open scenario into SERVICE.

    Call this only after every ACTIVE section holds at least one slip of its own,
    which the cut-over requires. The returned showtime is re-read so its
    `version` reflects every write that landed during the staging.
    """
    set_clock(clock)
    get_success_data(api_client.start_service(scenario["showtime"]["id"], LEAD))
    scenario["showtime"] = read_showtime(scenario["showtime"]["id"], LEAD)
    return scenario


def setup_in_service_showtime(start_at_utc: str = "2026-09-01T20:00:00Z",
                              runtime_minutes: int = 100,
                              clock: str = "2026-09-01T19:40:00Z",
                              service_clock: str = "2026-09-01T19:55:00Z",
                              with_section: bool = True,
                              section_label: str = "LEFT",
                              before_service=None,
                              **kwargs) -> dict:
    """As setup_dining_open_showtime, then the kitchen lead moves the showtime
    into SERVICE (which mints the station tickets for accepted slips).

    `before_service(scenario)` runs while the showtime is still open for dining,
    so a caller can place the slips the cut-over needs before it happens.
    """
    scenario = setup_dining_open_showtime(
        start_at_utc=start_at_utc, runtime_minutes=runtime_minutes, clock=clock,
        section_label=section_label, with_section=with_section, **kwargs,
    )
    if before_service is not None:
        before_service(scenario)
    return begin_service(scenario, service_clock)


# ═══════════════════════════════════════════════════════════════════════
# Tier 3 — full lifecycle shortcuts
# ═══════════════════════════════════════════════════════════════════════

def drive_slip_to_ready(slip: dict, server: dict, prepare_clock: str,
                        ready_clock: str) -> dict:
    """ACCEPTED → PREPARING → READY for one slip, all as its owning server."""
    set_clock(prepare_clock)
    get_success_data(api_client.prepare_order_slip(slip["id"], server_headers(server)))
    set_clock(ready_clock)
    return get_success_data(
        api_client.mark_order_slip_ready(slip["id"], server_headers(server))
    )


def drive_slip_to_delivered(slip: dict, server: dict, prepare_clock: str,
                            ready_clock: str, deliver_clock: str,
                            slip_id: str = None) -> dict:
    """ACCEPTED → PREPARING → READY → DELIVERED."""
    target = slip_id or slip["id"]
    set_clock(prepare_clock)
    get_success_data(api_client.prepare_order_slip(target, server_headers(server)))
    set_clock(ready_clock)
    get_success_data(api_client.mark_order_slip_ready(target, server_headers(server)))
    set_clock(deliver_clock)
    return get_success_data(api_client.deliver_order_slip(target, server_headers(server)))


def setup_delivered_entree_with_ejection(rating_grade: str = "B",
                                         kind: str = "NO_TEXTING",
                                         start_at_utc: str = "2026-09-01T20:00:00Z",
                                         price_cents: int = 1200,
                                         prep_minutes: int = 1) -> dict:
    """Running showtime, one rated section, one DELIVERED entree slip, and one
    filed disturbance report on that slip's seat, ready for approval."""
    box = {}

    def place(scenario):
        showtime, server, section = (
            scenario["showtime"], scenario["server"], scenario["section"]
        )
        item = make_menu_item("ENTREE", price_cents=price_cents, prep_minutes=prep_minutes,
                              catalog_name="Flatbread")
        get_success_data(api_client.score_section_assignment(section["id"], rating_grade, LEAD))
        version = get_success_data(api_client.get_showtime(showtime["id"], LEAD))["version"]
        box["item"] = item
        box["slip"] = make_slip(
            showtime["id"], section["id"], server, 30,
            [{"menu_item_id": item["id"], "quantity": 1}],
            expected_showtime_version=version,
        )

    scenario = setup_in_service_showtime(
        start_at_utc=start_at_utc, runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=place,
    )
    server = scenario["server"]
    # PRD §3.4 refuses an entree with `ERR_ENTREE_DEADLINE_PASSED` once the clock
    # is past the feature's entrée deadline, so the plate is carried through to
    # DELIVERED inside the window and the ejection happens afterwards.
    drive_slip_to_delivered(box["slip"], server, "2026-09-01T19:50:00Z",
                            "2026-09-01T19:52:00Z", "2026-09-01T19:55:00Z")
    set_clock("2026-09-01T20:20:00Z")
    disturbance = get_success_data(api_client.create_disturbance_event(
        {"order_slip_id": box["slip"]["id"], "kind": kind}, server_headers(server)
    ))
    scenario.update({"item": box["item"], "slip": box["slip"], "disturbance": disturbance})
    return scenario


def setup_two_slips_one_ejected(rating_grade: str = "B", kind: str = "NO_TALKING",
                                 price_cents: int = 1000) -> dict:
    """One section, two entrees: the first is ejected at the boundary and the
    second stays live, so §3.8's two liability figures diverge."""
    box = {}

    def place(scenario):
        showtime, server, section = (
            scenario["showtime"], scenario["server"], scenario["section"]
        )
        item = make_menu_item("ENTREE", price_cents=price_cents, prep_minutes=1,
                              catalog_name="Pretzel")
        box["item"] = item
        for seat in (10, 11):
            version = get_success_data(
                api_client.get_showtime(showtime["id"], LEAD))["version"]
            box.setdefault("slips", []).append(make_slip(
                showtime["id"], section["id"], server, seat,
                [{"menu_item_id": item["id"], "quantity": 1}],
                expected_showtime_version=version,
            ))

    scenario = setup_in_service_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=place,
    )
    server = scenario["server"]
    ejected, live = box["slips"][0], box["slips"][1]
    set_clock("2026-09-01T19:50:00Z")
    # Both plates go to the kitchen so both tabs adopt their own originals; only
    # the first is carried to the seat, so the second is still standing when the
    # ejection books.
    get_success_data(api_client.prepare_order_slip(ejected["id"], server_headers(server)))
    get_success_data(api_client.prepare_order_slip(live["id"], server_headers(server)))
    get_success_data(api_client.mark_order_slip_ready(ejected["id"], server_headers(server)))
    get_success_data(api_client.deliver_order_slip(ejected["id"], server_headers(server)))
    set_clock("2026-09-01T20:20:00Z")
    disturbance = get_success_data(api_client.create_disturbance_event(
        {"order_slip_id": ejected["id"], "kind": kind}, server_headers(server)
    ))
    box["disturbance"] = disturbance
    scenario.update({"item": box["item"], "ejected_slip": ejected,
                     "live_slip": box["slips"][1], "disturbance": disturbance})
    return scenario


def setup_compensated_check_for_ejection(start_at_utc: str = "2026-09-01T20:00:00Z",
                                         runtime_minutes: int = 100,
                                         price_cents: int = 1000) -> dict:
    """A slip still in flight at the feature boundary books the 30% automatic
    service compensation, leaving its check PARTIALLY_REFUNDED."""
    box = {}

    def place(scenario):
        showtime, server, section = (
            scenario["showtime"], scenario["server"], scenario["section"]
        )
        item = make_menu_item("ENTREE", price_cents=price_cents, prep_minutes=1,
                              catalog_name="Chili")
        version = get_success_data(api_client.get_showtime(showtime["id"], LEAD))["version"]
        box["item"] = item
        box["slip"] = make_slip(
            showtime["id"], section["id"], server, 40,
            [{"menu_item_id": item["id"], "quantity": 1}],
            expected_showtime_version=version,
        )

    scenario = setup_in_service_showtime(
        start_at_utc=start_at_utc, runtime_minutes=runtime_minutes,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=place,
    )
    slip = box["slip"]
    # The tab adopts the slip's total when the slip is sent to the kitchen.
    set_clock("2026-09-01T19:50:00Z")
    get_success_data(api_client.prepare_order_slip(slip["id"], server_headers(scenario["server"])))
    # Push the clock past the entree deadline (21:15) and cut over to the feature.
    set_clock("2026-09-01T21:20:00Z")
    get_success_data(api_client.start_feature(scenario["showtime"]["id"], LEAD))
    scenario["showtime"] = read_showtime(scenario["showtime"]["id"], LEAD)
    checks, _ = _list_checks_for_slip(slip["id"])
    assert checks, (
        "the boundary cascade books the automatic compensation against the tab "
        "the slip opened at acceptance"
    )
    box["check_id"] = checks[0]["id"]
    scenario.update({"item": box["item"], "slip": slip, "check": checks[0]})
    return scenario


def setup_three_cold_line_tickets(costs=(1, 3, 1), start_at_utc="2026-09-01T20:00:00Z"):
    """Three entree slips on one section, moved into service so the cold-line
    cohort exists in fire order. Returns the tickets in that order."""
    box = {"slips": []}

    def place(scenario):
        showtime, server, section = (
            scenario["showtime"], scenario["server"], scenario["section"]
        )
        items = [
            make_menu_item("ENTREE", price_cents=1000, prep_minutes=cost,
                           catalog_name=f"Cold {idx}")
            for idx, cost in enumerate(costs)
        ]
        box["items"] = items
        for idx, item in enumerate(items):
            version = get_success_data(
                api_client.get_showtime(showtime["id"], LEAD)
            )["version"]
            box["slips"].append(make_slip(
                showtime["id"], section["id"], server, idx + 1,
                [{"menu_item_id": item["id"], "quantity": 1}],
                expected_showtime_version=version,
            ))
        set_clock("2026-09-01T19:45:00Z")

    scenario = setup_in_service_showtime(
        start_at_utc=start_at_utc, runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=place,
    )
    # The cold-line run is anchored at `start_at_utc` minus thirty minutes, so a
    # read taken before that anchor would show a `fire_at_utc` still ahead of the
    # clock. The scenario reads its cohort once the anchor has been reached, in
    # fire order — PRD §3.5 makes `sequence_position` the 1-based place in that
    # ordering, and the three tickets here tie on every key.
    set_clock("2026-09-01T19:30:00Z")
    tickets, _ = _list_tickets(scenario["showtime"]["id"], {"station": "cold_line"})
    tickets.sort(key=lambda t: t["sequence_position"])
    scenario.update({"items": box["items"], "slips": box["slips"], "tickets": tickets})
    return scenario


# ═══════════════════════════════════════════════════════════════════════
# Tier 4 — accumulation / threshold targeting
# ═══════════════════════════════════════════════════════════════════════

def setup_entree_load(load_points: int, prep_minutes: int = 1,
                      start_at_utc: str = "2026-09-01T20:00:00Z",
                      runtime_minutes: int = 60,
                      order_clock: str = "2026-09-01T19:40:00Z",
                      read_clock: str = "2026-09-01T19:40:00Z",
                      alighted_seats: int = 0, capacity_ack: bool = False,
                      **kwargs) -> dict:
    """Accumulate exactly `load_points` of cold-line entree demand on one
    showtime, so a capacity test can be staged at a precise loading.

    Demand is `prep_minutes` points per unit, so the slip count is derived
    rather than hard-coded.
    """
    scenario = setup_dining_open_showtime(
        start_at_utc=start_at_utc, runtime_minutes=runtime_minutes,
        clock=order_clock, **kwargs,
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    item = make_menu_item("ENTREE", price_cents=1000, prep_minutes=prep_minutes,
                          catalog_name="Load Item")
    per_unit = prep_minutes
    assert load_points % per_unit == 0, (
        f"{load_points} points is not reachable with {per_unit}-point units"
    )
    units_needed = load_points // per_unit
    slips = []
    seat = 1
    for _ in range(units_needed):
        current = get_success_data(api_client.get_showtime(showtime["id"], LEAD))
        slips.append(make_slip(
            showtime["id"], section["id"], server, seat,
            [{"menu_item_id": item["id"], "quantity": 1}],
            expected_showtime_version=current["version"],
            capacity_ack=True if capacity_ack else None,
        ))
        seat += 1
    set_clock(read_clock)
    scenario.update({"item": item, "slips": slips, "load_points": load_points,
                     "next_seat": seat})
    return scenario


def setup_with_voided_entree(keep_points: int = 2, doomed_points: int = 4,
                             prep_minutes: int = 2,
                             start_at_utc: str = "2026-09-01T20:00:00Z"):
    """One in-flight entree slip (`keep_points`) plus one cancelled entree slip
    (`doomed_points`) and one beverage slip that never enters the cold-line
    cohort at all, so the load filter can be observed."""
    scenario = setup_dining_open_showtime(
        start_at_utc=start_at_utc, runtime_minutes=100,
        clock="2026-09-01T19:40:00Z",
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    entree = make_menu_item("ENTREE", price_cents=1000, prep_minutes=prep_minutes,
                            catalog_name="Calzone")
    beverage = make_menu_item("BEVERAGE", price_cents=500, prep_minutes=1,
                              catalog_name="Lemonade")

    current = get_success_data(api_client.get_showtime(showtime["id"], LEAD))
    kept = make_slip(showtime["id"], section["id"], server, 1,
                     [{"menu_item_id": entree["id"], "quantity": 1}],
                     expected_showtime_version=current["version"])
    current = get_success_data(api_client.get_showtime(showtime["id"], LEAD))
    make_slip(showtime["id"], section["id"], server, 2,
              [{"menu_item_id": beverage["id"], "quantity": 4}],
              expected_showtime_version=current["version"])
    current = get_success_data(api_client.get_showtime(showtime["id"], LEAD))
    doomed = make_slip(showtime["id"], section["id"], server, 3,
                       [{"menu_item_id": entree["id"], "quantity": 2}],
                       expected_showtime_version=current["version"])
    get_success_data(api_client.cancel_order_slip(
        doomed["id"], {"reason_code": "SERVICE_OVERFLOW"}, LEAD
    ))
    scenario.update({"entree": entree, "beverage": beverage,
                     "kept_slip": kept, "doomed_slip": doomed})
    return scenario


# ═══════════════════════════════════════════════════════════════════════
# Tier 5 — cancellation / setback and read helpers
# ═══════════════════════════════════════════════════════════════════════

def setup_scheduled_showtime(start_at_utc: str = "2026-09-01T20:00:00Z",
                             runtime_minutes: int = 60,
                             clock: str = "2026-09-01T19:00:00Z",
                             **auditorium_kwargs) -> dict:
    """Auditorium + one SCHEDULED showtime, so a posture read can be observed
    without any intervening write to the auditorium."""
    set_clock(clock)
    auditorium = make_auditorium(**auditorium_kwargs)
    showtime = make_showtime(auditorium["id"], start_at_utc, runtime_minutes)
    return {"auditorium": auditorium, "showtime": showtime}


def setup_showtime_with_two_servers(section_owner_index: int = 0) -> dict:
    """Two real servers, one showtime open for dining, and two sections — one
    owned by each — so an ownership-gated call can be made by the wrong one."""
    scenario = setup_dining_open_showtime(section_label="LEFT")
    auditorium, showtime = scenario["auditorium"], scenario["showtime"]
    first = scenario["server"]
    second = make_server(auditorium["id"], "Gil")
    second_section = make_section(showtime["id"], second["id"], "RIGHT")
    scenario.update({"first_server": first, "second_server": second,
                     "first_section": scenario["section"],
                     "second_section": second_section})
    return scenario


def setup_three_servers_one_section() -> dict:
    """Three servers and a single section owned by the first, for the
    stale-reassignment path."""
    scenario = setup_dining_open_showtime(section_label="LEFT")
    auditorium = scenario["auditorium"]
    second = make_server(auditorium["id"], "Uma")
    third = make_server(auditorium["id"], "Vic")
    scenario.update({"server_s1": scenario["server"], "server_s2": second,
                     "server_s3": third, "assignment": scenario["section"]})
    return scenario


def setup_servobuffer_candidate_showtimes(start_at_utc: str = "2026-09-01T20:00:00Z"):
    """A server holding one section, plus two candidate showtimes whose on-floor
    windows sit a different distance from the held one.

    A server's on-floor interval runs from `dining_open_at_utc` to `start_at_utc`
    — the closed interval [start - 20, start] — so the candidates live on a
    second auditorium: the two windows on one room could never overlap at all,
    let alone sit inside the buffer.

    PRD §2.12 also constrains each candidate: two showtimes on one auditorium may
    not have overlapping *dining* windows, and a `runtime_minutes` whose
    three-quarter product floors to zero makes `dining_close_at_utc` fall before
    `dining_open_at_utc`. Both candidates therefore carry a runtime of 100
    minutes, which gives each one a well-formed 45-minute dining window.

    `too_close` opens 10 minutes before the held window closes (inside the
    buffer); `admitted` opens exactly SERVO_BUFFER_MINUTES before it closes.
    """
    # The candidate room is left DARK so that PRD §2.11's three routing
    # invariants are the only things the request can trip; a room with a
    # scheduled member would be TURNOVER, which the platform treats as serving.
    set_clock("2026-09-01T19:45:00Z")
    held_room = make_auditorium(name="Theater 15")
    cand_room = make_auditorium(name="Theater 15B")
    third_room = make_auditorium(name="Theater 15C")
    server = make_server(held_room["id"], "Zoe")

    held = make_showtime(held_room["id"], start_at_utc, 60, title="Se7en")
    held_section = make_section(held["id"], server["id"], "LEFT")

    # A server's on-floor interval is the CLOSED [start - 20, start], so the held
    # interval is [19:40, 20:00]. `too_close` opens twenty minutes after the held
    # window closes, leaving a ten-minute separation and breaching the buffer.
    # `admitted` opens exactly at the held interval's close, leaving the buffer's
    # own fifteen minutes, and its dining window abuts the held one so the two
    # still do not overlap. `same_room` runs long after `admitted` has closed,
    # clearing the temporal invariant, so only occupancy can answer it.
    too_close = make_showtime(cand_room["id"], _shift(start_at_utc, 30), 60, title="Zodiac")
    admitted = make_showtime(held_room["id"], _shift(start_at_utc, 35), 60, title="Prisoners")
    same_room = make_showtime(held_room["id"], _shift(start_at_utc, 95), 60, title="Memento")
    return {"held_room": held_room, "other_room": cand_room, "cand_room": cand_room,
            "third_room": third_room, "server": server, "held": held,
            "held_section": held_section, "too_close": too_close,
            "admitted": admitted, "same_room": same_room}


def setup_daily_cap_showtimes():
    """Four well-separated showtimes on one auditorium on one service day, with
    the first three already rostered to the same server.

    PRD §2.12 constrains each of these: `dining_close_at_utc` is the entrée
    deadline minus thirty minutes, and the entrée deadline is the feature start
    plus three-quarters of the runtime floored. A 60-minute runtime hence puts
    each showtime's dining close *before* its own dining open; the runtimes here
    are 100 minutes so every window is well formed, and the four are far enough
    apart that none of the dining windows overlap.
    """
    set_clock("2026-09-01T19:45:00Z")
    auditorium = make_auditorium()
    server = make_server(auditorium["id"], "Abe")
    starts = ["2026-09-01T20:00:00Z", "2026-09-01T22:00:00Z",
              "2026-09-02T00:00:00Z", "2026-09-02T03:00:00Z"]
    labels = ["LEFT", "CENTER", "RIGHT", "LEFT"]
    showtimes, assignments = [], []
    for start, label in zip(starts, labels):
        showtimes.append(make_showtime(auditorium["id"], start, 100))
    for showtime, label in zip(showtimes[:DAILY_SECTION_CAP], labels):
        assignments.append(make_section(showtime["id"], server["id"], label))
    return {"auditorium": auditorium, "server": server, "showtimes": showtimes,
            "assignments": assignments}


def setup_completed_showtime_for_reopen(rating_grade: str = None,
                                        start_at_utc: str = "2026-09-01T20:00:00Z",
                                        runtime_minutes: int = 100) -> dict:
    """A showtime in SERVICE with one rostered section and a clean kitchen,
    staged so the caller can complete it and then reopen it.

    The window opens at 19:40 and the service phase at 19:50. PRD §3.5 opens the
    service window at `start_at_utc` minus ten minutes, so a cut-over attempted
    at 19:45 is refused with `ERR_NOT_IN_SERVICE_WINDOW`; the staging here is
    timed to the instant the window is actually open.
    """
    # PRD §3.5 refuses the cut-over with `ERR_SECTION_UNCOVERED` unless every
    # ACTIVE section holds at least one order slip of its own, so the section is
    # worked before the service phase begins. §3.7 then refuses the close-out with
    # `ERR_OPEN_KITCHEN_TICKETS` unless every ticket is DELIVERED or VOIDED, and
    # PRD §3.5 defines a completed showtime as the one the LIFECYCLE has put in
    # `RUNNING` — so the close-out the caller is staging for is exercised against
    # a showtime whose kitchen has already closed clean.
    scenario = setup_in_service_showtime(
        start_at_utc=start_at_utc, runtime_minutes=runtime_minutes,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=lambda s: place_scenario_slip(s, seat=1, catalog_name="Arepa"),
    )
    drive_slip_to_delivered(scenario["slip"], scenario["server"],
                            "2026-09-01T19:50:00Z", "2026-09-01T19:52:00Z",
                            "2026-09-01T19:55:00Z")
    if rating_grade:
        get_success_data(api_client.score_section_assignment(
            scenario["section"]["id"], rating_grade, LEAD
        ))
    # PRD §2.5 makes a room LIVE only while a member showtime is DINING_OPEN,
    # SERVICE or RUNNING, and §3.7 refuses a reopen from anything but a LIVE room
    # (`ERR_AUDITORIUM_NOT_SERVING`). A second showtime is therefore scheduled on
    # the far side of the first one's seating window and opened for dining, so the
    # room is still LIVE when the first showtime is completed and reopened.
    set_clock("2026-09-01T20:00:00Z")
    get_success_data(api_client.start_feature(scenario["showtime"]["id"], LEAD))
    sibling = make_showtime(scenario["auditorium"]["id"], "2026-09-01T21:05:00Z",
                            runtime_minutes, title="Second Feature")
    set_clock("2026-09-01T20:45:00Z")
    sibling = get_success_data(api_client.open_dining(sibling["id"], LEAD))
    scenario["showtime"] = read_showtime(scenario["showtime"]["id"], LEAD)
    scenario["sibling"] = sibling
    return scenario


# ═══════════════════════════════════════════════════════════════════════
# Special-event staging
# ═══════════════════════════════════════════════════════════════════════

def setup_themed_event(auditorium_id: str = None, state: str = "DRAFT",
                       with_signature: bool = True,
                       theme_name: str = None) -> dict:
    """An auditorium (unless supplied), a catalogue item, a programming event
    and a themed menu attachment on it.

    `state` is one of DRAFT | IN_REVIEW | APPROVED | ACTIVATED | CANCELLED and
    drives only as far as that point.
    """
    auditorium = (
        get_success_data(api_client.get_auditorium(auditorium_id, ADMIN))
        if auditorium_id else make_auditorium()
    )
    item = make_menu_item("ENTREE", price_cents=1200, prep_minutes=2,
                          catalog_name="Reuben")
    event = make_programming_event(auditorium["id"], theme_name=theme_name,
                                   requires_themed_menu=True)
    themed = make_themed_menu_item(event["id"], item["id"], 1350, with_signature)

    if state == "DRAFT":
        return {"auditorium": auditorium, "item": item, "event": event,
                "themed": themed}

    event = get_success_data(api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER))
    if state == "IN_REVIEW":
        return {"auditorium": auditorium, "item": item, "event": event,
                "themed": themed}
    if state == "REJECTED":
        event = get_success_data(api_client.reject_pre_show_content(
            event["id"], {"notes": "recut"}, PRODUCER
        ))
        return {"auditorium": auditorium, "item": item, "event": event,
                "themed": themed}

    event = get_success_data(api_client.approve_pre_show_content(event["id"], {}, PRODUCER))
    if state == "APPROVED":
        return {"auditorium": auditorium, "item": item, "event": event,
                "themed": themed}

    event = get_success_data(api_client.activate_programming_event(
        event["id"], {"expected_programming_event_version": event["version"]}, PROGRAMMER
    ))
    return {"auditorium": auditorium, "item": item, "event": event, "themed": themed}


def setup_special_event_showtime(event_state: str = "DRAFT",
                                 start_at_utc: str = "2026-09-01T20:00:00Z",
                                 runtime_minutes: int = 100,
                                 clock: str = "2026-09-01T19:40:00Z",
                                 with_section: bool = False) -> dict:
    """Themed event plus a SPECIAL_EVENT showtime on the same auditorium, staged
    so the linked-event gate is the only thing standing in the way.

    `event_state` is DRAFT | IN_REVIEW | APPROVED | ACTIVATED.
    """
    set_clock(clock)
    auditorium = make_auditorium(name="Theater 14")
    item = make_menu_item("ENTREE", price_cents=1100, prep_minutes=1,
                          catalog_name="Curry Poutine")
    event = make_programming_event(auditorium["id"], "Almost Famous Mixtape", True)
    make_themed_menu_item(event["id"], item["id"], 1250, is_signature=True)

    if event_state in ("IN_REVIEW", "APPROVED", "ACTIVATED"):
        event = get_success_data(
            api_client.submit_pre_show_content(event["id"], {}, PROGRAMMER)
        )
    if event_state in ("APPROVED", "ACTIVATED"):
        event = get_success_data(
            api_client.approve_pre_show_content(event["id"], {}, PRODUCER)
        )

    showtime = make_showtime(auditorium["id"], start_at_utc, runtime_minutes,
                             content_type="SPECIAL_EVENT")
    if event_state == "ACTIVATED":
        event = get_success_data(api_client.activate_programming_event(
            event["id"], {"expected_programming_event_version": event["version"]}, PROGRAMMER
        ))
    server = make_server(auditorium["id"], "Hal")
    section = make_section(showtime["id"], server["id"], "CENTER") if with_section else None
    return {"auditorium": auditorium, "item": item, "event": event,
            "showtime": showtime, "server": server, "section": section}


def setup_standard_and_special_showtimes() -> dict:
    """One STANDARD and one SPECIAL_EVENT showtime on one auditorium, with no
    programming event in existence at all."""
    set_clock("2026-09-01T19:50:00Z")
    auditorium = make_auditorium(name="Theater 17")
    standard = make_showtime(auditorium["id"], "2026-09-01T20:00:00Z", 60,
                             content_type="STANDARD", title="Standard Cut")
    special = make_showtime(auditorium["id"], "2026-09-01T21:30:00Z", 60,
                            content_type="SPECIAL_EVENT", title="Special Cut")
    return {"auditorium": auditorium, "standard": standard, "special": special}


def place_scenario_slip(scenario: dict, *, channel: str = "ENTREE", seat: int = 1,
                        price_cents: int = 1000, prep_minutes: int = 1,
                        is_alcoholic: bool = False, catalog_name: str = None,
                        quantity: int = 1, prepare_clock: str = None) -> dict:
    """Place one slip on a staged scenario's section and stash its item.

    Intended for use inside a `before_service` callback, because the cut-over
    refuses a section that holds no slip of its own.

    `prepare_clock` additionally carries the slip into the kitchen at that
    instant. PRD §3.6 settles every slip still ACCEPTED or PREPARING at the
    feature boundary whose deadline has passed as a late delivery, so a caller
    that needs the slip to survive the boundary must move it past ACCEPTED first.
    """
    showtime, server, section = (
        scenario["showtime"], scenario["server"], scenario["section"]
    )
    item = make_menu_item(channel, price_cents=price_cents, prep_minutes=prep_minutes,
                          is_alcoholic=is_alcoholic, catalog_name=catalog_name)
    version = get_success_data(api_client.get_showtime(showtime["id"], LEAD))["version"]
    slip = make_slip(
        showtime["id"], section["id"], server, seat,
        [{"menu_item_id": item["id"], "quantity": quantity}],
        expected_showtime_version=version,
    )
    if prepare_clock is not None:
        set_clock(prepare_clock)
        slip = get_success_data(
            api_client.prepare_order_slip(slip["id"], server_headers(server))
        )
    scenario.update({"item": item, "slip": slip})
    return slip


def setup_alcohol_slip_in_service(clock: str = "2026-09-01T19:40:00Z",
                                  prepare_clock: str = "2026-09-01T19:55:00Z",
                                  ready_clock: str = "2026-09-01T20:05:00Z",
                                  start_at_utc: str = "2026-09-01T20:00:00Z",
                                  to_ready: bool = True) -> dict:
    """An alcoholic BEVERAGE slip carried through to PREPARING (or READY) while
    its identification axis is still PENDING."""
    box = {}

    def place(scenario):
        showtime, server, section = (
            scenario["showtime"], scenario["server"], scenario["section"]
        )
        liquor = make_menu_item("BEVERAGE", price_cents=1500, prep_minutes=1,
                                is_alcoholic=True, catalog_name="Local IPA")
        version = get_success_data(api_client.get_showtime(showtime["id"], LEAD))["version"]
        box["item"] = liquor
        box["slip"] = make_slip(
            showtime["id"], section["id"], server, 20,
            [{"menu_item_id": liquor["id"], "quantity": 1}],
            expected_showtime_version=version,
        )

    scenario = setup_in_service_showtime(
        start_at_utc=start_at_utc, runtime_minutes=100, clock=clock,
        service_clock="2026-09-01T19:50:00Z", before_service=place,
    )
    server, showtime = scenario["server"], scenario["showtime"]
    tickets, _ = _list_tickets(showtime["id"], {"station": "hot_line"})
    set_clock(prepare_clock)
    slip = get_success_data(
        api_client.prepare_order_slip(box["slip"]["id"], server_headers(server))
    )
    if to_ready:
        # PRD §3.4 admits `mark-ready` only once the clock has reached the
        # ticket's `projected_delivery_at_utc`, which the service-window cut-over
        # puts at 20:05 for a one-point hot-line ticket on a three-a-minute alcove.
        set_clock(ready_clock)
        get_success_data(api_client.mark_order_slip_ready(slip["id"], server_headers(server)))
        slip = get_success_data(api_client.get_order_slip(slip["id"], ADMIN))
    scenario.update({"item": box["item"], "slip": slip,
                     "hot_ticket": tickets[0] if tickets else None})
    return scenario


def setup_ready_entree_and_ready_alcohol_slips() -> dict:
    """One READY entree slip and one READY alcoholic beverage slip on the same
    section, with the clock pushed past the entree deadline."""
    box = {"slips": {}}

    def place(scenario):
        showtime, server, section = (
            scenario["showtime"], scenario["server"], scenario["section"]
        )
        entree = make_menu_item("ENTREE", price_cents=1200, prep_minutes=1,
                                catalog_name="Brisket Plate")
        liquor = make_menu_item("BEVERAGE", price_cents=1500, prep_minutes=1,
                                is_alcoholic=True, catalog_name="Cabernet")
        version = get_success_data(api_client.get_showtime(showtime["id"], LEAD))["version"]
        box["slips"]["entree"] = make_slip(
            showtime["id"], section["id"], server, 5,
            [{"menu_item_id": entree["id"], "quantity": 1}],
            expected_showtime_version=version,
        )
        version = get_success_data(api_client.get_showtime(showtime["id"], LEAD))["version"]
        box["slips"]["wine"] = make_slip(
            showtime["id"], section["id"], server, 6,
            [{"menu_item_id": liquor["id"], "quantity": 1}],
            expected_showtime_version=version,
        )
        box["entree"] = entree
        box["liquor"] = liquor

    scenario = setup_in_service_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=place,
    )
    server = scenario["server"]
    entree_slip, wine_slip = box["slips"]["entree"], box["slips"]["wine"]
    # The cut-over anchors the cold-line run at 19:30, so both slips' fire windows
    # are already open; they are carried to PREPARING now and to READY past the
    # 21:15 deadline, which is what makes the two delivery edges distinguishable.
    set_clock("2026-09-01T19:50:00Z")
    get_success_data(api_client.prepare_order_slip(entree_slip["id"], server_headers(server)))
    get_success_data(api_client.prepare_order_slip(wine_slip["id"], server_headers(server)))
    set_clock("2026-09-01T21:20:00Z")
    get_success_data(api_client.mark_order_slip_ready(entree_slip["id"], server_headers(server)))
    get_success_data(api_client.mark_order_slip_ready(wine_slip["id"], server_headers(server)))
    scenario.update({"entree": box["entree"], "liquor": box["liquor"],
                     "entree_slip": read_slip(entree_slip["id"], LEAD),
                     "wine_slip": read_slip(wine_slip["id"], LEAD)})
    return scenario


def setup_unverified_alcohol_in_service(start_at_utc: str = "2026-09-01T20:00:00Z",
                                        place_slip: bool = True) -> dict:
    """A showtime already in SERVICE with one unverified alcoholic slip on its
    section, so the caller can move the clock and cut over to the feature.

    Set place_slip False to receive the staged section and only place the slip
    afterwards, when the clock is already at the boundary.
    """
    box = {}

    def place(scenario):
        showtime, server, section = (
            scenario["showtime"], scenario["server"], scenario["section"]
        )
        liquor = make_menu_item("BEVERAGE", price_cents=1500, prep_minutes=1,
                                is_alcoholic=True, catalog_name="Stout")
        version = get_success_data(api_client.get_showtime(showtime["id"], LEAD))["version"]
        box["item"] = liquor
        box["slip"] = make_slip(
            showtime["id"], section["id"], server, 20,
            [{"menu_item_id": liquor["id"], "quantity": 1}],
            expected_showtime_version=version,
        )

    # PRD §3.5 opens the service window at `start_at_utc` minus ten minutes, so
    # the cut-over is staged at 19:50 and the clock then returns to the 19:55
    # read point. Leaving it at 19:50 would put the slip's `fire_at_utc` in the
    # future, which §3.4 refuses with `ERR_FIRE_WINDOW_NOT_OPEN`.
    # The clock is started at the seating window's open instant so the placed
    # slip exists while the cut-over runs; the service phase then begins at 19:50
    # and the clock is restored to the 19:55 read point afterwards.
    scenario = setup_in_service_showtime(
        start_at_utc=start_at_utc, runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=place if place_slip else None,
    )
    set_clock("2026-09-01T19:55:00Z")
    if place_slip:
        scenario.update({"item": box["item"], "slip": box["slip"]})
    return scenario


def setup_unverified_alcohol_at_boundary() -> dict:
    """A showtime in SERVICE plus one unverified alcoholic slip, ready for the
    caller to advance the clock to the feature's exact start instant."""
    return setup_unverified_alcohol_in_service()


def place_alcohol_slip_on(scenario: dict, seat: int = 20) -> dict:
    """Place one alcoholic beverage slip on an already-staged scenario."""
    showtime, server, section = (
        scenario["showtime"], scenario["server"], scenario["section"]
    )
    item = scenario["item"]
    current = get_success_data(api_client.get_showtime(showtime["id"], LEAD))
    slip = make_slip(showtime["id"], section["id"], server, seat,
                     [{"menu_item_id": item["id"], "quantity": 1}],
                     expected_showtime_version=current["version"])
    scenario["slip"] = slip
    return slip


# ═══════════════════════════════════════════════════════════════════════
# Read helpers
# ═══════════════════════════════════════════════════════════════════════

def _list_tickets(showtime_id: str, params: dict = None, headers=None):
    # A showtime's cold-line run can hold more than the pagination default of ten
    # tickets, and every caller here reads the *whole* cohort. PRD §2.3 caps
    # `limit` at 100, so the reader asks for the full window rather than the
    # default page.
    query = dict(params or {})
    query.setdefault("limit", PAGINATION_MAX_LIMIT)
    return _unpack(api_client.list_showtime_kitchen_tickets(
        showtime_id, headers or LEAD, params=query
    ))


def _list_checks_for_slip(slip_id: str, headers=None):
    """The tab keyed on this slip, if one has been opened.

    PRD §3.8 opens it at acceptance, but a slip whose identification failure or
    cancellation released it before the kitchen ever saw it never gets one, so a
    miss is reported as "no tab" rather than as a setup failure.
    """
    body = api_client.list_checks(headers or LEAD, params={"id": slip_id}).json()
    data = body.get("data")
    if not isinstance(data, list) or not data:
        return [], body.get("meta", {})
    return data, body.get("meta", {})


def _list_slips(showtime_id: str, params: dict = None, headers=None):
    return _unpack(api_client.list_showtime_order_slips(
        showtime_id, headers or LEAD, params=params
    ))


def _list_assignments(showtime_id: str, params: dict = None, headers=None):
    return _unpack(api_client.list_showtime_section_assignments(
        showtime_id, headers or LEAD, params=params
    ))


def _unpack(response):
    """(data_list, meta) from a paginated read, without demanding a status."""
    body = response.json()
    if body.get("response_type") == "error":
        raise AssertionError(
            f"Setup read failed: {body['data'].get('error_id')} - "
            f"{body['data'].get('message')}"
        )
    return body["data"], body.get("meta", {})


def _shift(iso_instant: str, minutes: int) -> str:
    from datetime import datetime, timedelta

    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(iso_instant, fmt) + timedelta(minutes=minutes)).strftime(fmt)


def read_capacity(showtime_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_dining_capacity(showtime_id, headers or LEAD))


def read_posture(auditorium_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_auditorium_posture(auditorium_id, headers or LEAD))


def read_section(assignment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_section_assignment(assignment_id, headers or LEAD))


def read_server(server_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_server(server_id, headers or LEAD))


def read_slip(slip_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_order_slip(slip_id, headers or LEAD))


def read_showtime(showtime_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_showtime(showtime_id, headers or LEAD))


def read_check(check_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_check(check_id, headers or LEAD))


def read_ticket(ticket_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_kitchen_ticket(ticket_id, headers or LEAD))