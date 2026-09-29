"""Endpoint corners: the logical clock's declared default and its monotonicity
guard, the report-window guard shared by both report endpoints, the compliance
sweep as a no-op over a world where nothing has lapsed, and the filter, ordering
and pagination behaviour of the collection channels.
"""

from test_helpers import (
    ApiErrorId,
    assert_list_count,
    assert_percent_2dp,
    assert_same_instant,
    assert_state_pair,
    make_compliance_headers,
    make_therapist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers import factories as f
from test_helpers import fixtures as fx

# ---------------------------------------------------------------------------
# logical_clock_default_instant_and_monotonic_advance_only
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"
ONE_MS_BEFORE_DEFAULT = "2026-07-31T23:59:59.999Z"
ADVANCED_CLOCK = "2026-08-05T09:00:00.000Z"
ONE_MS_BEFORE_ADVANCED = "2026-08-05T08:59:59.999Z"
NON_UTC_OFFSET_INSTANT = "2026-08-05T09:00:00.000+02:00"


def _set_clock_raw(current_utc, headers=None):
    """One unvalidated clock call, so a caller may assert the refused rung."""
    return api_client.set_clock(f.clock_payload(current_utc),
                                headers or fx.DIRECTOR)


def test_the_first_write_of_the_run_is_stamped_with_the_declared_default_clock():
    """No clock call precedes the first guest, and the rewind guard admits equality.

    PRD §2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`; it never falls back to real time."

    PRD §2.4: "The clock never rewinds: a requested instant earlier than the
    current logical instant is rejected with `ERR_CLOCK_REWIND` (HTTP 422), while
    an instant equal to the current one is accepted."

    Design: Corner/endpoints/logical_clock_default_instant_and_monotonic_advance_only
    """
    first = fx.create_guest(full_name="Default Clock Guest",
                            resort_room_number="2201",
                            folio_limit_cents=100000)
    assert_same_instant(first["created_at"], DEFAULT_CLOCK, "created_at")
    assert_same_instant(first["updated_at"], DEFAULT_CLOCK, "updated_at")

    validate_error(_set_clock_raw(ONE_MS_BEFORE_DEFAULT),
                   ApiErrorId.ERR_CLOCK_REWIND.value, 422)

    at_rest = validate_success(_set_clock_raw(DEFAULT_CLOCK))
    assert_same_instant(at_rest["current_utc"], DEFAULT_CLOCK, "current_utc")

    advanced = validate_success(_set_clock_raw(ADVANCED_CLOCK))
    assert_same_instant(advanced["current_utc"], ADVANCED_CLOCK, "current_utc")

    second = fx.create_guest(full_name="Advanced Clock Guest",
                             resort_room_number="2202",
                             folio_limit_cents=100000)
    assert_same_instant(second["created_at"], ADVANCED_CLOCK, "created_at")


def test_a_non_utc_offset_instant_is_a_shape_error_and_no_refusal_moves_the_clock():
    """Rung 3 outranks rung 33 on the clock endpoint itself, and the guest created
    afterwards proves neither refused call advanced or rewound anything.

    PRD §2.5: "Every datetime the client submits — `start_at`, `end_at`,
    `current_utc`, `from_at`, `to_at` — must be a valid ISO 8601 UTC instant, and
    every date-only field the client submits — `issued_on`, `expires_on`,
    `current_period_start_on`, `granted_on`, `completed_on`, `as_of` — must be a
    valid `YYYY-MM-DD` calendar date."

    PRD §2.7 rung 33: "**Clock monotonicity** — the requested clock instant is
    greater than or equal to the current logical clock. Applies to the clock-setting
    capability. Violation: `ERR_CLOCK_REWIND` (422)."

    Design: Corner/endpoints/logical_clock_default_instant_and_monotonic_advance_only
    """
    validate_success(_set_clock_raw(ADVANCED_CLOCK))

    validate_error(_set_clock_raw(NON_UTC_OFFSET_INSTANT),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    validate_error(_set_clock_raw(ONE_MS_BEFORE_ADVANCED),
                   ApiErrorId.ERR_CLOCK_REWIND.value, 422)

    guest = fx.create_guest(full_name="Unmoved Clock Guest",
                            resort_room_number="2203",
                            folio_limit_cents=100000)
    assert_same_instant(guest["created_at"], ADVANCED_CLOCK, "created_at")

    still_there = validate_success(_set_clock_raw(ADVANCED_CLOCK))
    assert_same_instant(still_there["current_utc"], ADVANCED_CLOCK, "current_utc")


# ---------------------------------------------------------------------------
# report_window_guards_on_both_report_endpoints
# ---------------------------------------------------------------------------

REPORT_CLOCK = "2026-08-01T09:00:00.000Z"
WINDOW_FROM_AT = "2026-05-01T00:00:00.000Z"
WINDOW_TO_AT_EXACTLY_92_DAYS = "2026-08-01T00:00:00.000Z"
WINDOW_TO_AT_ONE_MS_TOO_LONG = "2026-08-01T00:00:00.001Z"
NINETY_TWO_DAYS_IN_MINUTES = 132480              # 92 * 24 * 60
ZERO_WIDTH_AT = "2026-08-10T00:00:00.000Z"
INVERTED_FROM_AT = "2026-08-11T00:00:00.000Z"
INVERTED_TO_AT = "2026-08-10T00:00:00.000Z"


def _report_world():
    """One DRY room so the utilisation report has a row to compute, and one
    therapist so the retail report's optional scope filter has a target. No
    appointments are needed: the window guard is evaluated before the aggregate."""
    fx.set_clock(REPORT_CLOCK)
    room = fx.create_room(code="DRY-1", room_class="DRY",
                          turnover_buffer_minutes=15,
                          hourly_fixed_cost_cents=2500)
    therapist = fx.create_therapist(full_name="Report Window Therapist")
    return room, therapist


def test_the_room_utilization_report_admits_exactly_ninety_two_days():
    """A zero-width window, an inverted window and a 92-day-plus-one-millisecond
    window are all refused, while the exact span is accepted.

    PRD §3.10: "Both reports reject a window whose `from_at` is not strictly earlier
    than its `to_at`, and both reject a window spanning more than 92 days, with
    `ERR_INVALID_REPORT_WINDOW` (HTTP 422)."

    PRD §3.10: "`window_minutes` is the number of minutes between `from_at` and
    `to_at`, and the response echoes `from_at`, `to_at` and `window_minutes`
    alongside a `rooms` array."

    PRD §3.10: "A room with no completed appointments in the window reports
    `occupied_minutes` 0, `utilization_pct` exactly `0.00` and every money field 0
    rather than being omitted."

    Design: Corner/endpoints/report_window_guards_on_both_report_endpoints
    """
    room, _ = _report_world()

    # A zero-width window, an inverted window and a window one millisecond over
    # the 92-day ceiling.
    for from_at, to_at in ((ZERO_WIDTH_AT, ZERO_WIDTH_AT),
                           (INVERTED_FROM_AT, INVERTED_TO_AT),
                           (WINDOW_FROM_AT, WINDOW_TO_AT_ONE_MS_TOO_LONG)):
        validate_error(
            api_client.get_room_utilization_report(
                fx.DIRECTOR, params=f.report_window(from_at, to_at)),
            ApiErrorId.ERR_INVALID_REPORT_WINDOW.value, 422)

    report = validate_success(api_client.get_room_utilization_report(
        fx.DIRECTOR,
        params=f.report_window(WINDOW_FROM_AT, WINDOW_TO_AT_EXACTLY_92_DAYS)))
    assert_same_instant(report["from_at"], WINDOW_FROM_AT, "from_at")
    assert_same_instant(report["to_at"], WINDOW_TO_AT_EXACTLY_92_DAYS, "to_at")
    assert report["window_minutes"] == NINETY_TWO_DAYS_IN_MINUTES

    assert len(report["rooms"]) == 1, f"expected one room row, got {report['rooms']}"
    element = report["rooms"][0]
    assert element["room_id"] == room["id"]
    assert element["room_code"] == "DRY-1"
    assert element["occupied_minutes"] == 0
    assert_percent_2dp(element["utilization_pct"], "utilization_pct")
    assert float(element["utilization_pct"]) == 0.00
    for field in ("revenue_cents", "labor_cost_cents", "room_fixed_cost_cents",
                  "net_margin_cents", "revenue_per_room_hour_cents"):
        assert element[field] == 0, (
            f"{field} must be 0 rather than omitted, got {element.get(field)!r}")


def test_the_retail_report_enforces_the_identical_window_guard():
    """The guard is shared rather than per-endpoint, and the optional therapist
    scope narrows the aggregate without relaxing it.

    PRD §3.10: "Both reports reject a window whose `from_at` is not strictly earlier
    than its `to_at`, and both reject a window spanning more than 92 days, with
    `ERR_INVALID_REPORT_WINDOW` (HTTP 422)."

    PRD §3.10: "`attach_rate_pct` is exactly `0.00` when `eligible_appointment_count`
    is 0 — never an error — and is otherwise `purchased_count` multiplied by 100 and
    divided by `eligible_appointment_count`, rounded half up to two decimal places."

    PRD §3.10: "The response echoes `from_at` and `to_at` alongside the five
    figures."

    Design: Corner/endpoints/report_window_guards_on_both_report_endpoints
    """
    _, therapist = _report_world()

    validate_error(
        api_client.get_retail_attachment_report(
            fx.COORDINATOR,
            params=f.report_window(INVERTED_FROM_AT, INVERTED_TO_AT)),
        ApiErrorId.ERR_INVALID_REPORT_WINDOW.value, 422)
    validate_error(
        api_client.get_retail_attachment_report(
            fx.COORDINATOR,
            params=f.report_window(WINDOW_FROM_AT, WINDOW_TO_AT_ONE_MS_TOO_LONG,
                                   therapist_id=therapist["id"])),
        ApiErrorId.ERR_INVALID_REPORT_WINDOW.value, 422)

    report = validate_success(api_client.get_retail_attachment_report(
        fx.COORDINATOR,
        params=f.report_window(WINDOW_FROM_AT, WINDOW_TO_AT_EXACTLY_92_DAYS,
                               therapist_id=therapist["id"])))
    assert_same_instant(report["from_at"], WINDOW_FROM_AT, "from_at")
    assert_same_instant(report["to_at"], WINDOW_TO_AT_EXACTLY_92_DAYS, "to_at")
    assert report["eligible_appointment_count"] == 0
    assert report["purchased_count"] == 0
    assert report["purchased_amount_cents"] == 0
    assert report["commission_cents"] == 0
    assert_percent_2dp(report["attach_rate_pct"], "attach_rate_pct")
    assert float(report["attach_rate_pct"]) == 0.00, (
        "an empty eligible set reports 0.00 rather than raising")


# ---------------------------------------------------------------------------
# compliance_sweep_is_a_no_op_when_nothing_has_lapsed
# ---------------------------------------------------------------------------

SWEEP_CLOCK = "2026-08-09T09:00:00.000Z"
SWEEP_DAY_EXPIRY = "2026-08-09"                  # the sweep date exactly
SWEEP_APPOINTMENT_AT = "2026-08-09T11:00:00.000Z"
SWEEP_ARRAY_FIELDS = ("expired_license_ids", "suspended_therapist_ids",
                      "blocked_appointment_ids", "auto_cancelled_appointment_ids",
                      "expired_attachment_ids")


def _sweep_world():
    """A world in which the licence and the certification both expire exactly on
    the sweep date and one REQUESTED appointment sits later the same day, so every
    hop of the cascade should find an empty candidate set."""
    world = fx.build_world(
        clock=SWEEP_CLOCK,
        license_overrides={"expires_on": SWEEP_DAY_EXPIRY},
        certification_overrides={"expires_on": SWEEP_DAY_EXPIRY},
        shift_block_overrides={"start_at": SWEEP_APPOINTMENT_AT,
                               "end_at": "2026-08-09T18:00:00.000Z"})
    world.appointments["a"] = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id,
        SWEEP_APPOINTMENT_AT, world.therapist_id)
    return world


def _sweep(headers):
    return validate_success(api_client.run_compliance_sweep({}, headers))


def test_a_licence_expiring_on_the_sweep_date_is_not_swept():
    """The first hop's comparison is strictly before the sweep date, so the
    same-day licence survives and the whole cascade reports nothing.

    PRD §3.10: "It takes no input, evaluates everything at the current logical
    instant, and reports what it did as `swept_at` together with five arrays:
    `expired_license_ids`, `suspended_therapist_ids`, `blocked_appointment_ids`,
    `auto_cancelled_appointment_ids` and `expired_attachment_ids`."

    PRD §3.10: "The first hop expires credentials: every licence whose
    `verification_status` is `VERIFIED` and whose `expires_on` falls strictly before
    the sweep instant's UTC date moves `VERIFIED → EXPIRED`."

    PRD §3.10: "Its work is a five-hop cascade in which each hop exists only because
    the previous one fired."

    Design: Corner/endpoints/compliance_sweep_is_a_no_op_when_nothing_has_lapsed
    """
    world = _sweep_world()

    swept = _sweep(make_compliance_headers(fx.CO_REVIEW))
    assert_same_instant(swept["swept_at"], SWEEP_CLOCK, "swept_at")
    for field in SWEEP_ARRAY_FIELDS:
        assert swept[field] == [], (
            f"{field} must be an empty array, got {swept.get(field)!r}")

    licence = validate_success(api_client.get_license(
        world.license_id, fx.DIRECTOR))
    assert licence["verification_status"] == "VERIFIED"
    assert licence["expires_on"] == SWEEP_DAY_EXPIRY, (
        "the licence expires on the sweep date and is therefore not yet lapsed")


def test_a_second_sweep_by_the_other_permitted_role_is_identical_and_inert():
    """Both roles may run it, no clock movement happens in between, and nothing in
    the world has moved after two sweeps.

    PRD §3.10: "The compliance sweep is the operator batch step that keeps the
    credential chain honest as the logical clock advances, and either a
    `ComplianceOfficer` or a `SpaDirector` may run it."

    PRD §3.10: "The second hop suspends the therapist: because a licence expired,
    any therapist who is `ACTIVE` and now holds no `VERIFIED` unexpired licence at
    all moves `ACTIVE → SUSPENDED` with `suspension_reason` `LICENSE_EXPIRED` — a
    therapist who still holds a second valid licence is left alone."

    PRD §3.3: "Expiry is not a status rewrite — a grant is treated as valid only
    while its `expires_on` falls on or after the current logical-clock date, so an
    unrevoked grant simply stops satisfying scope checks once that date has passed."

    Design: Corner/endpoints/compliance_sweep_is_a_no_op_when_nothing_has_lapsed
    """
    world = _sweep_world()
    appointment_id = world.appointments["a"]["id"]

    first = _sweep(make_compliance_headers(fx.CO_REVIEW))
    second = _sweep(fx.DIRECTOR)
    assert_same_instant(second["swept_at"], first["swept_at"], "swept_at")
    for field in SWEEP_ARRAY_FIELDS:
        assert second[field] == [], (
            f"{field} must still be empty on the second sweep, "
            f"got {second.get(field)!r}")

    therapist = world.fetch_therapist()
    assert therapist["status"] == "ACTIVE"
    assert therapist["suspension_reason"] is None
    grants = assert_list_count(api_client.list_certifications(
        world.therapist_id, fx.DIRECTOR), 1, "certification grants")
    assert grants[0]["status"] == "ACTIVE"
    assert grants[0]["expires_on"] == SWEEP_DAY_EXPIRY

    appointment = world.fetch_appointment(appointment_id)
    assert_state_pair(appointment, "REQUESTED", "PENDING")
    assert appointment["clearance_block_reason"] is None


# ---------------------------------------------------------------------------
# list_filters_and_pagination_bounds_across_collection_channels
# ---------------------------------------------------------------------------

LIST_CLOCK = "2026-08-01T09:00:00.000Z"
LIST_BLOCK_START_AT = "2026-08-10T08:00:00.000Z"
LIST_BLOCK_END_AT = "2026-08-12T22:00:00.000Z"
LIST_START_ATS = ("2026-08-10T10:00:00.000Z", "2026-08-11T10:00:00.000Z",
                  "2026-08-12T10:00:00.000Z")
DEFAULT_PAGE_LIMIT = 10


def _listing_world():
    """One therapist holding one VERIFIED and one PENDING_REVIEW licence, three CE
    records in two categories, two certification grants of which one is revoked, one
    AVAILABLE block and no BREAK block, and three appointments created at three
    distinct logical instants so that `created_at` ascending order is unambiguous.
    The clock is advanced one minute before each creation for exactly that reason."""
    world = fx.build_world(
        clock=LIST_CLOCK,
        shift_block_overrides={"start_at": LIST_BLOCK_START_AT,
                               "end_at": LIST_BLOCK_END_AT})

    fx.set_clock("2026-08-01T09:01:00.000Z")
    world.licenses["pending"] = fx.submit_license(
        world.therapist_id, submit_user=fx.CO_SUBMIT,
        license_number="HI-ESTH-8002", license_type="ESTHETICIAN",
        issued_on="2026-01-01", expires_on="2028-01-01",
        current_period_start_on="2026-01-01")

    verified_license_id = world.license_id
    for minute, (course_code, category, ce_hours, completed_on) in enumerate((
            ("ETH-301", "ETHICS", 2.0, "2025-06-01"),
            ("CLIN-101", "CLINICAL", 6.0, "2025-03-01"),
            ("CLIN-102", "CLINICAL", 4.0, "2025-04-01")), start=2):
        fx.set_clock(f"2026-08-01T09:0{minute}:00.000Z")
        fx.add_ce_record(verified_license_id, course_code=course_code,
                         category=category, ce_hours=ce_hours,
                         completed_on=completed_on)

    fx.set_clock("2026-08-01T09:05:00.000Z")
    revoked = fx.grant_certification(world.therapist_id, user=fx.CO_SUBMIT,
                                     skill_code="SWEDISH", scope_level="BASIC")
    world.certifications["revoked"] = validate_success(
        api_client.revoke_certification(
            revoked["id"], {"reason_note": "scope withdrawn"},
            make_compliance_headers(fx.CO_REVOKE)))

    for minute, start_at in enumerate(LIST_START_ATS, start=6):
        fx.set_clock(f"2026-08-01T09:0{minute}:00.000Z")
        world.appointments[start_at] = fx.book_appointment(
            world.guest_id, world.treatment_type_id, world.room_id, start_at,
            world.therapist_id)

    world.appointments[LIST_START_ATS[1]] = fx.confirm(
        world.appointments[LIST_START_ATS[1]]["id"])
    world.appointments[LIST_START_ATS[2]] = validate_success(
        api_client.cancel_appointment(
            world.appointments[LIST_START_ATS[2]]["id"],
            f.cancel_payload("guest changed plans"), fx.COORDINATOR))
    return world


def test_credential_list_filters_narrow_the_population_not_merely_the_page():
    """`total_count` reports the filtered population, ordering is `created_at`
    ascending, and an empty filtered result is still a full pagination envelope.

    PRD §2.3: "Unless a specific list endpoint states otherwise, records are
    returned sorted by their creation timestamp `created_at` in ascending order."

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the envelope's `meta` object, where `total_count` is the number of records
    matching the request's filters before pagination is applied and `has_more` states
    whether any matching record remains beyond the returned page."

    PRD §3.3: "A licence's records are listable with an optional `category` filter."

    Design: Corner/endpoints/list_filters_and_pagination_bounds_across_collection_channels
    """
    world = _listing_world()
    verified_license_id = world.license_id
    pending_license_id = world.licenses["pending"]["id"]
    compliance = make_compliance_headers(fx.CO_REVIEW)

    filtered, meta = validate_paginated(api_client.list_licenses(
        world.therapist_id, compliance, params={"verification_status": "VERIFIED"}))
    assert [row["id"] for row in filtered] == [verified_license_id]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    unfiltered, meta = validate_paginated(api_client.list_licenses(
        world.therapist_id, fx.DIRECTOR))
    assert [row["id"] for row in unfiltered] == [verified_license_id,
                                                 pending_license_id], (
        "the unfiltered read returns both licences in created_at ascending order")
    assert meta["total_count"] == 2

    clinical, meta = validate_paginated(api_client.list_ce_records(
        verified_license_id, compliance, params={"category": "CLINICAL"}))
    assert [row["course_code"] for row in clinical] == ["CLIN-101", "CLIN-102"]
    assert meta["total_count"] == 2, (
        "the ETHICS record is excluded from the filtered population, not just "
        "from the page")

    empty, meta = validate_paginated(api_client.list_shift_blocks(
        world.therapist_id, make_therapist_headers(world.therapist_id),
        params={"block_type": "BREAK"}))
    assert empty == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == DEFAULT_PAGE_LIMIT
    assert meta["offset"] == 0


def test_a_revoked_grant_and_a_cancelled_appointment_are_filtered_not_deleted():
    """Both rows survive in the unfiltered channel with their terminal status
    visible; the filters merely select.

    PRD §3.3: "Revocation is the one transition the API exposes: it sets `status` to
    `REVOKED`, records the revoking officer as `revoked_by_user_id`, accepts an
    optional `reason_note`, and immediately removes that therapist from the eligible
    pool for every treatment requiring that skill."

    PRD §3.3: "A therapist's grants are listable with an optional `status` filter."

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the envelope's `meta` object, where `total_count` is the number of records
    matching the request's filters before pagination is applied and `has_more` states
    whether any matching record remains beyond the returned page."

    Design: Corner/endpoints/list_filters_and_pagination_bounds_across_collection_channels
    """
    world = _listing_world()
    revoked_id = world.certifications["revoked"]["id"]

    active = assert_list_count(api_client.list_certifications(
        world.therapist_id, fx.COORDINATOR, params={"status": "ACTIVE"}), 1,
        "ACTIVE certification grants")
    assert [row["id"] for row in active] == [world.certification_id]

    both = assert_list_count(api_client.list_certifications(
        world.therapist_id, fx.DIRECTOR), 2, "all certification grants")
    by_id = {row["id"]: row for row in both}
    assert by_id[revoked_id]["status"] == "REVOKED"
    assert by_id[revoked_id]["revoked_by_user_id"] == fx.CO_REVOKE
    assert by_id[world.certification_id]["status"] == "ACTIVE"

    cancelled_id = world.appointments[LIST_START_ATS[2]]["id"]
    cancelled = assert_list_count(api_client.list_appointments(
        fx.COORDINATOR, params={"guest_id": world.guest_id,
                                "schedule_status": "CANCELLED"}), 1,
        "CANCELLED appointments of this guest")
    assert [row["id"] for row in cancelled] == [cancelled_id], (
        "the two live appointments are filtered out of the population")

    everything = assert_list_count(api_client.list_appointments(
        fx.COORDINATOR, params={"guest_id": world.guest_id}), 3,
        "all appointments of this guest")
    assert cancelled_id in [row["id"] for row in everything]


def test_the_pagination_window_composes_with_a_filter_and_its_bounds_are_shape_rules():
    """`limit` and `offset` page through the filtered population, and out-of-range
    values are refused rather than clamped.

    PRD §2.3: "Every list endpoint accepts two query parameters. `limit` caps the
    number of records returned; it defaults to 10, its minimum accepted value is 1
    and its maximum accepted value is 100. `offset` skips that many records before
    the page begins; it defaults to 0 and its minimum accepted value is 0. A `limit`
    outside the range of 1 through 100, or a negative `offset`, is a shape violation
    and is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    PRD §2.7 rung 3: "**Request shape** — required fields present, enum values legal,
    integers within their declared ranges, datetimes valid ISO 8601 UTC instants,
    dates valid calendar dates, `limit` within 1 through 100 and `offset` not
    negative."

    Design: Corner/endpoints/list_filters_and_pagination_bounds_across_collection_channels
    """
    world = _listing_world()
    expected_ids = [world.appointments[start_at]["id"]
                    for start_at in LIST_START_ATS]

    first_page, meta = validate_paginated(api_client.list_appointments(
        fx.COORDINATOR,
        params={"guest_id": world.guest_id, "limit": 2, "offset": 0}))
    assert [row["id"] for row in first_page] == expected_ids[:2]
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second_page, meta = validate_paginated(api_client.list_appointments(
        fx.COORDINATOR,
        params={"guest_id": world.guest_id, "limit": 2, "offset": 2}))
    assert [row["id"] for row in second_page] == expected_ids[2:]
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    default_page, meta = validate_paginated(api_client.list_appointments(
        fx.COORDINATOR, params={"guest_id": world.guest_id}))
    assert meta["limit"] == DEFAULT_PAGE_LIMIT
    assert meta["offset"] == 0
    assert [row["id"] for row in default_page] == expected_ids

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        query = dict(params, guest_id=world.guest_id)
        validate_error(api_client.list_appointments(fx.COORDINATOR, params=query),
                       ApiErrorId.ERR_INVALID_REQUEST.value, 422)
