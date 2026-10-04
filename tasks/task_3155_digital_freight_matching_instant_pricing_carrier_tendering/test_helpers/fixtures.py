"""Composite setup helpers.

Every helper builds its preconditions from scratch with PRD-declared endpoints
only: the harness restarts the server before every test, so nothing carries
over between tests.  Setup calls use the lenient validator so a broken
precondition surfaces as a clear setup failure rather than a confusing
assertion failure.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    attest_insurance_payload,
    create_booking_payload,
    create_carrier_payload,
    create_claim_payload,
    create_equipment_payload,
    create_facility_payload,
    create_lane_contract_payload,
    create_load_payload,
    create_shipper_payload,
    create_tracking_ping_payload,
)
from .test_users import (
    make_carrier_headers,
    make_claims_adjuster_headers,
    make_compliance_reviewer_headers,
    make_platform_admin_headers,
    make_shipper_headers,
)

# --------------------------------------------------------------------------
# Scenario instants
# --------------------------------------------------------------------------
BASE_CLOCK = "2026-09-20T00:00:00Z"

WINDOW_A = ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
WINDOW_B = ("2026-10-06T08:00:00Z", "2026-10-06T12:00:00Z")
WINDOW_C = ("2026-10-07T08:00:00Z", "2026-10-07T12:00:00Z")
DEADLINE_A = "2026-10-07T18:00:00Z"
DEADLINE_B = "2026-10-08T18:00:00Z"
DEADLINE_C = "2026-10-09T18:00:00Z"

# The canonical priced load: TX>CA, DRY_VAN, BALANCED, 40,000 lb, GENERAL,
# 1,200 effective miles, tendered in the 06:00-14:59 band.
FLAT_LANE_RATE_CENTS = 372240


def _ok(response, what):
    data = get_success_data(response)
    assert data is not None, (
        f"setup failed: {what} returned {response.status_code} {response.text}"
    )
    return data


# ==========================================================================
# Single-call wrappers
# ==========================================================================
def set_clock(current_utc):
    return _ok(api.set_current_utc(current_utc, make_platform_admin_headers()), "set clock")


def run_sweep():
    return _ok(api.run_sweep(make_platform_admin_headers()), "run sweep")


def create_shipper(**overrides):
    return _ok(api.create_shipper(create_shipper_payload(**overrides),
                                  make_platform_admin_headers()), "create shipper")


def create_facility(state_code="TX", **overrides):
    return _ok(api.create_facility(create_facility_payload(state_code, **overrides),
                                   make_platform_admin_headers()), "create facility")


def verify_authority(carrier_id):
    return _ok(api.verify_authority(carrier_id, make_compliance_reviewer_headers()),
               "verify authority")


def attest_insurance(carrier_id, **overrides):
    return _ok(api.attest_insurance(carrier_id, attest_insurance_payload(**overrides),
                                    make_compliance_reviewer_headers()), "attest insurance")


def verify_safety(carrier_id, safety_score=72.0):
    return _ok(api.verify_safety(carrier_id, {"safety_score": safety_score},
                                 make_compliance_reviewer_headers()), "verify safety")


_DOCKET_SERIAL = [0]


def create_equipment(carrier_id, unit_number, **overrides):
    return _ok(api.create_equipment(
        create_equipment_payload(carrier_id, unit_number, **overrides),
        make_carrier_headers(carrier_id)), "create equipment")


def create_carrier(mc_number=None, **overrides):
    # The MC number is unique across the whole platform (PRD 3.1).  Vary the
    # docket per enrollment so tests that build more than one carrier of their
    # own get distinct, valid rows; callers that need a specific docket pass it.
    if mc_number is None:
        _DOCKET_SERIAL[0] += 1
        mc_number = f"9{_DOCKET_SERIAL[0]:05d}"
    return _ok(api.create_carrier(create_carrier_payload(mc_number, **overrides),
                                  make_compliance_reviewer_headers()), "create carrier")


def create_lane_contract(shipper_id, origin_facility_id, destination_facility_id, **overrides):
    return _ok(api.create_lane_contract(
        create_lane_contract_payload(shipper_id, origin_facility_id, destination_facility_id,
                                     **overrides),
        make_shipper_headers(shipper_id)), "create lane contract")


def activate_lane_contract(shipper_id, contract_id):
    return _ok(api.activate_lane_contract(contract_id, make_shipper_headers(shipper_id)),
               "activate lane contract")


def create_load(shipper_id, origin_facility_id, destination_facility_id, **overrides):
    return _ok(api.create_load(
        create_load_payload(shipper_id, origin_facility_id, destination_facility_id, **overrides),
        make_shipper_headers(shipper_id)), "create load")


def post_load(shipper_id, load_id):
    return _ok(api.post_load(load_id, make_shipper_headers(shipper_id)), "post load")


def newest_quote(shipper_id, load_id):
    quotes = get_success_data(
        api.list_load_rate_quotes(load_id, make_shipper_headers(shipper_id)))
    assert quotes, f"setup failed: load {load_id} has no quote"
    return quotes[-1]


def book_load(shipper_id, carrier_id, load, quote, equipment, expected_load_version=None):
    if expected_load_version is None:
        expected_load_version = load["version"]
    return _ok(api.create_booking(
        create_booking_payload(load["id"], carrier_id, quote["id"], equipment["id"],
                               expected_load_version),
        make_carrier_headers(carrier_id)), "create booking")


def post_and_quote(shipper_id, board=None, **load_kwargs):
    if board is not None:
        load_kwargs.setdefault("origin_facility_id", board["origin_facility_id"])
        load_kwargs.setdefault("destination_facility_id", board["destination_facility_id"])
    load = create_load(shipper_id, load_kwargs.pop("origin_facility_id"),
                       load_kwargs.pop("destination_facility_id"), **load_kwargs)
    load = post_load(shipper_id, load["id"])
    return load, newest_quote(shipper_id, load["id"])


def post_book(shipper_id, carrier_id, equipment, board=None, **load_kwargs):
    if board is not None:
        # Every scenario in this suite runs on one TX>CA board; let callers name
        # the board instead of repeating its two facility ids.
        load_kwargs.setdefault("origin_facility_id", board["origin_facility_id"])
        load_kwargs.setdefault("destination_facility_id", board["destination_facility_id"])
    load, quote = post_and_quote(shipper_id, **load_kwargs)
    booking = book_load(shipper_id, carrier_id, load, quote, equipment)
    return load, quote, booking


def send_ping(load_id, carrier_id, sequence, reported_status, location_code, eta_utc=None):
    payload = create_tracking_ping_payload(carrier_id, sequence, reported_status, location_code)
    if eta_utc is not None:
        payload["eta_utc"] = eta_utc
    return api.report_tracking_ping(load_id, payload, make_carrier_headers(carrier_id))


def send_ping_ok(load_id, carrier_id, sequence, reported_status, location_code, eta_utc=None):
    response = send_ping(load_id, carrier_id, sequence, reported_status, location_code, eta_utc)
    assert response.status_code < 300, (
        f"setup failed: ping {sequence} {reported_status} returned "
        f"{response.status_code} {response.text}"
    )
    return get_success_data(response)


def read_load(shipper_id, load_id):
    return _ok(api.get_load(load_id, make_shipper_headers(shipper_id)), "read load")


def read_carrier(carrier_id):
    return _ok(api.get_carrier(carrier_id, make_carrier_headers(carrier_id)), "read carrier")


def read_carrier_as_admin(carrier_id):
    return _ok(api.get_carrier(carrier_id, make_platform_admin_headers()), "read carrier")


def read_facility(facility_id):
    return _ok(api.get_facility(facility_id, make_platform_admin_headers()), "read facility")


def read_shipper(shipper_id):
    return _ok(api.get_shipper(shipper_id, make_shipper_headers(shipper_id)), "read shipper")


def read_settlement(settlement_id):
    return _ok(api.get_settlement(settlement_id, make_platform_admin_headers()), "read settlement")


def read_quote(shipper_id, quote_id):
    return _ok(api.get_rate_quote(quote_id, make_shipper_headers(shipper_id)), "read quote")


def list_settlements(**params):
    return get_success_data(api.list_settlements(make_platform_admin_headers(), params))


def list_detention_events_for(carrier_id, **params):
    return get_success_data(
        api.list_detention_events(make_carrier_headers(carrier_id), params or None))


def list_load_detention(shipper_id, load_id):
    return get_success_data(
        api.list_load_detention_events(load_id, make_shipper_headers(shipper_id)))


def list_load_appointments(shipper_id, load_id):
    return get_success_data(
        api.list_load_appointments(load_id, make_shipper_headers(shipper_id)))


def list_load_pings(shipper_id, load_id):
    return get_success_data(api.list_load_tracking_pings(load_id, make_shipper_headers(shipper_id)))


def list_load_status_events(shipper_id, load_id):
    return get_success_data(api.list_load_status_events(load_id, make_shipper_headers(shipper_id)))


def list_load_quotes(shipper_id, load_id):
    return get_success_data(api.list_load_rate_quotes(load_id, make_shipper_headers(shipper_id)))


def list_load_settlements(load_id):
    return get_success_data(api.list_load_settlements(load_id, make_platform_admin_headers()))


def shift(iso_instant, minutes=0, days=0, hours=0):
    moment = datetime.fromisoformat(iso_instant.replace("Z", "+00:00"))
    moment += timedelta(minutes=minutes, days=days, hours=hours)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso3(value):
    """Normalise any ISO 8601 UTC instant to the PRD's three-fractional-digit form.

    PRD 2.5 fixes the transport form at three fractional digits, so a value the
    server returns as ``...T08:00:00.000Z`` denotes the same instant the test's
    fixture wrote as ``...T08:00:00Z``.
    """
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ==========================================================================
# Lifecycle walkers
# ==========================================================================
def drive_load(load_id, carrier_id, en_route, at_pickup, in_transit, at_delivery,
               delivered, eta_utc=None, location_prefix="9vg8"):
    """Walk a BOOKED load through the full five-rung ping ladder.

    Every instant is supplied so a caller can pin an exact dwell at the pickup.
    """
    rungs = [
        (1, "EN_ROUTE_PICKUP", en_route),
        (2, "AT_PICKUP", at_pickup),
        (3, "IN_TRANSIT", in_transit),
        (4, "AT_DELIVERY", at_delivery),
        (5, "DELIVERED", delivered),
    ]
    for sequence, status, instant in rungs:
        set_clock(instant)
        eta = eta_utc if status in ("EN_ROUTE_PICKUP", "IN_TRANSIT") else (
            eta_utc if status == "AT_DELIVERY" else None)
        send_ping_ok(load_id, carrier_id, sequence, status,
                     f"{location_prefix}{sequence}", eta)
    return load_id


def drive_clean(load_id, carrier_id, pickup_window=WINDOW_A, delivery_deadline=DEADLINE_A,
                pickup_dwell_minutes=30, leg_minutes=180, pre_minutes=30):
    """A tidy delivery: arrival inside the pickup window, no breach, no detention."""
    pickup_start, _ = pickup_window
    at_pickup = shift(pickup_start, minutes=pre_minutes)
    in_transit = shift(at_pickup, minutes=pickup_dwell_minutes)
    at_delivery = shift(in_transit, minutes=leg_minutes)
    delivered = shift(at_delivery, minutes=30)
    eta = shift(delivered, minutes=-60)
    return drive_load(load_id, carrier_id, shift(pickup_start, minutes=pre_minutes - 10),
                      at_pickup, in_transit, at_delivery, delivered, eta_utc=eta)


def drive_with_pickup_dwell(load_id, carrier_id, pickup_window=WINDOW_A,
                            dwell_minutes=185, deadline=DEADLINE_A):
    """Walk a load to `IN_TRANSIT` with a pickup dwell of exactly `dwell_minutes`.

    Departure closes the pickup detention event and leaves it visible on the
    load; stopping there keeps the load's detention trail at that single event.
    """
    pickup_start, _ = pickup_window
    at_pickup = pickup_start
    in_transit = shift(at_pickup, minutes=dwell_minutes)
    rungs = [
        (1, "EN_ROUTE_PICKUP", shift(at_pickup, minutes=-30)),
        (2, "AT_PICKUP", at_pickup),
        (3, "IN_TRANSIT", in_transit),
    ]
    for sequence, status, instant in rungs:
        set_clock(instant)
        send_ping_ok(load_id, carrier_id, sequence, status, f"9vg8{sequence}")
    return load_id


# ==========================================================================
# Tier 1/2: entity setup
# ==========================================================================
# Each enrollment rung demands at least one AVAILABLE unit on file (PRD 3.1:
# "the carrier must already have at least one equipment unit on file in
# `AVAILABLE` status").  Tests routinely build a board with zero spare units
# because they only need an identity, so the shared board helper files one
# roster unit that is not part of the returned `equipment` list.
def _roster_unit(carrier_id, equipment_type="DRY_VAN"):
    """File one unattached unit so the safety rung can be cleared."""
    return create_equipment(carrier_id, "ROSTER-01", equipment_type=equipment_type)


def setup_board(units=1, shipper_overrides=None, carrier_overrides=None,
                origin_overrides=None, destination_overrides=None, mc_number="100001",
                equipment_type="DRY_VAN"):
    """Shipper + TX and CA facilities + one VERIFIED carrier with `units` units."""
    set_clock(BASE_CLOCK)
    shipper = create_shipper(**(shipper_overrides or {}))
    origin = create_facility("TX", **(origin_overrides or {}))
    destination = create_facility("CA", **(destination_overrides or {}))
    carrier = create_carrier(mc_number=mc_number, **(carrier_overrides or {}))
    if units == 0:
        _roster_unit(carrier["id"], equipment_type)
    equipment = [
        create_equipment(carrier["id"], f"TR-90{i + 1:02d}", equipment_type=equipment_type)
        for i in range(units)
    ]
    verify_authority(carrier["id"])
    # The insurance attestation is what records the certificate, so honour any
    # insurance overrides the caller passed when onboarding the carrier.
    attest = {key: carrier_overrides[key]
              for key in ("insurance_expires_at", "insurance_liability_limit_cents",
                          "cargo_coverage_limit_cents", "certificate_reference")
              if carrier_overrides and key in carrier_overrides}
    attest_insurance(carrier["id"], **attest)
    carrier = verify_safety(carrier["id"])
    return {
        "shipper": shipper, "origin": origin, "destination": destination,
        "carrier": carrier, "equipment": equipment,
        "shipper_id": shipper["id"], "carrier_id": carrier["id"],
        "origin_facility_id": origin["id"], "destination_facility_id": destination["id"],
    }


def setup_plain_carrier(units=0, mc_number=None):
    """A freshly onboarded PENDING carrier, optionally with units on file."""
    carrier = create_carrier(mc_number=mc_number)
    for i in range(units):
        create_equipment(carrier["id"], f"TR-92{i + 1:02d}")
    return carrier


def add_facility(board, state_code, **overrides):
    facility = create_facility(state_code, **overrides)
    board[f"facility_{state_code}"] = facility
    return facility


def add_additional_carrier(board, mc_number="100777", units=1):
    carrier = create_carrier(mc_number=mc_number)
    equipment = [create_equipment(carrier["id"], f"ALT-{mc_number}-{i + 1}")
                 for i in range(units)]
    if units == 0:
        _roster_unit(carrier["id"])
    verify_authority(carrier["id"])
    attest_insurance(carrier["id"])
    carrier = verify_safety(carrier["id"])
    board.setdefault("extra_carriers", []).append(carrier)
    board.setdefault("extra_equipment", []).append(equipment)
    return carrier, equipment


# ==========================================================================
# Tier 3: full lifecycle shortcuts
# ==========================================================================
def setup_delivered_load(dwell_minutes=30, shipper_overrides=None,
                         carrier_overrides=None, **load_kwargs):
    """Booked load driven to DELIVERED with an ACCRUED settlement."""
    board = setup_board(units=1, shipper_overrides=shipper_overrides,
                        carrier_overrides=carrier_overrides)
    load, quote, booking = post_book(
        board["shipper_id"], board["carrier_id"], board["equipment"][0], board=board,
        **load_kwargs)
    drive_clean(load["id"], board["carrier_id"], pickup_dwell_minutes=dwell_minutes)
    board.update({
        "load": read_load(board["shipper_id"], load["id"]),
        "quote": quote, "booking": booking,
        "settlement": list_load_settlements(load["id"])[0],
    })
    return board


def setup_invoiced_load(dwell_minutes=30, shipper_overrides=None,
                        carrier_overrides=None, **load_kwargs):
    """Delivered load with its settlement advanced to READY."""
    board = setup_delivered_load(dwell_minutes=dwell_minutes,
                                 shipper_overrides=shipper_overrides,
                                 carrier_overrides=carrier_overrides, **load_kwargs)
    _ok(api.invoice_booking(board["booking"]["id"], make_shipper_headers(board["shipper_id"])),
        "invoice booking")
    board["settlement"] = read_settlement(board["settlement"]["id"])
    board["load"] = read_load(board["shipper_id"], board["load"]["id"])
    return board


def setup_paid_load(dwell_minutes=30, shipper_overrides=None,
                    carrier_overrides=None, **load_kwargs):
    """Invoiced load whose settlement has been paid on terms."""
    board = setup_invoiced_load(dwell_minutes=dwell_minutes,
                                shipper_overrides=shipper_overrides,
                                carrier_overrides=carrier_overrides, **load_kwargs)
    settlement = board["settlement"]
    set_clock(settlement["payout_due_at"])
    _ok(api.payout_settlement(
        settlement["id"],
        {"payout_mode": "TERMS", "expected_settlement_version": settlement["version"]},
        make_platform_admin_headers()), "terms payout")
    board["settlement"] = read_settlement(settlement["id"])
    board["load"] = read_load(board["shipper_id"], board["load"]["id"])
    return board


def file_claim(board, claimed_amount_cents, commodity=None):
    carrier = read_carrier(board["carrier_id"])
    payload = create_claim_payload(board["load"]["id"], board["carrier_id"],
                                   claimed_amount_cents, carrier["version"])
    return _ok(api.file_claim(payload, make_shipper_headers(board["shipper_id"])), "file claim")


def review_claim(claim_id):
    return _ok(api.review_claim(claim_id, make_claims_adjuster_headers()), "review claim")


def setup_ready_settlement_with_reviewed_claim(claimed_amount_cents=150000,
                                               declared_cargo_value_cents=5000000,
                                               commodity="GENERAL", **load_kwargs):
    """Invoiced load (settlement READY) plus a reviewed claim on the same load."""
    board = setup_invoiced_load(declared_cargo_value_cents=declared_cargo_value_cents,
                                commodity=commodity, **load_kwargs)
    claim = file_claim(board, claimed_amount_cents)
    board["claim"] = review_claim(claim["id"])
    return board


def add_paid_history(board, count, shipper=None, origin=None, destination=None,
                     unit_prefix="HIST"):
    """Drive `count` extra loads to a fully PAID settlement on board's carrier.

    Each history load gets its own facility pair and its own equipment unit, so
    no dock or equipment window contention can perturb the fixture.
    """
    shipper = shipper or board["shipper"]
    paid = []
    for index in range(count):
        day = 1 + (index // 4)
        hour = (index % 4) + 1
        window_start = f"2026-10-{day:02d}T{hour:02d}:00:00Z"
        window_end = f"2026-10-{day:02d}T{hour:02d}:30:00Z"
        history_origin = create_facility("TX", dock_capacity=10)
        history_destination = create_facility("CA", dock_capacity=10)
        unit = create_equipment(board["carrier_id"], f"{unit_prefix}-{index + 1}")
        load = create_load(shipper["id"], history_origin["id"], history_destination["id"],
                           pickup_window_start=window_start, pickup_window_end=window_end,
                           delivery_deadline="2026-12-31T18:00:00Z")
        load = post_load(shipper["id"], load["id"])
        quote = newest_quote(shipper["id"], load["id"])
        booking = book_load(shipper["id"], board["carrier_id"], load, quote, unit)
        drive_clean(load["id"], board["carrier_id"],
                    pickup_window=(window_start, window_end),
                    delivery_deadline="2026-12-31T18:00:00Z")
        _ok(api.invoice_booking(booking["id"], make_shipper_headers(shipper["id"])),
            "history invoice")
        settlement = read_settlement(list_load_settlements(load["id"])[0]["id"])
        set_clock(settlement["payout_due_at"])
        _ok(api.payout_settlement(
            settlement["id"],
            {"payout_mode": "TERMS", "expected_settlement_version": settlement["version"]},
            make_platform_admin_headers()), "history payout")
        paid.append(read_settlement(settlement["id"]))
    return paid


# ==========================================================================
# Tier 4/5: scenario-targeted setups
# ==========================================================================
def setup_spot_vs_contract_scenario():
    """One SPOT and one CONTRACT load with byte-identical pricing inputs."""
    board = setup_board(units=1)
    contract = create_lane_contract(
        board["shipper_id"], board["origin_facility_id"], board["destination_facility_id"],
        committed_rate_cents=215000, committed_weekly_volume=6,
        contract_carrier_ids=[board["carrier_id"]])
    activate_lane_contract(board["shipper_id"], contract["id"])
    common = dict(equipment_type="DRY_VAN", commodity="GENERAL", weight_lbs=40000,
                  declared_cargo_value_cents=5000000, distance_miles=1200,
                  pickup_window_start=WINDOW_A[0], pickup_window_end=WINDOW_A[1],
                  delivery_deadline=DEADLINE_A, market_band="BALANCED")
    spot = create_load(board["shipper_id"], board["origin_facility_id"],
                       board["destination_facility_id"], pricing_mode="SPOT", **common)
    contract_load = create_load(board["shipper_id"], board["origin_facility_id"],
                                board["destination_facility_id"], pricing_mode="CONTRACT",
                                lane_contract_id=contract["id"], **common)
    board.update({"contract": contract, "spot_load": spot, "contract_load": contract_load})
    return board


def setup_lock_window_scenario():
    """Two identical 389-mile loads; one booked inside the lock window, one after it."""
    board = setup_board(units=2)
    set_clock("2026-10-05T00:00:00Z")
    common = dict(equipment_type="DRY_VAN", commodity="GENERAL", weight_lbs=44000,
                  declared_cargo_value_cents=5000000, distance_miles=389,
                  pickup_window_start="2026-10-05T03:00:00Z",
                  pickup_window_end="2026-10-05T07:00:00Z",
                  delivery_deadline=DEADLINE_A, market_band="BALANCED")
    locked = create_load(board["shipper_id"], board["origin_facility_id"],
                         board["destination_facility_id"], **common)
    live = create_load(board["shipper_id"], board["origin_facility_id"],
                       board["destination_facility_id"], **common)
    locked = post_load(board["shipper_id"], locked["id"])
    live = post_load(board["shipper_id"], live["id"])
    locked_quote = newest_quote(board["shipper_id"], locked["id"])
    live_quote = newest_quote(board["shipper_id"], live["id"])
    set_clock("2026-10-05T01:00:00Z")
    locked_booking = book_load(board["shipper_id"], board["carrier_id"], locked,
                               locked_quote, board["equipment"][0])
    set_clock("2026-10-05T01:01:00Z")
    board.update({"locked_load": read_load(board["shipper_id"], locked["id"]),
                  "live_load": live, "locked_quote": locked_quote,
                  "live_quote": live_quote, "locked_booking": locked_booking})
    return board


def setup_detention_boundary_scenario():
    """Three loads on the same facility whose pickup dwells are 185, 120 and 121 minutes."""
    board = setup_board(units=3)
    windows = {"a": (WINDOW_A, DEADLINE_A), "b": (WINDOW_B, DEADLINE_B),
               "c": (WINDOW_C, DEADLINE_C)}
    dwells = {"a": 185, "b": 120, "c": 121}
    loads = {}
    for key in ("a", "b", "c"):
        window, deadline = windows[key]
        load, quote, booking = post_book(
            board["shipper_id"], board["carrier_id"],
            board["equipment"][{"a": 0, "b": 1, "c": 2}[key]], board=board,
            pickup_window_start=window[0], pickup_window_end=window[1],
            delivery_deadline=deadline)
        loads[key] = {"load": load, "quote": quote, "booking": booking}
    for key in ("a", "b", "c"):
        window, _ = windows[key]
        drive_with_pickup_dwell(loads[key]["load"]["id"], board["carrier_id"],
                                pickup_window=window, dwell_minutes=dwells[key])
        loads[key]["load"] = read_load(board["shipper_id"], loads[key]["load"]["id"])
    board["loads"] = loads
    return board


def setup_dock_selector_scenario():
    """Three posted loads against one capacity-3 facility.

    The second window's buffered span collides with the first on position 1, so
    the selector must fall to position 2; the third window clears both buffered
    spans and must therefore take position 1 again.
    """
    board = setup_board(units=1, origin_overrides={"dock_capacity": 3})
    set_clock("2026-10-05T00:00:00Z")
    windows = [("2026-10-05T08:00:00Z", "2026-10-05T09:00:00Z"),
               ("2026-10-05T09:00:00Z", "2026-10-05T10:00:00Z"),
               ("2026-10-05T14:00:00Z", "2026-10-05T15:00:00Z")]
    loads = []
    for index, window in enumerate(windows):
        load, quote = post_and_quote(
            board["shipper_id"], origin_facility_id=board["origin_facility_id"],
            board=board,
            pickup_window_start=window[0], pickup_window_end=window[1],
            delivery_deadline=DEADLINE_A)
        loads.append({"load": load, "quote": quote, "unit_index": index, "window": window})
    board["slot_loads"] = loads
    return board


def setup_dock_capacity_scenario(dock_capacity=3, load_count=4):
    """A saturated facility: `dock_capacity` live bookings plus one spare load.

    Every window falls on the clock's current logical date so the committed
    count actually accumulates, and the spare load's window is buffered-clear on
    the lowest position so only the capacity guard can reject it.
    """
    board = setup_board(units=load_count, origin_overrides={"dock_capacity": dock_capacity})
    set_clock("2026-10-05T00:00:00Z")
    windows = [
        ("2026-10-05T08:00:00Z", "2026-10-05T09:00:00Z"),
        ("2026-10-05T11:00:00Z", "2026-10-05T12:00:00Z"),
        ("2026-10-05T14:00:00Z", "2026-10-05T15:00:00Z"),
        ("2026-10-05T19:00:00Z", "2026-10-05T20:00:00Z"),
    ]
    loads = []
    for index in range(load_count):
        window = windows[index]
        load, quote = post_and_quote(
            board["shipper_id"], origin_facility_id=board["origin_facility_id"],
            board=board,
            pickup_window_start=window[0], pickup_window_end=window[1],
            delivery_deadline=DEADLINE_A)
        loads.append({"load": load, "quote": quote, "window": window})
    board["capacity_loads"] = loads
    board["dock_capacity"] = dock_capacity
    return board


def setup_dock_buffer_scenario(dock_capacity=1):
    """One booked anchor slot at 08:00-08:30 plus two spare posted loads whose
    windows sit three hours and five hours after the anchor."""
    board = setup_board(units=1, origin_overrides={"dock_capacity": dock_capacity})
    set_clock("2026-10-05T00:00:00Z")
    anchor_window = ("2026-10-05T08:00:00Z", "2026-10-05T08:30:00Z")
    gap3_window = ("2026-10-05T11:00:00Z", "2026-10-05T11:30:00Z")
    gap5_window = ("2026-10-05T13:00:00Z", "2026-10-05T13:30:00Z")
    loads = {}
    for key, window in (("anchor", anchor_window), ("gap3", gap3_window), ("gap5", gap5_window)):
        load, quote = post_and_quote(
            board["shipper_id"], origin_facility_id=board["origin_facility_id"],
            board=board,
            pickup_window_start=window[0], pickup_window_end=window[1],
            delivery_deadline=DEADLINE_A)
        loads[key] = {"load": load, "quote": quote, "window": window}
    booking = book_load(board["shipper_id"], board["carrier_id"], loads["anchor"]["load"],
                        loads["anchor"]["quote"], board["equipment"][0])
    loads["anchor"]["booking"] = booking
    board["buffer_loads"] = loads
    return board


def setup_equipment_window_scenario():
    """One unit and four loads whose windows tile, tile again, then overlap by a
    single minute and finally clear the failed attempt."""
    board = setup_board(units=1)
    set_clock("2026-10-05T00:00:00Z")
    windows = [
        ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"),
        ("2026-10-05T12:00:00Z", "2026-10-05T16:00:00Z"),
        ("2026-10-05T15:59:00Z", "2026-10-05T19:00:00Z"),
        ("2026-10-06T08:00:00Z", "2026-10-06T12:00:00Z"),
    ]
    loads = []
    for window in windows:
        load, quote = post_and_quote(
            board["shipper_id"], origin_facility_id=board["origin_facility_id"],
            board=board,
            pickup_window_start=window[0], pickup_window_end=window[1],
            delivery_deadline=DEADLINE_C)
        loads.append({"load": load, "quote": quote, "window": window})
    board["window_loads"] = loads
    return board


def setup_two_quotes_on_one_load(window=None, repost=True, **load_kwargs):
    """A TX>GA posted load carrying a SUPERSEDED quote and a fresh ACTIVE one.

    The lane is TX>GA over 900 miles so the indexed quote figures (325,710 cents
    initially, 381,150 cents once repriced TIGHT) hold exactly.  With
    ``repost=False`` the load keeps a single ACTIVE quote whose deadline is the
    creation instant plus the quote's 24-hour TTL.
    """
    board = setup_board(units=1)
    ga_facility = add_facility(board, "GA")
    window = window or ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
    load, first_quote = post_and_quote(
        board["shipper_id"], board=board,
        destination_facility_id=ga_facility["id"],
        distance_miles=900,
        pickup_window_start=window[0], pickup_window_end=window[1],
        delivery_deadline=DEADLINE_A)
    if not repost:
        quotes = list_load_quotes(board["shipper_id"], load["id"])
        board.update({"load": load, "quotes": quotes,
                      "first_quote": first_quote, "active_quote": quotes[-1]})
        return board
    set_clock(shift(window[0], hours=-24))
    run_sweep()
    load = read_load(board["shipper_id"], load["id"])
    assert load["status"] == "UNCOVERED", "setup failed: the load was not swept to UNCOVERED"
    reposted = api.repost_load(load["id"], load["shipper_version"],
                               make_shipper_headers(board["shipper_id"]))
    assert reposted.status_code < 300, f"setup failed: repost returned {reposted.text}"
    quotes = list_load_quotes(board["shipper_id"], load["id"])
    board.update({"load": reposted.json()["data"], "quotes": quotes,
                  "first_quote": first_quote, "active_quote": quotes[-1]})
    return board


def setup_sweep_scenario():
    """One overdue appointment, one uncovered load and one expired certificate.

    The booked load's window has already closed by more than the 60-minute grace
    at the sweep instant, while the open load's window still sits inside the
    24-hour coverage horizon, so exactly one appointment and one load are swept.
    """
    board = setup_board(units=2, carrier_overrides={"insurance_expires_at": "2026-10-10T00:00:00Z"})
    booked = post_book(board["shipper_id"], board["carrier_id"], board["equipment"][0],
                       board=board,
                       pickup_window_start="2026-09-25T08:00:00Z",
                       pickup_window_end="2026-09-25T12:00:00Z",
                       delivery_deadline=DEADLINE_A)
    abandoned = post_and_quote(board["shipper_id"],
                               origin_facility_id=board["origin_facility_id"],
                               board=board,
                               pickup_window_start="2026-10-05T08:00:00Z",
                               pickup_window_end="2026-10-05T12:00:00Z",
                               delivery_deadline=DEADLINE_C)
    board.update({"booked_load": booked[0], "booked_quote": booked[1],
                  "booked_booking": booked[2], "abandoned_load": abandoned[0],
                  "abandoned_quote": abandoned[1]})
    return board