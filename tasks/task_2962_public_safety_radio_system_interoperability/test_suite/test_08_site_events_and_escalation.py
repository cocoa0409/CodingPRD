"""Site events: maintenance scheduling, backup-power decay, and tier-3 escalation.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_MAINTENANCE_BUFFER_VIOLATION,
    ERR_MAINTENANCE_CONCURRENCY_CAP,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pagination_meta,
    assert_site_capacity_counters,
)
from test_helpers.constants import (
    AGENCY_TYPE_EMS,
    AGENCY_TYPE_FIRE,
    BACKUP_BATTERY_ONLY,
    BACKUP_GENERATOR,
    CAPACITY_EMERGENCY_ONLY,
    CAPACITY_NORMAL,
    CAUSE_COMMERCIAL_POWER_LOSS,
    CAUSE_SCHEDULED_WORK,
    ENC_CLEAR,
    EV_ACTION_BACKUP_ENGAGED,
    EV_ACTION_ESCALATE,
    EVENT_ESCALATED,
    EVENT_ON_BACKUP_POWER,
    EVENT_OPEN,
    EVENT_PLANNED_MAINTENANCE,
    EVENT_UNPLANNED_OUTAGE,
    KIND_NORMAL,
    MODEL_MOBILE,
    MODEL_PORTABLE,
    OUTCOME_BUSIED,
    OUTCOME_GRANTED,
    OUTCOME_PREEMPTED,
    OUTCOME_RELEASED,
    SITE_DEGRADED,
    SITE_IN_SERVICE,
    STANDARD_P25_PHASE1,
    STANDARD_P25_PHASE2,
    TG_KIND_DISPATCH,
)
from test_helpers.test_users import RF_ENGINEER, SYSTEM_ADMIN


def _battery_site_on_backup(api: ApiClient):
    """Site `BAT-1` on battery backup with exactly 121 minutes left.

    Capacity is 240 minutes (the generator contribution is dropped for a
    `BATTERY_ONLY` site) and 119 whole minutes have elapsed since `detected_at`,
    so the decay function reports 121 — one minute above the tier-1 boundary.

    Returns `(site, event_on_backup)` with the logical clock at
    `2026-08-01T01:59:00Z`.
    """
    site = fx.register_site(
        api,
        site_code="BAT-1",
        name="Battery One",
        channel_capacity=8,
        backup_power_type=BACKUP_BATTERY_ONLY,
        battery_runtime_minutes=240,
        generator_fuel_hours=0,
    )
    event = fx.open_site_event(
        api,
        site["id"],
        event_class=EVENT_UNPLANNED_OUTAGE,
        cause=CAUSE_COMMERCIAL_POWER_LOSS,
    )
    assert_instant_equals(event["detected_at"], "2026-08-01T00:00:00Z", "detected_at")

    fx.set_clock(api, "2026-08-01T01:59:00Z")
    on_backup = fx.advance_event(api, event["id"], EV_ACTION_BACKUP_ENGAGED)

    assert_fields(
        on_backup,
        status=EVENT_ON_BACKUP_POWER,
        backup_minutes_remaining=121,
        escalation_tier=0,
    )
    assert_fields(fx.read_site(api, site["id"]), status=SITE_DEGRADED)
    return site, on_backup


def _hotel_outage_at_capacity(api: ApiClient):
    """Site `OUT-1` on battery backup with all four usable talkpaths held by
    `NORMAL` traffic and a fifth request already busied.

    Returns `(site, event, talkpaths)` where `talkpaths` is the list of the five
    request rows in submission order. The logical clock is left at
    `2026-08-01T00:00:00Z`.
    """
    site = fx.register_site(
        api,
        site_code="OUT-1",
        name="Outage One",
        channel_capacity=5,
        backup_power_type=BACKUP_BATTERY_ONLY,
        battery_runtime_minutes=240,
        generator_fuel_hours=0,
    )
    agency = fx.register_agency(
        api,
        name="Hotel Fire Department",
        agency_code="FIRH1",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="HOTEL-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        talkgroup_slot_count=4,
    )
    talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="HFD-DISP",
        tg_decimal_id=201,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    units = [
        fx.assigned_unit(
            api,
            agency["id"],
            template["id"],
            serial_number="SNH001",
            radio_id=7001,
            model=MODEL_PORTABLE,
            priority_class=7,
        ),
        fx.assigned_unit(
            api,
            agency["id"],
            template["id"],
            serial_number="SNH002",
            radio_id=7002,
            model=MODEL_PORTABLE,
            priority_class=4,
        ),
        fx.assigned_unit(
            api,
            agency["id"],
            template["id"],
            serial_number="SNH003",
            radio_id=7003,
            model=MODEL_MOBILE,
            priority_class=7,
        ),
        fx.assigned_unit(
            api,
            agency["id"],
            template["id"],
            serial_number="SNH004",
            radio_id=7004,
            model=MODEL_MOBILE,
            priority_class=2,
        ),
    ]
    event = fx.open_site_event(
        api,
        site["id"],
        event_class=EVENT_UNPLANNED_OUTAGE,
        cause=CAUSE_COMMERCIAL_POWER_LOSS,
    )
    on_backup = fx.advance_event(api, event["id"], EV_ACTION_BACKUP_ENGAGED)
    assert_fields(
        on_backup,
        status=EVENT_ON_BACKUP_POWER,
        backup_minutes_remaining=240,
        escalation_tier=0,
    )
    assert_fields(
        fx.read_site(api, site["id"]),
        status=SITE_DEGRADED,
        capacity_mode=CAPACITY_NORMAL,
    )

    # channel_capacity 5 less the control channel leaves 4 usable talkpaths, so
    # the fifth NORMAL request meets exactly zero headroom.
    holders = [units[0], units[1], units[2], units[3], units[0]]
    talkpaths = [
        fx.request_talkpath(
            api,
            site["id"],
            talkgroup["id"],
            unit["id"],
            agency["id"],
            request_kind=KIND_NORMAL,
            site_event_id=event["id"],
        )
        for unit in holders
    ]
    for granted in talkpaths[:4]:
        assert_fields(granted, outcome=OUTCOME_GRANTED)
    assert_fields(
        talkpaths[4],
        outcome=OUTCOME_BUSIED,
        available_talkpaths_at_decision=0,
        reserve_talkpaths_at_decision=0,
    )
    return site, on_backup, talkpaths


def test_site_event_starts_open_with_detected_at_stamped(
    api: ApiClient, clock_at_start: str
):
    """A freshly opened outage is `OPEN` with `detected_at` at the logical clock,
    nothing computed yet, and — crucially — a parent site that has not moved.

    PRD 3.7: "A newly opened event sits in `OPEN` with `detected_at` stamped at
    the current logical clock instant, `escalation_tier` 0,
    `backup_minutes_remaining` null, `restored_at` null, and
    `preempted_talkpath_count` 0."

    PRD 3.7: "Crucially, opening an event changes nothing about the parent site:
    its `status` and `capacity_mode` stay exactly as they were until the event is
    advanced."

    Design: Corner/state_machines/site_event_starts_open_with_detected_at_stamped
    """
    fx.set_clock(api, "2026-08-01T03:00:00Z")
    site = fx.register_site(
        api,
        site_code="INIT-1",
        name="Initial One",
        channel_capacity=6,
        backup_power_type=BACKUP_GENERATOR,
        generator_fuel_hours=8,
    )

    event = validate_success(
        api.create_site_event(
            f.site_event_payload(
                site["id"],
                event_class=EVENT_UNPLANNED_OUTAGE,
                cause=CAUSE_COMMERCIAL_POWER_LOSS,
            ),
            RF_ENGINEER,
        ),
        201,
    )

    assert_common_fields(event, expected_version=1)
    assert_fields(
        event,
        site_id=site["id"],
        event_class=EVENT_UNPLANNED_OUTAGE,
        cause=CAUSE_COMMERCIAL_POWER_LOSS,
        status=EVENT_OPEN,
        escalation_tier=0,
        preempted_talkpath_count=0,
    )
    assert_instant_equals(event["detected_at"], "2026-08-01T03:00:00Z", "detected_at")
    assert_nulls(
        event,
        "backup_minutes_remaining",
        "restored_at",
        "window_start",
        "window_end",
    )

    # Opening the event alone moves nothing on the site.
    assert_fields(
        fx.read_site(api, site["id"]),
        status=SITE_IN_SERVICE,
        capacity_mode=CAPACITY_NORMAL,
        version=site["version"],
    )


def test_maintenance_concurrency_cap_rejected(api: ApiClient, clock_at_start: str):
    """Two sites may hold overlapping maintenance windows; a third overlapping
    site breaks the region-wide cap, while a window that merely abuts theirs is
    accepted because the intersection test is half-open.

    PRD 3.7: "The second rule protects the region from losing too much
    infrastructure at once: at most 2 distinct sites may hold planned maintenance
    windows covering the same instant, so a new window is rejected when 2 or more
    *other* sites already have a planned maintenance event whose window intersects
    the new one."

    PRD 3.7: "That intersection test uses half-open intervals, meaning a new
    window that begins exactly when another site's window ends does not intersect
    it."

    Design: Corner/validations/maintenance_concurrency_cap_rejected
    """
    first = fx.register_site(
        api,
        site_code="CAP-1",
        name="Cap One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )
    second = fx.register_site(
        api,
        site_code="CAP-2",
        name="Cap Two",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )
    third = fx.register_site(
        api,
        site_code="CAP-3",
        name="Cap Three",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )
    for site in (first, second):
        window = fx.planned_maintenance(
            api, site["id"], "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
        )
        assert_fields(window, status=EVENT_OPEN, event_class=EVENT_PLANNED_MAINTENANCE)

    over_cap = api.create_site_event(
        f.site_event_payload(
            third["id"],
            event_class=EVENT_PLANNED_MAINTENANCE,
            cause=CAUSE_SCHEDULED_WORK,
            window_start="2026-08-10T10:00:00Z",
            window_end="2026-08-10T14:00:00Z",
        ),
        RF_ENGINEER,
    )
    validate_error(over_cap, ERR_MAINTENANCE_CONCURRENCY_CAP, 409)

    # [12:00, 16:00) begins exactly when the other two windows end.
    abutting = validate_success(
        api.create_site_event(
            f.site_event_payload(
                third["id"],
                event_class=EVENT_PLANNED_MAINTENANCE,
                cause=CAUSE_SCHEDULED_WORK,
                window_start="2026-08-10T12:00:00Z",
                window_end="2026-08-10T16:00:00Z",
            ),
            RF_ENGINEER,
        ),
        201,
    )
    assert_fields(abutting, status=EVENT_OPEN)

    rows, meta = validate_paginated(
        api.list_site_events(SYSTEM_ADMIN, {"site_id": third["id"]})
    )
    assert_pagination_meta(meta, total_count=1)
    assert_fields(rows[0], id=abutting["id"])

    # Scheduling a window does not start it.
    assert_fields(fx.read_site(api, first["id"]), status=SITE_IN_SERVICE)
    assert_fields(fx.read_site(api, third["id"]), status=SITE_IN_SERVICE)


def test_immediate_consistency_denormalized_site_counters_never_lag(
    api: ApiClient, clock_at_start: str
):
    """Every denormalized counter is correct in the very first read after the
    write: the grant snapshot, the site occupancy, and the monotonic peak all
    settle with no retry and no delay.

    PRD 2.7: "Consistency is immediate: by the time the response is emitted, every
    dependent row has already been rewritten."

    PRD 2.7: "A caller that reads any affected row immediately after a cascading
    write observes the settled result."

    PRD 3.8: "On release, `released_at` is stamped with now, `hold_seconds` is
    computed as the number of whole seconds from `granted_at` to `released_at`
    with any partial second discarded downward, the site's `busy_talkpaths` falls
    by one, `grade_of_service_pct` is recomputed, and `peak_talkpaths` is
    deliberately left where it is."

    Design: Corner/consistency_model/immediate_consistency_denormalized_site_counters_never_lag
    """
    agency = fx.register_agency(
        api,
        name="Immediate Consistency Agency",
        agency_code="IMC01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    site = fx.register_site(
        api,
        site_code="IMC-1",
        name="Immediate One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )
    template = fx.published_template(
        api,
        template_name="IMC-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="IMC-A",
        tg_decimal_id=2601,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="IMC0001",
        radio_id=45001,
        model=MODEL_PORTABLE,
    )

    granted = fx.request_talkpath(
        api,
        site["id"],
        talkgroup["id"],
        unit["id"],
        agency["id"],
        request_kind=KIND_NORMAL,
    )
    # usable 3 = channel_capacity 4 less the control channel; reserve 0 at NORMAL.
    assert_fields(
        granted,
        outcome=OUTCOME_GRANTED,
        available_talkpaths_at_decision=3,
        reserve_talkpaths_at_decision=0,
    )
    assert_instant_equals(granted["granted_at"], "2026-08-01T00:00:00Z", "granted_at")
    assert_nulls(granted, "released_at", "hold_seconds", "preempted_request_id")

    # The very next read already shows the settled occupancy.
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=1,
        peak_talkpaths=1,
        granted_request_count=1,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )

    released = fx.release_talkpath(api, granted["id"], agency["id"])
    assert_fields(released, outcome=OUTCOME_RELEASED, hold_seconds=0)
    assert_instant_equals(released["released_at"], "2026-08-01T00:00:00Z", "released_at")

    # busy_talkpaths drops immediately while peak_talkpaths stays at its mark.
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=0,
        peak_talkpaths=1,
        granted_request_count=1,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )


def test_backup_power_tier_one_refuses_escalation_at_121_minutes_remaining(
    api: ApiClient, clock_at_start: str
):
    """With 121 minutes of battery left the tier map still reads 0, so the
    monotonicity guard refuses the escalation and leaves the event untouched.

    PRD 3.7: "The remaining-minutes figure maps to an escalation tier on inclusive
    low-side boundaries: at most 30 minutes remaining is tier 3, more than 30 but
    at most 60 minutes is tier 2, more than 60 but at most 120 minutes is tier 1,
    and more than 120 minutes remaining is tier 0."

    PRD 3.7: "Escalation is monotonic — the tier computed from the fresh
    remaining-minutes figure must be strictly greater than the event's current
    `escalation_tier`, and an escalation that would hold the tier steady or lower
    it is rejected with `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/boundary_precision_check/backup_power_tier_one_inclusive_at_exactly_120_minutes
    """
    site, on_backup = _battery_site_on_backup(api)

    too_early = api.advance_site_event(
        on_backup["id"], f.advance_payload(EV_ACTION_ESCALATE), RF_ENGINEER
    )
    validate_error(too_early, ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_site_event(on_backup["id"], SYSTEM_ADMIN), 200)
    assert_fields(
        unchanged,
        status=EVENT_ON_BACKUP_POWER,
        escalation_tier=0,
        backup_minutes_remaining=121,
        version=on_backup["version"],
    )
    assert_fields(fx.read_site(api, site["id"]), status=SITE_DEGRADED)


def test_backup_power_tier_one_escalates_at_exactly_120_minutes_remaining(
    api: ApiClient, clock_at_start: str
):
    """One more elapsed minute lands the figure on exactly 120, and because the
    tier-1 boundary is inclusive on the low side the same call now succeeds — while
    tier 1 leaves the site's `capacity_mode` alone.

    PRD 3.7: "`ESCALATE` is available from `ON_BACKUP_POWER` and again from
    `ESCALATED`, and it recomputes `backup_minutes_remaining` before deciding
    anything."

    PRD 3.7: "When the check passes, the event's `status` becomes `ESCALATED` (a
    self-loop when it was already `ESCALATED`) and `escalation_tier` is set to the
    newly computed tier. Tiers 1 and 2 have no further effect beyond recording the
    tier."

    Design: Difficulty/boundary_precision_check/backup_power_tier_one_inclusive_at_exactly_120_minutes
    """
    site, on_backup = _battery_site_on_backup(api)

    fx.set_clock(api, "2026-08-01T02:00:00Z")
    escalated = fx.advance_event(api, on_backup["id"], EV_ACTION_ESCALATE)

    # capacity 240 less 120 whole elapsed minutes leaves exactly the boundary.
    assert_fields(
        escalated,
        status=EVENT_ESCALATED,
        backup_minutes_remaining=120,
        escalation_tier=1,
        preempted_talkpath_count=0,
        version=on_backup["version"] + 1,
    )
    assert_nulls(escalated, "restored_at")

    # Only tier 3 forces EMERGENCY_ONLY.
    assert_fields(
        fx.read_site(api, site["id"]),
        status=SITE_DEGRADED,
        capacity_mode=CAPACITY_NORMAL,
    )


def test_site_escalation_tier_three_cascades_to_normal_talkpath_preemption(
    api: ApiClient, clock_at_start: str
):
    """A tier-3 escalation is a depth-four chain: the tier flip forces
    `EMERGENCY_ONLY`, that flip preempts every held `NORMAL` talkpath, and the
    victims are counted onto the event — all inside the one advance call.

    PRD 3.7: "Tier 3 is where the escalation bites, and it bites in four linked
    steps."

    PRD 3.7: "First, the parent site's `capacity_mode` becomes `EMERGENCY_ONLY`,
    and its `status` becomes `OFF_AIR` when `backup_minutes_remaining` has reached
    exactly 0 or `DEGRADED` when some backup time is still left."

    PRD 3.7: "Second, because the site went `EMERGENCY_ONLY`, every talkpath
    request on that site whose `outcome` is `GRANTED`, whose `released_at` is still
    null, and whose `request_kind` is `NORMAL` becomes `outcome` `PREEMPTED` with
    `released_at` stamped at now; those victims are processed in descending
    `priority_class_at_grant` order — least important first, since a higher class
    number means lower priority — with ties broken by ascending `created_at`, and
    `preempted_talkpath_count` on the event is set to how many were preempted."

    Design: Difficulty/transitive_cascade/site_escalation_tier_three_cascades_to_normal_talkpath_preemption
    """
    site, on_backup, talkpaths = _hotel_outage_at_capacity(api)

    fx.set_clock(api, "2026-08-01T03:31:00Z")
    escalated = fx.advance_event(api, on_backup["id"], EV_ACTION_ESCALATE)

    # Link 1: 240 capacity less 211 whole elapsed minutes leaves 29, which is at
    # most 30 and therefore tier 3.
    assert_fields(
        escalated,
        status=EVENT_ESCALATED,
        backup_minutes_remaining=29,
        escalation_tier=3,
        preempted_talkpath_count=4,
    )

    # Link 2: the tier flipped the site's capacity mode; backup time is left, so
    # the status stays DEGRADED rather than going OFF_AIR.
    assert_fields(
        fx.read_site(api, site["id"]),
        capacity_mode=CAPACITY_EMERGENCY_ONLY,
        status=SITE_DEGRADED,
    )

    # Link 3: all four held NORMAL talkpaths were taken away at once.
    for held in talkpaths[:4]:
        victim = validate_success(
            api.get_talkpath_request(held["id"], SYSTEM_ADMIN), 200
        )
        assert_fields(victim, outcome=OUTCOME_PREEMPTED)
        assert_instant_equals(
            victim["released_at"], "2026-08-01T03:31:00Z", "released_at"
        )

    first_victim = validate_success(
        api.get_talkpath_request(talkpaths[0]["id"], SYSTEM_ADMIN), 200
    )
    last_victim = validate_success(
        api.get_talkpath_request(talkpaths[3]["id"], SYSTEM_ADMIN), 200
    )
    assert_fields(first_victim, priority_class_at_grant=7)
    assert_fields(last_victim, priority_class_at_grant=2)

    # A BUSIED row never held a channel, so it is never a victim.
    busied = validate_success(
        api.get_talkpath_request(talkpaths[4]["id"], SYSTEM_ADMIN), 200
    )
    assert_fields(busied, outcome=OUTCOME_BUSIED)
    assert_nulls(busied, "released_at", "granted_at")


def test_site_escalation_tier_three_leaves_the_grade_of_service_history_intact(
    api: ApiClient, clock_at_start: str
):
    """The fourth link recomputes occupancy but not history: `busy_talkpaths` drops
    to zero while `peak_talkpaths` keeps its high-water mark and the two
    grade-of-service tallies — and so the statistic itself — do not move.

    PRD 3.7: "Third, because those talkpaths went away, the site's
    `busy_talkpaths` and `grade_of_service_pct` are recomputed."

    PRD 3.8: "`peak_talkpaths` is the greater of its previous value and the freshly
    computed busy figure — monotonic, and never lowered."

    PRD 3.8: "`granted_request_count` is the number of requests for the site whose
    `outcome` is `GRANTED`, `PREEMPTED`, or `RELEASED`; preempted and released rows
    still count as grants because the channel really was delivered."

    Design: Difficulty/transitive_cascade/site_escalation_tier_three_cascades_to_normal_talkpath_preemption
    """
    site, on_backup, _talkpaths = _hotel_outage_at_capacity(api)

    # Pre-trigger baseline: four grants and one busied call give 80.0.
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=4,
        peak_talkpaths=4,
        granted_request_count=4,
        busied_request_count=1,
        grade_of_service_pct=80.0,
    )

    fx.set_clock(api, "2026-08-01T03:31:00Z")
    fx.advance_event(api, on_backup["id"], EV_ACTION_ESCALATE)

    settled = fx.read_site(api, site["id"])
    assert_site_capacity_counters(
        settled,
        busy_talkpaths=0,
        peak_talkpaths=4,
        granted_request_count=4,
        busied_request_count=1,
        grade_of_service_pct=80.0,
    )
    assert settled["peak_talkpaths"] > settled["busy_talkpaths"], (
        "peak_talkpaths is monotonic and must survive the preemption sweep"
    )


def test_maintenance_window_closed_interval_forty_five_minute_buffer(
    api: ApiClient, clock_at_start: str
):
    """The same-site buffer treats the windows as closed intervals widened by 45
    minutes on each side, so a gap of exactly 45 minutes is refused — and refused
    on the buffer rule, not on the concurrency cap, since only one site is booked.

    PRD 3.7: "The first protects a single site from back-to-back crews: a new
    planned window must clear every other planned window **on the same site** by
    more than 45 minutes on either side."

    PRD 3.7: "The intervals here are closed, so both endpoints count, and the
    buffer is applied on both sides — the request is rejected when the new window's
    start falls at or before the existing window's end plus 45 minutes *and* the
    existing window's start falls at or before the new window's end plus 45
    minutes."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_interval_forty_five_minute_buffer
    """
    site = fx.register_site(
        api,
        site_code="MNT-1",
        name="Maintenance One",
        channel_capacity=12,
        backup_power_type=BACKUP_GENERATOR,
        generator_fuel_hours=24,
    )
    booked = fx.planned_maintenance(
        api, site["id"], "2026-08-10T02:00:00Z", "2026-08-10T04:00:00Z"
    )
    assert_fields(
        booked, status=EVENT_OPEN, event_class=EVENT_PLANNED_MAINTENANCE
    )
    assert_fields(fx.read_site(api, site["id"]), status=SITE_IN_SERVICE)

    # 04:45 is exactly window_end plus 45 minutes, and the comparison is inclusive.
    on_the_buffer = api.create_site_event(
        f.site_event_payload(
            site["id"],
            event_class=EVENT_PLANNED_MAINTENANCE,
            cause=CAUSE_SCHEDULED_WORK,
            window_start="2026-08-10T04:45:00Z",
            window_end="2026-08-10T06:00:00Z",
        ),
        RF_ENGINEER,
    )
    error = validate_error(on_the_buffer, ERR_MAINTENANCE_BUFFER_VIOLATION, 409)
    assert error["error_id"] != ERR_MAINTENANCE_CONCURRENCY_CAP, (
        "only one site holds maintenance windows, so the cap cannot fire"
    )

    rows, meta = validate_paginated(
        api.list_site_events(SYSTEM_ADMIN, {"site_id": site["id"]})
    )
    assert_pagination_meta(meta, total_count=1)
    assert_fields(rows[0], id=booked["id"])


def test_maintenance_window_forty_six_minute_gap_clears_the_buffer(
    api: ApiClient, clock_at_start: str
):
    """One minute more of separation clears the same guard, and the accepted window
    is stored verbatim while the site itself stays in service.

    PRD 3.7: "A gap of exactly 45 minutes is therefore rejected while a gap of 46
    minutes is accepted, and the rejection is
    `ERR_MAINTENANCE_BUFFER_VIOLATION`."

    PRD 3.7: "Its single consequence is that the parent site's `status` becomes
    `MAINTENANCE`; `capacity_mode` is untouched, so channel access continues under
    normal rules."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_interval_forty_five_minute_buffer
    """
    site = fx.register_site(
        api,
        site_code="MNT-1",
        name="Maintenance One",
        channel_capacity=12,
        backup_power_type=BACKUP_GENERATOR,
        generator_fuel_hours=24,
    )
    fx.planned_maintenance(
        api, site["id"], "2026-08-10T02:00:00Z", "2026-08-10T04:00:00Z"
    )

    accepted = validate_success(
        api.create_site_event(
            f.site_event_payload(
                site["id"],
                event_class=EVENT_PLANNED_MAINTENANCE,
                cause=CAUSE_SCHEDULED_WORK,
                window_start="2026-08-10T04:46:00Z",
                window_end="2026-08-10T06:00:00Z",
            ),
            RF_ENGINEER,
        ),
        201,
    )
    assert_fields(
        accepted, status=EVENT_OPEN, event_class=EVENT_PLANNED_MAINTENANCE
    )
    assert_instant_equals(
        accepted["window_start"], "2026-08-10T04:46:00Z", "window_start"
    )
    assert_instant_equals(accepted["window_end"], "2026-08-10T06:00:00Z", "window_end")

    _rows, meta = validate_paginated(
        api.list_site_events(
            SYSTEM_ADMIN,
            {"site_id": site["id"], "event_class": EVENT_PLANNED_MAINTENANCE},
        )
    )
    assert_pagination_meta(meta, total_count=2)

    # An OPEN window does not itself change the site; only START does.
    assert_fields(fx.read_site(api, site["id"]), status=SITE_IN_SERVICE)
