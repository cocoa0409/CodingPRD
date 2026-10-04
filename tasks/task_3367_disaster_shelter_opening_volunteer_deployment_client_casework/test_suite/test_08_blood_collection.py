"""Blood collection continuity: drive windows, collections and the regional index."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_blood_continuity_status,
    create_blood_drive,
    create_region,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _continuity_scenario(api):
    """One completed drive with 100 collected units and one still-planned drive."""
    region = create_region()
    # Rewind into the first drive's window *before* scheduling it: automatic
    # transitions run on every write, so a drive whose window already sits in the
    # past would be completed before a single unit could be collected.
    set_clock("2026-08-01T12:00:00Z")
    drive1 = create_blood_drive(
        region["id"], site_name="VFW Hall",
        scheduled_start_at="2026-08-01T08:00:00Z",
        scheduled_end_at="2026-08-02T08:00:00Z", target_units=100)
    drive2 = create_blood_drive(
        region["id"], site_name="Elks Lodge",
        scheduled_start_at="2026-09-10T08:00:00Z",
        scheduled_end_at="2026-09-11T08:00:00Z", target_units=200)

    validate_success(api.record_collection(drive1["id"], 100, BLOOD))
    set_clock("2026-08-05T00:00:00Z")
    return region, drive1, drive2


BLOOD = TEST_USERS["blood_services_coordinator_headers"]


def test_trailing_continuity_counts_only_banked_units(api):
    """PRD §3.9: "The `TRAILING` variant, which is the default, counts only what has actually
    been banked: the sum of `usable_units` over drives in the region whose status is `COMPLETED`
    and whose `scheduled_end_at` falls within the 42 days preceding the logical clock."

    PRD §3.9: "The index is the numerator divided by the denominator, rounded half up to four
    decimal places."

    Design: Difficulty/dual_variant_calc/region_blood_continuity_trailing_vs_forward
    """
    region, _drive1, _drive2 = _continuity_scenario(api)

    read = validate_success(api.get_region(
        region["id"], BLOOD, params={"continuity_mode": "TRAILING"}))
    assert float(read["blood_continuity_index"]) == 0.1163
    assert read["blood_continuity_status"] == "CRITICAL"


def test_forward_looking_continuity_adds_planned_drive_targets(api):
    """PRD §3.9: "The `FORWARD_LOOKING` variant adds to that the `target_units` of every
    `PLANNED` drive in the region, and is used when briefing emergency management on projected
    supply."

    PRD §3.9: "Both variants share the same denominator: a baseline of 600 units plus the
    `target_units` of every drive in the region whose status is `PLANNED` or `ACTIVE`."

    Design: Difficulty/dual_variant_calc/region_blood_continuity_trailing_vs_forward
    """
    region, _drive1, _drive2 = _continuity_scenario(api)

    read = validate_success(api.get_region(
        region["id"], BLOOD, params={"continuity_mode": "FORWARD_LOOKING"}))
    assert float(read["blood_continuity_index"]) == 0.3663
    assert_blood_continuity_status(float(read["blood_continuity_index"]),
                                   read["blood_continuity_status"])


def test_second_drive_intersecting_the_same_site_window_is_refused(api):
    """PRD §3.9: "it must not intersect another non-cancelled drive at the same `site_name`,
    which is refused with `ERR_BLOOD_DRIVE_WINDOW_OVERLAP` at HTTP status 409."

    Design: Difficulty/resource_temporal_overlap/blood_drive_site_window_aggregate_overlap
    """
    region = create_region()
    create_blood_drive(region["id"], site_name="VFW Hall",
                       scheduled_start_at="2026-09-10T08:00:00Z",
                       scheduled_end_at="2026-09-10T18:00:00Z", target_units=120)

    resp = api.create_blood_drive(
        {"region_id": region["id"], "site_name": "VFW Hall",
         "scheduled_start_at": "2026-09-10T17:00:00Z",
         "scheduled_end_at": "2026-09-10T21:00:00Z", "target_units": 60},
        BLOOD)
    validate_error(resp, ApiErrorId.ERR_BLOOD_DRIVE_WINDOW_OVERLAP)


def test_adjacent_and_other_site_drive_windows_are_accepted(api):
    """PRD §3.9: "The window must be a real interval — `scheduled_end_at` strictly after
    `scheduled_start_at` — and it must not intersect another non-cancelled drive at the same
    `site_name`."

    Design: Difficulty/resource_temporal_overlap/blood_drive_site_window_aggregate_overlap
    """
    region = create_region()
    create_blood_drive(region["id"], site_name="VFW Hall",
                       scheduled_start_at="2026-09-10T08:00:00Z",
                       scheduled_end_at="2026-09-10T18:00:00Z", target_units=120)

    adjacent = validate_success(api.create_blood_drive(
        {"region_id": region["id"], "site_name": "VFW Hall",
         "scheduled_start_at": "2026-09-10T18:00:00Z",
         "scheduled_end_at": "2026-09-10T21:00:00Z", "target_units": 60},
        BLOOD), 201)
    assert adjacent["status"] == "PLANNED"

    other_site = validate_success(api.create_blood_drive(
        {"region_id": region["id"], "site_name": "Elks Lodge",
         "scheduled_start_at": "2026-09-10T17:00:00Z",
         "scheduled_end_at": "2026-09-10T21:00:00Z", "target_units": 60},
        BLOOD), 201)
    assert other_site["status"] == "PLANNED"


def test_collection_past_the_target_is_refused_but_the_exact_target_is_taken(api):
    """PRD §3.9: "an event that would push `collected_units` past the drive's `target_units` is
    refused with `ERR_COLLECTION_TARGET_EXCEEDED` at HTTP status 409 rather than being
    truncated."

    PRD §3.9: "Each accepted event also recomputes `usable_units`: the collected count is
    multiplied by 700 and divided by 10,000, the fractional part is discarded, and the result is
    subtracted from `collected_units`."

    Design: Corner/errors/blood_collection_over_target_rejected
    """
    region = create_region()
    drive = create_blood_drive(
        region["id"], site_name="VFW Hall",
        scheduled_start_at="2026-09-01T08:00:00Z",
        scheduled_end_at="2026-09-01T18:00:00Z", target_units=100)
    set_clock("2026-09-01T12:00:00Z")

    first = validate_success(api.record_collection(drive["id"], 50, BLOOD))
    assert first["collected_units"] == 50

    validate_error(api.record_collection(drive["id"], 60, BLOOD),
                   ApiErrorId.ERR_COLLECTION_TARGET_EXCEEDED)

    final = validate_success(api.record_collection(drive["id"], 50, BLOOD))
    assert final["collected_units"] == 100, "the target itself is reachable"
    assert final["usable_units"] == 93


def test_completed_drive_rejects_cancellation(api):
    """PRD §3.9: "A `PLANNED` drive may only be cancelled while `collected_units` is zero; an
    `ACTIVE` drive may be cancelled freely, and cancellation recomputes the region's continuity
    figures. `COMPLETED` and `CANCELLED` are terminal."

    PRD §2.4: "`CLOSED` is terminal and rejects every further transition with
    `ERR_ALREADY_TERMINAL` at HTTP status 409."

    Design: Corner/state_machines/completed_blood_drive_cancel_rejected
    """
    region = create_region()
    # The clock has to sit inside the window before the drive is scheduled, or the
    # automatic transitions complete it on the next write (PRD §2.10).
    set_clock("2026-08-01T12:00:00Z")
    drive = create_blood_drive(
        region["id"], site_name="VFW Hall",
        scheduled_start_at="2026-08-01T08:00:00Z",
        scheduled_end_at="2026-08-02T08:00:00Z", target_units=120)
    validate_success(api.record_collection(drive["id"], 40, BLOOD))
    set_clock("2026-08-05T00:00:00Z")

    completed = validate_success(api.get_blood_drive(drive["id"], BLOOD))
    assert completed["status"] == "COMPLETED"

    resp = api.cancel_blood_drive(drive["id"], BLOOD)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE])


def test_region_with_no_collection_history_reports_the_worst_posture(api):
    """PRD §3.1: "A newly created region reports zero `available_volunteer_count` and zero
    `deployed_volunteer_count`, a `blood_continuity_index` of 0.0, and a
    `blood_continuity_status` of `CRITICAL` — a region with no collection history is, correctly,
    in the worst posture."

    Design: Corner/endpoints/region_computed_read_reports_critical_blood_posture
    """
    region = create_region()

    read = validate_success(api.get_region(region["id"], BLOOD))
    assert float(read["blood_continuity_index"]) == 0.0
    assert read["blood_continuity_status"] == "CRITICAL"
    assert read["available_volunteer_count"] == 0
    assert read["deployed_volunteer_count"] == 0
