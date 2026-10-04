"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup failures
produce clear "setup failed" errors rather than confusing assertion failures.

All fixtures build state from scratch per test: the harness restarts the API
server before every test, so no data survives across tests.
"""

import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, CLOCK_STARTUP_DEFAULT
from .factories import (
    create_station_payload,
    register_driver_payload,
    create_vehicle_payload,
    create_block_payload,
    create_offer_payload,
)
from .test_users import TEST_USERS, make_driver_headers


# ---------------------------------------------------------------------------
# Convenient header aliases (opaque roles)
# ---------------------------------------------------------------------------
ADMIN = TEST_USERS["platform_admin_headers"]
STATION_OPS = TEST_USERS["station_ops_headers"]
REVIEWER = TEST_USERS["appeals_reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Uniqueness counters (identifiers like VIN/email must be unique per test)
# ---------------------------------------------------------------------------
_uid_counter = itertools.count(1)


def _uid() -> int:
    return next(_uid_counter)


# ---------------------------------------------------------------------------
# Tier 0 — primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_STARTUP_DEFAULT):
    """Move the logical clock. Every time-derived rule reads this instant."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


def create_station(**overrides) -> dict:
    return get_success_data(
        api_client.create_station(create_station_payload(**overrides), ADMIN)
    )


def get_station(station_id: str) -> dict:
    return get_success_data(api_client.get_station(station_id, ADMIN))


def run_surge_cycle(station_id: str, expected_station_version: int) -> dict:
    return get_success_data(
        api_client.run_surge_cycle(
            station_id, {"expected_station_version": expected_station_version}, STATION_OPS
        )
    )


def register_driver(**overrides) -> dict:
    overrides.setdefault("email", f"driver.{_uid()}@example.com")
    return get_success_data(
        api_client.register_driver(register_driver_payload(**overrides), ANON)
    )


def get_driver(driver_id: str) -> dict:
    return get_success_data(api_client.get_driver(driver_id, ADMIN))


def latest_screening_id(driver_id: str) -> str:
    data, _meta = _list_paginated(
        api_client.list_driver_screenings(driver_id, ADMIN)
    )
    assert data, "a registered driver must have at least one screening"
    return data[0]["id"]


def _list_paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(resp)


def begin_screening_review(screening_id: str) -> dict:
    return get_success_data(api_client.begin_screening_review(screening_id, ADMIN))


def decide_screening(screening_id: str, decision: str, failure_reason=None) -> dict:
    payload = {"decision": decision}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    return get_success_data(api_client.decide_screening(screening_id, payload, ADMIN))


def clear_screening(screening_id: str) -> dict:
    begin_screening_review(screening_id)
    return decide_screening(screening_id, "CLEARED")


def create_vehicle(driver_id: str, **overrides) -> dict:
    overrides.setdefault("vin", f"VIN-AUTO-{_uid()}")
    headers = make_driver_headers(driver_id)
    return get_success_data(
        api_client.create_vehicle(driver_id, create_vehicle_payload(**overrides), headers)
    )


def get_vehicle(vehicle_id: str) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, ADMIN))


def attest_insurance(vehicle_id: str, driver_id: str, expires_on: str = None) -> dict:
    headers = make_driver_headers(driver_id)
    return get_success_data(
        api_client.attest_insurance(
            vehicle_id,
            {"insurance_expires_on": expires_on or TEST_DEFAULTS["INSURANCE_LONG"]},
            headers,
        )
    )


def activate_driver(driver_id: str) -> dict:
    return get_success_data(api_client.activate_driver(driver_id, ADMIN))


def deactivate_driver(driver_id: str, reason: str = "policy violation") -> dict:
    return get_success_data(
        api_client.deactivate_driver(driver_id, {"reason": reason}, ADMIN)
    )


def create_block(station_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_block(station_id, create_block_payload(**overrides), STATION_OPS)
    )


def publish_block(block_id: str) -> dict:
    return get_success_data(api_client.publish_block(block_id, STATION_OPS))


def get_block(block_id: str) -> dict:
    return get_success_data(api_client.get_block(block_id, STATION_OPS))


def create_offer(block_id: str, driver_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_offer(
            block_id, create_offer_payload(driver_id, **overrides), STATION_OPS
        )
    )


def get_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_offer(offer_id, STATION_OPS))


def accept_block(block_id: str, driver_id: str, vehicle_id: str) -> dict:
    return get_success_data(
        api_client.accept_block(
            block_id, {"vehicle_id": vehicle_id}, make_driver_headers(driver_id)
        )
    )


def accept_offer(offer_id: str, driver_id: str, vehicle_id: str) -> dict:
    return get_success_data(
        api_client.accept_offer(
            offer_id, {"vehicle_id": vehicle_id}, make_driver_headers(driver_id)
        )
    )


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, STATION_OPS))


def check_in(assignment_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.check_in_assignment(assignment_id, make_driver_headers(driver_id))
    )


def load_packages(assignment_id: str, packages: list) -> dict:
    return get_success_data(
        api_client.load_packages(assignment_id, {"packages": packages}, STATION_OPS)
    )


def depart(assignment_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.depart_assignment(assignment_id, make_driver_headers(driver_id))
    )


def forfeit(assignment_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.forfeit_assignment(assignment_id, {}, make_driver_headers(driver_id))
    )


def complete(assignment_id: str) -> dict:
    return get_success_data(api_client.complete_assignment(assignment_id, STATION_OPS))


def list_assignment_packages(assignment_id: str) -> list:
    data, _meta = _list_paginated(
        api_client.list_assignment_packages(assignment_id, STATION_OPS)
    )
    return data


def deliver_package(package_id: str, driver_id: str, photo_url: str, gps: bool) -> dict:
    return get_success_data(
        api_client.deliver_package(
            package_id,
            {"photo_url": photo_url, "photo_gps_tagged": gps},
            make_driver_headers(driver_id),
        )
    )


def report_package_failed(package_id: str, driver_id: str, reason: str = "damaged") -> dict:
    return get_success_data(
        api_client.report_package_failed(
            package_id, {"reason": reason}, make_driver_headers(driver_id)
        )
    )


def list_driver_rating_events(driver_id: str) -> list:
    data, _meta = _list_paginated(
        api_client.list_driver_rating_events(driver_id, make_driver_headers(driver_id))
    )
    return data


def list_driver_offers(driver_id: str) -> list:
    data, _meta = _list_paginated(
        api_client.list_driver_offers(driver_id, make_driver_headers(driver_id))
    )
    return data


def list_driver_assignments(driver_id: str, params=None) -> list:
    data, _meta = _list_paginated(
        api_client.list_driver_assignments(driver_id, ADMIN, params)
    )
    return data


def submit_appeal(driver_id: str, reason: str = "incorrect deactivation") -> dict:
    return get_success_data(
        api_client.create_appeal(
            driver_id, {"reason": reason}, make_driver_headers(driver_id)
        )
    )


def submit_evidence(appeal_id: str, driver_id: str, note: str = "evidence") -> dict:
    return get_success_data(
        api_client.submit_appeal_evidence(
            appeal_id, {"evidence_note": note}, make_driver_headers(driver_id)
        )
    )


def request_evidence(appeal_id: str, note: str = "need more") -> dict:
    return get_success_data(
        api_client.request_appeal_evidence(appeal_id, {"request_note": note}, REVIEWER)
    )


def decide_appeal(appeal_id: str, decision: str, reason: str = "reviewed") -> dict:
    return get_success_data(
        api_client.decide_appeal(
            appeal_id, {"decision": decision, "decision_reason": reason}, REVIEWER
        )
    )


def settle_pay_statement(pay_statement_id: str) -> dict:
    return get_success_data(api_client.settle_pay_statement(pay_statement_id, ADMIN))


def void_pay_statement(pay_statement_id: str) -> dict:
    return get_success_data(api_client.void_pay_statement(pay_statement_id, ADMIN))


def get_assignment_pay_statement(assignment_id: str) -> dict:
    data, _meta = _list_paginated(
        api_client.get_assignment_pay_statement(assignment_id, STATION_OPS)
    )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — onboarding composites
# ---------------------------------------------------------------------------

def onboard_active_driver(
    clock: str = CLOCK_STARTUP_DEFAULT,
    insurance_expires_on: str = None,
    vehicle_class: str = "SEDAN",
    email: str = None,
    name: str = None,
):
    """Register a driver, clear the screening, register + attest one vehicle,
    and activate. Returns (driver, vehicle, screening_id)."""
    set_clock(clock)
    driver = register_driver(
        **({"email": email} if email else {}),
        **({"legal_name": name} if name else {}),
    )
    screening_id = latest_screening_id(driver["id"])
    clear_screening(screening_id)
    vehicle = create_vehicle(driver["id"], vehicle_class=vehicle_class)
    attest_insurance(
        vehicle["id"], driver["id"], insurance_expires_on or TEST_DEFAULTS["INSURANCE_LONG"]
    )
    activate_driver(driver["id"])
    return driver, vehicle, screening_id


def setup_station_and_driver(**kwargs):
    """Create a station and one fully onboarded ACTIVE driver.

    Returns (station, driver, vehicle).
    """
    set_clock(kwargs.pop("clock", CLOCK_STARTUP_DEFAULT))
    station = create_station()
    driver, vehicle, _screening = onboard_active_driver(**kwargs)
    return station, driver, vehicle


# ---------------------------------------------------------------------------
# Tier 2 — block / assignment composites
# ---------------------------------------------------------------------------

def create_published_block(station_id: str, **overrides) -> dict:
    block = create_block(station_id, **overrides)
    return publish_block(block["id"])


def accept_published_block(block_id: str, driver_id: str, vehicle_id: str) -> dict:
    """First-come accept; returns the created assignment."""
    return accept_block(block_id, driver_id, vehicle_id)


def _iso_z(s: str) -> str:
    """Normalise an ISO instant to a plain seconds-precision Z string."""
    if s.endswith("Z"):
        s = s[:-1]
    if "." in s:
        s = s.split(".", 1)[0]
    return s + "Z"


def _shift_minutes(iso: str, minutes: int) -> str:
    """Shift an ISO8601 'Z' instant by whole minutes (and seconds)."""
    from datetime import datetime, timedelta

    base = datetime.strptime(_iso_z(iso), "%Y-%m-%dT%H:%M:%SZ")
    whole_minutes = int(minutes)
    seconds = round((minutes - whole_minutes) * 60)
    shifted = base + timedelta(minutes=whole_minutes, seconds=seconds)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def drive_assignment_to_in_delivery(
    station: dict,
    driver: dict,
    vehicle: dict,
    packages: list,
    starts_at: str,
    ends_at: str,
    base_pay_cents: int = 4000,
    required_vehicle_class: str = "SEDAN",
):
    """Create + publish + accept a block, then check in, load packages and
    depart. Returns (block, assignment, package_rows)."""
    block = create_published_block(
        station["id"],
        starts_at=starts_at,
        ends_at=ends_at,
        required_vehicle_class=required_vehicle_class,
        base_pay_cents=base_pay_cents,
    )
    set_clock(starts_at)
    assignment = accept_published_block(block["id"], driver["id"], vehicle["id"])
    check_in(assignment["id"], driver["id"])
    load_packages(assignment["id"], packages)
    depart(assignment["id"], driver["id"])
    rows = list_assignment_packages(assignment["id"])
    return block, assignment, rows


def complete_block_flow(
    station: dict,
    driver: dict,
    vehicle: dict,
    starts_at: str,
    ends_at: str,
    package_specs: list,
    delivery_clock: str = None,
    base_pay_cents: int = 4000,
    required_vehicle_class: str = "SEDAN",
):
    """Run a block end to end: create, publish, accept, check in, load,
    depart, resolve every package per spec, complete.

    Each entry of package_specs is a dict with keys:
      tracking_code, billable_weight_kg, promised_by, outcome
      where outcome is "deliver" or "failed"; "deliver" entries may add
      photo_url (default a real URL), photo_gps_tagged (default True),
      deliver_at (clock instant for the deliver call) and reason (failed).

    Returns (block, assignment, pay_statement_row, package_rows).
    """
    packages = [
        {
            "tracking_code": spec["tracking_code"],
            "billable_weight_kg": spec["billable_weight_kg"],
            "promised_by": spec["promised_by"],
        }
        for spec in package_specs
    ]
    block, assignment, rows = drive_assignment_to_in_delivery(
        station,
        driver,
        vehicle,
        packages,
        starts_at,
        ends_at,
        base_pay_cents=base_pay_cents,
        required_vehicle_class=required_vehicle_class,
    )
    by_tracking = {row["tracking_code"]: row for row in rows}
    for spec in package_specs:
        row = by_tracking[spec["tracking_code"]]
        if spec.get("deliver_at"):
            set_clock(spec["deliver_at"])
        elif delivery_clock:
            set_clock(delivery_clock)
        if spec.get("outcome", "deliver") == "deliver":
            deliver_package(
                row["id"],
                driver["id"],
                spec.get("photo_url", "https://img.example/deliver.jpg"),
                spec.get("photo_gps_tagged", True),
            )
        else:
            report_package_failed(
                row["id"], driver["id"], spec.get("reason", "recipient refused")
            )
    pay_statement = complete(assignment["id"])
    return block, assignment, pay_statement, list_assignment_packages(assignment["id"])


# ---------------------------------------------------------------------------
# Tier 3 — warm-up completions that raise the driver's rating
# ---------------------------------------------------------------------------

def warmup_clean_completion(
    station: dict,
    driver: dict,
    vehicle: dict,
    starts_at: str = "2026-09-01T02:00:00Z",
    ends_at: str = "2026-09-01T04:00:00Z",
    promised_by: str = "2026-09-01T03:00:00Z",
    deliver_at: str = "2026-09-01T02:30:00Z",
    base_pay_cents: int = 4000,
    tracking_code: str = None,
):
    """One clean completion: a single 1.0kg package delivered on time with a
    compliant photo. Produces a 500-point rating event."""
    return complete_block_flow(
        station,
        driver,
        vehicle,
        starts_at,
        ends_at,
        [
            {
                "tracking_code": tracking_code or f"PW-{_uid()}",
                "billable_weight_kg": 1.0,
                "promised_by": promised_by,
                "outcome": "deliver",
                "deliver_at": deliver_at,
            }
        ],
        base_pay_cents=base_pay_cents,
    )


def setup_premier_driver(station: dict = None):
    """An ACTIVE driver at PREMIER: one clean completion leaves rating 500
    and reliability 10000.

    Returns (station, driver, vehicle).
    """
    if station is None:
        set_clock(CLOCK_STARTUP_DEFAULT)
        station = create_station()
    driver, vehicle, _s = onboard_active_driver()
    warmup_clean_completion(station, driver, vehicle)
    return station, driver, vehicle


def setup_settlement_scenario():
    """The canonical settlement scenario.

    PREMIER driver (one clean warm-up completion); a main block
    [2026-09-01T10:00, 2026-09-01T13:00) base 6000 surged to 12500 bp by a
    cycle run at 08:30 (90 minutes before start); accepted at 08:35; checked
    in at 09:45; three packages (A 0.5kg promised 11:00, B 1.5kg promised
    11:00, C 2.0kg promised 12:00) loaded and departed; A delivered on time
    compliant at 10:30, B delivered late compliant at 11:05, C delivered on
    time with an untagged photo at 11:30.

    Returns (station, driver, vehicle, block, assignment, package_rows,
    provisional_pay_cents).
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    station = create_station()
    driver, vehicle, _s = onboard_active_driver()
    warmup_clean_completion(station, driver, vehicle)

    block = create_published_block(
        station["id"],
        starts_at="2026-09-01T10:00:00Z",
        ends_at="2026-09-01T13:00:00Z",
        required_vehicle_class="SEDAN",
        base_pay_cents=6000,
    )
    set_clock("2026-09-01T08:30:00Z")
    run_surge_cycle(station["id"], station["version"])
    set_clock("2026-09-01T08:35:00Z")
    assignment = accept_published_block(block["id"], driver["id"], vehicle["id"])
    provisional = assignment["provisional_pay_cents"]

    set_clock("2026-09-01T09:45:00Z")
    check_in(assignment["id"], driver["id"])
    load_packages(
        assignment["id"],
        [
            {
                "tracking_code": "M-A",
                "billable_weight_kg": 0.5,
                "promised_by": "2026-09-01T11:00:00Z",
            },
            {
                "tracking_code": "M-B",
                "billable_weight_kg": 1.5,
                "promised_by": "2026-09-01T11:00:00Z",
            },
            {
                "tracking_code": "M-C",
                "billable_weight_kg": 2.0,
                "promised_by": "2026-09-01T12:00:00Z",
            },
        ],
    )
    depart(assignment["id"], driver["id"])
    rows = {row["tracking_code"]: row for row in list_assignment_packages(assignment["id"])}

    set_clock("2026-09-01T10:30:00Z")
    deliver_package(rows["M-A"]["id"], driver["id"], "https://img.example/a.jpg", True)
    set_clock("2026-09-01T11:05:00Z")
    deliver_package(rows["M-B"]["id"], driver["id"], "https://img.example/b.jpg", True)
    set_clock("2026-09-01T11:30:00Z")
    deliver_package(rows["M-C"]["id"], driver["id"], "https://img.example/c.jpg", False)

    return (
        station,
        driver,
        vehicle,
        block,
        assignment,
        [rows["M-A"], rows["M-B"], rows["M-C"]],
        provisional,
    )


# ---------------------------------------------------------------------------
# Tier 4 — appeals composites
# ---------------------------------------------------------------------------

def setup_deactivated_driver(**kwargs):
    """Onboard a driver, activate, then deactivate. Returns (driver, vehicle)."""
    driver, vehicle, _s = onboard_active_driver(**kwargs)
    deactivate_driver(driver["id"])
    return driver, vehicle


def setup_appeal_under_review(**kwargs):
    """A deactivated driver with one appeal advanced to UNDER_REVIEW via one
    evidence submission. Returns (driver, vehicle, appeal)."""
    driver, vehicle = setup_deactivated_driver(**kwargs)
    appeal = submit_appeal(driver["id"])
    submit_evidence(appeal["id"], driver["id"])
    return driver, vehicle, appeal
