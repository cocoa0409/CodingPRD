"""Museums and the timed entry grid: creation defaults, pass quotas, closure
days, cancellation, admission grace and screening throughput (PRD §3.1, §2.4,
§2.5)."""

from test_helpers import (
    ApiErrorId,
    admit_pass,
    assert_museum,
    cancel_pass,
    close_museum_day,
    create_museum,
    create_timed_museum,
    get_museum,
    make_platform_admin_headers,
    make_public_headers,
    make_security_screener_headers,
    make_visitor_services_headers,
    reserve_pass,
    reset_clock,
    set_clock,
    slot_datetime,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_museum_create_returns_defaults_and_system_fields(api):
    """PRD §3.1: "A new museum's `closed_dates` list starts empty."
    PRD §2.5: "Every resource in the system carries four common properties. The `id` is a server-minted UUID with no type prefix."
    PRD §4: "Endpoints that create a new resource respond with HTTP 201 and the created resource; all other successful operations — modifications, actions, state transitions, and reads — respond with HTTP 200."

    Design: Corner/entities/museum_create_returns_defaults_and_system_fields
    """
    reset_clock()
    resp = api.create_museum(
        {
            "museum_code": "NMAAHC",
            "display_name": "National Museum of African American History and Culture",
            "requires_timed_pass": True,
            "quarter_hour_pass_quota": 4,
            "daily_pass_quota": 40,
            "screening_rate_per_quarter_hour": 8,
        },
        headers=make_platform_admin_headers(),
    )
    museum = validate_success(resp, 201)
    assert_museum(museum)
    assert museum["closed_dates"] == [], (
        f"new museum closed_dates must start empty, got {museum['closed_dates']!r}"
    )
    assert museum["version"] == 1, f"new museum version must be 1, got {museum['version']}"
    assert museum["quarter_hour_pass_quota"] == 4
    assert museum["daily_pass_quota"] == 40
    assert museum["screening_rate_per_quarter_hour"] == 8


def test_timed_pass_not_used_here_rejected(api):
    """PRD §3.1: "Reservation at a museum whose `requires_timed_pass` is false is rejected with `ERR_TIMED_PASS_NOT_USED_HERE`."

    Design: Corner/errors/timed_pass_not_used_here_rejected
    """
    reset_clock()
    museum = create_museum()  # a walk-in museum: requires_timed_pass False
    resp = api.create_timed_entry_pass(
        museum["id"],
        {"visitor_name": "Walk In", "visit_date": "2026-09-20", "entry_quarter_hour": 1},
        headers=make_public_headers("visitor-w"),
    )
    validate_error(resp, ApiErrorId.ERR_TIMED_PASS_NOT_USED_HERE)
    rows, meta = validate_paginated(
        api.list_timed_entry_passes(
            headers=make_visitor_services_headers(),
            params={"museum_id": museum["id"]},
        )
    )
    assert meta["total_count"] == 0 and rows == [], (
        "no pass row may be created against a walk-in museum"
    )


def test_duplicate_pass_rejected(api):
    """PRD §3.1: "One visitor may hold only one non-terminal pass per museum and date: a second reservation for the same `visitor_name`, museum, and `visit_date` while a `RESERVED` or `ADMITTED` pass exists is rejected with `ERR_DUPLICATE_PASS`."

    Design: Corner/errors/duplicate_pass_rejected
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=5, daily_pass_quota=20, screening_rate_per_quarter_hour=4
    )
    first = reserve_pass(
        museum["id"],
        creator_user_id="visitor-r1",
        visitor_name="Repeat Visitor",
        visit_date="2026-09-20",
        entry_quarter_hour=1,
    )
    assert first["status"] == "RESERVED"
    resp = api.create_timed_entry_pass(
        museum["id"],
        # A different, empty slot does not rescue the duplicate.
        {"visitor_name": "Repeat Visitor", "visit_date": "2026-09-20", "entry_quarter_hour": 7},
        headers=make_public_headers("visitor-r1"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PASS)
    after = validate_success(
        api.get_timed_entry_pass(first["id"], headers=make_visitor_services_headers())
    )
    assert after["status"] == "RESERVED"


def test_slot_quota_and_daily_quota_are_distinct_gates(api):
    """PRD §3.1: "Counting only passes in `RESERVED` or `ADMITTED` status — `CANCELLED` and `EXPIRED` never consume quota — the server first compares the requested slot's occupancy against `quarter_hour_pass_quota`: when the slot is already full the reservation fails with `ERR_SLOT_QUOTA_EXHAUSTED`. Only if the slot has room does the server compare the date's total occupancy against `daily_pass_quota`, failing with `ERR_DAILY_QUOTA_EXHAUSTED` when the date is full even though the slot is not."

    Design: Corner/calculations/slot_quota_and_daily_quota_are_distinct_gates
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=2, daily_pass_quota=3, screening_rate_per_quarter_hour=10
    )
    reserve_pass(museum["id"], visitor_name="Slot One A", visit_date="2026-09-20", entry_quarter_hour=1)
    reserve_pass(museum["id"], visitor_name="Slot One B", visit_date="2026-09-20", entry_quarter_hour=1)
    # Slot 1 is now at its quota of 2; the slot gate fires first.
    resp_slot = api.create_timed_entry_pass(
        museum["id"],
        {"visitor_name": "Slot One C", "visit_date": "2026-09-20", "entry_quarter_hour": 1},
        headers=make_public_headers("v-1c"),
    )
    validate_error(resp_slot, ApiErrorId.ERR_SLOT_QUOTA_EXHAUSTED)
    # A different slot still has room; the daily count rises to 3 == quota.
    third = reserve_pass(
        museum["id"], visitor_name="Slot Two A", visit_date="2026-09-20", entry_quarter_hour=2
    )
    assert third["status"] == "RESERVED"
    # Slot 3 is empty, but the date is full: the daily gate fires.
    resp_daily = api.create_timed_entry_pass(
        museum["id"],
        {"visitor_name": "Slot Three A", "visit_date": "2026-09-20", "entry_quarter_hour": 3},
        headers=make_public_headers("v-3a"),
    )
    validate_error(resp_daily, ApiErrorId.ERR_DAILY_QUOTA_EXHAUSTED)


def test_reserve_on_closed_date_rejected(api):
    """PRD §3.1: "A `visit_date` appearing in the museum's `closed_dates` is rejected with `ERR_MUSEUM_CLOSED_ON_DATE`."

    Design: Corner/errors/reserve_on_closed_date_rejected
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=5, daily_pass_quota=20, screening_rate_per_quarter_hour=4
    )
    close_museum_day(museum["id"], "2026-09-21")
    resp = api.create_timed_entry_pass(
        museum["id"],
        {"visitor_name": "Closure Day Visitor", "visit_date": "2026-09-21", "entry_quarter_hour": 1},
        headers=make_public_headers("visitor-cd"),
    )
    validate_error(resp, ApiErrorId.ERR_MUSEUM_CLOSED_ON_DATE)
    # The closure is date-scoped: the next day reserves normally.
    ok = reserve_pass(
        museum["id"],
        creator_user_id="visitor-cd",
        visitor_name="Closure Day Visitor",
        visit_date="2026-09-22",
        entry_quarter_hour=1,
    )
    assert ok["status"] == "RESERVED"


def test_pass_cancel_twice_returns_invalid_state(api):
    """PRD §3.1: "the pass moves `RESERVED` to `CANCELLED`, and both the slot quota and the daily quota for the pass's museum, date, and slot become reservable again."
    PRD §2.8: "5. **Transition legality** — the target resource stands in a state from which the requested transition exists, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pass_cancel_twice_returns_invalid_state
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=5, daily_pass_quota=20, screening_rate_per_quarter_hour=4
    )
    pass_ = reserve_pass(
        museum["id"],
        creator_user_id="visitor-d",
        visitor_name="Day Tripper",
        visit_date="2026-09-20",
        entry_quarter_hour=2,
    )
    cancelled = cancel_pass(pass_)
    assert cancelled["status"] == "CANCELLED"
    resp = api.cancel_timed_entry_pass(
        pass_["id"], headers=make_public_headers(pass_["created_by_user_id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(
        api.get_timed_entry_pass(pass_["id"], headers=make_visitor_services_headers())
    )
    assert after["status"] == "CANCELLED"
    assert after["version"] == cancelled["version"], (
        "a rejected second cancel must not advance the version"
    )


def test_pass_admit_after_grace_expires(api):
    """PRD §3.1: "A pass admits only on its `visit_date`, and only while the current slot index is no more than two slots — thirty minutes — beyond the pass's `entry_quarter_hour`. An admission attempted after that grace window first flips the pass to `EXPIRED` and then fails with `ERR_PASS_EXPIRED`"

    Design: Corner/errors/pass_admit_after_grace_expires
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=5, daily_pass_quota=20, screening_rate_per_quarter_hour=10
    )
    pass_ = reserve_pass(
        museum["id"],
        creator_user_id="visitor-la",
        visitor_name="Late Arrival",
        visit_date="2026-09-10",
        entry_quarter_hour=2,
    )
    # 11:20 UTC sits inside slot 5; the grace edge for slot 2 is slot 4.
    set_clock(slot_datetime("2026-09-10", 5))
    resp = api.admit_timed_entry_pass(pass_["id"], headers=make_security_screener_headers())
    validate_error(resp, ApiErrorId.ERR_PASS_EXPIRED)
    after = validate_success(
        api.get_timed_entry_pass(pass_["id"], headers=make_security_screener_headers())
    )
    assert after["status"] == "EXPIRED", (
        f"a late admit must flip the pass to EXPIRED, got {after['status']}"
    )


def test_screening_full_at_exact_rate_rejected(api):
    """PRD §3.1: "Within the window, the screening lane itself is the last gate: when the number of passes already admitted at this museum on this date in the current slot equals `screening_rate_per_quarter_hour` — equality means full — admission is rejected with `ERR_SCREENING_THROUGHPUT_FULL`."

    Design: Difficulty/boundary_precision_check/screening_full_at_exact_rate_rejected
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=3, daily_pass_quota=10, screening_rate_per_quarter_hour=2
    )
    pass_a = reserve_pass(museum["id"], creator_user_id="visitor-a", visitor_name="Visitor A", visit_date="2026-09-10", entry_quarter_hour=4)
    pass_b = reserve_pass(museum["id"], creator_user_id="visitor-b", visitor_name="Visitor B", visit_date="2026-09-10", entry_quarter_hour=4)
    pass_c = reserve_pass(museum["id"], creator_user_id="visitor-c", visitor_name="Visitor C", visit_date="2026-09-10", entry_quarter_hour=4)
    # 11:05 UTC sits inside slot 4, well within the grace window for slot 4.
    set_clock(slot_datetime("2026-09-10", 4))
    admitted_a = admit_pass(pass_a["id"])  # count 0 < rate 2
    assert admitted_a["status"] == "ADMITTED" and admitted_a["admitted_slot"] == 4
    admitted_b = admit_pass(pass_b["id"])  # count 1 < rate 2 — boundary rate-1 succeeds
    assert admitted_b["status"] == "ADMITTED" and admitted_b["admitted_slot"] == 4
    # count == rate == 2: equality means full.
    resp = api.admit_timed_entry_pass(pass_c["id"], headers=make_security_screener_headers())
    validate_error(resp, ApiErrorId.ERR_SCREENING_THROUGHPUT_FULL)
    after_c = validate_success(
        api.get_timed_entry_pass(pass_c["id"], headers=make_security_screener_headers())
    )
    assert after_c["status"] == "RESERVED"


def test_museum_closure_cascades_pass_expiry(api):
    """PRD §3.1: "When a museum must close on short notice, the `PlatformAdmin` performs a close-day action carrying a `closure_date`. The date is appended to `closed_dates`, the museum's `version` increments by 1, and every reserved pass at that museum on that date flips to `EXPIRED` in a single batch"
    PRD §2.8: "5. **Transition legality** — the target resource stands in a state from which the requested transition exists, else `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/museum_closure_cascades_pass_expiry
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=5, daily_pass_quota=20, screening_rate_per_quarter_hour=4
    )
    pass_ = reserve_pass(
        museum["id"],
        creator_user_id="visitor-d",
        visitor_name="Day Tripper",
        visit_date="2026-09-20",
        entry_quarter_hour=2,
    )
    close_museum_day(museum["id"], "2026-09-20")
    after_close = validate_success(
        api.get_timed_entry_pass(pass_["id"], headers=make_visitor_services_headers())
    )
    assert after_close["status"] == "EXPIRED", (
        "the close-day cascade must flip the reserved pass to EXPIRED"
    )
    # 10:35 UTC sits inside slot 2 — admission would be in-window — but an
    # EXPIRED pass admits no transition.
    set_clock(slot_datetime("2026-09-20", 2))
    resp = api.admit_timed_entry_pass(pass_["id"], headers=make_security_screener_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    museum_after = get_museum(museum["id"])
    assert "2026-09-20" in museum_after["closed_dates"]


def test_version_increments_on_every_mutation(api):
    """PRD §2.5: "The `version` is an integer that increments by one on every mutation of the resource."
    PRD §3.1: "The date is appended to `closed_dates`, the museum's `version` increments by 1"

    Design: Corner/endpoints/version_increments_on_every_mutation
    """
    reset_clock()
    museum = create_museum(museum_code="RENW", display_name="Renwick Gallery")
    assert museum["version"] == 1
    museum = close_museum_day(museum["id"], "2026-12-25")
    assert museum["version"] == 2
    museum = close_museum_day(museum["id"], "2026-07-04")
    assert museum["version"] == 3
    assert museum["closed_dates"] == ["2026-12-25", "2026-07-04"], (
        "closure dates append in call order"
    )
