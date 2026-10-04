"""Composite setup helpers for the service floor.

Every helper builds its preconditions from scratch with PRD-declared endpoints only;
the harness restarts the server before each test, so nothing is carried over.

Setup calls use get_success_data() (the lenient validator) so that a broken
precondition surfaces as a clear "setup failed" message rather than a confusing
assertion failure deep inside a test.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_chef_payload,
    create_maintenance_window_payload,
    create_party_payload,
    create_reservation_payload,
    create_sushi_ticket_payload,
    create_table_payload,
    create_tier_payload,
    create_venue_payload,
)
from .test_users import (
    TEST_USERS,
    make_chef_headers,
    make_sushi_chef_headers,
)

DEFAULT_CLOCK = "2026-09-02T12:00:00Z"
EMPTY_UUID = "00000000-0000-4000-8000-000000000000"

PA = TEST_USERS["platform_admin_headers"]
FM = TEST_USERS["floor_manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── Time helpers ─────────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_instant(instant: str, minutes: int) -> str:
    return format_instant(parse_instant(instant) + timedelta(minutes=minutes))


def minutes_between(later: str, earlier: str) -> int:
    return int((parse_instant(later) - parse_instant(earlier)).total_seconds() // 60)


def set_clock(current_utc: str, headers=None):
    """Point the logical clock at an instant. Returns the raw response."""
    res = api_client.set_clock(current_utc, headers or PA)
    assert res.status_code == 200, f"Setup failed: set_clock({current_utc}) -> {res.status_code} {res.text}"
    return res


def advance_clock(from_instant: str, minutes: int) -> str:
    """Move the logical clock `minutes` past `from_instant`; returns the new instant."""
    target = shift_instant(from_instant, minutes)
    set_clock(target)
    return target


# ─── Tier 1 / Tier 2: venue hierarchy ─────────────────────────────────────────

def setup_floor(clock: str = DEFAULT_CLOCK,
                tier_codes=("T6", "T4", "T2"),
                tables=(("T6", 6), ("T4", 4), ("T2", 2)),
                chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")),
                clock_in=None,
                venue_overrides=None,
                table_overrides=None,
                tier_overrides=None):
    """Clock + venue + tiers + grill tables + rostered chefs.

    `tables` entries are (tier_code, seat_capacity) tuples; `tier_overrides` maps a
    tier code to field overrides for that tier row. `clock_in` is the number of
    rostered chefs to put ON_STATION — None means every rostered chef, which is what
    the seating rule needs since a seat requires an on-station chef with a free table.
    Returns a scenario dict:
      venue, tiers (by code), tables (list), table_by_code,
      chefs (list), on_station (list of clocked-in chefs).
    """
    set_clock(clock)

    venue = get_success_data(api_client.create_venue(
        create_venue_payload(**(venue_overrides or {})), PA))

    tier_overrides = tier_overrides or {}
    tiers = {}
    for code in tier_codes:
        tiers[code] = get_success_data(api_client.create_tier(
            create_tier_payload(venue["id"], tier_code=code,
                                **tier_overrides.get(code, {})), PA))

    table_list = []
    table_by_code = {}
    for index, (code, seats) in enumerate(tables):
        payload = create_table_payload(venue["id"], tier_code=code, seat_capacity=seats)
        if index == 0 and table_overrides:
            payload.update(table_overrides)
        table = get_success_data(api_client.create_table(payload, FM))
        table_list.append(table)
        table_by_code.setdefault(code, table)

    chef_list = []
    for name, zone in chefs:
        chef_list.append(get_success_data(api_client.create_chef(
            create_chef_payload(venue["id"], chef_name=name, station_zone=zone), FM)))

    scenario = {
        "clock": clock,
        "venue": venue,
        "tiers": tiers,
        "tables": table_list,
        "table_by_code": table_by_code,
        "chefs": chef_list,
        "on_station": [],
    }

    for chef in (chef_list if clock_in is None else chef_list[:clock_in]):
        clock_in_chef(scenario, chef)

    return scenario


def minimal_floor(clock: str = DEFAULT_CLOCK, tier_codes=(), tables=(), chefs=(),
                  clock_in=None, venue_overrides=None):
    """Clock, venue, optionally some tiers / tables / chefs. Same shape as setup_floor."""
    return setup_floor(clock=clock, tier_codes=tier_codes, tables=tables, chefs=chefs,
                       clock_in=clock_in, venue_overrides=venue_overrides)


def fresh_venue_version(scenario) -> int:
    return get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))["version"]


def fresh_table(scenario, table_id) -> dict:
    return get_success_data(api_client.get_table(table_id, HOST))


def create_party(scenario, loyalty_tier="NONE", name="Dana Whitfield",
                 phone="212-555-0141"):
    payload = create_party_payload(scenario["venue"]["id"],
                                   lead_guest_name=name, contact_phone=phone)
    if loyalty_tier != "NONE":
        payload["loyalty_tier"] = loyalty_tier
    return get_success_data(api_client.create_party(payload, HOST))


def create_booking(scenario, party_id, tier_code, **overrides):
    tier = scenario["tiers"][tier_code]
    payload = create_reservation_payload(scenario["venue"]["id"], party_id, tier["id"],
                                         **overrides)
    return get_success_data(api_client.create_reservation(payload, HOST))


def submit_booking(reservation_id):
    return get_success_data(api_client.post_reservation_event(reservation_id, "SUBMIT", HOST))


def grant_hold(reservation_id, table_id, scenario=None):
    """Grant a first hold against `table_id`, reading the table's current version first."""
    table = get_success_data(api_client.get_table(table_id, HOST))
    return get_success_data(api_client.grant_hold(
        reservation_id,
        {"expected_table_version": table["version"], "table_id": table_id},
        HOST))


def seat_booking(reservation_id):
    return get_success_data(api_client.seat_reservation(reservation_id, HOST))


# ─── Chef rotation helpers ────────────────────────────────────────────────────

def clock_in_chef(scenario, chef):
    version = fresh_venue_version(scenario)
    res = api_client.post_chef_event(
        chef["id"], {"event_type": "CLOCK_IN", "expected_venue_version": version},
        make_chef_headers(chef["id"]))
    data = get_success_data(res)
    scenario["on_station"].append(data)
    scenario[f"chef_{chef['id']}"] = data
    return data


def chef_state(chef_id) -> dict:
    return get_success_data(api_client.get_chef(chef_id, FM))


def clear_chef(chef_id):
    """CLEAR_FINISH: ON_STATION -> CLEARING, current_table_id cleared."""
    version = get_success_data(api_client.get_venue(
        get_success_data(api_client.get_chef(chef_id, FM))["venue_id"], FM))["version"]
    return get_success_data(api_client.post_chef_event(
        chef_id, {"event_type": "CLEAR_FINISH", "expected_venue_version": version},
        make_chef_headers(chef_id)))


def clock_out_chef(chef_id):
    version = get_success_data(api_client.get_venue(
        get_success_data(api_client.get_chef(chef_id, FM))["venue_id"], FM))["version"]
    return get_success_data(api_client.post_chef_event(
        chef_id, {"event_type": "CLOCK_OUT", "expected_venue_version": version},
        make_chef_headers(chef_id)))


def rotate_suppress_chef(chef_id):
    """FloorManager drives CLEARING -> ON_STATION with a freshly assigned position."""
    version = get_success_data(api_client.get_venue(
        get_success_data(api_client.get_chef(chef_id, FM))["venue_id"], FM))["version"]
    return get_success_data(api_client.post_chef_event(
        chef_id, {"event_type": "ROTATE_SUPPRESS", "expected_venue_version": version},
        FM))


# ─── Show helpers ─────────────────────────────────────────────────────────────

def start_show(show_id, chef_id):
    """START a show phase as the chef the phase is assigned to."""
    return get_success_data(api_client.post_show_event(
        show_id, "START", make_chef_headers(chef_id)))


def finish_show(show_id, chef_id):
    return get_success_data(api_client.post_show_event(
        show_id, "FINISH", make_chef_headers(chef_id)))


def skip_show(show_id):
    return get_success_data(api_client.post_show_event(show_id, "SKIP", FM))


def perform_sushi_phase(sushi_show_id, start_instant, chef_id):
    """START + FINISH the sushi phase one and two minutes on from `start_instant`."""
    set_clock(shift_instant(start_instant, 1))
    start_show(sushi_show_id, chef_id)
    set_clock(shift_instant(start_instant, 2))
    return finish_show(sushi_show_id, chef_id)


def perform_grill_phase(grill_show_id, start_instant, chef_id, duration_minutes=46):
    """START the grill phase and FINISH it `duration_minutes` later, which clears the
    tier's per-table performance standard less the under-run tolerance."""
    set_clock(shift_instant(start_instant, 3))
    started = start_show(grill_show_id, chef_id)
    set_clock(shift_instant(start_instant, 3 + duration_minutes))
    finished = finish_show(grill_show_id, chef_id)
    return started, finished


# ─── Lifecycle shortcuts ──────────────────────────────────────────────────────

def book_hold_seat(scenario, party_id, tier_code, table_id, **overrides):
    """Draft -> SUBMIT -> hold -> seat. Returns a dict of the seeded rows."""
    reservation = create_booking(scenario, party_id, tier_code, **overrides)
    submit_booking(reservation["id"])
    grant_hold(reservation["id"], table_id, scenario)
    seated = seat_booking(reservation["id"])
    return {
        "reservation": seated,
        "seating_id": seated["current_seating_id"],
        "sushi_show_id": seated["current_sushi_show_id"],
        "grill_show_id": seated["current_grill_show_id"],
        "table_id": table_id,
    }


def seed_seated_booking_with_finished_grill(scenario, party_id, tier_code, table_id,
                                            at_instant=None, party_size=4,
                                            **overrides):
    """A seated booking whose sushi and grill phases are both FINISHED.

    The show phases are driven by the chef the seat pinned to the booking, so the
    calls pass ownership. Returns the seeded rows plus the protein ticket the grill
    start posted.
    """
    if at_instant:
        set_clock(at_instant)
        scenario["clock"] = at_instant
    seafood = book_hold_seat(scenario, party_id, tier_code, table_id,
                             party_size=party_size, **overrides)
    chef_id = seafood["reservation"]["chef_assignment_id"]
    started_at = at_instant or scenario["clock"]
    perform_sushi_phase(seafood["sushi_show_id"], started_at, chef_id)
    _, grill = perform_grill_phase(seafood["grill_show_id"], started_at, chef_id)
    seafood["chef_id"] = chef_id
    seafood["grill_show"] = grill
    seafood["protein_ticket_id"] = grill.get("protein_ticket_id")
    seafood["last_instant"] = shift_instant(started_at, 3 + 46)
    return seafood


def prepare_table_for_turn(seafood):
    """Drive every remaining show phase at the booking's table to SKIPPED so the
    table's TURN transition is legal (it requires every show at the table to be
    FINISHED or SKIPPED)."""
    reservation_id = seafood["reservation"]["id"]
    for show in shows_for(reservation_id):
        if show["status"] in ("PLANNED", "STARTED"):
            api_client.post_show_event(show["id"], "SKIP", FM)
    return shows_for(reservation_id)


def grant_hold_at_later_clock(reservation_id, table_id):
    """Re-park a booking whose hold window has already closed onto another table."""
    table = get_success_data(api_client.get_table(table_id, HOST))
    return api_client.grant_hold(
        reservation_id,
        {"expected_table_version": table["version"], "table_id": table_id},
        HOST)


def schedule_ventilation_window(scenario, planned_start_at, planned_end_at,
                                accept=True):
    window = get_success_data(api_client.create_maintenance_window(
        create_maintenance_window_payload(
            scenario["venue"]["id"],
            maintenance_kind="VENTILATION_SERVICE",
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at),
        FM))
    if accept:
        accepted = get_success_data(api_client.accept_maintenance_window(window["id"], FM))
        return accepted
    return window


def schedule_table_window(scenario, table_id, maintenance_kind="GRILL_REBUILD",
                          planned_start_at="2026-09-03T11:00:00Z",
                          planned_end_at="2026-09-03T12:00:00Z",
                          accept=False):
    window = get_success_data(api_client.create_maintenance_window(
        create_maintenance_window_payload(
            scenario["venue"]["id"], maintenance_kind=maintenance_kind,
            table_id=table_id, planned_start_at=planned_start_at,
            planned_end_at=planned_end_at),
        FM))
    if accept:
        return get_success_data(api_client.accept_maintenance_window(window["id"], FM))
    return window


def fire_sushi_ticket(scenario, reservation_id, chef_id=None, **overrides):
    """Fire a sushi ticket as the SushiChef bound to the booking's chef row."""
    actor = chef_id or scenario["chefs"][0]["id"]
    return get_success_data(api_client.create_sushi_ticket(
        create_sushi_ticket_payload(scenario["venue"]["id"], reservation_id, **overrides),
        make_sushi_chef_headers(actor)))


def sushi_event(ticket_id, event_type, chef_id):
    return api_client.post_sushi_event(ticket_id, event_type, make_sushi_chef_headers(chef_id))


def ledger_entries(venue_id, reservation_id=None, entry_kind=None):
    params = {"venue_id": venue_id}
    if reservation_id:
        params["reservation_id"] = reservation_id
    if entry_kind:
        params["entry_kind"] = entry_kind
    return get_success_data(api_client.list_ledger_entries(FM, params))


def shows_for(reservation_id, course_phase=None):
    params = {"reservation_id": reservation_id}
    if course_phase:
        params["course_phase"] = course_phase
    return get_success_data(api_client.list_shows(HOST, params))


def seatings_for(table_id=None, reservation_id=None, status=None):
    params = {}
    if table_id:
        params["table_id"] = table_id
    if reservation_id:
        params["reservation_id"] = reservation_id
    if status:
        params["status"] = status
    return get_success_data(api_client.list_seatings(FM, params))


def mint_party_credit(scenario, party_id, tier_code, table_id, party_size=4,
                      at_instant=None):
    """Seat a booking, then void its seat surcharge so the party holds reusable credit.

    Returns (credit_before, credit_after, surcharge_amount_cents).
    """
    if at_instant:
        set_clock(at_instant)
    before = get_success_data(api_client.get_party(party_id, HOST))["loyalty_credit_cents"]
    seafood = book_hold_seat(scenario, party_id, tier_code, table_id,
                             party_size=party_size)
    entries = ledger_entries(scenario["venue"]["id"], seafood["reservation"]["id"],
                             "SEAT_SURCHARGE")
    assert len(entries) == 1, f"Setup failed: expected 1 SEAT_SURCHARGE row, got {len(entries)}"
    surcharge = entries[0]
    get_success_data(api_client.void_ledger_entry(surcharge["id"], HOST))
    after = get_success_data(api_client.get_party(party_id, HOST))["loyalty_credit_cents"]
    return before, after, surcharge["amount_cents"], seafood


def read_venue(scenario):
    return get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))


def read_party(party_id):
    return get_success_data(api_client.get_party(party_id, HOST))


def read_reservation(reservation_id):
    return get_success_data(api_client.get_reservation(reservation_id, HOST))